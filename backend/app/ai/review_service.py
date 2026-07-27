import os
import re

from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from app.ai.model_invocation import AIModelDeadlineExceeded, invoke_with_deadline
from app.schemas.output import ReviewResponseSchema
from app.schemas.review_context import ReviewContext

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    request_timeout=60,
    retries=2,
)

model = llm.with_structured_output(ReviewResponseSchema, method="json_schema")


class AIReviewServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        retryable: bool = True,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


def review_service_prompt() -> str:
    return f"""
You are a senior software engineer acting as a code reviewer for a GitHub Pull Request.

Your task is to review only the code introduced or modified in the provided GitHub Pull Request diff.
You are reviewing code within an existing repository.

Review scope:
{{review_scope}}

IMPORTANT RULES:
- Follow the repository's existing architecture and style.
- Do not report repository conventions as bugs.
- Do not recommend helpers, APIs, or abstractions absent from the supplied context.
- If repository context is insufficient, avoid speculative findings.
- Return only the existing structured review schema.
- Each supplied code line has a stable backend-generated line reference and explicit old/new file line metadata.
- Review only ADDED or otherwise modified lines in the diff.
- Prefer an ADDED line when the issue was introduced by this Pull Request.
- Use a CONTEXT line only when GitHub permits commenting there and it is necessary.
- Use a DELETED line only when the issue concerns removed code.
- Never return a hunk-header line or metadata line.
- Never invent a line reference.
- Return only the `line_ref` value present in the supplied annotated diff, for example `L7`.
- Do not return `new_file_line`, `old_file_line`, `NEW:<number>`, `OLD:<number>`, or an absolute line number as `line_ref`.
- The selected line reference must belong to the same file as the issue.
- Point to the most specific offending line, not merely the beginning of the function.
- Do not report issues that existed before this PR.
- Previously reported OPEN issues are provided below as context.
- Do not report an issue that matches the existing OPEN issue context unless the new diff introduces a genuinely new problem or materially changes the risk.
- Use surrounding context only to understand the change.
- Only flag issues that are likely to be real, actionable, and relevant to this change.
- Prefer precision over recall. Avoid noisy or stylistic comments unless they create a real correctness, security, maintainability, or performance risk.
- If no meaningful issues are found, return an empty issues list.

Focus on findings that materially affect:
- correctness or logic bugs
- security vulnerabilities
- performance issues
- maintainability problems that could cause future defects
- edge cases and failure modes

Do NOT flag:
- purely subjective style preferences
- naming nitpicks unless they create confusion or break conventions in a harmful way
- comments that are speculative without clear evidence from the diff

Severity guidance:
- high: likely security issue, data loss, broken functionality, or a serious production risk
- medium: meaningful correctness, reliability, or performance concern
- low: minor maintainability or clarity issue with limited impact

For each issue, provide:
- file_path exactly as shown after FILE:
- line_ref exactly as shown in the annotated diff
- severity
- category
- a concise, specific comment explaining the problem and why it matters
- a short suggested fix in the same comment under a "Suggested Fix:" label
- an optional short "Example:" section only when a minimal code example makes the fix materially clearer
- a concise impact sentence explaining what breaks or why the issue matters
- an optional structured fix only when a small, safe line-range replacement is obvious

Categories must be one of:
- security
- bug
- performance
- readability
- edge_case

Output requirements:
- Keep comments actionable and specific.
- Keep each comment concise, ideally 2-6 lines.
- Format each comment like this example:
  Dereferencing a nullable variable may raise an AttributeError.

  Suggested Fix:
  Check for None before accessing the attribute.

  Example:
  if user is not None:
      print(user.name)
- Include "Example:" only for concrete code transformations, such as null checks, missing imports, safer API usage, or corrected conditions.
- Omit "Example:" for findings where code would not add value, such as unclear naming, broad readability guidance, or conceptual explanations.
- Use a clear issue statement, then a separate "Suggested Fix:" section.
- Prefer short, practical guidance over long explanations.
- Do not include severity, category, impact, file, or line in the comment text; those are separate structured fields.
- Do not calculate or invent absolute GitHub line numbers.
- Return an impact sentence for each issue.
- For structured fixes, never rewrite an entire file. Provide only file_path, start_line, end_line, replacement_code, and explanation for the smallest safe replacement.
- When the correct fix is a small exact replacement in the same file and all referenced symbols are visible in the supplied diff/context, include a structured fix so GitHub can render an Apply suggestion button.
- Structured fixes may replace one changed line with multiple lines when that is the smallest complete fix.
- Omit structured fixes only when the correct code change is uncertain, references symbols not visible in the supplied diff/context, changes another file, or would require broad refactoring.
- Avoid duplicate findings.
- Do not include vague suggestions like "consider improving this".
- Be direct and evidence-based.

<repository_context>
{{repository_context}}
</repository_context>

<pull_request>
{{pull_request_context}}
</pull_request>

<file_context>
{{file_context}}
</file_context>

<existing_open_issues>
{{existing_issues_context}}
</existing_open_issues>

<annotated_diff>
{{diff_text}}
</annotated_diff>
"""


