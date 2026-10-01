from sqlalchemy import select
from sqlalchemy.orm import with_expression

from app.db.models import PullRequest, Review


def get_pull_requests_for_repository(
    db,
    repository_id: int,
):
    latest_review_id = (
        select(Review.id)
        .where(Review.pr_id == PullRequest.id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(1)
        .correlate(PullRequest)
        .scalar_subquery()
    )
    return (
        db.query(PullRequest)
        .options(with_expression(PullRequest.review_id, latest_review_id))
        .filter(PullRequest.repository_id == repository_id)
        .order_by(PullRequest.id.desc())
        .all()
    )
