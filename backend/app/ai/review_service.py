import os
import json

from langchain_google_genai import ChatGoogleGenerativeAI
from dotenv import load_dotenv

from app.schemas.output import ReviewResponseSchema

load_dotenv()

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

model = llm.with_structured_output(ReviewResponseSchema)


def review_code(diff_text):

    prompt = f"""
You are an experienced code reviewer reviewing a GitHub Pull Request.

Review ONLY code that was added (+) or modified in this diff.

IMPORTANT RULES:
- Do NOT report issues on unchanged context lines.
- Do NOT report issues that existed before this PR.
- Use surrounding context only to understand the change.
- Only create findings for code introduced by this PR.
- Only use line numbers that correspond to added or modified lines in the diff.
- If no issues are found, return an empty issues list.

Focus on:
- bugs
- security vulnerabilities
- performance concerns
- readability issues
- edge cases

Severity MUST be one of:
- high
- medium
- low

For each issue provide:
- file name
- line number
- severity
- category
- comment

Code Diff:
{diff_text}
"""

    response = model.invoke(prompt)

    return response