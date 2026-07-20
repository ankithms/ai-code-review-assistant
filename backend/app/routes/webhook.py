import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Review
from app.repositories.review_job_repository import (
    SUCCESS,
    create_review_job,
    get_active_review_job_by_commit,
    get_latest_review_job_by_commit,
    mark_review_job_failed,
)
from app.tasks.review_tasks import process_review_job

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"]
)

@router.post("/github")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    body = await request.body()
    verify_github_signature(request, body)

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid JSON payload",
        ) from exc

    action = payload.get("action")

    if action not in ["opened", "reopened", "synchronize"]:
        return {
            "status": "ignored",
            "action": action,
        }

    pull_request = payload.get("pull_request")
    if not pull_request:
        raise HTTPException(
            status_code=400,
            detail="Webhook payload is missing pull_request",
        )

    repository = payload.get("repository") or {}
    repository_full_name = repository.get("full_name")
    pull_request_number = pull_request.get("number")
    commit_sha = (pull_request.get("head") or {}).get("sha")
    base_commit_sha = payload.get("before") if action == "synchronize" else None
    head_commit_sha = payload.get("after") or commit_sha

    if not repository_full_name or not pull_request_number or not commit_sha:
        raise HTTPException(
            status_code=400,
            detail="Webhook payload is missing repository, pull request number, or commit sha",
        )

    if action == "synchronize" and not base_commit_sha:
        raise HTTPException(
            status_code=400,
            detail="Webhook payload is missing previous head commit sha for synchronize review",
        )

    active_job = get_active_review_job_by_commit(db, commit_sha)

    if active_job:
        logger.info(
            "Commit %s already has active review job %s",
            commit_sha,
            active_job.id,
        )
        return {
            "status": "queued",
            "job_id": active_job.id,
        }

    existing_review = (
        db.query(Review)
        .filter(Review.commit_sha == commit_sha)
        .first()
    )

    if existing_review:
        latest_job = get_latest_review_job_by_commit(db, commit_sha)

        if latest_job and latest_job.status == SUCCESS:
            logger.info("Commit %s already reviewed and posted", commit_sha)
            return {
                "status": "ignored",
                "reason": "commit_already_reviewed",
                "review_id": existing_review.id,
            }

        logger.info(
            "Commit %s has saved review %s but no successful posting job; enqueueing retry",
            commit_sha,
            existing_review.id,
        )

    job = create_review_job(
        db=db,
        repository=repository_full_name,
        pull_request_number=pull_request_number,
        commit_sha=commit_sha,
        event_action=action,
        base_commit_sha=base_commit_sha,
        head_commit_sha=head_commit_sha,
    )

    try:
        process_review_job.send(job.id)
    except Exception as exc:
        mark_review_job_failed(db, job, str(exc))
        logger.exception("Failed to enqueue review job %s", job.id)
        raise HTTPException(
            status_code=503,
            detail="Review queue is unavailable",
        ) from exc

    return {
        "status": "queued",
        "job_id": job.id,
    }


def verify_github_signature(request, body):
    import os

    secret = os.getenv("GITHUB_WEBHOOK_SECRET")

    if not secret:
        return

    signature = request.headers.get("X-Hub-Signature-256")

    if not signature:
        raise HTTPException(
            status_code=401,
            detail="Missing GitHub webhook signature",
        )

    expected = "sha256=" + hmac.new(
        secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(
            status_code=401,
            detail="Invalid GitHub webhook signature",
        )
