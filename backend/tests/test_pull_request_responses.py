from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, PullRequest, Repository, Review
from app.repositories.pull_request_repositories import get_pull_requests_for_repository
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
    assert response.review_id is None


@pytest.fixture()
def pull_request_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


def test_pull_request_list_includes_latest_review_id(pull_request_db):
    db = pull_request_db
    now = datetime(2026, 9, 20, tzinfo=UTC)
    repository = Repository(full_name="owner/repo")
    reviewed_pr = PullRequest(
        repository_ref=repository,
        github_pr_id=101,
        pull_request_number=42,
        title="Reviewed PR",
        repository="owner/repo",
        author="octocat",
    )
    unreviewed_pr = PullRequest(
        repository_ref=repository,
        github_pr_id=102,
        pull_request_number=43,
        title="Unreviewed PR",
        repository="owner/repo",
        author="hubot",
    )
    # Insert the latest review first to prove selection follows review time,
    # rather than assuming the highest database ID is always the newest.
    latest_review = Review(
        pull_request=reviewed_pr,
        summary="Latest",
        commit_sha="new1234",
        created_at=now,
    )
    older_review = Review(
        pull_request=reviewed_pr,
        summary="Older",
        commit_sha="old1234",
        created_at=now - timedelta(days=1),
    )
    db.add_all([repository, reviewed_pr, unreviewed_pr, latest_review, older_review])
    db.commit()

    pull_requests = get_pull_requests_for_repository(db, repository.id)
    responses = [PullRequestResponse.model_validate(item) for item in pull_requests]
    responses_by_title = {response.title: response for response in responses}

    assert latest_review.id < older_review.id
    assert responses_by_title["Reviewed PR"].review_id == latest_review.id
    assert responses_by_title["Unreviewed PR"].review_id is None
