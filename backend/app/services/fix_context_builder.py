import logging
import os
from collections.abc import Callable

from app.github.github_service import get_file_content, get_pr_files
from app.schemas.fix_context import FixContext, PreviousFixAttempt, RelatedFile
from app.services.call_site_context_service import CallSiteContextService
from app.services.context_budget_manager import ContextBudgetManager
from app.services.repository_context_service import RepositoryContextService
from app.services.symbol_context_service import SymbolContextService
from app.services.test_context_service import TestContextService

logger = logging.getLogger(__name__)


class FixContextBuilder:
    _file_cache: dict[tuple[str, str, str], dict] = {}
    _pr_files_cache: dict[tuple[str, int, str], list[dict]] = {}

    def __init__(
        self,
        file_fetcher: Callable[[str, str, str, str], dict] | None = None,
        pr_files_fetcher: Callable[[str, int, str], list[dict]] | None = None,
        repository_context_service: RepositoryContextService | None = None,
        symbol_context_service: SymbolContextService | None = None,
        call_site_context_service: CallSiteContextService | None = None,
        test_context_service: TestContextService | None = None,
        budget_manager: ContextBudgetManager | None = None,
    ) -> None:
        self.file_fetcher = file_fetcher or get_file_content
        self.pr_files_fetcher = pr_files_fetcher or get_pr_files
        self.repository_context_service = repository_context_service or RepositoryContextService(self.file_fetcher)
        self.symbol_context_service = symbol_context_service or SymbolContextService()
        self.call_site_context_service = call_site_context_service or CallSiteContextService(
            self.symbol_context_service
        )
        self.test_context_service = test_context_service or TestContextService(self.file_fetcher)
        self.budget_manager = budget_manager or ContextBudgetManager()

    def build(
        self,
        issue,
        repository: str,
        target_ref: str,
        target_head_sha: str,
        access_token: str,
        pull_request: dict | None = None,
        previous_fix=None,
        validation_errors: list[str] | None = None,
        missing_symbols: list[str] | None = None,
        missing_files: list[str] | None = None,
    ) -> FixContext:
        if not issue.file:
            raise ValueError("Cannot build fix context for an issue without a file")
        if not target_head_sha:
            raise ValueError("Cannot build fix context without a Pull Request HEAD SHA")

        file_payload = self._get_file(repository, issue.file, target_ref, access_token)
        current_file_content = file_payload["content"]
        issue_line = getattr(issue, "line", None)
        issue_line_start = getattr(issue, "start_line", None) or issue_line or 1
        issue_line_end = issue_line or issue_line_start

        repository_context = self.repository_context_service.build_context(
            repository=repository,
            ref=target_ref,
            access_token=access_token,
        )
        affected = self.symbol_context_service.affected_file_context(
            file_path=issue.file,
            content=current_file_content,
            line_start=issue_line_start,
            line_end=issue_line_end,
            repository_language=repository_context.language,
        )
        pr_files = self._get_pr_files(
            repository,
            pull_request,
            target_head_sha,
            access_token,
        )
        changed_files = {
            file["filename"]
            for file in pr_files
            if isinstance(file, dict) and file.get("filename")
        }
        known_file_contents = self._known_file_contents(
            repository=repository,
            target_ref=target_ref,
            access_token=access_token,
            target_file=issue.file,
            target_file_content=current_file_content,
            pr_files=pr_files,
            missing_files=missing_files or [],
        )
        related_symbols = self.symbol_context_service.related_symbols(
            file_contents=known_file_contents,
            referenced_symbols=affected.referenced_symbols.union(set(missing_symbols or [])),
            target_file=issue.file,
            changed_files=changed_files,
        )
        related_files = self._related_files(
            known_file_contents=known_file_contents,
            target_file=issue.file,
            changed_files=changed_files,
            missing_files=set(missing_files or []),
        )
        call_sites = self.call_site_context_service.collect_call_sites(
            file_contents=known_file_contents,
            enclosing_symbol=affected.enclosing_symbol,
            target_file=issue.file,
            changed_files=changed_files,
        )
        tests = self.test_context_service.collect_tests(
            repository=repository,
            ref=target_ref,
            access_token=access_token,
            affected_file=issue.file,
            enclosing_symbol=affected.enclosing_symbol,
            known_file_contents=known_file_contents,
        )

        context = FixContext(
            repository_name=repository,
            repository_description=self._repository_description(pull_request),
            default_branch=self._default_branch(pull_request),
            pull_request_number=self._pull_request_number(pull_request, issue),
            pull_request_title=self._pull_request_title(pull_request, issue),
            pull_request_description=self._pull_request_description(pull_request),
            source_commit_sha=target_head_sha,
            language=repository_context.language or self._language_from_file(issue.file),
            framework=repository_context.framework,
            architecture_summary=repository_context.architecture_summary,
            style_rules=repository_context.style_rules,
            issue_id=getattr(issue, "id", None),
            issue_category=getattr(issue, "category", None),
            issue_severity=getattr(issue, "severity", None),
            issue_explanation=getattr(issue, "comment", None),
            issue_impact=getattr(issue, "impact", None),
            issue_file=issue.file,
            issue_line_start=issue_line_start,
            issue_line_end=issue_line_end,
            original_code=affected.original_code,
            surrounding_code=affected.surrounding_code,
            enclosing_symbol=affected.enclosing_symbol,
            enclosing_symbol_name=affected.enclosing_symbol,
            enclosing_symbol_type=affected.enclosing_symbol_type,
            enclosing_symbol_start_line=affected.enclosing_symbol_start_line,
            enclosing_symbol_end_line=affected.enclosing_symbol_end_line,
            enclosing_code=affected.enclosing_code,
            enclosing_class_name=affected.enclosing_class_name,
            enclosing_class_signature=affected.enclosing_class_signature,
            enclosing_class_attributes=affected.enclosing_class_attributes,
            structural_language=affected.language.value,
            structural_parser_used=affected.parser_used,
            structural_extraction_succeeded=affected.extraction_succeeded,
            structural_fallback_reason=affected.fallback_reason,
            imports=affected.imports,
            current_file_content=current_file_content,
            validation_file_content=current_file_content,
            relevant_diff=self._relevant_diff(issue, pr_files),
            related_symbols=related_symbols,
            related_files=related_files,
            call_sites=call_sites,
            tests=tests,
            repository_instructions=repository_context.repository_instructions,
            previous_fix_attempt=self._previous_fix_attempt(previous_fix, validation_errors),
            previous_validation_errors=validation_errors or [],
            missing_symbols_requested=missing_symbols or [],
            missing_files_requested=missing_files or [],
        )
        fitted = self.budget_manager.fit(context)
        logger.info(
            "Built fix context issue=%s repository=%s sha=%s files=%s tokens=%s",
            getattr(issue, "id", None),
            repository,
            target_head_sha,
            fitted.context_files_selected,
            fitted.context_token_estimate,
        )
        if _context_debug_enabled():
            logger.info(
                "Context debug repository=%s pr=%s head_sha=%s issue=%s target=%s "
                "enclosing_symbol=%s related_files=%s tests=%s estimated_tokens=%s removed=%s",
                repository,
                fitted.pull_request_number,
                target_head_sha,
                fitted.issue_id,
                fitted.issue_file,
                fitted.enclosing_symbol_name,
                [item.file_path for item in fitted.related_files],
                [item.file_path for item in fitted.tests],
                fitted.context_token_estimate,
                fitted.context_items_removed,
            )
        return fitted

    def _get_file(
        self,
        repository: str,
        file_path: str,
        ref: str,
        access_token: str,
    ) -> dict:
        cache_key = (repository, ref, file_path)
        cached = self._file_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = self.file_fetcher(
            repository=repository,
            file_path=file_path,
            ref=ref,
            access_token=access_token,
        )
        self._file_cache[cache_key] = payload
        return payload

    def _get_pr_files(
        self,
        repository: str,
        pull_request: dict | None,
        head_sha: str,
        access_token: str,
    ) -> list[dict]:
        number = self._pull_request_number(pull_request, None)
        if number is None:
            return []
        if not head_sha:
            logger.warning(
                "Bypassing PR files cache because HEAD SHA is missing repository=%s pr=%s",
                repository,
                number,
            )
            return self._fetch_pr_files(repository, number, access_token)

        cache_key = (repository, number, head_sha)
        cached = self._pr_files_cache.get(cache_key)
        if cached is not None:
            _log_cache_event(
                "PR files cache hit repository=%s pr=%s head_sha=%s",
                repository,
                number,
                head_sha,
            )
            return cached

        _log_cache_event(
            "PR files cache miss repository=%s pr=%s head_sha=%s",
            repository,
            number,
            head_sha,
        )
        files = self._fetch_pr_files(repository, number, access_token)
        self._pr_files_cache[cache_key] = files
        _log_cache_event(
            "PR files cache write repository=%s pr=%s head_sha=%s",
            repository,
            number,
            head_sha,
        )
        return files

    def _fetch_pr_files(
        self,
        repository: str,
        number: int,
        access_token: str,
    ) -> list[dict]:
        try:
            files = self.pr_files_fetcher(
                repository=repository,
                pull_request_number=number,
                access_token=access_token,
            )
        except Exception:
            logger.exception("Could not fetch PR files for %s PR #%s", repository, number)
            files = []
        return files

    def _known_file_contents(
        self,
        repository: str,
        target_ref: str,
        access_token: str,
        target_file: str,
        target_file_content: str,
        pr_files: list[dict],
        missing_files: list[str],
    ) -> dict[str, str]:
        contents = {target_file: target_file_content}
        candidates = []
        for file in pr_files:
            file_path = file.get("filename") if isinstance(file, dict) else None
            if file_path and file_path != target_file:
                candidates.append(file_path)
        candidates.extend(missing_files)

        for file_path in list(dict.fromkeys(candidates))[:8]:
            try:
                contents[file_path] = self._get_file(
                    repository=repository,
                    file_path=file_path,
                    ref=target_ref,
                    access_token=access_token,
                )["content"]
            except Exception:
                continue

        return contents

    def _related_files(
        self,
        known_file_contents: dict[str, str],
        target_file: str,
        changed_files: set[str],
        missing_files: set[str],
    ) -> list[RelatedFile]:
        files = []
        for file_path, content in known_file_contents.items():
            if file_path == target_file:
                continue
            score = 1.0
            reasons = []
            if file_path in changed_files:
                score += 2
                reasons.append("changed in current PR")
            if file_path in missing_files:
                score += 3
                reasons.append("requested by the model after insufficient context")
            files.append(
                RelatedFile(
                    file_path=file_path,
                    reason=", ".join(reasons) or "related repository file",
                    content=content,
                    relevance_score=score,
                )
            )
        return sorted(files, key=lambda item: item.relevance_score, reverse=True)[:8]

    def _relevant_diff(self, issue, pr_files: list[dict]) -> str | None:
        if getattr(issue, "diff_hunk", None):
            return issue.diff_hunk

        for file in pr_files:
            if not isinstance(file, dict) or file.get("filename") != issue.file:
                continue
            return file.get("patch")
        return None

    def _previous_fix_attempt(
        self,
        previous_fix,
        validation_errors: list[str] | None,
    ) -> PreviousFixAttempt | None:
        if previous_fix is None and not validation_errors:
            return None
        return PreviousFixAttempt(
            file_path=getattr(previous_fix, "file_path", None),
            start_line=getattr(previous_fix, "start_line", None),
            end_line=getattr(previous_fix, "end_line", None),
            replacement_code=getattr(previous_fix, "replacement_code", None),
            validation_errors=validation_errors or [],
        )

    def _repository_description(self, pull_request: dict | None) -> str | None:
        repo = ((pull_request or {}).get("base") or {}).get("repo") or {}
        return repo.get("description")

    def _default_branch(self, pull_request: dict | None) -> str | None:
        repo = ((pull_request or {}).get("base") or {}).get("repo") or {}
        return repo.get("default_branch")

    def _pull_request_number(self, pull_request: dict | None, issue) -> int | None:
        number = (pull_request or {}).get("number")
        if number is not None:
            return number
        review = getattr(issue, "review", None)
        pull_request_record = getattr(review, "pull_request", None)
        return getattr(pull_request_record, "pull_request_number", None)

    def _pull_request_title(self, pull_request: dict | None, issue) -> str | None:
        title = (pull_request or {}).get("title")
        if title:
            return title
        review = getattr(issue, "review", None)
        pull_request_record = getattr(review, "pull_request", None)
        return getattr(pull_request_record, "title", None)

    def _pull_request_description(self, pull_request: dict | None) -> str | None:
        return (pull_request or {}).get("body")

    def _language_from_file(self, file_path: str) -> str | None:
        if file_path.endswith(".py"):
            return "Python"
        if file_path.endswith((".ts", ".tsx", ".mts", ".cts")):
            return "TypeScript"
        if file_path.endswith((".js", ".jsx", ".mjs", ".cjs")):
            return "JavaScript"
        return None


def _context_debug_enabled() -> bool:
    return os.getenv("CONTEXT_DEBUG", "").lower() == "true"


def _log_cache_event(message: str, *args) -> None:
    if _context_debug_enabled():
        logger.info(message, *args)
    else:
        logger.debug(message, *args)
