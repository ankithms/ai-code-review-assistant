import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from app.schemas.output import CategoryEnum, SeverityEnum
from app.services import review_processing_service


class GithubCommentPostingTests(unittest.TestCase):
    def test_posts_inline_comment_using_pr_file_diff(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=2,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,2 +1,2 @@\n unchanged\n+new line",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment") as post_pr_comment,
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        post_inline_comment.assert_called_once()
        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["file_path"], "src/app.py")
        self.assertEqual(inline_kwargs["line"], 2)
        self.assertEqual(inline_kwargs["side"], "RIGHT")
        self.assertNotIn("position", inline_kwargs)

        post_pr_comment.assert_called_once()

    def test_existing_saved_review_is_reposted_without_running_ai(self):
        saved_review = SimpleNamespace(id=7, commit_sha="abc123", issues=[], summary="Saved summary")
        job = SimpleNamespace(
            id=3,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="abc123",
        )

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return saved_review

        db = SimpleNamespace(query=lambda model: Query())
        files = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+new line"}]

        with (
            patch.dict(os.environ, {"GITHUB_ACCESS_TOKEN": "token"}),
            patch.object(review_processing_service, "get_pr_files", return_value=files),
            patch.object(review_processing_service, "_post_github_comments") as post_github_comments,
            patch.object(review_processing_service, "get_pull_request") as get_pull_request,
            patch.object(review_processing_service, "review_code") as review_code,
            patch.object(review_processing_service, "save_review") as save_review,
        ):
            review_processing_service._process_pull_request_review(db, job)

        post_github_comments.assert_called_once_with(
            review=saved_review,
            files=files,
            files_reviewed=1,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="abc123",
            access_token="token",
        )
        get_pull_request.assert_not_called()
        review_code.assert_not_called()
        save_review.assert_not_called()

    def test_posts_saved_db_issue_with_string_severity_and_category(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=2,
                    severity="medium",
                    category="edge_case",
                    comment="This misses an edge case.",
                    confidence=0.87,
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,2 +1,2 @@\n unchanged\n+new line",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment"),
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        body = post_inline_comment.call_args.kwargs["body"]
        self.assertIn("MEDIUM\nConfidence: 87%", body)
        self.assertIn("This misses an edge case.", body)
        self.assertNotIn("[Edge Case]", body)

    def test_formats_inline_comment_with_suggested_fix_and_example(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            confidence=0.94,
            comment=(
                "Dereferencing a nullable variable may raise an AttributeError."
                "Suggested Fix: Check for None before accessing the attribute."
                "Example: if user is not None:\n    print(user.name)"
            ),
        )

        body = review_processing_service._format_issue_comment_body(issue)

        self.assertEqual(
            body,
            "HIGH\n"
            "Confidence: 94%\n"
            "\n"
            "Dereferencing a nullable variable may raise an AttributeError.\n"
            "\n"
            "Suggested Fix:\n"
            "Check for None before accessing the attribute.\n"
            "\n"
            "Example:\n"
            "```\n"
            "if user is not None:\n"
            "    print(user.name)\n"
            "```",
        )

    def test_skips_inline_comment_when_line_is_not_in_pr_diff(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=10,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line is outside the patch.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,2 +1,2 @@\n unchanged\n+new line",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment") as post_pr_comment,
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        self.assertEqual(post_pr_comment.call_count, 2)
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("`src/app.py:10`", fallback_body)
        self.assertIn("Inline comment unavailable", fallback_body)

    def test_posts_inline_comment_on_visible_context_line(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="calculator.py",
                    line=8,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This can raise an AttributeError.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "calculator.py",
                "patch": "@@ -6,3 +6,4 @@\n user = None\n \n print(user.name)\n+",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment"),
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["line"], 8)
        self.assertEqual(inline_kwargs["side"], "RIGHT")

    def test_blank_line_issue_anchors_to_nearby_code_line(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="calculator.py",
                    line=9,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This can raise an AttributeError.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "calculator.py",
                "patch": "@@ -6,3 +6,4 @@\n user = None\n \n print(user.name)\n+",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment"),
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["start_line"], 8)
        self.assertEqual(inline_kwargs["start_side"], "RIGHT")
        self.assertEqual(inline_kwargs["line"], 9)
        self.assertEqual(inline_kwargs["side"], "RIGHT")

    def test_issue_line_near_hunk_anchors_to_nearest_visible_code_line(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=3,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line is close to the change.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,3 +1,3 @@\n value = 1\n+value = 2\n",
            }
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment"),
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["line"], 2)
        self.assertEqual(inline_kwargs["side"], "RIGHT")

    def test_inline_comment_failure_retries_with_diff_position(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=2,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,2 +1,2 @@\n unchanged\n+new line",
            }
        ]

        with (
            patch.object(
                review_processing_service,
                "post_inline_comment",
                side_effect=[
                    RuntimeError(
                        'GitHub inline comment failed: 422 {"message":"Validation Failed"}'
                    ),
                    {"id": 1},
                ],
            ) as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment") as post_pr_comment,
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        self.assertEqual(post_inline_comment.call_count, 2)
        fallback_kwargs = post_inline_comment.call_args_list[1].kwargs
        self.assertEqual(fallback_kwargs["position"], 2)
        self.assertNotIn("line", fallback_kwargs)
        post_pr_comment.assert_called_once()

    def test_inline_comment_failure_posts_fallback_pr_comment(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=2,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "patch": "@@ -1,2 +1,2 @@\n unchanged\n+new line",
            }
        ]

        with (
            patch.object(
                review_processing_service,
                "post_inline_comment",
                side_effect=RuntimeError(
                    'GitHub inline comment failed: 422 {"message":"Validation Failed"}'
                ),
            ) as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment") as post_pr_comment,
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=1,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                access_token="token",
            )

        self.assertEqual(post_inline_comment.call_count, 2)
        self.assertEqual(post_pr_comment.call_count, 2)
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("`src/app.py:2`", fallback_body)
        self.assertIn("GitHub rejected the inline comment", fallback_body)


if __name__ == "__main__":
    unittest.main()
