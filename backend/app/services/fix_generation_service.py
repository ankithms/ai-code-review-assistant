from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai.review_service import llm
from app.db.models import Issue
from app.github.github_service import get_file_content
from app.schemas.output import IssueFixStatus
from app.services.patch_service import PatchEdit, PatchService
from app.services.validation_service import ValidationService


class GeneratedFixSchema(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    replacement_code: str
    explanation: str | None = None


fix_model = llm.with_structured_output(GeneratedFixSchema)


class FixGenerationService:
    def generate_fixes(
        self,
        db: Session,
        issues: list[Issue],
        repository: str,
        target_ref: str,
        target_head_sha: str,
        access_token: str,
    ) -> list[Issue]:
        for issue in issues:
            file_content = None
            if self._has_fix(issue):
                file_content = get_file_content(
                    repository=repository,
                    file_path=issue.fix_file_path,
                    ref=target_ref,
                    access_token=access_token,
                )
                self._stamp_existing_fix(
                    issue=issue,
                    file_sha=file_content["sha"],
                    target_head_sha=target_head_sha,
                )
                validation_errors = self._validate_issue_fix(issue, file_content)
                if not validation_errors:
                    db.add(issue)
                    continue

                self._clear_fix(issue)
                file_content = None

            if not issue.file:
                continue

            if file_content is None:
                file_content = get_file_content(
                    repository=repository,
                    file_path=issue.file,
                    ref=target_ref,
                    access_token=access_token,
                )
            generated_fix = fix_model.invoke(
                self._build_prompt(
                    issue=issue,
                    file_content=file_content["content"],
                )
            )
            self._apply_generated_fix(
                issue=issue,
                generated_fix=generated_fix,
                target_head_sha=target_head_sha,
                file_sha=file_content["sha"],
            )
            validation_errors = self._validate_issue_fix(issue, file_content)
            if validation_errors:
                generated_fix = fix_model.invoke(
                    self._build_prompt(
                        issue=issue,
                        file_content=file_content["content"],
                        previous_fix=generated_fix,
                        validation_errors=validation_errors,
                    )
                )
                self._apply_generated_fix(
                    issue=issue,
                    generated_fix=generated_fix,
                    target_head_sha=target_head_sha,
                    file_sha=file_content["sha"],
                )
            db.add(issue)

        db.commit()
        return issues

    def _has_fix(self, issue: Issue) -> bool:
        return bool(
            issue.fix_file_path
            and issue.fix_start_line
            and issue.fix_end_line
            and issue.fix_replacement_code is not None
        )

    def _stamp_existing_fix(
        self,
        issue: Issue,
        target_head_sha: str,
        file_sha: str,
    ) -> None:
        issue.fix_status = IssueFixStatus.FIX_GENERATED.value
        issue.fix_base_commit_sha = target_head_sha
        issue.fix_file_sha = file_sha

    def _apply_generated_fix(
        self,
        issue: Issue,
        generated_fix: GeneratedFixSchema,
        target_head_sha: str,
        file_sha: str,
    ) -> None:
        issue.fix_file_path = generated_fix.file_path
        issue.fix_start_line = generated_fix.start_line
        issue.fix_end_line = generated_fix.end_line
        issue.fix_replacement_code = generated_fix.replacement_code
        issue.fix_explanation = generated_fix.explanation
        issue.fix_status = IssueFixStatus.FIX_GENERATED.value
        issue.fix_base_commit_sha = target_head_sha
        issue.fix_file_sha = file_sha

    def _build_prompt(
        self,
        issue: Issue,
        file_content: str,
        previous_fix: GeneratedFixSchema | None = None,
        validation_errors: list[str] | None = None,
    ) -> str:
        retry_context = ""
        if previous_fix and validation_errors:
            retry_context = f"""
Previous generated fix failed validation and must be corrected.

Previous fix:
file_path: {previous_fix.file_path}
start_line: {previous_fix.start_line}
end_line: {previous_fix.end_line}
replacement_code:
{previous_fix.replacement_code}

Validation errors:
{chr(10).join(f"- {error}" for error in validation_errors)}
"""

        return f"""
You are generating a minimal, safe code fix for one AI code review finding.

Return only a structured line-range replacement. Do not rewrite the whole file.

Rules:
- Choose the smallest line range that fixes the issue.
- Use 1-based inclusive line numbers.
- replacement_code must contain only the replacement text for that exact line range.
- Preserve existing style and indentation.
- For Python, the full patched file must parse successfully with ast.parse.
- Choose a line range that leaves surrounding code syntactically valid.
- If replacing a Python def/class/control-flow header, include the complete block that must change or choose only the body lines instead.
- If the issue cannot be fixed safely with a small replacement, return the smallest no-op replacement for the reported line and explain why.

Issue:
File: {issue.file}
Line: {issue.line}
Category: {issue.category}
Severity: {issue.severity}
Comment: {issue.comment}
Impact: {issue.impact or "N/A"}

{retry_context}

Current file with line numbers:
{self._numbered_file(file_content)}
"""

    def _numbered_file(self, file_content: str) -> str:
        return "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(file_content.splitlines(), start=1)
        )

    def _validate_issue_fix(
        self,
        issue: Issue,
        file_content: dict,
    ) -> list[str]:
        range_errors = self._validate_python_fix_range(issue, file_content["content"])
        if range_errors:
            return range_errors

        try:
            patched_files = PatchService().build_patched_files(
                file_contents={
                    issue.fix_file_path: file_content,
                },
                edits=[
                    PatchEdit(
                        file_path=issue.fix_file_path,
                        start_line=issue.fix_start_line,
                        end_line=issue.fix_end_line,
                        replacement_code=issue.fix_replacement_code,
                        expected_file_sha=issue.fix_file_sha,
                    )
                ],
            )
        except ValueError as exc:
            return [str(exc)]

        validation_errors = []
        validation_service = ValidationService()
        for patched_file in patched_files:
            validation_errors.extend(
                validation_service.validate_file(
                    file_path=patched_file.file_path,
                    content=patched_file.patched_content,
                )
            )

        return validation_errors

    def _validate_python_fix_range(
        self,
        issue: Issue,
        file_content: str,
    ) -> list[str]:
        if not str(issue.fix_file_path).endswith(".py"):
            return []

        source_lines = file_content.splitlines()
        replacement_lines = (issue.fix_replacement_code or "").splitlines()
        replacement_first_line = self._first_nonblank_line(replacement_lines)
        errors = []

        for line_number in range(issue.fix_start_line, issue.fix_end_line + 1):
            if line_number < 1 or line_number > len(source_lines):
                continue

            source_line = source_lines[line_number - 1]
            if not self._opens_python_block(source_line):
                continue

            block_end_line = self._python_block_end_line(source_lines, line_number)
            if block_end_line <= issue.fix_end_line:
                continue

            if replacement_first_line and self._opens_python_block(replacement_first_line):
                continue

            errors.append(
                (
                    f"{issue.fix_file_path}: fix range {issue.fix_start_line}-{issue.fix_end_line} "
                    f"cuts through the Python block starting at line {line_number}. "
                    "Choose only body lines or include a replacement block header."
                )
            )

        return errors

    def _opens_python_block(self, line: str) -> bool:
        return line.strip().endswith(":")

    def _python_block_end_line(
        self,
        source_lines: list[str],
        header_line_number: int,
    ) -> int:
        header_line = source_lines[header_line_number - 1]
        header_indent = len(header_line) - len(header_line.lstrip())
        block_end_line = header_line_number

        for line_number in range(header_line_number + 1, len(source_lines) + 1):
            line = source_lines[line_number - 1]
            if not line.strip():
                block_end_line = line_number
                continue

            line_indent = len(line) - len(line.lstrip())
            if line_indent <= header_indent:
                break

            block_end_line = line_number

        return block_end_line

    def _first_nonblank_line(self, lines: list[str]) -> str | None:
        for line in lines:
            if line.strip():
                return line

        return None

    def _clear_fix(self, issue: Issue) -> None:
        issue.fix_file_path = None
        issue.fix_start_line = None
        issue.fix_end_line = None
        issue.fix_replacement_code = None
        issue.fix_explanation = None
        issue.fix_base_commit_sha = None
        issue.fix_file_sha = None
        issue.fix_status = IssueFixStatus.NO_FIX.value
