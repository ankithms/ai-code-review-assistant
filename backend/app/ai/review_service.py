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


def review_code(diff_text):

    prompt = f"""
You are a senior software engineer acting as a code reviewer for a GitHub Pull Request.

Your task is to review only the code introduced or modified in the provided diff.

IMPORTANT RULES:
- Review only added (+) or modified lines in the diff.
- Do not comment on unchanged context lines.
- Do not report issues that existed before this PR.
- Use surrounding context only to understand the change.
- Only flag issues that are likely to be real, actionable, and relevant to this change.
- Prefer precision over recall. Avoid noisy or stylistic comments unless they create a real correctness, security, maintainability, or performance risk.
- Only use line numbers that correspond to added or modified lines in the diff.
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
- file name
- line number
- severity
- category
- a concise, specific comment explaining the problem and why it matters

Categories must be one of:
- security
- bug
- performance
- readability
- edge_case

Output requirements:
- Keep comments actionable and specific.
- Avoid duplicate findings.
- Do not include vague suggestions like "consider improving this".
- Be direct and evidence-based.

Code Diff:
{diff_text}
"""

    try:
        response = model.invoke(prompt)
    except Exception as exc:
        raise RuntimeError("AI review service failed") from exc

    return response