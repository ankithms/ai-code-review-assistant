import json
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, Issue, PullRequest, Repository, Review
from app.routes.fixes import _fix_commit_response
from app.schemas.output import FixCommitIssueStatus, FixCommitStatus, IssueStatus
from app.services.fix_commit_tracking_service import FixCommitTrackingService
from app.services.issue_matching_service import IssueMatchingService


@pytest.fixture()
def verification_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    repository = Repository(full_name="owner/repo")
    pull_request = PullRequest(
        repository_ref=repository,
        github_pr_id=301,
        pull_request_number=17,
        title="Verification",
        repository="owner/repo",
        author="developer",
    )
    review = Review(pull_request=pull_request, summary="original", commit_sha="source-head")
    db.add_all([repository, pull_request, review])
    db.commit()
    try:
        yield db, repository, pull_request, review
    finally:
        db.close()


def _issue(review, *, file="src/service.py", line=10, category="bug", comment="Unchecked result can fail"):
    issue = Issue(
        review=review,
        severity="high",
        category=category,
        file=file,
        line=line,
        comment=comment,
        status=IssueStatus.OPEN.value,
    )
    return issue


def _committed_record(db, repository, pull_request, review, issues, *, head="source-head"):
    tracking = FixCommitTrackingService()
    record, _ = tracking.create_or_get(
        db,
        repository_id=repository.id,
        pull_request_id=pull_request.id,
        review_id=review.id,
        issues=issues,
        source_head_sha=head,
        source_branch="feature",
    )
    tracking.transition(db, record, FixCommitStatus.GENERATING)
    for issue in issues:
        issue.fix_file_path = issue.file
        issue.fix_start_line = issue.line
        issue.fix_end_line = issue.line
        issue.fix_replacement_code = "fixed = True"
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
    tracking.mark_committing(db, record, "fix(ai): verify")
    tracking.mark_committed(
        db,
        record,
        SimpleNamespace(
            branch_name="feature",
            commit_sha=f"ai-fix-{record.id}",
            commit_url=f"https://github.com/owner/repo/commit/ai-fix-{record.id}",
        ),
    )
    return tracking, record


def _complete(db, tracking, record, pull_request, current_issues, *, rename_map=None):
    follow_up = Review(
        pull_request=pull_request,
        summary="follow-up",
        commit_sha=record.generated_commit_sha,
    )
    for issue in current_issues:
        if isinstance(issue, Issue):
            issue.review = follow_up
    db.add(follow_up)
    db.commit()
    return tracking.complete_review(
        db,
        record=record,
        review=follow_up,
        new_issues=current_issues,
        rename_map=rename_map,
    )


def test_issue_disappears_and_deleted_file_are_resolved(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])

    _complete(db, tracking, record, pull_request, [])

    assert record.issue_links[0].status == FixCommitIssueStatus.RESOLVED.value
    assert original.status == IssueStatus.RESOLVED.value
    assert record.resolved_issue_count == 1


