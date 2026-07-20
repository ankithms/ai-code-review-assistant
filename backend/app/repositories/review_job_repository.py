from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models import ReviewJob


PENDING = "PENDING"
RUNNING = "RUNNING"
SUCCESS = "SUCCESS"
FAILED = "FAILED"

ACTIVE_STATUSES = (PENDING, RUNNING)


def create_review_job(
    db: Session,
    repository: str,
    pull_request_number: int,
    commit_sha: str,
    event_action: str | None = None,
    base_commit_sha: str | None = None,
    head_commit_sha: str | None = None,
) -> ReviewJob:
    job = ReviewJob(
        repository=repository,
        pull_request_number=pull_request_number,
        commit_sha=commit_sha,
        event_action=event_action,
        base_commit_sha=base_commit_sha,
        head_commit_sha=head_commit_sha or commit_sha,
        status=PENDING,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


def get_review_job(db: Session, job_id: int) -> ReviewJob | None:
    return db.query(ReviewJob).filter(ReviewJob.id == job_id).first()


def get_active_review_job_by_commit(
    db: Session,
    commit_sha: str,
) -> ReviewJob | None:
    return (
        db.query(ReviewJob)
        .filter(
            ReviewJob.commit_sha == commit_sha,
            ReviewJob.status.in_(ACTIVE_STATUSES),
        )
        .first()
    )


def get_latest_review_job_by_commit(
    db: Session,
    commit_sha: str,
) -> ReviewJob | None:
    return (
        db.query(ReviewJob)
        .filter(ReviewJob.commit_sha == commit_sha)
        .order_by(ReviewJob.id.desc())
        .first()
    )


def mark_review_job_running(db: Session, job: ReviewJob) -> ReviewJob:
    job.status = RUNNING
    job.started_at = datetime.now(UTC)
    job.completed_at = None
    job.error_message = None

    db.commit()
    db.refresh(job)

    return job


def mark_review_job_success(db: Session, job: ReviewJob) -> ReviewJob:
    job.status = SUCCESS
    job.completed_at = datetime.now(UTC)
    job.error_message = None

    db.commit()
    db.refresh(job)

    return job


def mark_review_job_failed(
    db: Session,
    job: ReviewJob,
    error_message: str,
) -> ReviewJob:
    job.status = FAILED
    job.completed_at = datetime.now(UTC)
    job.error_message = error_message[:4000]

    db.commit()
    db.refresh(job)

    return job
