from app.schemas.fix_context import FixContext


class ContextBudgetManager:
    def __init__(self, max_tokens: int = 18000) -> None:
        self.max_tokens = max_tokens

    def fit(self, context: FixContext) -> FixContext:
        fitted = context.model_copy(deep=True)
        fitted.context_items_removed = []
        fitted.context_token_estimate = 0
        fitted.related_symbols.sort(key=lambda item: item.relevance_score, reverse=True)
        fitted.related_files.sort(key=lambda item: item.relevance_score, reverse=True)
        fitted.call_sites.sort(key=lambda item: item.relevance_score, reverse=True)
        fitted.tests.sort(key=lambda item: item.relevance_score, reverse=True)

        while self._estimate_tokens(fitted) > self.max_tokens and fitted.related_files:
            removed = fitted.related_files.pop()
            fitted.context_items_removed.append(f"related_file:{removed.file_path}")
        while self._estimate_tokens(fitted) > self.max_tokens and fitted.tests:
            removed = fitted.tests.pop()
            fitted.context_items_removed.append(f"test:{removed.file_path}")
        while self._estimate_tokens(fitted) > self.max_tokens and fitted.call_sites:
            removed = fitted.call_sites.pop()
            fitted.context_items_removed.append(
                f"call_site:{removed.file_path}:{removed.line}"
            )
        while self._estimate_tokens(fitted) > self.max_tokens and fitted.related_symbols:
            removed = fitted.related_symbols.pop()
            fitted.context_items_removed.append(
                f"related_symbol:{removed.file_path}:{removed.name}"
            )
        while self._estimate_tokens(fitted) > self.max_tokens and fitted.repository_instructions:
            fitted.repository_instructions.pop()
            fitted.context_items_removed.append("repository_instruction")

        if self._estimate_tokens(fitted) > self.max_tokens:
            fitted.current_file_content = self._trim_current_file_content(fitted)
            fitted.context_items_removed.append("full_target_file")

        if (
            self._estimate_tokens(fitted) > self.max_tokens
            and fitted.enclosing_symbol_type in {"class", "component"}
            and fitted.enclosing_code
        ):
            fitted.enclosing_code = self._trim_large_enclosing_scope(fitted)
            fitted.context_items_removed.append("unrelated_enclosing_scope_sections")

        fitted.context_files_selected = self._context_files(fitted)
        fitted.context_token_estimate = self._estimate_tokens(fitted)
        return fitted

    def _estimate_tokens(self, context: FixContext) -> int:
        return max(1, len(context.model_dump_json()) // 4)

    def _context_files(self, context: FixContext) -> list[str]:
        files = {context.issue_file}
        files.update(symbol.file_path for symbol in context.related_symbols)
        files.update(file.file_path for file in context.related_files)
        files.update(call.file_path for call in context.call_sites)
        files.update(test.file_path for test in context.tests)
        return sorted(files)

    def _trim_current_file_content(self, context: FixContext) -> str:
        if context.current_file_content.startswith(
            "Full target file omitted from prompt due context budget."
        ):
            return context.current_file_content
        return (
            "Full target file omitted from prompt due context budget. "
            "Use the exact target code, surrounding code, enclosing symbol, imports, and related context below.\n\n"
            f"{context.surrounding_code}"
        )

    def _trim_large_enclosing_scope(self, context: FixContext) -> str:
        parts = [
            "Complete enclosing class/component omitted due context budget; retained metadata and local context.",
            context.enclosing_class_signature or context.enclosing_symbol_name or "class",
        ]
        if context.enclosing_class_attributes:
            parts.extend(context.enclosing_class_attributes)
        if context.surrounding_code:
            parts.append(context.surrounding_code)
        return "\n".join(parts)
