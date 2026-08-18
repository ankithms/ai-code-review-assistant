"""Dramatiq worker entry point for the deterministic E2E environment.

The application, database, broker, and worker are real. Only calls that would
leave the test environment (GitHub and the AI model) are replaced here.
"""

from app.schemas.output import (
    CategoryEnum,
    IssueSchema,
    ReviewResponseSchema,
    SeverityEnum,
)
from app.services import review_processing_service


E2E_COMMIT_SHA = "e2e-head-sha"
E2E_REPOSITORY = "e2e/code-review-fixture"


def _get_pr_files(**_kwargs):
    return [
        {
            "filename": "src/pricing.py",
            "status": "modified",
            "patch": (
                "@@ -1 +1,2 @@\n"
                " def total(subtotal, tax):\n"
                "+    return subtotal + tax"
            ),
        }
    ]


def _get_pull_request(**_kwargs):
    return {
        "id": 9000000001,
        "number": 7,
        "title": "E2E review fixture",
        "body": "Exercises the complete asynchronous review pipeline.",
        "user": {"login": "e2e-author"},
        "head": {
            "sha": E2E_COMMIT_SHA,
            "ref": "e2e-review-branch",
        },
        "base": {
            "ref": "main",
            "repo": {
                "description": "A deterministic E2E repository fixture.",
            },
        },
    }


def _review_code(*_args, **_kwargs):
    return ReviewResponseSchema(
        summary="E2E review completed successfully.",
        issues=[
            IssueSchema(
                severity=SeverityEnum.medium,
                category=CategoryEnum.bug,
                file="src/pricing.py",
                line_ref="L2",
                comment="Tax must be validated before it is added to the subtotal.",
                impact="A negative tax value can produce an invalid order total.",
            )
        ],
    )


class _DeterministicContextBuilder:
    def build(self, **_kwargs):
        return None


def _post_inline_comment(**_kwargs):
    return {
        "id": 9100000001,
        "node_id": "E2E_INLINE_COMMENT",
    }


def _post_pr_comment(**_kwargs):
    return {
        "id": 9200000001,
        "node_id": "E2E_SUMMARY_COMMENT",
    }


review_processing_service.get_pr_files = _get_pr_files
review_processing_service.get_pull_request = _get_pull_request
review_processing_service.review_code = _review_code
review_processing_service.ReviewContextBuilder = _DeterministicContextBuilder
review_processing_service.post_inline_comment = _post_inline_comment
review_processing_service.post_pr_comment = _post_pr_comment

# Importing the actor after installing the deterministic boundaries makes this
# module a valid Dramatiq CLI entry point without changing production behavior.
from app.tasks.review_tasks import process_review_job  # noqa: E402, F401

