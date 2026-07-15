import unittest

from app.schemas.output import IssueSchema


class ConfidenceSchemaTests(unittest.TestCase):
    def test_issue_schema_accepts_confidence_score(self):
        issue = IssueSchema(
            severity="high",
            category="bug",
            file="src/app.py",
            line=3,
            comment="This can fail.",
            confidence=0.94,
        )

        self.assertEqual(issue.confidence, 0.94)


if __name__ == "__main__":
    unittest.main()
