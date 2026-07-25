from types import SimpleNamespace

from app.schemas.responses import PullRequestResponse


def test_pull_request_response_allows_legacy_rows_without_pull_request_number():
    response = PullRequestResponse.model_validate(
        SimpleNamespace(
            id=1,
            github_pr_id=123456,
            pull_request_number=None,
            title="Legacy PR",
            repository="owner/repo",
            author="octocat",
        )
    )

    assert response.pull_request_number is None
