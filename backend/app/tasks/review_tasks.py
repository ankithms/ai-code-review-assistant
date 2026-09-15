import dramatiq

from app.logging import configure_logging
from app.monitoring import start_worker_metrics_server
from app.queue.broker import redis_broker


configure_logging()
start_worker_metrics_server()


@dramatiq.actor(
    broker=redis_broker,
    max_retries=3,
    min_backoff=30_000,
    max_backoff=300_000,
    time_limit=600_000,
)
def process_review_job(job_id: int) -> None:
    from app.services.review_processing_service import process_review_job as process_job

    process_job(job_id)


@dramatiq.actor(
    broker=redis_broker,
    # Command processing records and reports terminal failures itself. Automatic
    # retries could duplicate GitHub replies; users explicitly retry FAILED or
    # STALE attempts by posting a new command comment.
    max_retries=0,
    time_limit=600_000,
)
def process_github_native_fix_command(payload: dict, event: str | None) -> None:
    import os

    from app.db.database import SessionLocal
    from app.services.github_native_fix_service import handle_github_native_fix_comment

    db = SessionLocal()
    try:
        handle_github_native_fix_comment(
            db=db,
            payload=payload,
            event=event,
            access_token=os.getenv("GITHUB_ACCESS_TOKEN"),
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
