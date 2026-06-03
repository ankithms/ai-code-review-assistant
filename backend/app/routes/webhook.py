import hashlib
import hmac
import json
import os

import requests
from fastapi import APIRouter, HTTPException, Request

from app.github.github_service import (
    get_pr_files,
    post_pr_comment
)
from app.ai.review_service import review_code
from app.db.database import SessionLocal
from app.repositories.review_repository import save_review
from app.schemas.output import PullRequestSchema

router = APIRouter()

@router.post("/github")
async def github_webhook(request: Request):
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

    try:
        files = get_pr_files(files_url, token)
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to fetch pull request files from GitHub",
        ) from exc

    if not isinstance(files, list):
        raise HTTPException(
            status_code=502,
            detail="GitHub returned an unexpected files response",
        )

    full_diff = ""

    for file in files:

        patch = file.get("patch")

        if patch:

            full_diff += f"\n\nFILE: {file['filename']}\n"
            full_diff += patch

    if not full_diff:
        return {
            "status": "ignored",
            "reason": "No reviewable diff found",
        }

    print("\nSending diff to AI...\n")

    try:
        ai_review = review_code(full_diff)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="AI review failed",
        ) from exc

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
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Failed to save review",
        ) from exc
    finally:
        db.close()

    comments_url = pull_request["comments_url"]

    formatted_review = format_review(ai_review)

    try:
        comment = post_pr_comment(
            comments_url=comments_url,
            access_token=token,
            body=formatted_review
        )
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="Failed to post pull request comment to GitHub",
        ) from exc

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
