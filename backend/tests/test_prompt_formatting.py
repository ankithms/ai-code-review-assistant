import unittest

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
        self.assertNotIn("confidence score", prompt.lower())


if __name__ == "__main__":
    unittest.main()
