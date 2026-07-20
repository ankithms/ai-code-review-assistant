import unittest
from unittest.mock import patch

from app.ai import review_service
from app.ai.review_service import review_service_prompt


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


class _FakeReviewModel:
    def __init__(self):
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return "ok"


if __name__ == "__main__":
    unittest.main()