def review_code(
    diff_text,
    existing_issues_context: str | None = None,
    incremental: bool = False,
    review_context: ReviewContext | None = None,
):
    if review_context is not None:
        diff_text = review_context.annotated_diff
        existing_issues_context = review_context.existing_open_issues
        incremental = review_context.review_mode == "incremental"

    review_scope = (
        "This is an incremental review. The diff contains only changes introduced since the previous PR head commit. "
        "Focus exclusively on problems introduced by these latest changes."
        if incremental
        else "This is a full PR review. The diff contains the current pull request changes."
    )
    prompt = review_service_prompt().format(
        diff_text=diff_text,
        existing_issues_context=existing_issues_context or "None.",
        review_scope=review_scope,
        repository_context=_format_repository_context(review_context),
        pull_request_context=_format_pull_request_context(review_context),
        file_context=_format_file_context(review_context),
    )

    try:
        response = invoke_with_deadline(model, prompt)
    except Exception as exc:
        raise ai_service_error(
            exc,
            operation="AI review",
            retry_message="The review job will be retried.",
        ) from exc

    return response


def _format_repository_context(context: ReviewContext | None) -> str:
    if context is None:
        return "Repository context was not supplied."
    return f"""Repository: {context.repository_name}
Language: {context.language or "Unknown"}
Framework: {context.framework or "Unknown"}
Architecture:
{_bullets(context.architecture_summary)}
Style rules:
{_bullets(context.style_rules)}
Repository instructions:
{_bullets(context.repository_instructions)}"""


def _format_pull_request_context(context: ReviewContext | None) -> str:
    if context is None:
        return "Pull Request metadata was not supplied."
    return f"""Number: {context.pull_request_number or "N/A"}
Title: {context.pull_request_title or "N/A"}
Description: {context.pull_request_description or "N/A"}
Source branch: {context.source_branch or "N/A"}
Target branch: {context.target_branch or "N/A"}
Review mode: {context.review_mode}
HEAD SHA: {context.source_commit_sha}"""


def _format_file_context(context: ReviewContext | None) -> str:
    if context is None or not context.files:
        return "No additional per-file repository context was supplied."

    blocks = []
    for file in context.files:
        symbols = []
        for symbol in file.enclosing_symbols:
            symbols.append(
                f"Name: {symbol.name}\n"
                f"Type: {symbol.symbol_type}\n"
                f"Lines: {symbol.start_line}-{symbol.end_line}\n"
                f"Enclosing class/component: {symbol.class_name or 'N/A'}\n"
                f"Class/component signature: {symbol.class_signature or 'N/A'}\n"
                f"Complete code:\n{symbol.code}"
            )
        related = [
            f"{symbol.kind} {symbol.name} ({symbol.signature or 'N/A'}):\n{symbol.definition}"
            for symbol in file.related_symbols
        ]
        formatted_symbols = "\n\n".join(symbols) if symbols else "- None"
        formatted_related = "\n\n".join(related) if related else "- None"
        blocks.append(
            f"Path: {file.file_path}\n"
            f"Language: {file.language or 'Unknown'}\n"
            f"Parser: {file.parser_used or 'N/A'}\n"
            f"Structural extraction succeeded: {file.structural_extraction_succeeded}\n"
            f"Fallback reason: {file.fallback_reason or 'N/A'}\n"
            f"Relevant imports:\n{_bullets(file.relevant_imports)}\n"
            f"Enclosing symbols:\n{formatted_symbols}\n"
            f"Directly related symbols:\n{formatted_related}"
        )
    return "\n\n".join(blocks)


def _bullets(values: list[str]) -> str:
    if not values:
        return "- None"
    return "\n".join(f"- {value}" for value in values)


def ai_service_error(
    exc: Exception,
    *,
    operation: str,
    retry_message: str,
) -> AIReviewServiceError:
    error_text = str(exc)
    if isinstance(exc, AIModelDeadlineExceeded):
        return AIReviewServiceError(
            f"{operation} service timed out. {retry_message}",
            retryable=True,
        )

    if _is_quota_exhausted_error(error_text):
        retry_after = _retry_after_seconds(error_text)
        return AIReviewServiceError(
            (
                f"{operation} service quota was exhausted. "
                "Retry after quota resets or configure a higher quota/billing plan."
            ),
            retryable=False,
            retry_after_seconds=retry_after,
        )

    if _is_rate_limit_error(error_text):
        retry_after = _retry_after_seconds(error_text)
        retry_after_message = (
            f" Retry after about {retry_after} seconds."
            if retry_after is not None
            else ""
        )
        return AIReviewServiceError(
            f"{operation} service was rate limited.{retry_after_message}",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    if _is_temporary_availability_error(error_text):
        return AIReviewServiceError(
            (
                f"{operation} service is temporarily unavailable due to provider "
                f"capacity. {retry_message}"
            ),
            retryable=True,
        )

    return AIReviewServiceError(f"{operation} service failed", retryable=True)


def _is_quota_exhausted_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return (
        "resource_exhausted" in lowered
        and "quota" in lowered
        and (
            "perday" in lowered
            or "per day" in lowered
            or "free_tier_requests" in lowered
            or "billing" in lowered
        )
    )


def _is_rate_limit_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return "429" in lowered or "rate limit" in lowered or "resource_exhausted" in lowered


def _is_temporary_availability_error(error_text: str) -> bool:
    lowered = error_text.lower()
    return (
        "503" in lowered
        or "unavailable" in lowered
        or "high demand" in lowered
        or "service unavailable" in lowered
    )


def _retry_after_seconds(error_text: str) -> int | None:
    match = re.search(r"retry(?:Delay| in)?[': ]+\s*(?P<seconds>\d+)", error_text, flags=re.IGNORECASE)
    if match:
        return int(match.group("seconds"))

    match = re.search(r"retryDelay['\"]?:\s*['\"](?P<seconds>\d+)s", error_text)
    if match:
        return int(match.group("seconds"))

    return None
