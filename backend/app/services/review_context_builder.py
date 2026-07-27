import ast
import logging
import os
import re
from collections.abc import Callable

from app.github.github_service import get_file_content
from app.schemas.review_context import (
    ReviewContext,
    ReviewEnclosingSymbol,
    ReviewFileContext,
)
from app.services.diff_line_mapper import DiffLineMapper, LineType
from app.services.repository_context_service import RepositoryContextService
from app.services.review_context_budget_manager import ReviewContextBudgetManager
from app.services.symbol_context_service import SymbolContextService

logger = logging.getLogger(__name__)


class ReviewContextBuilder:
    def __init__(
        self,
        file_fetcher: Callable[[str, str, str, str], dict] | None = None,
        repository_context_service: RepositoryContextService | None = None,
        symbol_context_service: SymbolContextService | None = None,
        budget_manager: ReviewContextBudgetManager | None = None,
    ) -> None:
        self.file_fetcher = file_fetcher or get_file_content
        self.repository_context_service = repository_context_service or RepositoryContextService(
            self.file_fetcher
        )
        self.symbol_context_service = symbol_context_service or SymbolContextService()
        self.budget_manager = budget_manager or ReviewContextBudgetManager(
            max_tokens=_review_context_max_tokens()
        )

    def build(
        self,
        repository: str,
        pull_request: dict,
        source_commit_sha: str,
        files: list[dict],
        annotated_diff: str,
        existing_open_issues: str,
        review_mode: str,
        access_token: str,
    ) -> ReviewContext:
        if not source_commit_sha:
            raise ValueError("Cannot build review context without a Pull Request HEAD SHA")

        repository_context = self.repository_context_service.build_context(
            repository=repository,
            ref=source_commit_sha,
            access_token=access_token,
        )
        changed_file_contents = self._fetch_changed_file_contents(
            repository=repository,
            source_commit_sha=source_commit_sha,
            files=files,
            access_token=access_token,
        )
        file_contexts = [
            self._build_file_context(
                file=file,
                changed_file_contents=changed_file_contents,
                repository_language=repository_context.language,
            )
            for file in files
            if file.get("filename") and file.get("patch")
        ]
        file_contexts = [context for context in file_contexts if context is not None]

        head = pull_request.get("head") or {}
        base = pull_request.get("base") or {}
        repository_data = base.get("repo") or {}
        context = ReviewContext(
            repository_name=repository,
            repository_description=repository_data.get("description"),
            language=repository_context.language,
            framework=repository_context.framework,
            architecture_summary=repository_context.architecture_summary,
            style_rules=repository_context.style_rules,
            repository_instructions=repository_context.repository_instructions,
            pull_request_number=pull_request.get("number"),
            pull_request_title=pull_request.get("title"),
            pull_request_description=pull_request.get("body"),
            source_branch=head.get("ref"),
            target_branch=base.get("ref"),
            source_commit_sha=source_commit_sha,
            changed_files=[file["filename"] for file in files if file.get("filename")],
            annotated_diff=annotated_diff,
            files=file_contexts,
            existing_open_issues=existing_open_issues or "None.",
            review_mode=review_mode,
        )
        fitted = self.budget_manager.fit(context)
        if _context_debug_enabled():
            logger.info(
                "Context debug repository=%s pr=%s head_sha=%s review_mode=%s files=%s "
                "enclosing_symbols=%s estimated_tokens=%s removed=%s",
                repository,
                pull_request.get("number"),
                source_commit_sha,
                review_mode,
                fitted.changed_files,
                {
                    item.file_path: [symbol.name for symbol in item.enclosing_symbols]
                    for item in fitted.files
                },
                fitted.context_token_estimate,
                fitted.context_items_removed,
            )
        return fitted

    def _build_file_context(
        self,
        file: dict,
        changed_file_contents: dict[str, str],
        repository_language: str | None,
    ) -> ReviewFileContext | None:
        file_path = file["filename"]
        mapper = DiffLineMapper(file_path=file_path, patch=file.get("patch"))
        content = changed_file_contents.get(file_path)
        if not content:
            return ReviewFileContext(
                file_path=file_path,
                language=self._language_from_file(file_path),
                annotated_diff=mapper.annotated_diff(),
            )

        affected_contexts = self.symbol_context_service.affected_file_contexts(
            file_path=file_path,
            content=content,
            line_ranges=self._changed_hunk_ranges(mapper),
            repository_language=repository_language,
        )
        enclosing_symbols = [
            ReviewEnclosingSymbol(
                name=context.enclosing_symbol,
                symbol_type=context.enclosing_symbol_type or "unknown",
                start_line=context.enclosing_symbol_start_line or 1,
                end_line=context.enclosing_symbol_end_line or 1,
                code=context.enclosing_code or "",
                class_name=context.enclosing_class_name,
                class_signature=context.enclosing_class_signature,
            )
            for context in affected_contexts
            if context.enclosing_symbol and context.enclosing_code
        ]
        referenced_symbols = set().union(
            *(context.referenced_symbols for context in affected_contexts)
        ) if affected_contexts else set()
        enclosing_names = {symbol.name for symbol in enclosing_symbols}
        related_symbols = self.symbol_context_service.related_symbols(
            file_contents=changed_file_contents,
            referenced_symbols=referenced_symbols - enclosing_names,
            target_file=file_path,
            changed_files=set(changed_file_contents),
            max_symbols=4,
        )

        imports = []
        for context in affected_contexts:
            imports.extend(context.imports)

        return ReviewFileContext(
            file_path=file_path,
            language=self._language_from_file(file_path),
            parser_used=affected_contexts[0].parser_used if affected_contexts else None,
            structural_extraction_succeeded=any(
                context.extraction_succeeded for context in affected_contexts
            ),
            fallback_reason=next(
                (
                    context.fallback_reason
                    for context in affected_contexts
                    if context.fallback_reason
                ),
                None,
            ),
            annotated_diff=mapper.annotated_diff(),
            enclosing_symbols=enclosing_symbols,
            relevant_imports=self._relevant_imports(
                list(dict.fromkeys(imports)),
                referenced_symbols,
            ),
            related_symbols=related_symbols,
        )

    def _fetch_changed_file_contents(
        self,
        repository: str,
        source_commit_sha: str,
        files: list[dict],
        access_token: str,
    ) -> dict[str, str]:
        contents = {}
        for file in files:
            file_path = file.get("filename")
            if not file_path or not file.get("patch"):
                continue
            try:
                payload = self.file_fetcher(
                    repository=repository,
                    file_path=file_path,
                    ref=source_commit_sha,
                    access_token=access_token,
                )
            except Exception:
                logger.info(
                    "Review context could not fetch file repository=%s head_sha=%s file=%s",
                    repository,
                    source_commit_sha,
                    file_path,
                )
                continue
            content = payload.get("content")
            if content:
                contents[file_path] = content
        return contents

    def _changed_hunk_ranges(self, mapper: DiffLineMapper) -> list[tuple[int, int]]:
        hunk_lines: dict[str, list[int]] = {}
        fallback_lines: dict[str, list[int]] = {}
        for line in mapper.lines:
            hunk = line.hunk_header or "unknown"
            if line.line_type == LineType.ADDED and line.new_line is not None:
                hunk_lines.setdefault(hunk, []).append(line.new_line)
            elif line.line_type == LineType.CONTEXT and line.new_line is not None:
                fallback_lines.setdefault(hunk, []).append(line.new_line)

        ranges = []
        for hunk in dict.fromkeys([*hunk_lines, *fallback_lines]):
            lines = hunk_lines.get(hunk) or fallback_lines.get(hunk) or []
            ranges.extend(self._contiguous_ranges(lines))
        return ranges

    def _contiguous_ranges(self, lines: list[int]) -> list[tuple[int, int]]:
        if not lines:
            return []
        ordered = sorted(set(lines))
        ranges = []
        start = previous = ordered[0]
        for line in ordered[1:]:
            if line == previous + 1:
                previous = line
                continue
            ranges.append((start, previous))
            start = previous = line
        ranges.append((start, previous))
        return ranges

    def _relevant_imports(
        self,
        imports: list[str],
        referenced_symbols: set[str],
    ) -> list[str]:
        if not referenced_symbols:
            return []

        relevant = []
        for import_line in imports:
            try:
                tree = ast.parse(import_line)
            except SyntaxError:
                if any(
                    re.search(rf"\b{re.escape(symbol)}\b", import_line)
                    for symbol in referenced_symbols
                ):
                    relevant.append(import_line)
                continue
            imported_names = {
                node.asname or node.name.split(".")[0]
                for node in ast.walk(tree)
                if isinstance(node, ast.alias)
            }
            if imported_names.intersection(referenced_symbols):
                relevant.append(import_line)
        return relevant

    def _language_from_file(self, file_path: str) -> str | None:
        if file_path.endswith(".py"):
            return "Python"
        if file_path.endswith((".ts", ".tsx", ".mts", ".cts")):
            return "TypeScript"
        if file_path.endswith((".js", ".jsx", ".mjs", ".cjs")):
            return "JavaScript"
        return None


def _review_context_max_tokens() -> int:
    raw_value = os.getenv("REVIEW_CONTEXT_MAX_TOKENS", "8000")
    try:
        return max(1000, int(raw_value))
    except ValueError:
        return 8000


def _context_debug_enabled() -> bool:
    return os.getenv("CONTEXT_DEBUG", "").lower() == "true"
