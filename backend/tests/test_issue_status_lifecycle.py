import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Issue, PullRequest, Review
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
        pull_request = PullRequest(github_pr_id=1, title="PR", repository="owner/repo", author="user")
        self.session.add(pull_request)
        self.session.flush()

        review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="abc")
        self.session.add(review)
        self.session.flush()

        self.session.add_all(
            [
                Issue(review_id=review.id, severity="high", category="bug", file="src/app.py", comment="One", status=IssueStatus.OPEN.value),
                Issue(review_id=review.id, severity="medium", category="bug", file="src/app.py", comment="Two", status=IssueStatus.RESOLVED.value),
                Issue(review_id=review.id, severity="low", category="bug", file="src/app.py", comment="Three", status=IssueStatus.IGNORED.value),
            ]
        )
        self.session.commit()

        analytics = get_analytics(self.session)

        self.assertEqual(analytics["open_issues"], 1)
        self.assertEqual(analytics["resolved_issues"], 1)
        self.assertEqual(analytics["ignored_issues"], 1)


if __name__ == "__main__":
    unittest.main()
