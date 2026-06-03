from sqlalchemy.orm import Session

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
    )

    db.add(review)
    db.flush()

    for issue_data in review_data.issues:

        issue = Issue(
            review_id=review.id,
            severity=issue_data.severity,
            category=issue_data.category,
            file=issue_data.file,
            comment=issue_data.comment,
        )

        db.add(issue)

    db.commit()
    db.refresh(review)

    return review
