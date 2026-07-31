import hashlib
import hmac
import json
import logging
import os
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import FixPullRequest, Repository, Review
from app.repositories.review_job_repository import (
    SUCCESS,
    create_review_job,
    get_active_review_job_by_commit,
    get_latest_review_job_by_commit,
    mark_review_job_failed,
)
from app.schemas.output import FixPullRequestStatus, IssueFixStatus, IssueStatus
from app.services.github_native_fix_service import handle_github_native_fix_comment
from app.services.fix_commit_tracking_service import FixCommitTrackingService
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
    event = request.headers.get("X-GitHub-Event")

    if event in {"issue_comment", "pull_request_review_comment"} and action == "created":
        if handle_github_native_fix_comment(
            db=db,
            payload=payload,
            event=event,
            access_token=os.getenv("GITHUB_ACCESS_TOKEN"),
        ):
            return {
                "status": "tracked",
                "action": action,
                "event": event,
            }

        return {
            "status": "ignored",
            "action": action,
            "event": event,
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

    if _handle_fix_pull_request_webhook(
        db=db,
        repository_full_name=repository_full_name,
        action=action,
        pull_request=pull_request,
    ):
        return {
            "status": "tracked",
            "action": action,
        }

    if action not in ["opened", "reopened", "synchronize"]:
        return {
            "status": "ignored",
            "action": action,
        }

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

    tracking = FixCommitTrackingService()
    matched_fix_commit = None
    if action == "synchronize":
        matched_fix_commit = tracking.match_synchronize_commit(
            db,
            repository_full_name=repository_full_name,
            pull_request_number=pull_request_number,
            commit_sha=commit_sha,
        )

    active_job = get_active_review_job_by_commit(db, commit_sha)

    if active_job:
        if matched_fix_commit is not None and active_job.fix_commit_id is None:
            active_job.fix_commit_id = matched_fix_commit.id
            db.commit()
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
    if matched_fix_commit is not None:
        job.fix_commit_id = matched_fix_commit.id
        db.commit()
        db.refresh(job)

    try:
        process_review_job.send(job.id)
    except Exception as exc:
        mark_review_job_failed(db, job, str(exc))
        if matched_fix_commit is not None:
            tracking.record_review_failure(db, matched_fix_commit.id, str(exc))
        logger.exception("Failed to enqueue review job %s", job.id)
        raise HTTPException(
            status_code=503,
            detail="Review queue is unavailable",
        ) from exc

    return {
        "status": "queued",
        "job_id": job.id,
    }


def _handle_fix_pull_request_webhook(
    db: Session,
    repository_full_name: str | None,
    action: str | None,
    pull_request: dict,
) -> bool:
    if action not in {"opened", "reopened", "synchronize", "closed"}:
        return False

    fix_pull_request = _find_fix_pull_request(
        db=db,
        repository_full_name=repository_full_name,
        pull_request=pull_request,
    )
    if fix_pull_request is None:
        return False

    now = datetime.now(UTC)
    fix_pull_request.updated_at = now

    if action in {"opened", "reopened"}:
        fix_pull_request.status = FixPullRequestStatus.PR_CREATED.value
        fix_pull_request.closed_at = None
        fix_pull_request.failure_message = None
        for issue in fix_pull_request.issues:
            if issue.status == IssueStatus.OPEN.value:
                issue.fix_status = IssueFixStatus.FIX_PR_CREATED.value
                db.add(issue)
    elif action == "synchronize":
        fix_pull_request.status = FixPullRequestStatus.PR_CREATED.value
        head_sha = (pull_request.get("head") or {}).get("sha")
        if head_sha:
            fix_pull_request.github_commit_sha = head_sha
    elif action == "closed":
        if pull_request.get("merged"):
            fix_pull_request.status = FixPullRequestStatus.MERGED.value
            if fix_pull_request.merged_at is None:
                fix_pull_request.merged_at = now
            for issue in fix_pull_request.issues:
                issue.status = IssueStatus.RESOLVED.value
                if issue.resolved_at is None:
                    issue.resolved_at = fix_pull_request.merged_at or now
                issue.fix_status = IssueFixStatus.FIX_MERGED.value
                db.add(issue)
        else:
            fix_pull_request.status = FixPullRequestStatus.CLOSED.value
            if fix_pull_request.closed_at is None:
                fix_pull_request.closed_at = now
            for issue in fix_pull_request.issues:
                if issue.status == IssueStatus.OPEN.value:
                    issue.fix_status = IssueFixStatus.FIX_PR_CLOSED.value
                    db.add(issue)

    db.add(fix_pull_request)
    db.commit()
    return True


def _find_fix_pull_request(
    db: Session,
    repository_full_name: str | None,
    pull_request: dict,
) -> FixPullRequest | None:
    if not repository_full_name:
        return None

    query = (
        db.query(FixPullRequest)
        .join(Repository)
        .filter(Repository.full_name == repository_full_name)
    )
    github_pr_number = pull_request.get("number")
    head_ref = (pull_request.get("head") or {}).get("ref")

    if github_pr_number is not None:
        fix_pull_request = (
            query
            .filter(FixPullRequest.github_pr_number == github_pr_number)
            .one_or_none()
        )
        if fix_pull_request is not None:
            return fix_pull_request

    if head_ref:
        return (
            query
            .filter(FixPullRequest.fix_branch == head_ref)
            .one_or_none()
        )

    return None


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
