from app.schemas.review_context import ReviewContext


class ReviewContextBudgetManager:
    def __init__(self, max_tokens: int = 8000) -> None:
        self.max_tokens = max_tokens

    def fit(self, context: ReviewContext) -> ReviewContext:
        fitted = context.model_copy(deep=True)
        fitted.context_items_removed = []
        fitted.context_token_estimate = 0

        for file_context in reversed(fitted.files):
            while self._estimate_tokens(fitted) > self.max_tokens and file_context.related_symbols:
                removed = file_context.related_symbols.pop()
                fitted.context_items_removed.append(
                    f"related_symbol:{removed.file_path}:{removed.name}"
                )

        while self._estimate_tokens(fitted) > self.max_tokens and fitted.repository_instructions:
            fitted.repository_instructions.pop()
            fitted.context_items_removed.append("repository_instruction")

        for file_context in reversed(fitted.files):
            for symbol in reversed(file_context.enclosing_symbols):
                if self._estimate_tokens(fitted) <= self.max_tokens:
                    break
                symbol.code = "Complete enclosing code omitted from this review batch due context budget."
                fitted.context_items_removed.append(
                    f"enclosing_code:{file_context.file_path}:{symbol.name}"
                )

        while self._estimate_tokens(fitted) > self.max_tokens and fitted.style_rules:
            fitted.style_rules.pop()
            fitted.context_items_removed.append("style_rule")
        while self._estimate_tokens(fitted) > self.max_tokens and fitted.architecture_summary:
            fitted.architecture_summary.pop()
            fitted.context_items_removed.append("architecture_summary")

        fitted.context_token_estimate = self._estimate_tokens(fitted)
        return fitted

    def _estimate_tokens(self, context: ReviewContext) -> int:
        # Per-file annotated diffs duplicate the canonical combined diff in the
        # typed context, but the prompt emits only the canonical copy.
        prompt_context = context.model_copy(deep=True)
        for file_context in prompt_context.files:
            file_context.annotated_diff = ""
        return max(1, len(prompt_context.model_dump_json()) // 4)
