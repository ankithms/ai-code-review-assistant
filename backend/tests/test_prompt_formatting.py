import unittest

from app.ai.review_service import review_service_prompt


class ReviewPromptFormattingTests(unittest.TestCase):
    def test_prompt_includes_short_suggested_fix_guidance(self):
        prompt = review_service_prompt()

        self.assertIn("short suggested fix", prompt.lower())
        self.assertIn("keep each comment concise", prompt.lower())
        self.assertIn("suggested fix:", prompt.lower())
        self.assertIn("example:", prompt.lower())
        self.assertIn("do not include severity, category, confidence, file, or line", prompt.lower())


if __name__ == "__main__":
    unittest.main()
