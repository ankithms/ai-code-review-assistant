from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    PullRequest,
    Review,
    Issue,
)

from app.schemas.output import (
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
