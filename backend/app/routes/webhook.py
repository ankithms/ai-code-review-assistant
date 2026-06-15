import hashlib
import hmac
import json
import os

import requests
from fastapi import APIRouter, HTTPException, Request
from fastapi import BackgroundTasks

from app.github.github_service import (
    get_pr_files,
    post_pr_comment
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


def format_review(review):
    lines = [
        "## 🤖 AI Review",
        "",
        review.summary,
        "",
    ]

    for issue in review.issues:
        location = f" `{issue.file}`" if issue.file else ""
        lines.append(
            f"- **{issue.severity.upper()}**{location} "
            f"[{issue.category}] "
            f"{issue.comment}"
        )

    return "\n".join(lines)


def process_pull_request(payload):
    token = os.getenv("GITHUB_ACCESS_TOKEN")

    pull_request = payload["pull_request"]

    files_url = pull_request["url"] + "/files"

    files = get_pr_files(files_url, token)

    full_diff = ""

    for file in files:
        patch = file.get("patch")

        if patch:
            full_diff += f"\n\nFILE: {file['filename']}\n"
            full_diff += patch

    ai_review = review_code(full_diff)

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
        )
    finally:
        db.close()

    post_pr_comment(
        comments_url=pull_request["comments_url"],
        access_token=token,
        body=format_review(ai_review),
    )