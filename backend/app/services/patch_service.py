from dataclasses import dataclass


@dataclass(frozen=True)
class PatchEdit:
    file_path: str
    start_line: int
    end_line: int
    replacement_code: str
    expected_file_sha: str | None = None


@dataclass(frozen=True)
class PatchedFile:
    file_path: str
    original_sha: str
    patched_content: str


class PatchService:
    def build_patched_files(
        self,
        file_contents: dict[str, dict[str, str]],
        edits: list[PatchEdit],
    ) -> list[PatchedFile]:
        self._reject_overlapping_edits(edits)
        edits_by_file: dict[str, list[PatchEdit]] = {}

        for edit in edits:
            edits_by_file.setdefault(edit.file_path, []).append(edit)

        patched_files = []
        for file_path, file_edits in edits_by_file.items():
            file_content = file_contents.get(file_path)
            if file_content is None:
                raise ValueError(f"Missing file content for {file_path}")

            patched_files.append(
                PatchedFile(
                    file_path=file_path,
                    original_sha=file_content["sha"],
                    patched_content=self.apply_edits(
                        source=file_content["content"],
                        edits=file_edits,
                    ),
                )
            )

        return patched_files

    def apply_edits(
        self,
        source: str,
        edits: list[PatchEdit],
    ) -> str:
        self._reject_overlapping_edits(edits)
        has_trailing_newline = source.endswith("\n")
        lines = source.splitlines()

        for edit in sorted(edits, key=lambda item: item.start_line, reverse=True):
            self._validate_line_range(edit, len(lines))
            replacement_lines = self._replacement_lines_for_edit(
                edit=edit,
                source_lines=lines,
            )
            lines[edit.start_line - 1:edit.end_line] = replacement_lines

        patched = "\n".join(lines)
        if has_trailing_newline:
            patched += "\n"

        return patched

    def _reject_overlapping_edits(self, edits: list[PatchEdit]) -> None:
        edits_by_file: dict[str, list[PatchEdit]] = {}
        for edit in edits:
            edits_by_file.setdefault(edit.file_path, []).append(edit)

        for file_path, file_edits in edits_by_file.items():
            ordered_edits = sorted(file_edits, key=lambda item: item.start_line)
            previous_end = 0
            for edit in ordered_edits:
                self._validate_line_range(edit, None)
                if edit.start_line <= previous_end:
                    raise ValueError(f"Overlapping fix edits detected in {file_path}")
                previous_end = edit.end_line

    def _validate_line_range(self, edit: PatchEdit, line_count: int | None) -> None:
        if edit.start_line < 1:
            raise ValueError(f"Invalid start line for {edit.file_path}")

        if edit.end_line < edit.start_line:
            raise ValueError(f"Invalid end line for {edit.file_path}")

        if line_count is not None and edit.end_line > line_count:
            raise ValueError(
                f"Target lines {edit.start_line}-{edit.end_line} no longer exist in {edit.file_path}"
            )

    def _replacement_lines_for_edit(
        self,
        edit: PatchEdit,
        source_lines: list[str],
    ) -> list[str]:
        replacement_lines = edit.replacement_code.splitlines()
        if not replacement_lines or not edit.file_path.endswith(".py"):
            return replacement_lines

        original_lines = source_lines[edit.start_line - 1:edit.end_line]
        target_indent = self._first_line_indent(original_lines)
        common_replacement_indent = self._common_indent(replacement_lines)
        if common_replacement_indent is None:
            return replacement_lines

        normalized_lines = []
        for line in replacement_lines:
            if not line.strip():
                normalized_lines.append("")
                continue

            stripped_line = line[len(common_replacement_indent):]
            normalized_lines.append(f"{target_indent}{stripped_line}")

        return normalized_lines

    def _first_line_indent(self, lines: list[str]) -> str:
        for line in lines:
            if line.strip():
                return line[:len(line) - len(line.lstrip())]

        if lines:
            return lines[0][:len(lines[0]) - len(lines[0].lstrip())]

        return ""

    def _common_indent(self, lines: list[str]) -> str | None:
        indents = [
            line[:len(line) - len(line.lstrip())]
            for line in lines
            if line.strip()
        ]
        if not indents:
            return None

        common_indent = indents[0]
        for indent in indents[1:]:
            while common_indent and not indent.startswith(common_indent):
                common_indent = common_indent[:-1]

        return common_indent
