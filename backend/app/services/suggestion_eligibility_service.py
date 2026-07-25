import re
from dataclasses import dataclass
from typing import Callable

from app.github.github_service import get_file_content
from app.services.patch_service import PatchEdit, PatchService
from app.services.suggestion_formatter import SuggestionFormatter
from app.services.validation_service import ValidationService


LARGE_FIX_FALLBACK_MESSAGE = (
    "This issue requires multiple coordinated changes and cannot be applied as a GitHub Suggestion."
)


@dataclass(frozen=True)
class SuggestionResult:
    eligible: bool
    markdown: str | None = None
    anchor: dict[str, int | str] | None = None
    reason: str | None = None


class SuggestionEligibilityService:
    def __init__(
        self,
        formatter: SuggestionFormatter | None = None,
        patch_service: PatchService | None = None,
        validation_service: ValidationService | None = None,
        file_content_provider: Callable[..., dict] | None = None,
    ):
        self.formatter = formatter or SuggestionFormatter()
        self.patch_service = patch_service or PatchService()
        self.validation_service = validation_service or ValidationService()
        self.file_content_provider = file_content_provider or get_file_content

    def evaluate(
        self,
        issue,
        all_issues,
        files: list[dict],
        repository: str,
        source_commit_sha: str,
        current_head_sha: str | None,
        access_token: str,
    ) -> SuggestionResult:
        edit = issue_to_patch_edit(issue)
        if edit is None:
            return SuggestionResult(eligible=False)

        reason = self._basic_rejection_reason(
            issue=issue,
            edit=edit,
            all_issues=all_issues,
            files=files,
            source_commit_sha=source_commit_sha,
            current_head_sha=current_head_sha,
        )
        if reason:
            return SuggestionResult(eligible=False, reason=reason)

        try:
            file_content = self.file_content_provider(
                repository=repository,
                file_path=edit.file_path,
                ref=current_head_sha,
                access_token=access_token,
            )
        except Exception as exc:
            return SuggestionResult(
                eligible=False,
                reason=f"could not load current file content for validation: {exc}",
            )

        file_sha = getattr(issue, "fix_file_sha", None)
        if file_sha and file_sha != file_content.get("sha"):
            return SuggestionResult(
                eligible=False,
                reason="replacement was generated for an older version of the file",
            )

        source = file_content.get("content") or ""
        if edit.end_line > len(source.splitlines()):
            return SuggestionResult(
                eligible=False,
                reason="target lines no longer exist in the current file",
            )

        try:
            patched_content = self.patch_service.apply_edits(source=source, edits=[edit])
        except ValueError as exc:
            return SuggestionResult(eligible=False, reason=str(exc))

        validation_errors = self.validation_service.validate_file(
            file_path=edit.file_path,
            content=patched_content,
        )
        if validation_errors:
            return SuggestionResult(
                eligible=False,
                reason="replacement is not syntactically valid",
            )

        return SuggestionResult(
            eligible=True,
            markdown=self.formatter.format_suggestion(edit.replacement_code),
            anchor=self._anchor_for_edit(edit),
        )

    def _basic_rejection_reason(
        self,
        issue,
        edit: PatchEdit,
        all_issues,
        files: list[dict],
        source_commit_sha: str,
        current_head_sha: str | None,
    ) -> str | None:
        if not edit.replacement_code.strip():
            return "replacement is empty"

        if not current_head_sha or source_commit_sha != current_head_sha:
            return "source commit SHA does not match the current PR HEAD"

        issue_file = _normalize_path(getattr(issue, "file", None))
        fix_file = _normalize_path(edit.file_path)
        if not issue_file or issue_file != fix_file:
            return "fix changes a different file than the review finding"

        if self._overlaps_another_fix(edit, issue, all_issues):
            return "replacement overlaps another generated fix"

        diff_lines = self._diff_right_side_lines_for(files, edit.file_path)
        if not diff_lines:
            return "target file is not present in the PR diff"

        target_lines = set(range(edit.start_line, edit.end_line + 1))
        if not target_lines.issubset(diff_lines):
            return "target lines are not all present in the PR diff"

        return None

    def _overlaps_another_fix(
        self,
        edit: PatchEdit,
        issue,
        all_issues,
    ) -> bool:
        for other_issue in all_issues:
            if other_issue is issue:
                continue

            other_edit = issue_to_patch_edit(other_issue)
            if other_edit is None:
                continue

            if _normalize_path(other_edit.file_path) != _normalize_path(edit.file_path):
                continue

            if edit.start_line <= other_edit.end_line and other_edit.start_line <= edit.end_line:
                return True

        return False

    def _diff_right_side_lines_for(
        self,
        files: list[dict],
        file_path: str,
    ) -> set[int]:
        normalized_file_path = _normalize_path(file_path)
        for file in files:
            candidate_path = _normalize_path(file.get("filename"))
            if candidate_path != normalized_file_path:
                continue

            patch = file.get("patch") or ""
            return _right_side_lines_from_patch(patch)

        return set()

    def _anchor_for_edit(self, edit: PatchEdit) -> dict[str, int | str]:
        if edit.start_line == edit.end_line:
            return {
                "line": edit.end_line,
                "side": "RIGHT",
            }

        return {
            "start_line": edit.start_line,
            "start_side": "RIGHT",
            "line": edit.end_line,
            "side": "RIGHT",
        }


def issue_to_patch_edit(issue) -> PatchEdit | None:
    fix = getattr(issue, "fix", None)
    file_path = getattr(fix, "file_path", None) if fix else getattr(issue, "fix_file_path", None)
    start_line = getattr(fix, "start_line", None) if fix else getattr(issue, "fix_start_line", None)
    end_line = getattr(fix, "end_line", None) if fix else getattr(issue, "fix_end_line", None)
    replacement_code = (
        getattr(fix, "replacement_code", None)
        if fix
        else getattr(issue, "fix_replacement_code", None)
    )

    if not file_path or not start_line or not end_line or replacement_code is None:
        return None

    return PatchEdit(
        file_path=file_path,
        start_line=int(start_line),
        end_line=int(end_line),
        replacement_code=replacement_code,
        expected_file_sha=getattr(issue, "fix_file_sha", None),
    )


def issue_has_structured_fix(issue) -> bool:
    return issue_to_patch_edit(issue) is not None


def _right_side_lines_from_patch(patch: str) -> set[int]:
    lines = set()
    new_line = None

    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@", raw_line)
            new_line = int(match.group("new_start")) if match else None
            continue

        if new_line is None or not raw_line:
            continue

        marker = raw_line[0]
        if marker in {" ", "+"}:
            lines.add(new_line)
            new_line += 1
        elif marker == "-":
            continue
        else:
            new_line += 1

    return lines


def _normalize_path(file_path: str | None) -> str:
    if not file_path:
        return ""

    return file_path.replace("\\", "/").lstrip("/")
