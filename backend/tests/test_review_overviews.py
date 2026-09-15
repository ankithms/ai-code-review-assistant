from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, FixCommit, Issue, PullRequest, Repository, Review, ReviewJob
from app.schemas.output import FixCommitStatus, IssueStatus
from app.schemas.responses import PullRequestReviewOverviewResponse
from app.services.issue_matching_service import IssueMatchingService
from app.services.review_overview_service import get_pull_request_review_overviews


@pytest.fixture()
def overview_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        yield db
    finally:
        db.close()


def _issue(review, *, comment, status="OPEN", severity="high", line=10):
    issue = Issue(
        review=review, severity=severity, category="bug", file="app/orders.py",
        line=line, comment=comment, status=status,
    )
    issue.fingerprint = IssueMatchingService().fingerprint(issue)
    return issue


def test_overview_groups_reviews_by_pr_and_preserves_current_health(overview_db):
    db = overview_db
    start = datetime(2026, 9, 14, tzinfo=UTC)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository, github_pr_id=100, pull_request_number=42,
        title="Harden order lookup", repository="owner/repo", author="octocat",
    )
    initial = Review(pull_request=pull_request, summary="Two findings", commit_sha="abc1234", created_at=start)
    incremental = Review(
        pull_request=pull_request, summary="No new findings", commit_sha="def5678",
        created_at=start + timedelta(days=1),
    )
    original = _issue(initial, comment="Missing ownership check causes an authorization bypass")
    # A historical duplicate is deliberately persisted to prove logical findings
    # are counted once. The newer zero-finding run must not erase it.
    duplicate_review = Review(
        pull_request=pull_request, summary="Carried finding", commit_sha="cab9999",
        created_at=start + timedelta(hours=1),
    )
    duplicate = _issue(duplicate_review, comment="Missing ownership check causes an authorization bypass", line=12)
    ignored = _issue(
        initial, comment="Naming could be clearer", status=IssueStatus.IGNORED.value,
        severity="low", line=30,
    )
    clean_pr = PullRequest(
        repository_ref=repository, github_pr_id=101, pull_request_number=43,
        title="Document API", repository="owner/repo", author="hubot",
    )
    clean_review = Review(
        pull_request=clean_pr, summary="No findings", commit_sha="clean123",
        created_at=start - timedelta(days=1),
    )
    jobs = [
        ReviewJob(repository="owner/repo", pull_request_number=42, commit_sha="abc1234", event_action="opened", status="SUCCESS", created_at=start),
        ReviewJob(repository="owner/repo", pull_request_number=42, commit_sha="def5678", event_action="synchronize", status="SUCCESS", created_at=start + timedelta(days=1)),
        ReviewJob(repository="owner/repo", pull_request_number=43, commit_sha="clean123", event_action="opened", status="SUCCESS", created_at=start - timedelta(days=1)),
    ]
    db.add_all([repository, pull_request, clean_pr, initial, duplicate_review, incremental, clean_review, original, duplicate, ignored, *jobs])
    db.commit()

    response = [PullRequestReviewOverviewResponse.model_validate(item) for item in get_pull_request_review_overviews(db, repository.id)]

    assert len(response) == 2
    overview = response[0]
    assert overview.pr_id == pull_request.id
    assert overview.latest_review_id == incremental.id
    assert overview.latest_reviewed_commit_sha == "def5678"
    assert overview.open_findings == 1
    assert overview.resolved_findings == 0
    assert overview.ignored_findings == 1
    assert overview.latest_run.run_type == "Incremental review"
    assert overview.latest_run.result == "No new findings"
    assert [run.review_id for run in overview.review_history] == [incremental.id, duplicate_review.id, initial.id]
    assert response[1].open_findings == 0


def test_fix_verification_updates_aggregate_and_classifies_run(overview_db):
    db = overview_db
    start = datetime(2026, 9, 15, tzinfo=UTC)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository, github_pr_id=200, pull_request_number=51,
        title="Fix importer", repository="owner/repo", author="octocat",
    )
    initial = Review(pull_request=pull_request, summary="One finding", commit_sha="head111", created_at=start)
    issue = _issue(initial, comment="Batch import can deadlock", status=IssueStatus.RESOLVED.value)
    db.add_all([repository, pull_request, initial, issue])
    db.flush()
    fix_commit = FixCommit(
        repository_ref=repository, pull_request=pull_request, review=initial,
        source_head_sha="head111", source_branch="feature/imports",
        generated_commit_sha="fix2222", status=FixCommitStatus.RESOLVED.value,
        requested_issue_count=1, valid_issue_count=1, resolved_issue_count=1,
    )
    db.add(fix_commit)
    db.flush()
    verification = Review(
        pull_request=pull_request, summary="Fix verified", commit_sha="fix2222",
        fix_commit_id=fix_commit.id, created_at=start + timedelta(hours=1),
    )
    job = ReviewJob(
        repository="owner/repo", pull_request_number=51, commit_sha="fix2222",
        event_action="synchronize", fix_commit=fix_commit, status="SUCCESS",
        created_at=start + timedelta(hours=1),
    )
    db.add_all([verification, job])
    db.commit()

    overview = PullRequestReviewOverviewResponse.model_validate(
        get_pull_request_review_overviews(db, repository.id)[0]
    )

    assert overview.open_findings == 0
    assert overview.resolved_findings == 1
    assert overview.latest_run.run_type == "Fix verification"
    assert overview.latest_run.result == "1 resolved"


def test_unclassified_history_falls_back_and_queued_jobs_are_visible(overview_db):
    db = overview_db
    start = datetime(2026, 9, 16, tzinfo=UTC)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository, github_pr_id=300, pull_request_number=60,
        title="Legacy review", repository="owner/repo", author="octocat",
    )
    legacy_a = Review(pull_request=pull_request, summary="Legacy", commit_sha="same333", created_at=start)
    legacy_b = Review(pull_request=pull_request, summary="Legacy retry", commit_sha="same333", created_at=start + timedelta(minutes=1))
    queued = ReviewJob(
        repository="owner/repo", pull_request_number=60, commit_sha="next444",
        event_action="synchronize", status="PENDING", created_at=start + timedelta(minutes=2),
    )
    db.add_all([repository, pull_request, legacy_a, legacy_b, queued])
    db.commit()

    overview = PullRequestReviewOverviewResponse.model_validate(
        get_pull_request_review_overviews(db, repository.id)[0]
    )

    assert overview.latest_run.status == "PENDING"
    assert overview.latest_run.run_type == "Incremental review"
    assert overview.latest_run.result == "Analysis queued"
    assert len(overview.review_history) == 3
    assert [run.run_type for run in overview.review_history[1:]] == ["Review", "Review"]
