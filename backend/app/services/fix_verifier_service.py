import ast

from app.schemas.fix_context import FixContext, FixVerificationResult, GeneratedFix


class FixVerifierService:
    def verify(self, context: FixContext, generated_fix: GeneratedFix) -> FixVerificationResult:
        if generated_fix.requires_more_context:
            return FixVerificationResult(
                approved=False,
                rejected=True,
                reason=generated_fix.insufficient_context_reason or "The model requested more context.",
            )

        if generated_fix.file_path != context.issue_file and not generated_fix.additional_edits:
            return FixVerificationResult(
                approved=False,
                rejected=True,
                reason="The fix targets a different file without an explicit additional edit.",
            )

        if generated_fix.requires_additional_files and not generated_fix.additional_edits:
            return FixVerificationResult(
                approved=False,
                rejected=True,
                reason="The fix says additional files are required but does not provide explicit edits.",
            )

        if self._line_span(generated_fix) > 120:
            return FixVerificationResult(
                approved=False,
                rejected=True,
                reason="The edit is larger than expected for an AI review fix.",
            )

        nonexistent_imports = self._nonexistent_imports(context, generated_fix.imports_required)
        if nonexistent_imports:
            return FixVerificationResult(
                approved=False,
                rejected=True,
                reason=f"Required imports are not present in supplied context: {', '.join(nonexistent_imports)}",
            )

        return FixVerificationResult(approved=True)

    def _line_span(self, generated_fix: GeneratedFix) -> int:
        return generated_fix.end_line - generated_fix.start_line + 1

    def _nonexistent_imports(
        self,
        context: FixContext,
        imports_required: list[str],
    ) -> list[str]:
        if not imports_required:
            return []

        available_symbols = set()
        for import_line in context.imports:
            try:
                parsed = ast.parse(import_line)
            except SyntaxError:
                continue
            for node in ast.walk(parsed):
                if isinstance(node, ast.alias):
                    available_symbols.add(node.asname or node.name.split(".")[0])

        for symbol in context.related_symbols:
            available_symbols.add(symbol.name)

        missing = []
        for import_name in imports_required:
            name = import_name.split(" import ")[-1].split(".")[0].strip()
            if name and name not in available_symbols and import_name not in context.imports:
                missing.append(import_name)
        return missing
