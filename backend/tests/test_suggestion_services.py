import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.schemas.output import CategoryEnum, SeverityEnum
from app.services import review_processing_service
from app.services.suggestion_eligibility_service import (
    LARGE_FIX_FALLBACK_MESSAGE,
    SuggestionEligibilityService,
)
from app.services.suggestion_formatter import SuggestionFormatter


def _issue(**overrides):
    defaults = {
        "id": 1,
        "file": "app.py",
        "line": 2,
        "severity": SeverityEnum.high,
        "category": CategoryEnum.bug,
        "comment": "The current code returns the wrong value.",
        "impact": "The caller receives incorrect data.",
        "fix_file_path": "app.py",
        "fix_start_line": 2,
        "fix_end_line": 2,
        "fix_replacement_code": "    return value + 1",
        "fix_file_sha": None,
        "github_comment_id": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _files():
    return [
        {
            "filename": "app.py",
            "patch": "@@ -1,2 +1,2 @@\n def inc(value):\n+    return value\n",
        }
    ]


def _content():
    return {
        "path": "app.py",
        "sha": "file-sha",
        "content": "def inc(value):\n    return value\n",
    }


class SuggestionFormatterTests(unittest.TestCase):
    def test_preserves_indentation_blank_lines_and_line_endings(self):
        replacement = "    if value:\r\n\r\n        return value\r\n"

        markdown = SuggestionFormatter().format_suggestion(replacement)

        self.assertEqual(markdown, "```suggestion\n" + replacement + "```")

    def test_escapes_markdown_fence_collisions(self):
        replacement = '    return "```"\n'

        markdown = SuggestionFormatter().format_suggestion(replacement)

        self.assertEqual(markdown, '````suggestion\n    return "```"\n````')


class SuggestionEligibilityServiceTests(unittest.TestCase):
    def test_eligible_fix_generates_suggestion(self):
        issue = _issue()
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=issue,
            all_issues=[issue],
            files=_files(),
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertTrue(result.eligible)
        self.assertEqual(result.anchor, {"line": 2, "side": "RIGHT"})
        self.assertEqual(result.markdown, "```suggestion\n    return value + 1\n```")

    def test_multiline_single_block_fix_is_eligible(self):
        replacement = (
            "import aiohttp\n\n"
            "async def fetch_data():\n"
            "    try:\n"
            "        async with aiohttp.ClientSession() as session:\n"
            "            async with session.get('https://api.example.com') as response:\n"
            "                response.raise_for_status()\n"
            "                return await response.json()\n"
            "    except aiohttp.ClientError:\n"
            "        return None"
        )
        issue = _issue(
            file="calculator.py",
            line=10,
            fix_file_path="calculator.py",
            fix_start_line=10,
            fix_end_line=12,
            fix_replacement_code=replacement,
        )
        service = SuggestionEligibilityService(
            file_content_provider=lambda **_: {
                "path": "calculator.py",
                "sha": "file-sha",
                "content": (
                    "value = 1\n" * 9
                    + "async def fetch_data():\n"
                    + "    response = requests.get('https://api.example.com')\n"
                    + "    return response.json()\n"
                ),
            }
        )

        result = service.evaluate(
            issue=issue,
            all_issues=[issue],
            files=[
                {
                    "filename": "calculator.py",
                    "patch": (
                        "@@ -10,3 +10,3 @@\n"
                        "+async def fetch_data():\n"
                        "+    response = requests.get('https://api.example.com')\n"
                        "+    return response.json()\n"
                    ),
                }
            ],
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertTrue(result.eligible)
        self.assertEqual(
            result.anchor,
            {
                "start_line": 10,
                "start_side": "RIGHT",
                "line": 12,
                "side": "RIGHT",
            },
        )
        self.assertIn("```suggestion\nimport aiohttp", result.markdown)

    def test_multi_file_fix_is_rejected(self):
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=_issue(fix_file_path="other.py"),
            all_issues=[],
            files=_files(),
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertFalse(result.eligible)
        self.assertIn("different file", result.reason)

    def test_overlapping_edits_are_rejected(self):
        issue = _issue(id=1, fix_start_line=2, fix_end_line=3)
        other_issue = _issue(id=2, fix_start_line=3, fix_end_line=4)
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=issue,
            all_issues=[issue, other_issue],
            files=[
                {
                    "filename": "app.py",
                    "patch": "@@ -1,4 +1,4 @@\n def inc(value):\n+    return value\n+    return value\n+    return value\n",
                }
            ],
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertFalse(result.eligible)
        self.assertIn("overlaps", result.reason)

    def test_stale_sha_is_rejected(self):
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=_issue(),
            all_issues=[],
            files=_files(),
            repository="owner/repo",
            source_commit_sha="old-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertFalse(result.eligible)
        self.assertIn("current PR HEAD", result.reason)

    def test_invalid_syntax_is_rejected(self):
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=_issue(fix_replacement_code="    return ("),
            all_issues=[],
            files=_files(),
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertFalse(result.eligible)
        self.assertIn("syntactically valid", result.reason)

    def test_lines_outside_diff_are_rejected(self):
        service = SuggestionEligibilityService(file_content_provider=lambda **_: _content())

        result = service.evaluate(
            issue=_issue(fix_start_line=3, fix_end_line=3),
            all_issues=[],
            files=_files(),
            repository="owner/repo",
            source_commit_sha="head-sha",
            current_head_sha="head-sha",
            access_token="token",
        )

        self.assertFalse(result.eligible)
        self.assertIn("PR diff", result.reason)

    def test_fallback_comment_uses_large_fix_message(self):
        body = review_processing_service._format_issue_comment_body(
            _issue(
                fix_start_line=1,
                fix_end_line=12,
                fix_replacement_code="\n".join(f"line_{index}" for index in range(12)),
            ),
            suggestion_rejection_reason=LARGE_FIX_FALLBACK_MESSAGE,
        )

        self.assertNotIn("```suggestion", body)
        self.assertIn(LARGE_FIX_FALLBACK_MESSAGE, body)
        self.assertIn("Reply `/ai-fix`", body)

    def test_duplicate_suggestion_is_not_reposted(self):
        issue = _issue(github_comment_id=123)
        review = SimpleNamespace(issues=[issue], summary="Review summary")

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment") as post_pr_comment,
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=_files(),
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="head-sha",
                current_head_sha="head-sha",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        post_pr_comment.assert_called_once()


if __name__ == "__main__":
    unittest.main()
