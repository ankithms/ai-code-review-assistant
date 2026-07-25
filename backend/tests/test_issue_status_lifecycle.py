import unittest
from datetime import UTC, datetime, timedelta

from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, FixPullRequest, Issue, PullRequest, Repository, Review, ReviewJob
from app.repositories.analytics_repository import get_analytics
from app.repositories.review_repository import reconcile_merged_fix_issue_statuses, update_issue_status
from app.schemas.output import FixPullRequestStatus, IssueFixStatus, IssueStatus
from app.services.github_thread_sync_service import sync_issue_statuses_from_github


class IssueStatusLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self):
        self.session.close()

    def test_update_issue_status_rejects_invalid_status_value(self):
        issue = Issue(status=IssueStatus.OPEN.value)
        self.session.add(issue)
        self.session.commit()

        with self.assertRaises(ValueError):
            update_issue_status(self.session, issue, "INVALID")

    def test_update_issue_status_tracks_resolution_timestamps(self):
        issue = Issue(status=IssueStatus.OPEN.value)
        self.session.add(issue)
        self.session.commit()

        updated_issue = update_issue_status(self.session, issue, IssueStatus.RESOLVED)
        self.assertEqual(updated_issue.status, IssueStatus.RESOLVED.value)
        self.assertIsNotNone(updated_issue.resolved_at)
        self.assertIsNone(updated_issue.resolved_by)

        reopened_issue = update_issue_status(self.session, issue, IssueStatus.OPEN)
        self.assertEqual(reopened_issue.status, IssueStatus.OPEN.value)
        self.assertIsNone(reopened_issue.resolved_at)
        self.assertIsNone(reopened_issue.resolved_by)

    def test_update_issue_status_rejects_reopening_merged_fix_issue(self):
        issue = Issue(
            status=IssueStatus.RESOLVED.value,
            fix_status=IssueFixStatus.FIX_MERGED.value,
        )
        self.session.add(issue)
        self.session.commit()

        with self.assertRaisesRegex(ValueError, "merged AI Fix PR"):
            update_issue_status(self.session, issue, IssueStatus.OPEN)

    def test_reconcile_merged_fix_issue_statuses_resolves_stale_open_issue(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=1,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        issue = Issue(
            review_id=review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            status=IssueStatus.OPEN.value,
            fix_status=IssueFixStatus.FIX_PR_CREATED.value,
        )
        fix_pull_request = FixPullRequest(
            repository_id=repository.id,
            review_id=review.id,
            original_pull_request_id=pull_request.id,
            original_pr_number=pull_request.pull_request_number,
            source_commit_sha="abc",
            fix_branch="ai-fix/1-20260721",
            github_pr_number=34,
            github_pr_url="https://github.com/owner/repo/pull/34",
            status=FixPullRequestStatus.MERGED.value,
            merged_at=datetime(2026, 7, 21, tzinfo=UTC),
            issues=[issue],
        )
        self.session.add_all([issue, fix_pull_request])
        self.session.commit()

        reconciled_count = reconcile_merged_fix_issue_statuses(self.session, review)

        self.session.refresh(issue)
        self.assertEqual(reconciled_count, 1)
        self.assertEqual(issue.status, IssueStatus.RESOLVED.value)
        self.assertEqual(issue.fix_status, IssueFixStatus.FIX_MERGED.value)
        self.assertEqual(issue.resolved_at, fix_pull_request.merged_at)

    def test_sync_issue_statuses_from_github_updates_issue_statuses(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=1,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        issue = Issue(
            review_id=review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            github_review_thread_id="thread-1",
            status=IssueStatus.OPEN.value,
        )
        self.session.add(issue)
        self.session.commit()

        with patch(
            "app.services.github_thread_sync_service._fetch_review_thread_states",
            return_value={
                "thread-1": {
                    "is_resolved": True,
                    "resolved_by": "octocat",
                    "resolved_at": "2026-07-19T00:00:00Z",
                }
            },
        ):
            sync_issue_statuses_from_github(self.session, repository.id, repository.full_name, "token")

        self.session.refresh(issue)
        self.assertEqual(issue.status, IssueStatus.RESOLVED.value)
        self.assertIsNotNone(issue.resolved_at)
        self.assertEqual(issue.resolved_by, "octocat")

    def test_sync_does_not_reopen_issues_resolved_by_merged_fix_pr(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=1,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        resolved_at = datetime(2026, 7, 21, tzinfo=UTC)
        issue = Issue(
            review_id=review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            github_review_thread_id="thread-1",
            status=IssueStatus.RESOLVED.value,
            resolved_at=resolved_at,
            fix_status=IssueFixStatus.FIX_MERGED.value,
        )
        self.session.add(issue)
        self.session.commit()

        with patch(
            "app.services.github_thread_sync_service._fetch_review_thread_states",
            return_value={
                "thread-1": {
                    "is_resolved": False,
                    "resolved_by": None,
                }
            },
        ):
            sync_issue_statuses_from_github(self.session, repository.id, repository.full_name, "token")

        self.session.refresh(issue)
        self.assertEqual(issue.status, IssueStatus.RESOLVED.value)
        self.assertEqual(issue.resolved_at.replace(tzinfo=UTC), resolved_at)
        self.assertEqual(issue.fix_status, IssueFixStatus.FIX_MERGED.value)

    def test_sync_ignores_pull_requests_without_a_number(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        pull_request_with_number = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=7,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        pull_request_without_number = PullRequest(
            repository_id=repository.id,
            github_pr_id=2,
            pull_request_number=None,
            title="PR 2",
            repository=repository.full_name,
            author="user",
        )
        self.session.add_all([pull_request_with_number, pull_request_without_number])
        self.session.flush()

        review = Review(pr_id=pull_request_with_number.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        issue = Issue(
            review_id=review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            github_review_thread_id="thread-1",
            status=IssueStatus.OPEN.value,
        )
        self.session.add(issue)
        self.session.commit()

        with patch("app.services.github_thread_sync_service._fetch_review_thread_states", return_value={}) as mock_fetch:
            sync_issue_statuses_from_github(self.session, repository.id, repository.full_name, "token")

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(mock_fetch.call_args.kwargs["pull_request_number"], 7)

    def test_sync_can_be_scoped_to_one_pull_request(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        first_pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=7,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        second_pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=2,
            pull_request_number=8,
            title="PR 2",
            repository=repository.full_name,
            author="user",
        )
        self.session.add_all([first_pull_request, second_pull_request])
        self.session.flush()

        first_review = Review(pr_id=first_pull_request.id, summary="Summary", commit_sha="abc")
        second_review = Review(pr_id=second_pull_request.id, summary="Summary 2", commit_sha="def")
        self.session.add_all([first_review, second_review])
        self.session.flush()

        first_issue = Issue(
            review_id=first_review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            github_review_thread_id="thread-1",
            status=IssueStatus.OPEN.value,
        )
        second_issue = Issue(
            review_id=second_review.id,
            severity="high",
            category="bug",
            file="src/other.py",
            comment="Issue 2",
            github_review_thread_id="thread-2",
            status=IssueStatus.OPEN.value,
        )
        self.session.add_all([first_issue, second_issue])
        self.session.commit()

        with patch(
            "app.services.github_thread_sync_service._fetch_review_thread_states",
            return_value={
                "thread-1": {"is_resolved": True, "resolved_by": "octocat"},
                "thread-2": {"is_resolved": True, "resolved_by": "octocat"},
            },
        ) as mock_fetch:
            sync_issue_statuses_from_github(
                self.session,
                repository.id,
                repository.full_name,
                "token",
                pull_request_id=first_pull_request.id,
            )

        self.session.refresh(first_issue)
        self.session.refresh(second_issue)
        self.assertEqual(mock_fetch.call_count, 1)
        self.assertEqual(mock_fetch.call_args.kwargs["pull_request_number"], 7)
        self.assertEqual(first_issue.status, IssueStatus.RESOLVED.value)
        self.assertEqual(second_issue.status, IssueStatus.OPEN.value)

    def test_sync_does_not_overwrite_ignored_issues(self):
        repository = Repository(full_name="owner/repo")
        self.session.add(repository)
        self.session.flush()

        pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            pull_request_number=1,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        issue = Issue(
            review_id=review.id,
            severity="high",
            category="bug",
            file="src/app.py",
            comment="Issue",
            github_review_thread_id="thread-1",
            status=IssueStatus.IGNORED.value,
        )
        self.session.add(issue)
        self.session.commit()

        with patch(
            "app.services.github_thread_sync_service._fetch_review_thread_states",
            return_value={
                "thread-1": {
                    "is_resolved": True,
                    "resolved_by": "octocat",
                }
            },
        ):
            sync_issue_statuses_from_github(
                self.session,
                repository.id,
                repository.full_name,
                "token",
                pull_request_id=pull_request.id,
            )

        self.session.refresh(issue)
        self.assertEqual(issue.status, IssueStatus.IGNORED.value)
        self.assertIsNone(issue.resolved_at)
        self.assertIsNone(issue.resolved_by)

    def test_get_analytics_includes_status_breakdown(self):
        repository = Repository(full_name="owner/repo")
        other_repository = Repository(full_name="owner/other")
        self.session.add_all([repository, other_repository])
        self.session.flush()

        pull_request = PullRequest(
            repository_id=repository.id,
            github_pr_id=1,
            title="PR",
            repository=repository.full_name,
            author="user",
        )
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        second_pull_request = PullRequest(
            repository_id=other_repository.id,
            github_pr_id=2,
            title="PR 2",
            repository=other_repository.full_name,
            author="user",
        )
        self.session.add(second_pull_request)
        self.session.flush()
        other_review = Review(pr_id=second_pull_request.id, summary="Other summary", commit_sha="def")
        self.session.add(other_review)
        self.session.flush()

        started_at = datetime.now(UTC)
        self.session.add(
            ReviewJob(
                repository="owner/repo",
                pull_request_number=1,
                commit_sha="abc",
                status="SUCCESS",
                started_at=started_at,
                completed_at=started_at + timedelta(seconds=12),
            )
        )
        self.session.add_all([
            Issue(review_id=review.id, severity="high", category="bug", file="src/app.py", comment="One", status=IssueStatus.OPEN.value),
            Issue(review_id=review.id, severity="medium", category="security", file="src/app.py", comment="Two", status=IssueStatus.RESOLVED.value),
            Issue(review_id=review.id, severity="low", category="performance", file="src/db.py", comment="Three", status=IssueStatus.IGNORED.value),
            Issue(review_id=review.id, severity="low", category="readability", file="src/db.py", comment="Four", status=IssueStatus.OPEN.value),
            Issue(review_id=review.id, severity="low", category="edge_case", file="src/db.py", comment="Five", status=IssueStatus.OPEN.value),
            Issue(review_id=other_review.id, severity="high", category="bug", file="other.py", comment="Other", status=IssueStatus.OPEN.value),
        ])
        self.session.commit()

        analytics = get_analytics(self.session, repository.id)

        self.assertEqual(analytics["total_pull_requests"], 1)
        self.assertEqual(analytics["total_ai_reviews"], 1)
        self.assertEqual(analytics["total_issues"], 5)
        self.assertEqual(analytics["open_issues"], 3)
        self.assertEqual(analytics["resolved_issues"], 1)
        self.assertEqual(analytics["ignored_issues"], 1)
        self.assertEqual(analytics["high_severity"], 1)
        self.assertEqual(analytics["medium_severity"], 1)
        self.assertEqual(analytics["low_severity"], 3)
        self.assertEqual(analytics["bug_issues"], 1)
        self.assertEqual(analytics["security_issues"], 1)
        self.assertEqual(analytics["performance_issues"], 1)
        self.assertEqual(analytics["readability_issues"], 1)
        self.assertEqual(analytics["edge_case_issues"], 1)
        self.assertEqual(analytics["top_problematic_files"][0], {"file": "src/db.py", "total_issues": 3})
        self.assertEqual(analytics["average_issues_per_pull_request"], 5)
        self.assertEqual(analytics["average_review_processing_time_seconds"], 12)


if __name__ == "__main__":
    unittest.main()
