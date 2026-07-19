from app.db.models import PullRequest


def get_pull_requests_for_repository(
    db,
    repository_id: int,
):
    return (
        db.query(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
        .order_by(PullRequest.id.desc())
        .all()
    )
