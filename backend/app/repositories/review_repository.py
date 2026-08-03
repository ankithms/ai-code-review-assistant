from datetime import UTC, datetime

from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    FixCommit,
    FixPullRequest,
    PullRequest,
    Review,
    Issue,
    IssueTimelineEvent,
)
from app.repositories.repository_repository import get_or_create_repository

from app.schemas.output import (
    FixPullRequestStatus,
    IssueFixStatus,
    IssueStatus,
    PullRequestSchema,
    ReviewResponseSchema,
)
from app.services.issue_matching_service import IssueMatchingService


def save_review(
    db: Session,
    pr_data: PullRequestSchema,
    review_data: ReviewResponseSchema,
    commit_sha
):
    repository = get_or_create_repository(db, pr_data.repository)
    pr = (
        db.query(PullRequest)
        .filter(PullRequest.github_pr_id == pr_data.github_pr_id)
        .one_or_none()
    )

    if pr is None:
        pr = PullRequest(
            repository_id=repository.id,
            github_pr_id=pr_data.github_pr_id,
            pull_request_number=pr_data.pull_request_number,
            title=pr_data.title,
            repository=pr_data.repository,
            author=pr_data.author,
        )
        db.add(pr)
    else:
        pr.title = pr_data.title
        pr.repository_id = repository.id
        pr.pull_request_number = pr_data.pull_request_number
        pr.repository = pr_data.repository
        pr.author = pr_data.author

    db.flush()

    review = Review(
        pr_id=pr.id,
        summary=review_data.summary,
        commit_sha=commit_sha
    )

    db.add(review)
    db.flush()

    for issue_data in review_data.issues:
        fix = getattr(issue_data, "fix", None)

        issue = Issue(
            review_id=review.id,
            severity=issue_data.severity,
            category=issue_data.category,
            file=issue_data.file,
            line=issue_data.line,
            line_ref=getattr(issue_data, "line_ref", None),
            side=_enum_value(getattr(issue_data, "side", None)),
            start_line=getattr(issue_data, "start_line", None),
            start_side=_enum_value(getattr(issue_data, "start_side", None)),
            old_line=getattr(issue_data, "old_line", None),
            diff_hunk=getattr(issue_data, "diff_hunk", None),
            source_commit_sha=getattr(issue_data, "source_commit_sha", None),
            comment=issue_data.comment,
            impact=issue_data.impact,
            fix_file_path=fix.file_path if fix else None,
            fix_start_line=fix.start_line if fix else None,
            fix_end_line=fix.end_line if fix else None,
            fix_replacement_code=fix.replacement_code if fix else None,
            fix_explanation=fix.explanation if fix else None,
            fix_status=(
                IssueFixStatus.FIX_GENERATED.value
                if fix
                else IssueFixStatus.NO_FIX.value
            ),
            github_review_thread_id=issue_data.github_review_thread_id,
            github_comment_id=issue_data.github_comment_id,
            github_comment_node_id=issue_data.github_comment_node_id,
            github_review_id=issue_data.github_review_id,
            status=IssueStatus.OPEN.value,
        )
        db.add(issue)
        db.flush()
        issue.fingerprint = IssueMatchingService().fingerprint(issue)
        db.add(
            IssueTimelineEvent(
                issue_id=issue.id,
                event="DETECTED",
                details=f"review {review.id}",
            )
        )

    db.commit()
    db.refresh(review)

    return review


