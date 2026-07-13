import hashlib
import hmac
import json
import logging
import os

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi import BackgroundTasks

from app.github.summary_formatter import format_review_summary
from app.db.models import Review

logger = logging.getLogger(__name__)

from app.github.github_service import (
    get_pr_files,
    post_pr_comment,
    post_inline_comment
)
from app.ai.review_service import review_code
from app.db.database import SessionLocal
from app.repositories.review_repository import save_review
from app.schemas.output import PullRequestSchema

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"]
)

@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
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

    if action not in ["opened", "synchronize"]:
        return {
            "status": "ignored",
            "action": action,
        }

    pull_request = payload.get("pull_request")
    commit_id = pull_request["head"]["sha"]

    db = SessionLocal()
    
    existing_review = (
        db.query(Review)
        .filter(Review.commit_sha == commit_id)
        .first()
    )

    if existing_review:
        print("Commit already reviewed")
        return  

    if not pull_request:
        raise HTTPException(
            status_code=400,
            detail="Webhook payload is missing pull_request",
        )

    token = os.getenv("GITHUB_ACCESS_TOKEN")

    if not token:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_ACCESS_TOKEN is not configured",
        )

    files_url = pull_request["url"] + "/files"

    background_tasks.add_task(
        process_pull_request,
        payload,
        commit_id,
    )

    return {
        "status": "success"
    }


def verify_github_signature(request, body):
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


def process_pull_request(payload, commit_id):
    logger.info("Starting process_pull_request")
    token = os.getenv("GITHUB_ACCESS_TOKEN")

    pull_request = payload["pull_request"]
    logger.info(f"Processing PR #{pull_request['number']}")

    files_url = pull_request["url"] + "/files"

    files = get_pr_files(files_url, token)
    logger.info(f"Retrieved {len(files)} files")

    full_diff = ""

    for file in files:
        patch = file["patch"]

        if patch:
            full_diff += f"\n\nFILE: {file['filename']}\n"
            full_diff += patch

    logger.info("Calling AI review service")
    ai_review = review_code(full_diff)
    logger.info(f"AI review returned {len(ai_review.issues)} issues")

    pr_schema = PullRequestSchema(
        github_pr_id=pull_request["id"],
        title=pull_request["title"],
        repository=payload["repository"]["full_name"],
        author=pull_request["user"]["login"],
    )

    db = SessionLocal()

    try:
        save_review(
            db=db,
            pr_data=pr_schema,
            review_data=ai_review,
            commit_sha=commit_id
        )
    finally:
        db.close()

    review_comments_url = pull_request["review_comments_url"].replace("{/number}", "")
    logger.info(f"Review comments URL: {review_comments_url}")
    logger.info(f"Commit ID: {commit_id}")
    
    # Post inline comments for each issue
    for issue in ai_review.issues:
        logger.info(f"Processing issue: file={issue.file}, line={issue.line}, category={issue.category}")
        if issue.file and issue.line:
            try:
                post_inline_comment(
                    comments_url=review_comments_url,
                    access_token=token,
                    commit_id=commit_id,
                    file_path=issue.file,
                    line=issue.line,
                    body=(
                        f"**{issue.severity.upper()}** "
                        f"[{issue.category.value.replace('_', ' ').title()}] "
                        f"{issue.comment}"
                    )
                )
                logger.info(f"Posted inline comment for {issue.file}:{issue.line}")
            except Exception as e:
                logger.error(f"Failed to post inline comment: {e}", exc_info=True)
        else:
            logger.warning(f"Skipping issue without file/line: file={issue.file}, line={issue.line}")

    # Post general review summary as a PR comment
    try:
        summary = format_review_summary(
            review=ai_review,
            files_reviewed=len(files)
        )

        post_pr_comment(
            comments_url=pull_request["comments_url"],
            access_token=token,
            body=summary,
        )
        logger.info("Posted general review comment")
    except Exception as e:
        logger.error(f"Failed to post general comment: {e}", exc_info=True)
        