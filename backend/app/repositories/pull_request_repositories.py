from app.db.models import PullRequest


def get_pull_requests(db):
    return db.query(PullRequest).all()