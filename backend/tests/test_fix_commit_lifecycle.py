import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Issue, PullRequest, Repository, Review, ReviewJob
from app.routes import webhook
from app.routes.fix_commits import get_fix_commit, get_pull_request_fix_commits
from app.routes.fixes import _fix_commit_response
from app.schemas.output import FixCommitIssueStatus, FixCommitStatus, IssueStatus
from app.services.fix_commit_tracking_service import (
    FixCommitAlreadyClaimedError,
    FixCommitTrackingService,
)


@pytest.fixture()
def lifecycle_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository,
        github_pr_id=99,
        pull_request_number=12,
        title="PR",
        repository="owner/repo",
        author="octocat",
    )
    review = Review(pull_request=pull_request, summary="summary", commit_sha="head-1")
    issues = [
        Issue(
            review=review,
            severity="high",
            category="bug",
            file=f"file-{index}.py",
            line=index,
            comment=f"Issue {index}",
            status=IssueStatus.OPEN.value,
        )
        for index in (1, 2)
    ]
    db.add_all([repository, pull_request, review, *issues])
    db.commit()
    try:
        yield db, repository, pull_request, review, issues
    finally:
        db.close()


def _create(db, repository, pull_request, review, issues, head="head-1", retry=False):
    return FixCommitTrackingService().create_or_get(
        db,
        repository_id=repository.id,
        pull_request_id=pull_request.id,
        review_id=review.id,
        issues=issues,
        source_head_sha=head,
        source_branch="feature",
        retry=retry,
    )


def _generated(issue):
    issue.fix_file_path = issue.file
    issue.fix_start_line = 1
    issue.fix_end_line = 1
    issue.fix_replacement_code = "fixed = True"


def _commit(db, record, issues):
    tracking = FixCommitTrackingService()
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    for issue in issues:
        _generated(issue)
    tracking.mark_generated(db, record, issues)
    tracking.mark_validating(db, record)
    tracking.record_validation(
        db,
        record,
        SimpleNamespace(
            valid=True,
            included_issue_ids=[issue.id for issue in issues],
            excluded_issue_ids=[],
            errors=[],
        ),
    )
    tracking.mark_committing(db, record, "fix(ai): test")
    tracking.mark_committed(
        db,
        record,
        SimpleNamespace(
            branch_name="feature",
            commit_sha=f"fix-{record.id}",
            commit_url=f"https://github.com/owner/repo/commit/fix-{record.id}",
            commit_message="fix(ai): test",
        ),
    )
    return tracking


