from sqlalchemy import func

from app.db.models import (
    PullRequest,
    Review,
    Issue,
)


def get_analytics(db):

    total_reviews = (
        db.query(func.count(Review.id))
        .scalar()
    )

    total_pull_requests = (
        db.query(func.count(PullRequest.id))
        .scalar()
    )

    total_issues = (
        db.query(func.count(Issue.id))
        .scalar()
    )

    high_severity = (
        db.query(func.count(Issue.id))
        .filter(func.lower(Issue.severity) == "high")
        .scalar()
    )

    medium_severity = (
        db.query(func.count(Issue.id))
        .filter(func.lower(Issue.severity) == "medium")
        .scalar()
    )

    low_severity = (
        db.query(func.count(Issue.id))
        .filter(func.lower(Issue.severity) == "low")
        .scalar()
    )

    return {
        "total_reviews": total_reviews,
        "total_pull_requests": total_pull_requests,
        "total_issues": total_issues,
        "high_severity": high_severity,
        "medium_severity": medium_severity,
        "low_severity": low_severity,
    }