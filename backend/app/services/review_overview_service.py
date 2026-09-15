from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from app.db.models import FixCommit, Issue, PullRequest, Review, ReviewJob
from app.schemas.output import FixCommitStatus, IssueStatus
from app.services.issue_matching_service import IssueMatchingService


_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}
_ACTIVE_JOB_STATUSES = {"PENDING", "RUNNING"}


def get_pull_request_review_overviews(db: Session, repository_id: int) -> list[dict]:
    """Build the PR-centric read model without changing the review audit trail."""
    pull_requests = (
        db.query(PullRequest)
        .options(
            joinedload(PullRequest.reviews).joinedload(Review.issues),
            joinedload(PullRequest.reviews).joinedload(Review.triggering_fix_commit),
            joinedload(PullRequest.fix_commits),
        )
        .filter(PullRequest.repository_id == repository_id)
        .all()
    )
    if not pull_requests:
        return []

    repositories = {pull_request.repository for pull_request in pull_requests}
    pr_numbers = {
        pull_request.pull_request_number
        for pull_request in pull_requests
        if pull_request.pull_request_number is not None
    }
    jobs = []
    if repositories and pr_numbers:
        jobs = (
            db.query(ReviewJob)
            .options(joinedload(ReviewJob.fix_commit))
            .filter(
                ReviewJob.repository.in_(repositories),
                ReviewJob.pull_request_number.in_(pr_numbers),
            )
            .all()
        )

    jobs_by_pr = defaultdict(list)
    for job in jobs:
        jobs_by_pr[(job.repository, job.pull_request_number)].append(job)

    overviews = [
        _build_overview(
            pull_request,
            jobs_by_pr[(pull_request.repository, pull_request.pull_request_number)],
        )
        for pull_request in pull_requests
    ]
    return sorted(
        overviews,
        key=lambda overview: (
            _datetime_timestamp(
                overview["latest_run"]["created_at"]
                if overview["latest_run"]
                else overview["latest_review_time"]
            ),
            overview["pr_id"],
        ),
        reverse=True,
    )


def _build_overview(pull_request: PullRequest, jobs: list[ReviewJob]) -> dict:
    reviews = sorted(
        pull_request.reviews,
        key=lambda review: (_datetime_timestamp(review.created_at), review.id or 0),
        reverse=True,
    )
    jobs = sorted(
        jobs,
        key=lambda job: (_datetime_timestamp(job.created_at), job.id or 0),
        reverse=True,
    )
    jobs_by_commit = defaultdict(list)
    for job in jobs:
        jobs_by_commit[job.commit_sha].append(job)

    fix_commits_by_sha = {
        fix_commit.generated_commit_sha: fix_commit
        for fix_commit in pull_request.fix_commits
        if fix_commit.generated_commit_sha
    }
    history = []
    reviewed_commits = set()
    for review in reviews:
        reviewed_commits.add(review.commit_sha)
        job = jobs_by_commit[review.commit_sha][0] if jobs_by_commit[review.commit_sha] else None
        fix_commit = review.triggering_fix_commit or fix_commits_by_sha.get(review.commit_sha)
        if fix_commit is None and job is not None:
            fix_commit = job.fix_commit
        history.append(_review_run(review, job, fix_commit))

    # A queued or failed job has no Review row yet, but is still useful current
    # activity. Successful/retry jobs with a saved snapshot stay collapsed into it.
    history.extend(
        _job_run(job)
        for job in jobs
        if job.commit_sha not in reviewed_commits
    )
    history.sort(
        key=lambda run: (
            _datetime_timestamp(run["created_at"]),
            run["review_id"] or 0,
            run["job_id"] or 0,
        ),
        reverse=True,
    )

    current = _current_finding_counts(reviews)
    latest_review = reviews[0] if reviews else None
    return {
        "pr_id": pull_request.id,
        "repository": pull_request.repository,
        "pr_number": pull_request.pull_request_number,
        "title": pull_request.title,
        "author": pull_request.author,
        "latest_reviewed_commit_sha": latest_review.commit_sha if latest_review else None,
        "latest_review_id": latest_review.id if latest_review else None,
        "latest_review_time": latest_review.created_at if latest_review else None,
        **current,
        "latest_run": history[0] if history else None,
        "review_history": history,
    }