def test_request_is_persisted_with_issue_membership_before_generation(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, created = _create(db, repository, pull_request, review, issues)

    assert created is True
    assert record.status == FixCommitStatus.REQUESTED.value
    assert record.requested_issue_count == 2
    assert [link.issue_id for link in record.issue_links] == [issue.id for issue in issues]
    assert all(link.status == FixCommitIssueStatus.REQUESTED.value for link in record.issue_links)


def test_idempotency_reuses_same_request_and_changes_with_head_or_selection(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    first, _ = _create(db, repository, pull_request, review, issues)
    duplicate, created = _create(db, repository, pull_request, review, list(reversed(issues)))
    new_head, new_head_created = _create(
        db, repository, pull_request, review, issues, head="head-2"
    )
    new_selection, new_selection_created = _create(
        db, repository, pull_request, review, issues[:1]
    )

    assert created is False
    assert duplicate.id == first.id
    assert new_head_created is True and new_head.id != first.id
    assert new_selection_created is True and new_selection.id != first.id


def test_explicit_retry_creates_a_new_attempt_after_failure(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    first, _ = _create(db, repository, pull_request, review, issues)
    tracking.mark_failed(db, first, "model generation failed")

    without_retry, created = _create(db, repository, pull_request, review, issues)
    retried, retry_created = _create(
        db, repository, pull_request, review, issues, retry=True
    )

    assert created is False and without_retry.id == first.id
    assert retry_created is True
    assert retried.attempt == 2


def test_partial_validation_records_committed_and_skipped_issue_counts(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    record, _ = _create(db, repository, pull_request, review, issues)
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    _generated(issues[0])
    tracking.mark_generated(db, record, issues)
    tracking.mark_validating(db, record)
    tracking.record_validation(
        db,
        record,
        SimpleNamespace(
            valid=True,
            included_issue_ids=[issues[0].id],
            excluded_issue_ids=[issues[1].id],
            errors=[f"Issue {issues[1].id} excluded: no safe edit"],
        ),
    )

    links = {link.issue_id: link for link in record.issue_links}
    assert record.valid_issue_count == 0
    assert record.skipped_issue_count == 1
    assert links[issues[0].id].status == FixCommitIssueStatus.VALIDATED.value
    assert links[issues[1].id].status == FixCommitIssueStatus.SKIPPED.value
    assert links[issues[1].id].skip_reason == "no safe edit"


def test_no_valid_edits_fails_without_commit_metadata(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    record, _ = _create(db, repository, pull_request, review, issues)
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    tracking.mark_validating(db, record)
    tracking.record_validation(
        db,
        record,
        SimpleNamespace(
            valid=False,
            included_issue_ids=[],
            excluded_issue_ids=[issue.id for issue in issues],
            errors=[f"Issue {issues[0].id} excluded: invalid patch"],
        ),
    )
    tracking.mark_failed(db, record, "No selected fix passed validation")

    assert record.status == FixCommitStatus.FAILED.value
    assert record.generated_commit_sha is None


def test_stale_head_marks_uncommitted_issue_records_failed(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    record, _ = _create(db, repository, pull_request, review, issues)
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    tracking.mark_stale(db, record)

    assert record.status == FixCommitStatus.STALE.value
    assert record.failure_reason == "Pull Request changed during fix generation"
    assert all(link.status == FixCommitIssueStatus.FAILED.value for link in record.issue_links)


def test_commit_metadata_and_webhook_sha_matching(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, _ = _create(db, repository, pull_request, review, issues[:1])
    tracking = _commit(db, record, issues[:1])

    matched = tracking.match_synchronize_commit(
        db,
        repository_full_name="owner/repo",
        pull_request_number=12,
        commit_sha=record.generated_commit_sha,
    )
    developer_commit = tracking.match_synchronize_commit(
        db,
        repository_full_name="owner/repo",
        pull_request_number=12,
        commit_sha="developer-sha",
    )

    assert record.status == FixCommitStatus.REVIEW_PENDING.value
    assert record.resulting_head_sha == record.generated_commit_sha
    assert record.generated_commit_url.endswith(record.generated_commit_sha)
    assert record.committed_at is not None
    assert matched.id == record.id
    assert developer_commit is None


def test_synchronize_webhook_associates_review_job_by_generated_sha(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, _ = _create(db, repository, pull_request, review, issues[:1])
    _commit(db, record, issues[:1])
    payload = {
        "action": "synchronize",
        "before": record.source_head_sha,
        "after": record.generated_commit_sha,
        "repository": {"full_name": repository.full_name},
        "pull_request": {
            "number": pull_request.pull_request_number,
            "head": {"sha": record.generated_commit_sha},
        },
    }

    class Request:
        headers = {"X-GitHub-Event": "pull_request"}

        async def body(self):
            return json.dumps(payload).encode()

    with (
        patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": ""}),
        patch.object(webhook.process_review_job, "send") as send,
    ):
        response = asyncio.run(webhook.github_webhook(Request(), db))

    job = db.query(ReviewJob).filter(ReviewJob.id == response["job_id"]).one()
    assert response["status"] == "queued"
    assert job.fix_commit_id == record.id
    send.assert_called_once_with(job.id)


def test_follow_up_review_resolves_all_committed_issues_and_api_exposes_metadata(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, _ = _create(db, repository, pull_request, review, issues[:1])
    tracking = _commit(db, record, issues[:1])
    follow_up = Review(pull_request=pull_request, summary="clean", commit_sha=record.generated_commit_sha)
    db.add(follow_up)
    db.commit()

    tracking.complete_review(
        db,
        record=record,
        review=follow_up,
        new_issues=[],
        issues_match=lambda current, original: current.comment == original.comment,
    )
    response = _fix_commit_response(record)

    assert record.status == FixCommitStatus.RESOLVED.value
    assert record.resolved_issue_count == 1
    assert record.remaining_issue_count == 0
    assert follow_up.fix_commit_id == record.id
    assert issues[0].status == IssueStatus.RESOLVED.value
    assert response.generated_commit_sha == record.generated_commit_sha
    assert response.follow_up_review_id == follow_up.id
    assert response.issues[0].status == FixCommitIssueStatus.RESOLVED

    detail = get_fix_commit(repository.id, record.id, db)
    history = get_pull_request_fix_commits(repository.id, pull_request.id, db)
    assert detail.generated_commit_sha == record.generated_commit_sha
    assert detail.source_head_sha == "head-1"
    assert history[0].id == record.id


def test_mixed_follow_up_review_is_partially_resolved(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, _ = _create(db, repository, pull_request, review, issues)
    tracking = _commit(db, record, issues)
    follow_up = Review(pull_request=pull_request, summary="one remains", commit_sha=record.generated_commit_sha)
    db.add(follow_up)
    db.commit()

    tracking.complete_review(
        db,
        record=record,
        review=follow_up,
        new_issues=[SimpleNamespace(comment=issues[1].comment)],
        issues_match=lambda current, original: current.comment == original.comment,
    )

    assert record.status == FixCommitStatus.PARTIALLY_RESOLVED.value
    assert record.resolved_issue_count == 1
    assert record.remaining_issue_count == 1


def test_invalid_status_transition_is_rejected(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    record, _ = _create(db, repository, pull_request, review, issues[:1])

    with pytest.raises(ValueError, match="REQUESTED -> COMMITTING"):
        FixCommitTrackingService().transition(db, record, FixCommitStatus.COMMITTING)


def test_only_one_request_can_claim_commit_creation(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    record, _ = _create(db, repository, pull_request, review, issues[:1])
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    tracking.mark_validating(db, record)
    tracking.mark_committing(db, record, "fix(ai): once")

    with pytest.raises(FixCommitAlreadyClaimedError):
        tracking.mark_committing(db, record, "fix(ai): duplicate")

    assert record.status == FixCommitStatus.COMMITTING.value
    assert record.commit_message == "fix(ai): once"


def test_pushed_commit_persistence_can_recover_from_committed_state(lifecycle_db):
    db, repository, pull_request, review, issues = lifecycle_db
    tracking = FixCommitTrackingService()
    record, _ = _create(db, repository, pull_request, review, issues[:1])
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    tracking.mark_validating(db, record)
    tracking.mark_committing(db, record, "fix(ai): recover")
    record.status = FixCommitStatus.COMMITTED.value
    db.commit()
    result = SimpleNamespace(
        branch_name="feature",
        commit_sha="recovered-sha",
        commit_url="https://github.com/owner/repo/commit/recovered-sha",
        commit_message="fix(ai): recover",
    )

    recovered = tracking.recover_after_push(
        db,
        fix_commit_id=record.id,
        result=result,
    )

    assert recovered.status == FixCommitStatus.REVIEW_PENDING.value
    assert recovered.generated_commit_sha == "recovered-sha"