def test_equivalent_issue_on_same_line_is_still_open(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    current = SimpleNamespace(**{
        "severity": original.severity,
        "category": original.category,
        "file": original.file,
        "line": original.line,
        "comment": original.comment,
        "impact": None,
    })

    _complete(db, tracking, record, pull_request, [current])

    link = record.issue_links[0]
    assert link.status == FixCommitIssueStatus.STILL_OPEN.value
    assert link.match_confidence == "HIGH"
    assert record.remaining_issue_count == 1


def test_equivalent_issue_on_new_line_is_moved_and_tracks_locations(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review, line=10)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    current = SimpleNamespace(
        severity="high",
        category="bug",
        file="src/service.py",
        line=42,
        comment=original.comment,
        impact=None,
    )

    _complete(db, tracking, record, pull_request, [current])

    link = record.issue_links[0]
    assert link.status == FixCommitIssueStatus.MOVED.value
    assert (link.original_line, link.current_line) == (10, 42)
    assert record.moved_issue_count == 1


def test_renamed_file_uses_github_rename_mapping(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review, file="src/old.py")
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    current = SimpleNamespace(
        severity="high",
        category="bug",
        file="src/new.py",
        line=10,
        comment=original.comment,
        impact=None,
    )

    _complete(
        db,
        tracking,
        record,
        pull_request,
        [current],
        rename_map={"src/old.py": "src/new.py"},
    )

    link = record.issue_links[0]
    assert link.status == FixCommitIssueStatus.MOVED.value
    assert link.current_file == "src/new.py"
    assert "rename mapping" in link.match_reason


def test_low_confidence_candidate_fails_verification_without_guessing(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    unrelated = SimpleNamespace(
        severity="low",
        category="bug",
        file="other.py",
        line=200,
        comment="A completely unrelated concern",
        impact=None,
    )

    _complete(db, tracking, record, pull_request, [unrelated])

    link = record.issue_links[0]
    assert link.status == FixCommitIssueStatus.FAILED_TO_VERIFY.value
    assert original.status == IssueStatus.OPEN.value
    assert record.failed_issue_count == 1


def test_new_issue_is_persisted_and_exposed_separately(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    introduced = _issue(
        review,
        file="src/new_problem.py",
        line=7,
        category="security",
        comment="User input reaches a shell command",
    )

    _complete(db, tracking, record, pull_request, [introduced])
    response = _fix_commit_response(record)

    assert record.new_issue_count == 1
    assert introduced.introduced_by_fix_commit_id == record.id
    assert response.new_issues[0].id == introduced.id
    assert response.resolved_issues[0].issue_id == original.id
    assert json.loads(response.verification_summary)["new"] == 1


def test_multiple_original_issues_can_match_one_remaining_finding(verification_db):
    db, repository, pull_request, review = verification_db
    originals = [
        _issue(review, line=10, comment="Shared unsafe state is not synchronized"),
        _issue(review, line=11, comment="Shared unsafe state is not synchronized"),
    ]
    db.add_all(originals)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, originals)
    merged = SimpleNamespace(
        severity="high",
        category="bug",
        file="src/service.py",
        line=10,
        comment="Shared unsafe state is not synchronized",
        impact=None,
    )

    _complete(db, tracking, record, pull_request, [merged])

    assert {link.status for link in record.issue_links} == {
        FixCommitIssueStatus.STILL_OPEN.value,
        FixCommitIssueStatus.MOVED.value,
    }


def test_split_finding_keeps_best_match_and_counts_extra_as_new(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review, comment="Unchecked result can fail")
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])
    matched = _issue(review, line=10, comment=original.comment)
    extra = _issue(
        review,
        file="src/extra.py",
        line=4,
        category="performance",
        comment="Repeated query causes excessive work",
    )

    _complete(db, tracking, record, pull_request, [matched, extra])

    assert record.issue_links[0].status == FixCommitIssueStatus.STILL_OPEN.value
    assert record.new_issue_count == 1
    assert extra.introduced_by_fix_commit_id == record.id


def test_review_failure_marks_committed_issues_failed_to_verify(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])

    tracking.record_review_failure(db, record.id, "model timed out")

    assert record.status == FixCommitStatus.REVIEW_PENDING.value
    assert record.issue_links[0].status == FixCommitIssueStatus.FAILED_TO_VERIFY.value
    assert record.failed_issue_count == 1


def test_timeline_records_selected_validated_committed_rereviewed_and_result(verification_db):
    db, repository, pull_request, review = verification_db
    original = _issue(review)
    db.add(original)
    db.commit()
    tracking, record = _committed_record(db, repository, pull_request, review, [original])

    _complete(db, tracking, record, pull_request, [])
    response = _fix_commit_response(record)
    events = [event.event for event in response.issues[0].timeline]

    assert events == [
        "DETECTED",
        "SELECTED_FOR_AI_FIX",
        "VALIDATED",
        "COMMITTED",
        "RE_REVIEWED",
        "RESOLVED",
    ]
    assert response.verification_status == "COMPLETED"


def test_manual_fix_and_multiple_ai_commits_remain_independently_verifiable(verification_db):
    db, repository, pull_request, review = verification_db
    first = _issue(review, line=10)
    second = _issue(review, line=20, file="src/second.py", comment="Second issue remains")
    db.add_all([first, second])
    db.commit()
    tracking, first_record = _committed_record(
        db, repository, pull_request, review, [first], head="source-head"
    )
    _complete(db, tracking, first_record, pull_request, [])
    _, second_record = _committed_record(
        db, repository, pull_request, review, [second], head=first_record.generated_commit_sha
    )

    assert first_record.status == FixCommitStatus.RESOLVED.value
    assert second_record.id != first_record.id
    assert second_record.status == FixCommitStatus.REVIEW_PENDING.value


def test_duplicate_detection_and_verification_share_the_same_matcher():
    matcher = IssueMatchingService()
    original = SimpleNamespace(
        severity="high",
        category="bug",
        file="src/a.py",
        line=10,
        comment="Unchecked result can fail",
        impact=None,
        fingerprint=None,
    )
    current = SimpleNamespace(
        severity="high",
        category="bug",
        file="src/a.py",
        line=12,
        comment="Unchecked result can fail",
        impact=None,
        fingerprint=None,
    )

    evidence = matcher.compare(current, original)

    assert matcher.matches(current, original) is True
    assert evidence.is_confident is True
    assert evidence.moved is True
