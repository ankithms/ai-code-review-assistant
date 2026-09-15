from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, FixCommit, FixCommitIssue, Issue, PullRequest, Repository, Review
from app.schemas.output import FixCommitIssueStatus, FixCommitStatus, IssueFixStatus, IssueStatus
from app.services.actionable_issue_service import get_current_actionable_issues_for_pull_request
from app.services.fix_commit_tracking_service import (
    FindingAlreadyClaimedError,
    FixCommitTrackingService,
)
from app.services.fix_generation_service import FixGenerationService
from app.services.github_native_fix_service import _selection_message


@pytest.fixture()
def pr_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository,
        repository="owner/repo",
        github_pr_id=99,
        pull_request_number=12,
        title="PR",
        author="octocat",
    )
    db.add_all([repository, pull_request])
    db.commit()
    try:
        yield db, repository, pull_request
    finally:
        db.close()


def _review(db, pull_request, sha):
    review = Review(pull_request=pull_request, summary=sha, commit_sha=sha)
    db.add(review)
    db.flush()
    return review


def _issue(db, review, *, comment="Dereference can be null", file="app.py", line=10, status="OPEN"):
    issue = Issue(
        review=review,
        severity="high",
        category="bug",
        file=file,
        line=line,
        comment=comment,
        status=status,
    )
    db.add(issue)
    db.flush()
    return issue


def _attempt(
    db,
    repository,
    pull_request,
    review,
    issue,
    *,
    link_status,
    resolution_status=None,
    record_status=FixCommitStatus.REVIEWED.value,
    current_issue=None,
):
    record = FixCommit(
        repository_id=repository.id,
        pull_request_id=pull_request.id,
        review_id=review.id,
        source_head_sha=f"head-{issue.id}-{link_status}",
        source_branch="feature",
        status=record_status,
        issue_links=[
            FixCommitIssue(
                issue_id=issue.id,
                current_issue_id=current_issue.id if current_issue else None,
                status=link_status,
                resolution_status=resolution_status,
            )
        ],
    )
    db.add(record)
    db.commit()
    return record


def _select(db, repository):
    return get_current_actionable_issues_for_pull_request(
        db,
        repository_id=repository.id,
        pull_request_number=12,
    )


def test_latest_empty_review_does_not_hide_earlier_open_finding(pr_db):
    db, repository, pull_request = pr_db
    old_review = _review(db, pull_request, "old")
    issue = _issue(db, old_review)
    _review(db, pull_request, "new-empty")
    db.commit()

    selection = _select(db, repository)

    assert [item.id for item in selection.selected] == [issue.id]


def test_duplicate_occurrences_select_newest_once(pr_db):
    db, repository, pull_request = pr_db
    old = _issue(db, _review(db, pull_request, "old"), line=10)
    new = _issue(db, _review(db, pull_request, "new"), line=14)
    db.commit()

    selection = _select(db, repository)

    assert [item.id for item in selection.selected] == [new.id]
    assert old.id != new.id


@pytest.mark.parametrize(
    ("issue_status", "resolution", "reason"),
    [
        (IssueStatus.RESOLVED.value, None, "resolved"),
        (IssueStatus.IGNORED.value, None, "explicitly ignored"),
        (IssueStatus.OPEN.value, FixCommitIssueStatus.RESOLVED.value, "conclusively resolved"),
    ],
)
def test_resolved_and_ignored_findings_are_excluded(pr_db, issue_status, resolution, reason):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    issue = _issue(db, review, status=issue_status)
    if resolution:
        _attempt(
            db,
            repository,
            pull_request,
            review,
            issue,
            link_status=resolution,
            resolution_status=resolution,
        )
    db.commit()

    selection = _select(db, repository)

    assert selection.selected == []
    assert reason in selection.excluded[0].reason


def test_active_fix_attempt_is_excluded(pr_db):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    issue = _issue(db, review)
    _attempt(
        db,
        repository,
        pull_request,
        review,
        issue,
        link_status=FixCommitIssueStatus.GENERATED.value,
        record_status=FixCommitStatus.GENERATING.value,
    )

    selection = _select(db, repository)

    assert selection.selected == []
    assert selection.excluded[0].reason == "already being processed"


