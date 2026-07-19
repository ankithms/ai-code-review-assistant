import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Issue, PullRequest, Repository, Review, ReviewJob
from app.repositories.analytics_repository import get_analytics
from app.repositories.review_repository import update_issue_status
from app.schemas.output import IssueStatus


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
