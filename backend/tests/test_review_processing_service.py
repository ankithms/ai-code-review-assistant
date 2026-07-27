import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

os.environ.setdefault("GOOGLE_API_KEY", "test-key")

from app.db.models import Base, PullRequest, Repository
from app.ai.review_service import AIReviewServiceError
from app.schemas.output import CategoryEnum, SeverityEnum
from app.services import review_processing_service


class GithubCommentPostingTests(unittest.TestCase):
    def test_posts_line_ref_issue_on_added_line_with_right_side(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="L2",
                    line=None,
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
                "patch": "@@ -1,2 +1,3 @@\n unchanged\n+new line\n tail",
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
                current_head_sha="abc123",
                access_token="token",
            )

        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["line"], 2)
        self.assertEqual(inline_kwargs["side"], "RIGHT")
        self.assertNotIn("position", inline_kwargs)
        post_pr_comment.assert_called_once()

    def test_posts_line_ref_issue_on_deleted_line_with_left_side(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="L2",
                    line=None,
                    severity=SeverityEnum.medium,
                    category=CategoryEnum.bug,
                    comment="This deleted line matters.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {
                "filename": "src/app.py",
                "status": "modified",
                "patch": "@@ -8,2 +8,1 @@\n keep\n-remove_me()",
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
                current_head_sha="abc123",
                access_token="token",
            )

        inline_kwargs = post_inline_comment.call_args.kwargs
        self.assertEqual(inline_kwargs["line"], 9)
        self.assertEqual(inline_kwargs["side"], "LEFT")
        self.assertNotIn("position", inline_kwargs)

    def test_invalid_line_ref_is_rejected(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="L99",
                    line=None,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+new line"}]

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
                current_head_sha="abc123",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("line reference does not exist", fallback_body)

    def test_hunk_header_reference_is_rejected(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="@@ -1 +1 @@",
                    line=None,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+new line"}]

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
                current_head_sha="abc123",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("line reference does not exist", fallback_body)

    def test_multiple_files_do_not_share_line_refs(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="b.py",
                    file="b.py",
                    line_ref="L1",
                    line=None,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [
            {"filename": "a.py", "patch": "@@ -10 +10 @@\n+first"},
            {"filename": "b.py", "patch": "@@ -50 +50 @@\n+second"},
        ]

        with (
            patch.object(review_processing_service, "post_inline_comment") as post_inline_comment,
            patch.object(review_processing_service, "post_pr_comment"),
        ):
            review_processing_service._post_github_comments(
                review=review,
                files=files,
                files_reviewed=2,
                repository="owner/repo",
                pull_request_number=12,
                commit_sha="abc123",
                current_head_sha="abc123",
                access_token="token",
            )

        self.assertEqual(post_inline_comment.call_args.kwargs["file_path"], "b.py")
        self.assertEqual(post_inline_comment.call_args.kwargs["line"], 50)

    def test_stale_commit_sha_prevents_posting(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="L1",
                    line=None,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+new line"}]

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
                commit_sha="oldsha",
                current_head_sha="newsha",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("current PR HEAD", fallback_body)

    def test_verification_mode_builds_payload_without_posting(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file_path="src/app.py",
                    file="src/app.py",
                    line_ref="L1",
                    line=None,
                    severity=SeverityEnum.high,
                    category=CategoryEnum.bug,
                    comment="This line can fail.",
                )
            ],
            summary="Review summary",
        )
        files = [{"filename": "src/app.py", "patch": "@@ -1 +1 @@\n+new line"}]

        with (
            patch.dict(os.environ, {"VERIFY_INLINE_COMMENTS_ONLY": "true"}),
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
                current_head_sha="abc123",
                access_token="token",
            )

        post_inline_comment.assert_not_called()
        post_pr_comment.assert_not_called()
        self.assertEqual(review.issues[0].line, 1)

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

    def test_persists_github_thread_metadata_after_inline_comment_posts(self):
        issue = SimpleNamespace(
            file="src/app.py",
            line=2,
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            comment="This line can fail.",
        )
        review = SimpleNamespace(
            issues=[issue],
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
                return_value={
                    "id": 123,
                    "node_id": "comment-node",
                    "pull_request_review_id": 456,
                },
            ),
            patch.object(
                review_processing_service,
                "get_review_thread_for_comment",
                return_value={
                    "id": "thread-node",
                    "comment_node_id": "graphql-comment-node",
                },
            ) as get_review_thread_for_comment,
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

        get_review_thread_for_comment.assert_called_once_with(
            repository="owner/repo",
            pull_request_number=12,
            access_token="token",
            comment_id=123,
        )
        self.assertEqual(issue.github_comment_id, 123)
        self.assertEqual(issue.github_comment_node_id, "graphql-comment-node")
        self.assertEqual(issue.github_review_id, 456)
        self.assertEqual(issue.github_review_thread_id, "thread-node")

    def test_ensure_pull_request_record_backfills_missing_pull_request_number(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(engine)

        try:
            repository = Repository(full_name="owner/repo")
            session.add(repository)
            session.flush()

            existing_pr = PullRequest(
                repository_id=repository.id,
                github_pr_id=99,
                pull_request_number=None,
                title="Old title",
                repository=repository.full_name,
                author="octocat",
            )
            session.add(existing_pr)
            session.commit()

            review_processing_service._ensure_pull_request_record(
                db=session,
                repository_full_name="owner/repo",
                pull_request_number=42,
                github_pr_id=99,
                title="Updated title",
                author="hubot",
            )

            session.refresh(existing_pr)
            self.assertEqual(existing_pr.pull_request_number, 42)
            self.assertEqual(existing_pr.title, "Updated title")
            self.assertEqual(existing_pr.author, "hubot")
        finally:
            session.close()

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
            patch.object(
                review_processing_service,
                "get_pull_request",
                return_value={"head": {"sha": "abc123"}},
            ) as get_pull_request,
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
            current_head_sha="abc123",
            access_token="token",
        )
        get_pull_request.assert_called_once()
        review_code.assert_not_called()
        save_review.assert_not_called()

    def test_non_retryable_ai_quota_failure_marks_job_failed_without_reraising(self):
        job = SimpleNamespace(
            id=50,
            status="PENDING",
            repository="owner/repo",
            pull_request_number=49,
            commit_sha="abc123",
        )
        db = SimpleNamespace(
            rollback=lambda: None,
            close=lambda: None,
        )
        quota_error = AIReviewServiceError(
            "AI review service quota was exhausted.",
            retryable=False,
        )

        with (
            patch.object(review_processing_service, "SessionLocal", return_value=db),
            patch.object(review_processing_service, "get_review_job", return_value=job),
            patch.object(review_processing_service, "mark_review_job_running"),
            patch.object(review_processing_service, "_process_pull_request_review", side_effect=quota_error),
            patch.object(review_processing_service, "mark_review_job_failed") as mark_failed,
        ):
            review_processing_service.process_review_job(50)

        mark_failed.assert_called_once_with(db, job, str(quota_error))

    def test_retryable_ai_failure_does_not_post_permanent_failure_comment(self):
        job = SimpleNamespace(
            id=51,
            repository="owner/repo",
            pull_request_number=49,
            commit_sha="abc123",
            event_action="opened",
            base_commit_sha=None,
            head_commit_sha="abc123",
        )
        retryable_error = AIReviewServiceError(
            "AI review service is temporarily unavailable.",
            retryable=True,
        )

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        files = [
            {
                "filename": "src/app.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n+value = 1",
            }
        ]
        pull_request = {
            "id": 99,
            "title": "PR title",
            "user": {"login": "octocat"},
            "head": {"sha": "abc123"},
        }

        with (
            patch.dict(os.environ, {"GITHUB_ACCESS_TOKEN": "token"}),
            patch.object(review_processing_service, "get_pr_files", return_value=files),
            patch.object(review_processing_service, "get_pull_request", return_value=pull_request),
            patch.object(
                review_processing_service,
                "_ensure_pull_request_record",
                return_value=SimpleNamespace(repository_id=5),
            ),
            patch.object(
                review_processing_service,
                "get_open_issues_for_pull_request",
                return_value=[],
            ),
            patch.object(
                review_processing_service.ReviewContextBuilder,
                "build",
                return_value=Mock(),
            ),
            patch.object(
                review_processing_service,
                "review_code",
                side_effect=retryable_error,
            ),
            patch.object(review_processing_service, "_post_ai_failure_comment") as post_failure,
        ):
            with self.assertRaises(AIReviewServiceError) as context:
                review_processing_service._process_pull_request_review(db, job)

        self.assertIs(context.exception, retryable_error)
        post_failure.assert_not_called()

    def test_duplicate_only_review_is_saved_without_posting_github_comments(self):
        issue = SimpleNamespace(
            file="calculator.py",
            line=2,
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            comment="Dereferencing a nullable user may raise an AttributeError.",
            impact="The request can crash when the user lookup returns None.",
        )
        ai_review = SimpleNamespace(
            summary="Review summary",
            issues=[issue],
        )
        previous_review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="calculator.py",
                    line=2,
                    category=CategoryEnum.bug,
                    comment="Dereferencing a nullable user may raise an AttributeError.",
                    impact="The request can crash when the user lookup returns None.",
                )
            ],
        )
        job = SimpleNamespace(
            id=3,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="def456",
        )

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        files = [{"filename": "calculator.py", "patch": "@@ -1,2 +1,2 @@\n user = None\n print(user.name)"}]
        pull_request = {
            "id": 99,
            "title": "PR title",
            "user": {"login": "octocat"},
        }

        with (
            patch.dict(os.environ, {"GITHUB_ACCESS_TOKEN": "token"}),
            patch.object(review_processing_service, "get_pr_files", return_value=files),
            patch.object(review_processing_service, "get_pull_request", return_value=pull_request),
            patch.object(review_processing_service.ReviewContextBuilder, "build", return_value=Mock()),
            patch.object(review_processing_service, "review_code", return_value=ai_review),
            patch.object(
                review_processing_service,
                "get_latest_review_for_pull_request",
                return_value=previous_review,
            ),
            patch.object(
                review_processing_service,
                "get_open_issues_for_pull_request",
                return_value=[],
            ),
            patch.object(review_processing_service, "_ensure_pull_request_record") as ensure_pr,
            patch.object(review_processing_service, "_post_github_comments") as post_github_comments,
            patch.object(review_processing_service, "save_review") as save_review,
        ):
            review_processing_service._process_pull_request_review(db, job)

        ensure_pr.assert_called_once()
        post_github_comments.assert_not_called()
        save_review.assert_called_once()
        self.assertEqual(save_review.call_args.kwargs["review_data"].issues, [])
        self.assertEqual(save_review.call_args.kwargs["commit_sha"], "def456")
        self.assertEqual(save_review.call_args.kwargs["pr_data"].pull_request_number, 12)

    def test_synchronize_review_uses_compare_diff_and_open_issue_context(self):
        new_issue = SimpleNamespace(
            file="src/app.py",
            line=4,
            severity=SeverityEnum.high,
            category=CategoryEnum.security,
            comment="Interpolating user input into SQL can allow injection.",
            impact="An attacker can alter the query.",
        )
        ai_review = SimpleNamespace(
            summary="Review summary",
            issues=[new_issue],
        )
        open_issue = SimpleNamespace(
            id=1,
            file="src/app.py",
            line=2,
            severity="medium",
            category="bug",
            comment="Dereferencing a nullable user may raise an AttributeError.",
            impact="The request can crash.",
        )
        job = SimpleNamespace(
            id=3,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="newsha",
            event_action="synchronize",
            base_commit_sha="oldsha",
            head_commit_sha="newsha",
        )

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        compare_files = [
            {
                "filename": "src/app.py",
                "status": "modified",
                "patch": "@@ -1,3 +1,4 @@\n user = None\n print(user.name)\n+query = f\"SELECT {user_id}\"",
            },
            {
                "filename": "src/old.py",
                "status": "removed",
                "patch": "@@ -1 +0,0 @@\n-old = True",
            },
            {
                "filename": "assets/logo.png",
                "status": "modified",
            },
        ]
        pull_request = {
            "id": 99,
            "title": "PR title",
            "user": {"login": "octocat"},
        }

        with (
            patch.dict(os.environ, {"GITHUB_ACCESS_TOKEN": "token"}),
            patch.object(review_processing_service, "get_compare_files", return_value=compare_files) as get_compare_files,
            patch.object(review_processing_service, "get_pr_files") as get_pr_files,
            patch.object(review_processing_service, "get_pull_request", return_value=pull_request),
            patch.object(review_processing_service.ReviewContextBuilder, "build", return_value=Mock()),
            patch.object(review_processing_service, "_ensure_pull_request_record", return_value=SimpleNamespace(repository_id=5)),
            patch.object(review_processing_service, "get_open_issues_for_pull_request", return_value=[open_issue]),
            patch.object(review_processing_service, "get_latest_review_for_pull_request", return_value=None),
            patch.object(review_processing_service, "review_code", return_value=ai_review) as review_code,
            patch.object(review_processing_service, "_post_github_comments") as post_github_comments,
            patch.object(review_processing_service, "save_review") as save_review,
        ):
            review_processing_service._process_pull_request_review(db, job)

        get_compare_files.assert_called_once_with(
            repository="owner/repo",
            base_commit_sha="oldsha",
            head_commit_sha="newsha",
            access_token="token",
        )
        get_pr_files.assert_not_called()
        review_code.assert_called_once()
        self.assertTrue(review_code.call_args.kwargs["incremental"])
        self.assertIn("src/app.py:2", review_code.call_args.kwargs["existing_issues_context"])
        self.assertIn("Dereferencing a nullable user", review_code.call_args.kwargs["existing_issues_context"])
        self.assertIn("query = f", review_code.call_args.args[0])
        self.assertIn("src/old.py", review_code.call_args.args[0])
        self.assertNotIn("assets/logo.png", review_code.call_args.args[0])
        post_github_comments.assert_called_once()
        self.assertEqual(save_review.call_args.kwargs["review_data"].issues, [new_issue])

    def test_opened_review_uses_full_pr_diff(self):
        job = SimpleNamespace(
            id=3,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="newsha",
            event_action="opened",
            base_commit_sha=None,
            head_commit_sha="newsha",
        )
        files = [
            {
                "filename": "src/app.py",
                "status": "modified",
                "patch": "@@ -1 +1 @@\n+value = 1",
            }
        ]

        with (
            patch.object(review_processing_service, "get_pr_files", return_value=files) as get_pr_files,
            patch.object(review_processing_service, "get_compare_files") as get_compare_files,
        ):
            reviewable_files = review_processing_service._get_files_for_review(job, "token")

        get_pr_files.assert_called_once_with(
            repository="owner/repo",
            pull_request_number=12,
            access_token="token",
        )
        get_compare_files.assert_not_called()
        self.assertEqual(reviewable_files, files)

    def test_synchronize_review_with_no_reviewable_files_saves_empty_review(self):
        job = SimpleNamespace(
            id=3,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="newsha",
            event_action="synchronize",
            base_commit_sha="oldsha",
            head_commit_sha="newsha",
        )

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        pull_request = {
            "id": 99,
            "title": "PR title",
            "user": {"login": "octocat"},
        }

        with (
            patch.dict(os.environ, {"GITHUB_ACCESS_TOKEN": "token"}),
            patch.object(
                review_processing_service,
                "get_compare_files",
                return_value=[
                    {"filename": "src/old.py", "status": "removed"},
                    {"filename": "assets/logo.png", "status": "modified"},
                ],
            ),
            patch.object(review_processing_service, "get_pull_request", return_value=pull_request),
            patch.object(review_processing_service, "_ensure_pull_request_record", return_value=SimpleNamespace(repository_id=5)),
            patch.object(review_processing_service, "get_open_issues_for_pull_request", return_value=[]),
            patch.object(review_processing_service, "review_code") as review_code,
            patch.object(review_processing_service, "_post_github_comments") as post_github_comments,
            patch.object(review_processing_service, "save_review") as save_review,
        ):
            review_processing_service._process_pull_request_review(db, job)

        review_code.assert_not_called()
        post_github_comments.assert_not_called()
        save_review.assert_called_once()
        self.assertEqual(save_review.call_args.kwargs["review_data"].issues, [])

    def test_posts_saved_db_issue_with_string_severity_and_category(self):
        review = SimpleNamespace(
            issues=[
                SimpleNamespace(
                    file="src/app.py",
                    line=2,
                    severity="medium",
                    category="edge_case",
                    comment="This misses an edge case.",
                    impact="The edge case can produce an incorrect result.",
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
        self.assertIn("🟠 Medium Severity\nCategory: Edge Case", body)
        self.assertIn("This misses an edge case.", body)
        self.assertIn("Why this matters\n\nThe edge case can produce an incorrect result.", body)
        self.assertNotIn("Confidence:", body)

    def test_formats_inline_comment_with_suggested_fix_and_impact(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            impact="The HTTP request will never be executed because the application crashes first.",
            comment=(
                "The 'requests' module is used without being imported. "
                "This raises a NameError when the code path executes."
                "Suggested Fix: import requests"
            ),
        )

        body = review_processing_service._format_issue_comment_body(issue)

        self.assertEqual(
            body,
            "🔴 High Severity\n"
            "Category: Bug\n"
            "\n"
            "Problem\n"
            "\n"
            "The 'requests' module is used without being imported. "
            "This raises a NameError when the code path executes.\n"
            "\n"
            "Why this matters\n"
            "\n"
            "The HTTP request will never be executed because the application crashes first.\n"
            "\n"
            "Suggested Fix\n"
            "\n"
            "import requests",
        )

    def test_formats_small_structured_fix_as_github_suggestion(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            file="calculator.py",
            line=8,
            impact="The code crashes when user is None.",
            comment=(
                "Dereferencing a nullable variable may raise an AttributeError."
                "Suggested Fix: Check for None before accessing the attribute."
            ),
            fix_file_path="calculator.py",
            fix_start_line=8,
            fix_end_line=8,
            fix_replacement_code="if user is not None:\n    print(user.name)",
        )

        body = review_processing_service._format_issue_comment_body(
            issue,
            suggested_change="```suggestion\nif user is not None:\n    print(user.name)\n```",
        )

        self.assertIn("Suggested Fix\n\nCheck for None before accessing the attribute.", body)
        self.assertIn("```suggestion\nif user is not None:\n    print(user.name)\n```", body)
        self.assertNotIn("Reply `/ai-fix`", body)

    def test_large_structured_fix_uses_ai_fix_command_hint(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.medium,
            category=CategoryEnum.bug,
            file="calculator.py",
            line=8,
            impact="The code returns the wrong value.",
            comment=(
                "The calculation uses the wrong sequence."
                "Suggested Fix: Replace the block with the corrected calculation."
            ),
            fix_file_path="calculator.py",
            fix_start_line=1,
            fix_end_line=12,
            fix_replacement_code="\n".join(f"line_{index}" for index in range(12)),
        )

        body = review_processing_service._format_issue_comment_body(issue)

        self.assertNotIn("```suggestion", body)
        self.assertIn(
            "This issue requires multiple coordinated changes and cannot be applied as a GitHub Suggestion.",
            body,
        )
        self.assertIn("Reply `/ai-fix` to create a separate AI Fix PR", body)

    def test_formats_inline_comment_with_impact_from_comment_text(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.high,
            category=CategoryEnum.bug,
            comment=(
                "The 'requests' module is used without being imported."
                "Suggested Fix: import requests"
                "Impact: The HTTP request will never be executed."
            ),
        )

        body = review_processing_service._format_issue_comment_body(issue)

        self.assertIn("Suggested Fix\n\nimport requests", body)
        self.assertIn("Why this matters\n\nThe HTTP request will never be executed.", body)
        self.assertNotIn("Confidence:", body)

    def test_omits_example_section_when_comment_has_no_example(self):
        issue = SimpleNamespace(
            severity=SeverityEnum.low,
            category=CategoryEnum.readability,
            impact="Future maintainers may misunderstand the value's purpose.",
            comment=(
                "The variable name is unclear."
                "Suggested Fix: Rename it to describe the value it stores."
            ),
        )

        body = review_processing_service._format_issue_comment_body(issue)

        self.assertIn("🟡 Low Severity\nCategory: Readability", body)
        self.assertIn("Suggested Fix\n\nRename it to describe the value it stores.", body)
        self.assertIn("Why this matters\n\nFuture maintainers may misunderstand the value's purpose.", body)
        self.assertNotIn("Example", body)

    def test_filters_duplicate_issue_from_latest_review(self):
        previous_issues = [
            SimpleNamespace(
                file="calculator.py",
                line=2,
                category=CategoryEnum.bug,
                comment="Dereferencing a nullable user may raise an AttributeError.",
                impact="The request can crash when the user lookup returns None.",
            )
        ]
        new_issues = [
            SimpleNamespace(
                file="calculator.py",
                line=2,
                category=CategoryEnum.bug,
                comment=(
                    "Dereferencing a nullable user may raise an AttributeError."
                    "Suggested Fix: Check for None before accessing the attribute."
                ),
                impact="The request can crash when the user lookup returns None.",
            ),
            SimpleNamespace(
                file="calculator.py",
                line=5,
                category=CategoryEnum.security,
                comment="Interpolating user input into SQL can allow injection.",
                impact="An attacker can alter the query and access unauthorized data.",
            ),
        ]

        filtered = review_processing_service._filter_duplicate_issues(
            new_issues=new_issues,
            previous_issues=previous_issues,
        )

        self.assertEqual(filtered, [new_issues[1]])

    def test_duplicate_detection_tolerates_shifted_lines(self):
        previous_issue = SimpleNamespace(
            file="calculator.py",
            line=8,
            category=CategoryEnum.bug,
            comment="Dereferencing a nullable user may raise an AttributeError.",
            impact="The request can crash when the user lookup returns None.",
        )
        new_issue = SimpleNamespace(
            file="calculator.py",
            line=16,
            category=CategoryEnum.bug,
            comment="Dereferencing a nullable user may raise an AttributeError.",
            impact="The request can crash when the user lookup returns None.",
        )

        self.assertTrue(
            review_processing_service._is_duplicate_issue(
                new_issue,
                [previous_issue],
            )
        )

    def test_non_duplicate_issue_is_kept_when_latest_review_does_not_contain_it(self):
        previous_issues = [
            SimpleNamespace(
                file="calculator.py",
                line=5,
                category=CategoryEnum.security,
                comment="Interpolating user input into SQL can allow injection.",
                impact="An attacker can alter the query and access unauthorized data.",
            )
        ]
        new_issue = SimpleNamespace(
            file="calculator.py",
            line=2,
            category=CategoryEnum.bug,
            comment="Dereferencing a nullable user may raise an AttributeError.",
            impact="The request can crash when the user lookup returns None.",
        )

        filtered = review_processing_service._filter_duplicate_issues(
            new_issues=[new_issue],
            previous_issues=previous_issues,
        )

        self.assertEqual(filtered, [new_issue])

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

    def test_blank_line_issue_posts_to_exact_blank_line(self):
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
        self.assertEqual(inline_kwargs["line"], 9)
        self.assertEqual(inline_kwargs["side"], "RIGHT")

    def test_issue_line_near_hunk_falls_back_instead_of_guessing(self):
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
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("Inline comment unavailable", fallback_body)

    def test_inline_comment_failure_does_not_retry_with_diff_position(self):
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

        self.assertEqual(post_inline_comment.call_count, 1)
        self.assertNotIn("position", post_inline_comment.call_args.kwargs)
        self.assertEqual(post_pr_comment.call_count, 2)
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("GitHub rejected the inline comment", fallback_body)

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

        self.assertEqual(post_inline_comment.call_count, 1)
        self.assertEqual(post_pr_comment.call_count, 2)
        fallback_body = post_pr_comment.call_args_list[0].kwargs["body"]
        self.assertIn("`src/app.py:2`", fallback_body)
        self.assertIn("GitHub rejected the inline comment", fallback_body)


if __name__ == "__main__":
    unittest.main()