def _enum_value(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return str(value)


def get_review_by_id_for_repository(
    db: Session,
    review_id: int,
    repository_id: int,
) -> Review | None:
    return (
        db.query(Review)
        .join(PullRequest)
        .options(
            joinedload(Review.issues).joinedload(Issue.fix_pull_requests),
            joinedload(Review.issues).joinedload(Issue.fix_commits),
            joinedload(Review.fix_pull_requests).joinedload(FixPullRequest.issues),
            joinedload(Review.fix_commits).joinedload(FixCommit.issues),
            joinedload(Review.fix_commits).joinedload(FixCommit.issue_links),
            joinedload(Review.fix_commits).joinedload(FixCommit.new_issues),
            joinedload(Review.issues).joinedload(Issue.timeline_events),
            joinedload(Review.fix_commits).joinedload(FixCommit.follow_up_review),
            joinedload(Review.pull_request),
        )
        .filter(
            Review.id == review_id,
            PullRequest.repository_id == repository_id,
        )
        .first()
    )


def get_reviews_for_repository(
    db: Session,
    repository_id: int,
) -> list[Review]:
    return (
        db.query(Review)
        .join(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
        .order_by(Review.id.desc())
        .all()
    )


def get_latest_review_for_pull_request(
    db: Session,
    github_pr_id: int | None = None,
    repository_id: int | None = None,
    pull_request_number: int | None = None,
    exclude_commit_sha: str | None = None,
) -> Review | None:
    query = (
        db.query(Review)
        .join(PullRequest)
        .options(joinedload(Review.issues))
    )

    if github_pr_id is not None:
        query = query.filter(PullRequest.github_pr_id == github_pr_id)

    if repository_id is not None:
        query = query.filter(PullRequest.repository_id == repository_id)

    if pull_request_number is not None:
        query = query.filter(PullRequest.pull_request_number == pull_request_number)

    if exclude_commit_sha is not None:
        query = query.filter(Review.commit_sha != exclude_commit_sha)

    return query.order_by(Review.id.desc()).first()


def get_open_issues_for_pull_request(
    db: Session,
    repository_id: int | None = None,
    github_pr_id: int | None = None,
    pull_request_number: int | None = None,
) -> list[Issue]:
    query = (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .filter(Issue.status == IssueStatus.OPEN.value)
    )

    if repository_id is not None:
        query = query.filter(PullRequest.repository_id == repository_id)

    if github_pr_id is not None:
        query = query.filter(PullRequest.github_pr_id == github_pr_id)

    if pull_request_number is not None:
        query = query.filter(PullRequest.pull_request_number == pull_request_number)

    return query.order_by(Issue.id.asc()).all()


def get_issue_by_id_for_repository(
    db: Session,
    issue_id: int,
    repository_id: int,
) -> Issue | None:
    return (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .filter(
            Issue.id == issue_id,
            PullRequest.repository_id == repository_id,
        )
        .first()
    )


def _coerce_issue_status(status) -> IssueStatus:
    if isinstance(status, IssueStatus):
        return status

    if isinstance(status, str):
        normalized_status = status.strip().upper()
        try:
            return IssueStatus(normalized_status)
        except ValueError as exc:
            raise ValueError(f"Invalid issue status: {status}") from exc

    raise ValueError(f"Invalid issue status: {status}")


def update_issue_status(
    db: Session,
    issue: Issue,
    status,
) -> Issue:
    resolved_status = _coerce_issue_status(status)
    if _issue_has_merged_fix(issue) and resolved_status != IssueStatus.RESOLVED:
        raise ValueError("Issues fixed by a merged AI Fix PR must remain RESOLVED")

    issue.status = resolved_status.value

    if resolved_status == IssueStatus.RESOLVED:
        if issue.resolved_at is None:
            issue.resolved_at = _merged_fix_resolved_at(issue) or datetime.now(UTC)
    else:
        issue.resolved_at = None
        issue.resolved_by = None

    db.add(
        IssueTimelineEvent(
            issue_id=issue.id,
            event=resolved_status.value,
            details="manual status update",
        )
    )

    db.commit()
    db.refresh(issue)

    return issue


def reconcile_merged_fix_issue_statuses(db: Session, review: Review) -> int:
    updated_count = 0
    for issue in review.issues:
        if not _issue_has_merged_fix(issue):
            continue

        resolved_at = _merged_fix_resolved_at(issue) or datetime.now(UTC)
        changed = False

        if issue.status != IssueStatus.RESOLVED.value:
            issue.status = IssueStatus.RESOLVED.value
            changed = True

        if issue.fix_status != IssueFixStatus.FIX_MERGED.value:
            issue.fix_status = IssueFixStatus.FIX_MERGED.value
            changed = True

        if issue.resolved_at is None:
            issue.resolved_at = resolved_at
            changed = True

        if changed:
            db.add(issue)
            updated_count += 1

    if updated_count:
        db.commit()

    return updated_count


def _issue_has_merged_fix(issue: Issue) -> bool:
    if issue.fix_status == IssueFixStatus.FIX_MERGED.value:
        return True

    return any(
        fix_pull_request.status == FixPullRequestStatus.MERGED.value
        for fix_pull_request in issue.fix_pull_requests
    )


def _merged_fix_resolved_at(issue: Issue):
    merged_times = [
        fix_pull_request.merged_at
        for fix_pull_request in issue.fix_pull_requests
        if (
            fix_pull_request.status == FixPullRequestStatus.MERGED.value
            and fix_pull_request.merged_at is not None
        )
    ]
    return max(merged_times) if merged_times else None
