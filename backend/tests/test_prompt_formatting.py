import unittest
import asyncio
from unittest.mock import patch

from app.ai import review_service
from app.ai.review_service import AIReviewServiceError, review_service_prompt


class ReviewPromptFormattingTests(unittest.TestCase):
    def test_prompt_includes_short_suggested_fix_guidance(self):
        prompt = review_service_prompt()

        self.assertIn("short suggested fix", prompt.lower())
        self.assertIn("keep each comment concise", prompt.lower())
        self.assertIn("suggested fix:", prompt.lower())
        self.assertIn("optional short \"example:\" section", prompt.lower())
        self.assertIn("include \"example:\" only for concrete code transformations", prompt.lower())
        self.assertIn("omit \"example:\" for findings where code would not add value", prompt.lower())
        self.assertIn("impact sentence", prompt.lower())
        self.assertIn("do not include severity, category, impact, file, or line", prompt.lower())
        self.assertIn("previously reported open issues", prompt.lower())
        self.assertIn("review scope", prompt.lower())
        self.assertIn("return only the `line_ref` value", prompt.lower())
        self.assertIn("do not return `new_file_line`", prompt.lower())
        self.assertIn("include a structured fix so github can render an apply suggestion button", prompt.lower())
        self.assertIn("replace one changed line with multiple lines", prompt.lower())
        self.assertNotIn("confidence score", prompt.lower())

    def test_incremental_review_prompt_includes_scope_and_existing_issue_context(self):
        fake_model = _FakeReviewModel()

        with patch.object(review_service, "model", fake_model):
            response = review_service.review_code(
                "FILE: src/app.py\n+print(user.name)",
                existing_issues_context="- src/app.py:2 [medium/bug] Existing nullable dereference.",
                incremental=True,
            )

        self.assertEqual(response, "ok")
        prompt = fake_model.prompt
        self.assertIn("This is an incremental review", prompt)
        self.assertIn("Focus exclusively on problems introduced by these latest changes", prompt)
        self.assertIn("Existing nullable dereference", prompt)
        self.assertIn("+print(user.name)", prompt)

    def test_quota_exhaustion_is_reported_as_non_retryable_ai_error(self):
        fake_model = _FakeReviewModel(
            error=RuntimeError(
                "429 RESOURCE_EXHAUSTED: quota exceeded for "
                "GenerateRequestsPerDayPerProjectPerModel-FreeTier. Please retry in 27s."
            )
        )

        with patch.object(review_service, "model", fake_model):
            with self.assertRaises(AIReviewServiceError) as context:
                review_service.review_code("FILE: src/app.py\n+print(user.name)")

        self.assertFalse(context.exception.retryable)
        self.assertIn("quota was exhausted", str(context.exception))

    def test_temporary_provider_unavailability_is_reported_as_retryable(self):
        fake_model = _FakeReviewModel(
            error=RuntimeError(
                "503 UNAVAILABLE: This model is currently experiencing high demand. "
                "Please try again later."
            )
        )

        with patch.object(review_service, "model", fake_model):
            with self.assertRaises(AIReviewServiceError) as context:
                review_service.review_code("FILE: src/app.py\n+print(user.name)")

        self.assertTrue(context.exception.retryable)
        self.assertIn("temporarily unavailable", str(context.exception))
        self.assertIn("will be retried", str(context.exception))

    def test_model_invocation_deadline_is_reported_as_retryable(self):
        fake_model = _SlowAsyncReviewModel()

        with (
            patch.object(review_service, "model", fake_model),
            patch.dict("os.environ", {"AI_MODEL_DEADLINE_SECONDS": "0.01"}),
        ):
            with self.assertRaises(AIReviewServiceError) as context:
                review_service.review_code("FILE: src/app.py\n+print(user.name)")

        self.assertTrue(context.exception.retryable)
        self.assertIn("service timed out", str(context.exception))
        self.assertIn("will be retried", str(context.exception))


class _SlowAsyncReviewModel:
    async def ainvoke(self, prompt, **kwargs):
        await asyncio.sleep(0.1)
        return "late response"


class _FakeReviewModel:
    def __init__(self, error=None):
        self.prompt = None
        self.error = error

    def invoke(self, prompt):
        self.prompt = prompt
        if self.error:
            raise self.error
        return "ok"


if __name__ == "__main__":
    unittest.main()
