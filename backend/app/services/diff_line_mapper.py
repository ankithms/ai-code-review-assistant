import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class LineType(str, Enum):
    HUNK_HEADER = "HUNK_HEADER"
    ADDED = "ADDED"
    DELETED = "DELETED"
    CONTEXT = "CONTEXT"
    NO_NEWLINE_MARKER = "NO_NEWLINE_MARKER"


class CommentSide(str, Enum):
    RIGHT = "RIGHT"
    LEFT = "LEFT"


@dataclass(frozen=True)
class PatchLine:
    patch_index: int
    content: str
    line_type: LineType
    old_line: int | None
    new_line: int | None
    commentable_side: CommentSide | None
    is_commentable: bool
    line_ref: str | None = None
    hunk_header: str | None = None


@dataclass(frozen=True)
class ResolvedLine:
    file_path: str
    line_ref: str
    patch_line: PatchLine

    @property
    def side(self) -> CommentSide:
        if self.patch_line.commentable_side is None:
            raise ValueError("Resolved line is not commentable")
        return self.patch_line.commentable_side

    @property
    def github_line(self) -> int:
        if self.side == CommentSide.LEFT:
            if self.patch_line.old_line is None:
                raise ValueError("Resolved LEFT line has no old-file line number")
            return self.patch_line.old_line

        if self.patch_line.new_line is None:
            raise ValueError("Resolved RIGHT line has no new-file line number")
        return self.patch_line.new_line


