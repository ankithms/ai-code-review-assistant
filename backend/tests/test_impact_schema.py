import unittest

from app.schemas.output import IssueSchema


class ImpactSchemaTests(unittest.TestCase):
    def test_issue_schema_accepts_impact(self):
        issue = IssueSchema(
            severity="high",
            category="bug",
            file="src/app.py",
            line=3,
            comment="This can fail.",
            impact="The application crashes before completing the request.",
        )

        self.assertEqual(
            issue.impact,
            "The application crashes before completing the request.",
        )


if __name__ == "__main__":
    unittest.main()
