from sqlalchemy import case, func

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

    issue_counts = _get_issue_counts(db, repository_id)
    total_issues = issue_counts["total_issues"]

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
        "high_severity": issue_counts["high_severity"],
        "medium_severity": issue_counts["medium_severity"],
        "low_severity": issue_counts["low_severity"],
        "open_issues": issue_counts["open_issues"],
        "resolved_issues": issue_counts["resolved_issues"],
        "ignored_issues": issue_counts["ignored_issues"],
        "bug_issues": issue_counts["bug_issues"],
        "security_issues": issue_counts["security_issues"],
        "performance_issues": issue_counts["performance_issues"],
        "readability_issues": issue_counts["readability_issues"],
        "edge_case_issues": issue_counts["edge_case_issues"],
        "top_problematic_files": top_problematic_files,
        "average_issues_per_pull_request": average_issues_per_pull_request,
        "average_review_processing_time_seconds": average_review_processing_time_seconds,
    }


def _count_when(condition):
    return func.sum(case((condition, 1), else_=0))


def _get_issue_counts(db, repository_id: int) -> dict[str, int]:
    counts = (
        db.query(
            func.count(Issue.id).label("total_issues"),
            _count_when(func.lower(Issue.severity) == "high").label("high_severity"),
            _count_when(func.lower(Issue.severity) == "medium").label("medium_severity"),
            _count_when(func.lower(Issue.severity) == "low").label("low_severity"),
            _count_when(Issue.status == "OPEN").label("open_issues"),
            _count_when(Issue.status == "RESOLVED").label("resolved_issues"),
            _count_when(Issue.status == "IGNORED").label("ignored_issues"),
            _count_when(func.lower(Issue.category) == "bug").label("bug_issues"),
            _count_when(func.lower(Issue.category) == "security").label("security_issues"),
            _count_when(func.lower(Issue.category) == "performance").label("performance_issues"),
            _count_when(func.lower(Issue.category) == "readability").label("readability_issues"),
            _count_when(func.lower(Issue.category) == "edge_case").label("edge_case_issues"),
        )
        .select_from(Issue)
        .join(Review)
        .join(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
        .one()
    )

    return {
        key: int(getattr(counts, key) or 0)
        for key in (
            "total_issues",
            "high_severity",
            "medium_severity",
            "low_severity",
            "open_issues",
            "resolved_issues",
            "ignored_issues",
            "bug_issues",
            "security_issues",
            "performance_issues",
            "readability_issues",
            "edge_case_issues",
        )
    }


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
