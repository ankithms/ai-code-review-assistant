import dramatiq

from app.queue.broker import redis_broker


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
