import logging
import json
import os

from sqlalchemy.orm import Session

from app.ai.model_invocation import invoke_with_deadline
from app.ai.review_service import AIReviewServiceError, ai_service_error, llm
from app.db.models import Issue
from app.github.github_service import get_file_content
from app.schemas.fix_context import FixContext, GeneratedFix
from app.schemas.output import IssueFixStatus
from app.services.fix_context_builder import FixContextBuilder
from app.services.fix_verifier_service import FixVerifierService
from app.services.patch_service import PatchEdit, PatchService
from app.services.validation_service import ValidationService

logger = logging.getLogger(__name__)


GeneratedFixSchema = GeneratedFix

fix_model = llm.with_structured_output(GeneratedFix, method="json_schema")


class FixGenerationService:
    def __init__(
        self,
        context_builder: FixContextBuilder | None = None,
        verifier_service: FixVerifierService | None = None,
    ) -> None:
        self.context_builder = context_builder or FixContextBuilder(file_fetcher=get_file_content)
        self.verifier_service = verifier_service or FixVerifierService()

    def generate_fixes(
        self,
        db: Session,
        issues: list[Issue],
        repository: str,
        target_ref: str,
        target_head_sha: str,
        access_token: str,
        pull_request: dict | None = None,
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
            fix_context = self.context_builder.build(
                issue=issue,
                repository=repository,
                target_ref=target_ref,
                target_head_sha=target_head_sha,
                access_token=access_token,
                pull_request=pull_request,
            )
            generated_fix = self._invoke_fix_model(fix_context)
            if generated_fix.requires_more_context:
                if _context_debug_enabled():
                    logger.info(
                        "Context debug retry requested repository=%s issue=%s head_sha=%s "
                        "missing_files=%s missing_symbols=%s",
                        repository,
                        getattr(issue, "id", None),
                        target_head_sha,
                        generated_fix.missing_files,
                        generated_fix.missing_symbols,
                    )
                generated_fix, fix_context = self._retry_with_requested_context(
                    issue=issue,
                    repository=repository,
                    target_ref=target_ref,
                    target_head_sha=target_head_sha,
                    access_token=access_token,
                    pull_request=pull_request,
                    previous_fix=generated_fix,
                )
            if generated_fix.requires_more_context:
                self._clear_fix(issue)
                logger.warning(
                    "Skipping fix for issue=%s because context is still insufficient: %s",
                    getattr(issue, "id", None),
                    generated_fix.insufficient_context_reason,
                )
                db.add(issue)
                continue

            generation_errors = self._validate_generated_fix_against_context(
                generated_fix=generated_fix,
                context=fix_context,
            )
            if generation_errors:
                self._clear_fix(issue)
                issue.fix_explanation = "; ".join(generation_errors)
                logger.warning(
                    "Rejected generated fix for issue=%s: %s",
                    getattr(issue, "id", None),
                    generation_errors,
                )
                db.add(issue)
                continue

            self._apply_generated_fix(
                issue=issue,
                generated_fix=generated_fix,
                target_head_sha=target_head_sha,
                file_sha=file_content["sha"],
            )
            validation_errors = self._validate_issue_fix(issue, file_content)
            if validation_errors:
                retry_context = self.context_builder.build(
                    issue=issue,
                    repository=repository,
                    target_ref=target_ref,
                    target_head_sha=target_head_sha,
                    access_token=access_token,
                    pull_request=pull_request,
                    previous_fix=generated_fix,
                    validation_errors=validation_errors,
                )
                generated_fix = self._invoke_fix_model(retry_context)
                if generated_fix.requires_more_context:
                    if _context_debug_enabled():
                        logger.info(
                            "Context debug retry requested repository=%s issue=%s head_sha=%s "
                            "missing_files=%s missing_symbols=%s",
                            repository,
                            getattr(issue, "id", None),
                            target_head_sha,
                            generated_fix.missing_files,
                            generated_fix.missing_symbols,
                        )
                    generated_fix, retry_context = self._retry_with_requested_context(
                        issue=issue,
                        repository=repository,
                        target_ref=target_ref,
                        target_head_sha=target_head_sha,
                        access_token=access_token,
                        pull_request=pull_request,
                        previous_fix=generated_fix,
                        validation_errors=validation_errors,
                    )
                generation_errors = self._validate_generated_fix_against_context(
                    generated_fix=generated_fix,
                    context=retry_context,
                )
                if generation_errors:
                    self._clear_fix(issue)
                    issue.fix_explanation = "; ".join(generation_errors)
                    logger.warning(
                        "Rejected regenerated fix for issue=%s: %s",
                        getattr(issue, "id", None),
                        generation_errors,
                    )
                    db.add(issue)
                    continue
                self._apply_generated_fix(
                    issue=issue,
                    generated_fix=generated_fix,
                    target_head_sha=target_head_sha,
                    file_sha=file_content["sha"],
                )
            db.add(issue)

        db.commit()
        return issues

    def _invoke_fix_model(self, context: FixContext) -> GeneratedFix:
        try:
            return invoke_with_deadline(
                fix_model,
                [
                    ("system", self._system_prompt()),
                    ("user", self._build_prompt(context)),
                ],
            )
        except AIReviewServiceError:
            raise
        except Exception as exc:
            raise ai_service_error(
                exc,
                operation="AI fix generation",
                retry_message="Please try the AI fix command again later.",
            ) from exc

    def _retry_with_requested_context(
        self,
        issue: Issue,
        repository: str,
        target_ref: str,
        target_head_sha: str,
        access_token: str,
        pull_request: dict | None,
        previous_fix: GeneratedFix,
        validation_errors: list[str] | None = None,
    ) -> tuple[GeneratedFix, FixContext]:
        retry_context = self.context_builder.build(
            issue=issue,
            repository=repository,
            target_ref=target_ref,
            target_head_sha=target_head_sha,
            access_token=access_token,
            pull_request=pull_request,
            previous_fix=previous_fix,
            validation_errors=validation_errors,
            missing_symbols=previous_fix.missing_symbols,
            missing_files=previous_fix.missing_files,
        )
        return self._invoke_fix_model(retry_context), retry_context

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
        generated_fix: GeneratedFix,
        target_head_sha: str,
        file_sha: str,
    ) -> None:
        issue.fix_file_path = generated_fix.file_path
        issue.fix_start_line = generated_fix.start_line
        issue.fix_end_line = generated_fix.end_line
        issue.fix_replacement_code = generated_fix.replacement_code
        issue.fix_additional_edits = self._serialized_additional_edits(generated_fix)
        issue.fix_explanation = generated_fix.explanation
        issue.fix_status = IssueFixStatus.FIX_GENERATED.value
        issue.fix_base_commit_sha = target_head_sha
        issue.fix_file_sha = file_sha

    def _system_prompt(self) -> str:
        return f"""
You are a senior software engineer generating a safe code fix for a real GitHub Pull Request.

Your task is to fix the reported issue while preserving existing behaviour and following repository conventions.

Rules:
1. Use only the provided repository context.
2. Do not invent functions, classes, imports, fields, APIs or configuration.
3. Reuse existing helpers and patterns whenever possible.
4. Produce the smallest complete fix.
5. Preserve public interfaces unless the issue requires changing them.
6. Respect async and sync boundaries.
7. Respect current database transaction patterns.
8. Preserve error-handling conventions.
9. Consider all provided call sites and tests.
10. Do not modify unrelated code.
11. Do not add dependencies unless strictly necessary.
12. Do not suppress errors merely to make validation pass.
13. Do not use placeholder code, TODOs or pseudocode.
14. Ensure every referenced symbol exists in the supplied context.
15. Include imports only when required.
16. If one edit is insufficient, return explicit additional edits.
17. If the supplied context is insufficient, set requires_more_context=true and explain what is missing.
18. The replacement must exactly correspond to the supplied line range and original code.
19. Return only the structured schema.
20. Do not wrap output in Markdown.
21. Do not replace the entire enclosing function or method unless the issue requires it.
22. Preserve unrelated logic inside the enclosing symbol.
23. Verify that the replacement is valid in the complete enclosing symbol.
24. Preserve decorators, signatures, type annotations and async behaviour.
"""

    def _build_prompt(self, context: FixContext) -> str:
        return f"""
<repository>
name: {context.repository_name}
description: {context.repository_description or "N/A"}
default_branch: {context.default_branch or "N/A"}
language: {context.language or "Unknown"}
framework: {context.framework or "Unknown"}
architecture:
{self._bullets(context.architecture_summary)}
</repository>

<pull_request>
number: {context.pull_request_number or "N/A"}
title: {context.pull_request_title or "N/A"}
description:
{context.pull_request_description or "N/A"}
head_sha: {context.source_commit_sha}
relevant_diff:
{context.relevant_diff or "N/A"}
</pull_request>

<issue>
id: {context.issue_id}
file: {context.issue_file}
line_start: {context.issue_line_start}
line_end: {context.issue_line_end}
category: {context.issue_category}
severity: {context.issue_severity}
explanation: {context.issue_explanation}
impact: {context.issue_impact or "N/A"}
</issue>

<target_file>
path: {context.issue_file}
current_file_with_line_numbers:
{self._format_current_file(context.current_file_content)}
</target_file>

<target_code>
{context.original_code}
</target_code>

<enclosing_symbol>
Language: {context.structural_language or context.language or "Unknown"}
Parser: {context.structural_parser_used or "N/A"}
Structural extraction succeeded: {context.structural_extraction_succeeded}
Fallback reason: {context.structural_fallback_reason or "N/A"}
Name: {context.enclosing_symbol_name or context.enclosing_symbol or "N/A"}
Type: {context.enclosing_symbol_type or "N/A"}
Start line: {context.enclosing_symbol_start_line or "N/A"}
End line: {context.enclosing_symbol_end_line or "N/A"}
Enclosing class/component: {context.enclosing_class_name or "N/A"}
Class/component signature: {context.enclosing_class_signature or "N/A"}
Relevant class attributes or component hooks/state:
{self._bullets(context.enclosing_class_attributes)}

Complete code:
{self._format_enclosing_code(context)}
</enclosing_symbol>

<surrounding_code>
Local line context around the exact edit target:
{self._format_surrounding_code(context)}
</surrounding_code>

<imports>
{self._bullets(context.imports)}
</imports>

<related_context>
symbols:
{self._format_related_symbols(context)}

files:
{self._format_related_files(context)}

call_sites:
{self._format_call_sites(context)}
</related_context>

<tests>
{self._format_tests(context)}
</tests>

<repository_rules>
style_rules:
{self._bullets(context.style_rules)}

instructions:
{self._bullets(context.repository_instructions)}
</repository_rules>

<previous_attempt>
{self._format_previous_attempt(context)}
</previous_attempt>

<task>
Generate the smallest complete fix for this issue.

`original_code` is the exact edit target. `enclosing_code` provides semantic context,
`surrounding_code` provides local line context, the target file is broader fallback
context, and the Pull Request diff explains what changed.

Before returning the fix, verify internally that:
- all referenced symbols exist
- imports are correct
- the replacement matches the target range and original code
- existing call sites remain valid
- repository conventions are followed
- the issue is actually resolved

If required context is missing, set requires_more_context=true with missing_symbols, missing_files, and insufficient_context_reason.
</task>
"""

    def _numbered_file(self, file_content: str) -> str:
        return "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(file_content.splitlines(), start=1)
        )

    def _format_current_file(self, file_content: str) -> str:
        if file_content.startswith("Full target file omitted from prompt due context budget."):
            return file_content
        return self._numbered_file(file_content)

    def _format_enclosing_code(self, context: FixContext) -> str:
        return context.enclosing_code or "N/A; use the bounded surrounding-code fallback."

    def _format_surrounding_code(self, context: FixContext) -> str:
        if (
            context.enclosing_code
            and self._without_line_numbers(context.surrounding_code).strip()
            == context.enclosing_code.strip()
        ):
            return "Same as the complete enclosing code above; not repeated."
        return context.surrounding_code

    def _without_line_numbers(self, code: str) -> str:
        lines = []
        for line in code.splitlines():
            prefix, separator, content = line.partition(": ")
            lines.append(content if separator and prefix.isdigit() else line)
        return "\n".join(lines)

    def _bullets(self, values: list[str]) -> str:
        if not values:
            return "- None"
        return "\n".join(f"- {value}" for value in values)

    def _format_related_symbols(self, context: FixContext) -> str:
        if not context.related_symbols:
            return "- None"
        blocks = []
        for symbol in context.related_symbols:
            blocks.append(
                f"- {symbol.kind} {symbol.name} in {symbol.file_path}:{symbol.start_line or '?'}\n"
                f"  signature: {symbol.signature or 'N/A'}\n"
                f"  docstring: {symbol.docstring or 'N/A'}\n"
                f"  definition:\n{symbol.definition}"
            )
        return "\n\n".join(blocks)

    def _format_related_files(self, context: FixContext) -> str:
        if not context.related_files:
            return "- None"
        return "\n\n".join(
            f"- {file.file_path} ({file.reason})\n{self._numbered_file(file.content)}"
            for file in context.related_files
        )

    def _format_call_sites(self, context: FixContext) -> str:
        if not context.call_sites:
            return "- None"
        return "\n\n".join(
            f"- {call.file_path}:{call.line} calls {call.symbol}\n{call.surrounding_code}"
            for call in context.call_sites
        )

    def _format_tests(self, context: FixContext) -> str:
        if not context.tests:
            return "- None"
        return "\n\n".join(
            f"- {test.file_path} ({test.reason})\n{self._numbered_file(test.content)}"
            for test in context.tests
        )

    def _format_previous_attempt(self, context: FixContext) -> str:
        previous = context.previous_fix_attempt
        if previous is None and not context.previous_validation_errors:
            return "None"

        return f"""
Previous generated fix failed or requested more context. Do not repeat the same failed approach.

file_path: {previous.file_path if previous else "N/A"}
start_line: {previous.start_line if previous else "N/A"}
end_line: {previous.end_line if previous else "N/A"}
replacement_code:
{previous.replacement_code if previous else "N/A"}

validation_errors:
{self._bullets(context.previous_validation_errors)}
"""

    def _validate_generated_fix_against_context(
        self,
        generated_fix: GeneratedFix,
        context: FixContext,
    ) -> list[str]:
        errors = []
        if generated_fix.requires_more_context:
            errors.append(
                generated_fix.insufficient_context_reason
                or "The model reported that more context is required."
            )
            return errors

        if generated_fix.issue_id is not None and context.issue_id is not None and generated_fix.issue_id != context.issue_id:
            errors.append("Generated fix issue_id does not match the requested issue")

        if generated_fix.original_code is not None:
            original_code = self._extract_line_range(
                file_content=context.validation_file_content or context.current_file_content,
                start_line=generated_fix.start_line,
                end_line=generated_fix.end_line,
            )
            if generated_fix.original_code.strip("\n") != original_code.strip("\n"):
                errors.append("Generated fix original_code does not match the current target file")

        context_files = self._context_file_contents(context)
        for edit in generated_fix.additional_edits:
            file_content = context_files.get(edit.file_path)
            if file_content is None:
                errors.append(f"Additional edit file was not supplied in context: {edit.file_path}")
                continue
            if edit.original_code is not None:
                original_code = self._extract_line_range(
                    file_content=file_content,
                    start_line=edit.start_line,
                    end_line=edit.end_line,
                )
                if edit.original_code.strip("\n") != original_code.strip("\n"):
                    errors.append(
                        f"Additional edit original_code does not match current file: {edit.file_path}"
                    )

        verifier_result = self.verifier_service.verify(context, generated_fix)
        if not verifier_result.approved:
            errors.append(verifier_result.reason or "Generated fix was rejected by the verifier")

        return errors

    def _extract_line_range(
        self,
        file_content: str,
        start_line: int,
        end_line: int,
    ) -> str:
        lines = file_content.splitlines()
        if start_line < 1 or end_line > len(lines) or end_line < start_line:
            return ""
        return "\n".join(lines[start_line - 1:end_line])

    def _context_file_contents(self, context: FixContext) -> dict[str, str]:
        contents = {
            context.issue_file: context.validation_file_content or context.current_file_content
        }
        for file in context.related_files:
            contents[file.file_path] = file.content
        for test in context.tests:
            contents[test.file_path] = test.content
        return contents

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
        if hasattr(issue, "fix_additional_edits"):
            issue.fix_additional_edits = None
        issue.fix_explanation = None
        issue.fix_base_commit_sha = None
        issue.fix_file_sha = None
        issue.fix_status = IssueFixStatus.NO_FIX.value

    def _serialized_additional_edits(self, generated_fix: GeneratedFix) -> str | None:
        if not generated_fix.additional_edits:
            return None
        return json.dumps(
            [edit.model_dump() for edit in generated_fix.additional_edits],
            separators=(",", ":"),
        )


def _context_debug_enabled() -> bool:
    return os.getenv("CONTEXT_DEBUG", "").lower() == "true"