def _review_run(review: Review, job: ReviewJob | None, fix_commit: FixCommit | None) -> dict:
    run_type = _run_type(job, fix_commit)
    status = _run_status(job)
    finding_count = len(review.issues)
    resolved_count = fix_commit.resolved_issue_count if fix_commit is not None else 0
    return {
        "review_id": review.id,
        "job_id": job.id if job is not None else None,
        "commit_sha": review.commit_sha,
        "run_type": run_type,
        "status": status,
        "result": _run_result(run_type, status, finding_count, fix_commit),
        "finding_count": finding_count,
        "resolved_count": resolved_count,
        "created_at": review.created_at,
        "completed_at": job.completed_at if job is not None else review.created_at,
    }


def _job_run(job: ReviewJob) -> dict:
    run_type = _run_type(job, job.fix_commit)
    status = _run_status(job)
    return {
        "review_id": None,
        "job_id": job.id,
        "commit_sha": job.commit_sha,
        "run_type": run_type,
        "status": status,
        "result": _run_result(run_type, status, 0, job.fix_commit),
        "finding_count": 0,
        "resolved_count": 0,
        "created_at": job.created_at,
        "completed_at": job.completed_at,
    }


def _run_type(job: ReviewJob | None, fix_commit: FixCommit | None) -> str:
    if fix_commit is not None or (job is not None and job.fix_commit_id is not None):
        return "Fix verification"
    action = job.event_action if job is not None else None
    if action in {"opened", "reopened"}:
        return "Initial review"
    if action == "synchronize":
        return "Incremental review"
    return "Review"


def _run_status(job: ReviewJob | None) -> str:
    if job is None or job.status == "SUCCESS":
        return "COMPLETED"
    return job.status


def _run_result(
    run_type: str,
    status: str,
    finding_count: int,
    fix_commit: FixCommit | None,
) -> str:
    if status in _ACTIVE_JOB_STATUSES:
        return "Analysis queued" if status == "PENDING" else "Analysis in progress"
    if status == "FAILED":
        return "Analysis failed"
    if run_type == "Fix verification" and fix_commit is not None:
        if fix_commit.status == FixCommitStatus.FAILED.value:
            return "Verification failed"
        parts = []
        if fix_commit.resolved_issue_count:
            parts.append(f"{fix_commit.resolved_issue_count} resolved")
        if fix_commit.remaining_issue_count:
            parts.append(f"{fix_commit.remaining_issue_count} still open")
        if fix_commit.moved_issue_count:
            parts.append(f"{fix_commit.moved_issue_count} moved")
        if fix_commit.failed_issue_count:
            parts.append(f"{fix_commit.failed_issue_count} not verified")
        if fix_commit.new_issue_count:
            parts.append(f"{fix_commit.new_issue_count} new")
        if parts:
            return " · ".join(parts)
        return "No new findings"
    if finding_count:
        suffix = "finding" if finding_count == 1 else "findings"
        return f"{finding_count} new {suffix}"
    return "No new findings" if run_type == "Incremental review" else "No findings"


def _current_finding_counts(reviews: list[Review]) -> dict:
    matcher = IssueMatchingService()
    groups: list[list[Issue]] = []
    groups_by_fingerprint: dict[str, list[Issue]] = {}
    issues = sorted(
        (issue for review in reviews for issue in review.issues),
        key=lambda issue: (
            _datetime_timestamp(issue.review.created_at if issue.review else issue.created_at),
            issue.id or 0,
        ),
    )

    for issue in issues:
        fingerprint = matcher.fingerprint(issue)
        group = groups_by_fingerprint.get(fingerprint)
        if group is None:
            group = next(
                (candidate for candidate in groups if matcher.matches(issue, candidate[-1])),
                None,
            )
        if group is None:
            group = []
            groups.append(group)
        group.append(issue)
        groups_by_fingerprint[fingerprint] = group

    open_groups = [
        group for group in groups
        if any(issue.status == IssueStatus.OPEN.value for issue in group)
    ]
    resolved_groups = [
        group for group in groups
        if not any(issue.status == IssueStatus.OPEN.value for issue in group)
        and any(issue.status == IssueStatus.RESOLVED.value for issue in group)
    ]
    ignored_groups = [
        group for group in groups
        if all(issue.status == IssueStatus.IGNORED.value for issue in group)
    ]
    open_severities = [
        str(issue.severity).lower()
        for group in open_groups
        for issue in group
        if issue.status == IssueStatus.OPEN.value
    ]
    highest_open_severity = max(
        open_severities,
        key=lambda severity: _SEVERITY_RANK.get(severity, 0),
        default=None,
    )
    return {
        "open_findings": len(open_groups),
        "resolved_findings": len(resolved_groups),
        "ignored_findings": len(ignored_groups),
        "highest_open_severity": highest_open_severity,
    }


def _datetime_timestamp(value: datetime | None) -> float:
    return value.timestamp() if value is not None else float("-inf")
