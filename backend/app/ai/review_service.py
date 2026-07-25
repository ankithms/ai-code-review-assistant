import os

from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from app.schemas.output import ReviewResponseSchema

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    request_timeout=60,
    retries=2,
)

model = llm.with_structured_output(ReviewResponseSchema)


def review_service_prompt() -> str:
    return f"""
You are a senior software engineer acting as a code reviewer for a GitHub Pull Request.

Your task is to review only the code introduced or modified in the provided GitHub Pull Request diff.

Review scope:
{{review_scope}}

IMPORTANT RULES:
- Each supplied code line has a stable backend-generated line reference and explicit old/new file line metadata.
- Review only ADDED or otherwise modified lines in the diff.
- Prefer an ADDED line when the issue was introduced by this Pull Request.
- Use a CONTEXT line only when GitHub permits commenting there and it is necessary.
- Use a DELETED line only when the issue concerns removed code.
- Never return a hunk-header line or metadata line.
- Never invent a line reference.
- Return only line references present in the supplied annotated diff.
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
- Omit structured fixes when the correct code change is uncertain or would require broad refactoring.
- Avoid duplicate findings.
- Do not include vague suggestions like "consider improving this".
- Be direct and evidence-based.

Existing OPEN issues for this PR:
{{existing_issues_context}}

Code Diff:
{{diff_text}}
"""


def review_code(
    diff_text,
    existing_issues_context: str | None = None,
    incremental: bool = False,
):
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
    )

    try:
        response = model.invoke(prompt)
    except Exception as exc:
        raise RuntimeError("AI review service failed") from exc

    return response
