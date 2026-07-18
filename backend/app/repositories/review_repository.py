from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    PullRequest,
    Review,
    Issue,
)

from app.schemas.output import (
    IssueStatus,
    PullRequestSchema,
    ReviewResponseSchema,
)


def save_review(
    db: Session,
    pr_data: PullRequestSchema,
    review_data: ReviewResponseSchema,
    commit_sha
):
    pr = (
        db.query(PullRequest)
        .filter(PullRequest.github_pr_id == pr_data.github_pr_id)
        .one_or_none()
    )

    if pr is None:
        pr = PullRequest(
            github_pr_id=pr_data.github_pr_id,
            title=pr_data.title,
            repository=pr_data.repository,
            author=pr_data.author,
        )
        db.add(pr)
    else:
        pr.title = pr_data.title
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

        issue = Issue(
            review_id=review.id,
            severity=issue_data.severity,
            category=issue_data.category,
            file=issue_data.file,
            line=issue_data.line,
            comment=issue_data.comment,
            impact=issue_data.impact,
            status=IssueStatus.OPEN.value,
        )

        db.add(issue)

    db.commit()
    db.refresh(review)

    return review


def get_review_by_id(
    db,
    review_id: int
):
    return (
        db.query(Review)
        .options(
            joinedload(Review.issues)
        )
        .filter(
            Review.id == review_id
        )
        .first()
    )


def get_all_reviews(
    db
):
    return db.query(Review).all()


def get_latest_review_for_pull_request(
    db: Session,
    github_pr_id: int,
    exclude_commit_sha: str | None = None,
) -> Review | None:
    query = (
        db.query(Review)
        .join(PullRequest)
        .options(joinedload(Review.issues))
        .filter(PullRequest.github_pr_id == github_pr_id)
    )

    if exclude_commit_sha is not None:
        query = query.filter(Review.commit_sha != exclude_commit_sha)

    return query.order_by(Review.id.desc()).first()


def get_issue_by_id(db: Session, issue_id: int) -> Issue | None:
    return db.query(Issue).filter(Issue.id == issue_id).first()


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
    issue.status = resolved_status.value

    db.commit()
    db.refresh(issue)

    return issue