class DiffLineMapper:
    """Maps GitHub unified diff lines to absolute old/new file line numbers."""

    HUNK_RE = re.compile(
        r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
        r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@"
    )

    def __init__(self, file_path: str, patch: str | None):
        self.file_path = file_path
        self.patch = patch
        self.lines: list[PatchLine] = []
        self._by_ref: dict[str, PatchLine] = {}

        if patch:
            self.lines = self._parse(patch)
            self._by_ref = {
                line.line_ref: line
                for line in self.lines
                if line.line_ref is not None
            }

    @property
    def is_inline_commentable(self) -> bool:
        return bool(self.patch and self._by_ref)

    def resolve_line_ref(self, line_ref: str) -> ResolvedLine | None:
        patch_line = self._by_ref.get(line_ref)
        if patch_line is None:
            return None

        return ResolvedLine(
            file_path=self.file_path,
            line_ref=line_ref,
            patch_line=patch_line,
        )

    def find_by_absolute_line(
        self,
        line: int,
        side: CommentSide = CommentSide.RIGHT,
    ) -> ResolvedLine | None:
        for patch_line in self.lines:
            if not patch_line.is_commentable:
                continue
            if side == CommentSide.RIGHT and patch_line.new_line == line:
                return ResolvedLine(
                    file_path=self.file_path,
                    line_ref=patch_line.line_ref or "",
                    patch_line=patch_line,
                )
            if side == CommentSide.LEFT and patch_line.old_line == line:
                return ResolvedLine(
                    file_path=self.file_path,
                    line_ref=patch_line.line_ref or "",
                    patch_line=patch_line,
                )

        return None

    def annotated_diff(self) -> str:
        annotated_lines = [f"FILE: {self.file_path}"]

        if not self.patch:
            annotated_lines.append("[NOT_INLINE_COMMENTABLE] patch data is unavailable")
            return "\n".join(annotated_lines)

        for line in self.lines:
            if line.line_type in {LineType.HUNK_HEADER, LineType.NO_NEWLINE_MARKER}:
                continue

            new_line = line.new_line if line.new_line is not None else "-"
            old_line = line.old_line if line.old_line is not None else "-"
            annotated_lines.append(
                f"[line_ref={line.line_ref} | new_file_line={new_line} | old_file_line={old_line} | "
                f"{line.line_type.value}] {line.content}"
            )

        return "\n".join(annotated_lines)

    def debug_mapping_table(self) -> str:
        rows = []
        for line in self.lines:
            rows.append(
                "\n".join(
                    [
                        f"{self.file_path}:{line.line_ref or '-'}",
                        f"patch_index={line.patch_index}",
                        f"type={line.line_type.value}",
                        f"old_line={line.old_line}",
                        f"new_line={line.new_line}",
                        f"side={line.commentable_side.value if line.commentable_side else None}",
                        f"commentable={line.is_commentable}",
                        f"content={line.content!r}",
                    ]
                )
            )

        return "\n\n".join(rows)

    def _parse(self, patch: str) -> list[PatchLine]:
        lines: list[PatchLine] = []
        old_line: int | None = None
        new_line: int | None = None
        current_hunk: str | None = None
        next_ref_number = 1

        for patch_index, raw_line in enumerate(patch.splitlines(), start=1):
            hunk_match = self.HUNK_RE.match(raw_line)
            if hunk_match:
                old_start = int(hunk_match.group("old_start"))
                old_count = self._count_or_default(hunk_match.group("old_count"))
                new_start = int(hunk_match.group("new_start"))
                new_count = self._count_or_default(hunk_match.group("new_count"))
                old_line = old_start if old_count > 0 else None
                new_line = new_start if new_count > 0 else None
                current_hunk = raw_line
                lines.append(
                    PatchLine(
                        patch_index=patch_index,
                        content=raw_line,
                        line_type=LineType.HUNK_HEADER,
                        old_line=None,
                        new_line=None,
                        commentable_side=None,
                        is_commentable=False,
                        hunk_header=current_hunk,
                    )
                )
                continue

            if raw_line.startswith("\\ No newline at end of file"):
                lines.append(
                    PatchLine(
                        patch_index=patch_index,
                        content=raw_line,
                        line_type=LineType.NO_NEWLINE_MARKER,
                        old_line=None,
                        new_line=None,
                        commentable_side=None,
                        is_commentable=False,
                        hunk_header=current_hunk,
                    )
                )
                continue

            if old_line is None and new_line is None:
                logger.debug(
                    "Ignoring patch line outside a hunk for %s at patch_index=%s",
                    self.file_path,
                    patch_index,
                )
                continue

            marker = raw_line[:1]
            content = raw_line[1:] if marker in {" ", "+", "-"} else raw_line
            line_ref = f"L{next_ref_number}"
            next_ref_number += 1

            if marker == "+":
                patch_line = PatchLine(
                    patch_index=patch_index,
                    content=content,
                    line_type=LineType.ADDED,
                    old_line=None,
                    new_line=new_line,
                    commentable_side=CommentSide.RIGHT,
                    is_commentable=new_line is not None,
                    line_ref=line_ref,
                    hunk_header=current_hunk,
                )
                if new_line is not None:
                    new_line += 1
            elif marker == "-":
                patch_line = PatchLine(
                    patch_index=patch_index,
                    content=content,
                    line_type=LineType.DELETED,
                    old_line=old_line,
                    new_line=None,
                    commentable_side=CommentSide.LEFT,
                    is_commentable=old_line is not None,
                    line_ref=line_ref,
                    hunk_header=current_hunk,
                )
                if old_line is not None:
                    old_line += 1
            else:
                patch_line = PatchLine(
                    patch_index=patch_index,
                    content=content,
                    line_type=LineType.CONTEXT,
                    old_line=old_line,
                    new_line=new_line,
                    commentable_side=CommentSide.RIGHT,
                    is_commentable=old_line is not None and new_line is not None,
                    line_ref=line_ref,
                    hunk_header=current_hunk,
                )
                if old_line is not None:
                    old_line += 1
                if new_line is not None:
                    new_line += 1

            lines.append(patch_line)

        return lines

    def _count_or_default(self, raw_count: str | None) -> int:
        if raw_count is None:
            return 1
        return int(raw_count)


class MultiFileDiffLineMapper:
    def __init__(self, mappers: dict[str, DiffLineMapper]):
        self.mappers = mappers

    @classmethod
    def from_files(cls, files: list[dict]) -> "MultiFileDiffLineMapper":
        mappers = {}
        for file in files:
            file_path = file.get("filename")
            if not file_path:
                continue
            mappers[_normalize_path(file_path)] = DiffLineMapper(
                file_path=file_path,
                patch=file.get("patch"),
            )

        return cls(mappers)

    def mapper_for_file(self, file_path: str | None) -> DiffLineMapper | None:
        if not file_path:
            return None

        return self.mappers.get(_normalize_path(file_path))

    def annotated_diff(self) -> str:
        return "\n\n".join(
            mapper.annotated_diff()
            for mapper in self.mappers.values()
            if mapper.is_inline_commentable
        )

    def log_debug_mapping_tables(self) -> None:
        for mapper in self.mappers.values():
            logger.debug(
                "Inline comment mapping table for %s:\n%s",
                mapper.file_path,
                mapper.debug_mapping_table(),
            )


def _normalize_path(file_path: str) -> str:
    return file_path.replace("\\", "/").lstrip("/")
