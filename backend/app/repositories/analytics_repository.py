from sqlalchemy import func

from app.db.models import (
    ReviewJob,
    Repository,
    PullRequest,
    Review,
    Issue,
)


def get_analytics(db, repository_id: int):
    total_reviews = (
        db.query(func.count(Review.id))
        .join(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
        .scalar()
    )

    total_pull_requests = (
        db.query(func.count(PullRequest.id))
        .filter(PullRequest.repository_id == repository_id)
        .scalar()
    )

    total_issues = _count_issues(db, repository_id)

    high_severity = _count_issues_by_severity(db, repository_id, "high")
    medium_severity = _count_issues_by_severity(db, repository_id, "medium")
    low_severity = _count_issues_by_severity(db, repository_id, "low")

    open_issues = _count_issues_by_status(db, repository_id, "OPEN")
    resolved_issues = _count_issues_by_status(db, repository_id, "RESOLVED")
    ignored_issues = _count_issues_by_status(db, repository_id, "IGNORED")

    bug_issues = _count_issues_by_category(db, repository_id, "bug")
    security_issues = _count_issues_by_category(db, repository_id, "security")
    performance_issues = _count_issues_by_category(db, repository_id, "performance")
    readability_issues = _count_issues_by_category(db, repository_id, "readability")
    edge_case_issues = _count_issues_by_category(db, repository_id, "edge_case")

    issue_count = func.count(Issue.id).label("issue_count")
    top_problematic_files = [
        {
            "file": file,
            "total_issues": count,
        }
        for file, count in (
            db.query(Issue.file, issue_count)
            .join(Review)
            .join(PullRequest)
            .filter(Issue.file.isnot(None))
            .filter(PullRequest.repository_id == repository_id)
            .group_by(Issue.file)
            .order_by(issue_count.desc(), Issue.file.asc())
            .limit(5)
            .all()
        )
    ]

    average_issues_per_pull_request = (
        round(total_issues / total_pull_requests, 2)
        if total_pull_requests
        else 0
    )
    average_review_processing_time_seconds = _average_review_processing_time_seconds(
        db,
        repository_id,
    )

    return {
        "total_ai_reviews": total_reviews,
        "total_reviews": total_reviews,
        "total_pull_requests": total_pull_requests,
        "total_issues": total_issues,
        "high_severity": high_severity,
        "medium_severity": medium_severity,
        "low_severity": low_severity,
        "open_issues": open_issues,
        "resolved_issues": resolved_issues,
        "ignored_issues": ignored_issues,
        "bug_issues": bug_issues,
        "security_issues": security_issues,
        "performance_issues": performance_issues,
        "readability_issues": readability_issues,
        "edge_case_issues": edge_case_issues,
        "top_problematic_files": top_problematic_files,
        "average_issues_per_pull_request": average_issues_per_pull_request,
        "average_review_processing_time_seconds": average_review_processing_time_seconds,
    }


def _repository_issue_query(db, repository_id: int):
    return (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
    )


def _count_issues(db, repository_id: int) -> int:
    return _repository_issue_query(db, repository_id).count()


def _count_issues_by_status(
    db,
    repository_id: int,
    status: str,
) -> int:
    return (
        _repository_issue_query(db, repository_id)
        .filter(Issue.status == status)
        .count()
    )


def _count_issues_by_severity(
    db,
    repository_id: int,
    severity: str,
) -> int:
    return (
        _repository_issue_query(db, repository_id)
        .filter(func.lower(Issue.severity) == severity)
        .count()
    )


def _count_issues_by_category(db, repository_id: int, category: str) -> int:
    return (
        _repository_issue_query(db, repository_id)
        .filter(func.lower(Issue.category) == category)
        .count()
    )


def _average_review_processing_time_seconds(
    db,
    repository_id: int,
) -> float | None:
    durations = []

    for started_at, completed_at in (
        db.query(ReviewJob.started_at, ReviewJob.completed_at)
        .join(Repository, Repository.full_name == ReviewJob.repository)
        .filter(
            Repository.id == repository_id,
            ReviewJob.started_at.isnot(None),
            ReviewJob.completed_at.isnot(None),
        )
        .all()
    ):
        duration = completed_at - started_at
        durations.append(duration.total_seconds())

    if not durations:
        return None

    return round(sum(durations) / len(durations), 2)
