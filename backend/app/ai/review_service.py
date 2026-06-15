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
                    Review this pull request diff.

                    Focus on:
                    - bugs
                    - security issues
                    - performance concerns
                    - readability
                    - edge cases

                    Severity MUST be one of:
                    - high
                    - medium
                    - low

                    Code Diff:
                    {diff_text}
                    """

    response = model.invoke(prompt)

    return response