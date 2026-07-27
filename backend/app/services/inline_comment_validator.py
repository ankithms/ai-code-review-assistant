import logging
import re
from dataclasses import dataclass

from app.services.diff_line_mapper import (
    CommentSide,
    LineType,
    MultiFileDiffLineMapper,
    ResolvedLine,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class InlineCommentValidationResult:
    valid: bool
    reason: str | None = None
    payload: dict[str, int | str] | None = None
    resolved_line: ResolvedLine | None = None


class InlineCommentValidator:
    def __init__(
        self,
        diff_mapper: MultiFileDiffLineMapper,
        source_commit_sha: str,
        current_head_sha: str | None = None,
    ):
        self.diff_mapper = diff_mapper
        self.source_commit_sha = source_commit_sha
        self.current_head_sha = current_head_sha

    def validate_issue(self, issue) -> InlineCommentValidationResult:
        source_commit_sha = getattr(issue, "source_commit_sha", None)
        if source_commit_sha and source_commit_sha != self.source_commit_sha:
            return self._invalid("issue source commit SHA does not match the review commit SHA")

        if self.current_head_sha and self.source_commit_sha != self.current_head_sha:
            return self._invalid("source commit SHA does not match the current PR HEAD")

        file_path = _issue_file_path(issue)
        mapper = self.diff_mapper.mapper_for_file(file_path)
        if mapper is None:
            return self._invalid("file is not present in the PR file list")

        if not mapper.is_inline_commentable:
            return self._invalid("patch data is unavailable for this file")

        line_ref = getattr(issue, "line_ref", None)
        if line_ref:
            resolved = mapper.resolve_line_ref(str(line_ref))
            if resolved is None:
                resolved = self._resolve_absolute_line_ref(str(line_ref), mapper)
            if resolved is None:
                return self._invalid("line reference does not exist for this file")
        else:
            resolved = self._resolve_legacy_absolute_line(issue, mapper)
            if resolved is None:
                return self._invalid("absolute line is not present in the PR diff")

        return self._validate_resolved_line(issue, resolved)

    def _resolve_legacy_absolute_line(self, issue, mapper) -> ResolvedLine | None:
        side = _issue_side(issue)
        line = _issue_line_for_side(issue, side)
        if line is None:
            return None

        return mapper.find_by_absolute_line(line=int(line), side=side)

    def _resolve_absolute_line_ref(self, line_ref: str, mapper) -> ResolvedLine | None:
        match = re.fullmatch(r"\s*(NEW|OLD):(\d+)\s*", line_ref, flags=re.IGNORECASE)
        if not match:
            return None

        side = CommentSide.RIGHT if match.group(1).upper() == "NEW" else CommentSide.LEFT
        return mapper.find_by_absolute_line(line=int(match.group(2)), side=side)

    def _validate_resolved_line(
        self,
        issue,
        resolved: ResolvedLine,
    ) -> InlineCommentValidationResult:
        patch_line = resolved.patch_line
        if patch_line.line_type == LineType.HUNK_HEADER:
            return self._invalid("line reference points to a hunk header")

        if not patch_line.is_commentable:
            return self._invalid("line reference is not commentable")

        if patch_line.commentable_side is None:
            return self._invalid("line reference has no GitHub comment side")

        payload = {
            "line": resolved.github_line,
            "side": resolved.side.value,
        }

        range_result = self._validate_range(issue, resolved)
        if not range_result.valid:
            return range_result
        if range_result.payload:
            payload.update(range_result.payload)

        return InlineCommentValidationResult(
            valid=True,
            payload=payload,
            resolved_line=resolved,
        )

    def _validate_range(
        self,
        issue,
        resolved: ResolvedLine,
    ) -> InlineCommentValidationResult:
        start_line = getattr(issue, "start_line", None)
        start_side = getattr(issue, "start_side", None)
        if start_line is None and start_side is None:
            return InlineCommentValidationResult(valid=True)

        if start_line is None or start_side is None:
            return self._invalid("multiline comments require both start_line and start_side")

        start_side = _coerce_side(start_side)
        if start_side is None:
            return self._invalid("start_side must be RIGHT or LEFT")

        if start_side != resolved.side:
            return self._invalid("multiline comments cannot cross sides")

        start_line = int(start_line)
        if start_line > resolved.github_line:
            return self._invalid("start_line must be less than or equal to line")

        mapper = self.diff_mapper.mapper_for_file(resolved.file_path)
        if mapper is None or mapper.find_by_absolute_line(start_line, start_side) is None:
            return self._invalid("start_line is not present in the PR diff")

        return InlineCommentValidationResult(
            valid=True,
            payload={
                "start_line": start_line,
                "start_side": start_side.value,
            },
        )

    def _invalid(self, reason: str) -> InlineCommentValidationResult:
        return InlineCommentValidationResult(valid=False, reason=reason)


def _issue_file_path(issue) -> str | None:
    return getattr(issue, "file_path", None) or getattr(issue, "file", None)


def _issue_side(issue) -> CommentSide:
    raw_side = getattr(issue, "side", None)
    side = _coerce_side(raw_side)
    if side is not None:
        return side

    if getattr(issue, "old_line", None) is not None and getattr(issue, "line", None) is None:
        return CommentSide.LEFT

    return CommentSide.RIGHT


def _issue_line_for_side(issue, side: CommentSide) -> int | None:
    if side == CommentSide.LEFT:
        return getattr(issue, "old_line", None) or getattr(issue, "line", None)

    return getattr(issue, "line", None)


def _coerce_side(value) -> CommentSide | None:
    if value is None:
        return None

    raw_value = value.value if hasattr(value, "value") else str(value)
    try:
        return CommentSide(raw_value)
    except ValueError:
        return None