@pytest.mark.parametrize(
    "outcome",
    [
        FixCommitIssueStatus.STILL_OPEN.value,
        FixCommitIssueStatus.FAILED_TO_VERIFY.value,
        FixCommitIssueStatus.SKIPPED.value,
        FixCommitIssueStatus.FAILED.value,
    ],
)
def test_retryable_outcomes_override_fix_committed(pr_db, outcome):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    issue = _issue(db, review)
    issue.fix_status = IssueFixStatus.FIX_COMMITTED.value
    _attempt(
        db,
        repository,
        pull_request,
        review,
        issue,
        link_status=outcome,
        resolution_status=outcome if outcome != FixCommitIssueStatus.SKIPPED.value else None,
        record_status=FixCommitStatus.FAILED.value,
    )

    assert [item.id for item in _select(db, repository).selected] == [issue.id]


def test_moved_outcome_selects_current_occurrence(pr_db):
    db, repository, pull_request = pr_db
    old_review = _review(db, pull_request, "old")
    old = _issue(db, old_review, file="old.py", line=5)
    new_review = _review(db, pull_request, "new")
    current = _issue(db, new_review, file="new.py", line=30)
    _attempt(
        db,
        repository,
        pull_request,
        old_review,
        old,
        link_status=FixCommitIssueStatus.MOVED.value,
        resolution_status=FixCommitIssueStatus.MOVED.value,
        current_issue=current,
    )

    assert [item.id for item in _select(db, repository).selected] == [current.id]


def test_retry_limit_requires_manual_review(pr_db):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    issue = _issue(db, review)
    for _ in range(3):
        _attempt(
            db,
            repository,
            pull_request,
            review,
            issue,
            link_status=FixCommitIssueStatus.FAILED.value,
            resolution_status=FixCommitIssueStatus.FAILED.value,
            record_status=FixCommitStatus.FAILED.value,
        )

    selection = _select(db, repository)

    assert selection.selected == []
    assert selection.excluded[0].manual_review is True
    assert "retry limit reached" in selection.excluded[0].reason
    message = _selection_message(selection, request_key="request-3")
    assert "Manual review required" in message
    assert f"#{issue.id}" in message
    assert "retry limit has been reached" in message


def test_different_request_cannot_claim_active_finding(pr_db):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    issue = _issue(db, review)
    db.commit()
    tracking = FixCommitTrackingService()
    tracking.create_or_get(
        db,
        repository_id=repository.id,
        pull_request_id=pull_request.id,
        review_id=review.id,
        issues=[issue],
        source_head_sha="head",
        source_branch="feature",
        request_key="request-1",
    )

    with pytest.raises(FindingAlreadyClaimedError):
        tracking.create_or_get(
            db,
            repository_id=repository.id,
            pull_request_id=pull_request.id,
            review_id=review.id,
            issues=[issue],
            source_head_sha="head",
            source_branch="feature",
            request_key="request-2",
        )


def test_regeneration_discards_stored_edit_before_generation():
    issue = SimpleNamespace(
        fix_file_path="app.py",
        fix_start_line=1,
        fix_end_line=1,
        fix_replacement_code="stale = True",
        fix_additional_edits=None,
        fix_explanation="old",
        fix_base_commit_sha="old-head",
        fix_file_sha="old-file",
        fix_status=IssueFixStatus.FIX_COMMITTED.value,
    )
    db = SimpleNamespace(add=Mock(), flush=Mock())
    service = FixGenerationService()
    service.generate_fixes = Mock(return_value=[issue])

    service.regenerate_fixes(
        db=db,
        issues=[issue],
        repository="owner/repo",
        target_ref="current-head",
        target_head_sha="current-head",
        access_token="token",
    )

    assert issue.fix_replacement_code is None
    assert issue.fix_base_commit_sha is None
    assert service.generate_fixes.call_args.kwargs["target_ref"] == "current-head"


def test_selection_comment_reports_counts_reasons_manual_review_and_job(pr_db):
    db, repository, pull_request = pr_db
    review = _review(db, pull_request, "head")
    _issue(db, review, comment="Actionable")
    ignored = _issue(db, review, comment="Ignored", file="ignored.py", status=IssueStatus.IGNORED.value)
    db.commit()
    selection = _select(db, repository)

    message = _selection_message(selection, queued=1, job_id=42)

    assert "Selected: 1" in message
    assert "Queued: 1" in message
    assert "Excluded: 1" in message
    assert f"#{ignored.id}" in message
    assert "explicitly ignored" in message
    assert "Request/job: `job 42`" in message
