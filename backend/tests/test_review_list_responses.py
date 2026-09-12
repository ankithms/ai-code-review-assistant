from datetime import UTC, datetime

from app.db.models import Issue, PullRequest, Review
from app.schemas.responses import ReviewListResponse


def test_review_list_response_includes_filter_and_display_metadata():
    pull_request = PullRequest(
        id=7,
        pull_request_number=42,
        title="Harden order lookup",
    )
    review = Review(
        id=11,
        pr_id=7,
        summary="One access-control finding needs attention.",
        commit_sha="abc123",
        created_at=datetime(2026, 9, 12, tzinfo=UTC),
        pull_request=pull_request,
        issues=[Issue(severity="high", status="OPEN")],
    )

    response = ReviewListResponse.model_validate(review)

    assert response.pr_number == 42
    assert response.pr_title == "Harden order lookup"
    assert response.created_at == datetime(2026, 9, 12, tzinfo=UTC)
    assert response.issues[0].severity == "high"
    assert response.issues[0].status.value == "OPEN"
