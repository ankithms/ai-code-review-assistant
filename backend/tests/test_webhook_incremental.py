import asyncio
import hashlib
import hmac
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, FixPullRequest, Issue, PullRequest, Repository, Review
from app.routes import webhook
from app.schemas.output import FixPullRequestStatus, IssueFixStatus, IssueStatus


WEBHOOK_SECRET = "unit-test-webhook-secret"


class GithubWebhookIncrementalTests(unittest.TestCase):
    def test_signature_verification_fails_closed_without_configured_secret(self):
        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": ""}):
            with self.assertRaises(HTTPException) as context:
                webhook.verify_github_signature(_FakeRequest(b"{}"), b"{}")

        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(
            context.exception.detail,
            "GitHub webhook verification is unavailable",
        )

    def test_signature_verification_rejects_missing_signature(self):
        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET}):
            with self.assertRaises(HTTPException) as context:
                webhook.verify_github_signature(_FakeRequest(b"{}"), b"{}")

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "Missing GitHub webhook signature")

    def test_signature_verification_rejects_invalid_signature(self):
        request = _FakeRequest(
            b"{}",
            headers={"X-Hub-Signature-256": "sha256=invalid"},
        )

        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET}):
            with self.assertRaises(HTTPException) as context:
                webhook.verify_github_signature(request, b"{}")

        self.assertEqual(context.exception.status_code, 401)
        self.assertEqual(context.exception.detail, "Invalid GitHub webhook signature")

    def test_signature_verification_accepts_valid_signature(self):
        body = b'{"action":"opened"}'
        request = _FakeRequest(body, headers=_signed_headers(body))

        with patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET}):
            webhook.verify_github_signature(request, body)

    def test_pull_request_review_comment_ai_fix_command_dispatches_to_native_handler(self):
        payload = {
            "action": "created",
            "repository": {
                "full_name": "owner/repo",
            },
            "pull_request": {
                "number": 12,
            },
            "comment": {
                "id": 101,
                "in_reply_to_id": 99,
                "body": "/ai-fix",
            },
        }
        body = json.dumps(payload).encode()
        request = _FakeRequest(
            body,
            headers=_signed_headers(
                body,
                event="pull_request_review_comment",
            ),
        )

        with (
            patch.dict(
                os.environ,
                {
                    "GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET,
                    "GITHUB_ACCESS_TOKEN": "token",
                },
            ),
            patch.object(webhook, "handle_github_native_fix_comment", return_value=True) as handle_native_fix,
        ):
            response = asyncio.run(webhook.github_webhook(request, SimpleNamespace()))

        self.assertEqual(
            response,
            {
                "status": "tracked",
                "action": "created",
                "event": "pull_request_review_comment",
            },
        )
        handle_native_fix.assert_called_once_with(
            db=ANY,
            payload=payload,
            event="pull_request_review_comment",
            access_token="token",
        )

    def test_synchronize_webhook_stores_incremental_commit_range(self):
        payload = {
            "action": "synchronize",
            "before": "old-head-sha",
            "after": "new-head-sha",
            "repository": {
                "full_name": "owner/repo",
            },
            "pull_request": {
                "number": 12,
                "head": {
                    "sha": "new-head-sha",
                },
            },
        }
        body = json.dumps(payload).encode()
        request = _FakeRequest(body, headers=_signed_headers(body))

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        job = SimpleNamespace(id=42)

        with (
            patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": WEBHOOK_SECRET}),
            patch.object(webhook, "_handle_fix_pull_request_webhook", return_value=False),
            patch.object(webhook, "get_active_review_job_by_commit", return_value=None),
            patch.object(webhook, "create_review_job", return_value=job) as create_review_job,
            patch.object(webhook.process_review_job, "send") as send_review_job,
        ):
            response = asyncio.run(webhook.github_webhook(request, db))

        self.assertEqual(response, {"status": "queued", "job_id": 42})
        create_review_job.assert_called_once_with(
            db=db,
            repository="owner/repo",
            pull_request_number=12,
            commit_sha="new-head-sha",
            event_action="synchronize",
            base_commit_sha="old-head-sha",
            head_commit_sha="new-head-sha",
        )
        send_review_job.assert_called_once_with(42)

    def test_merged_fix_pr_resolves_associated_open_issues(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = Session(engine)

        try:
            repository = Repository(full_name="owner/repo")
            session.add(repository)
            session.flush()

            pull_request = PullRequest(
                repository_id=repository.id,
                github_pr_id=99,
                pull_request_number=12,
                title="Original PR",
                repository=repository.full_name,
                author="octocat",
            )
            session.add(pull_request)
            session.flush()

            review = Review(pr_id=pull_request.id, summary="Summary", commit_sha="head")
            session.add(review)
            session.flush()

            issue = Issue(
                review_id=review.id,
                severity="high",
                category="bug",
                file="app.py",
                comment="Bug",
                status=IssueStatus.OPEN.value,
                fix_status=IssueFixStatus.FIX_PR_CREATED.value,
            )
            session.add(issue)
            session.flush()

            fix_pull_request = FixPullRequest(
                repository_id=repository.id,
                review_id=review.id,
                original_pull_request_id=pull_request.id,
                original_pr_number=pull_request.pull_request_number,
                source_commit_sha="head",
                fix_branch="ai-fix/12-20260721",
                github_pr_number=45,
                github_pr_url="https://github.com/owner/repo/pull/45",
                github_commit_sha="fixsha",
                github_commit_url="https://github.com/owner/repo/commit/fixsha",
                status=FixPullRequestStatus.PR_CREATED.value,
                issues=[issue],
            )
            session.add(fix_pull_request)
            session.commit()

            handled = webhook._handle_fix_pull_request_webhook(
                db=session,
                repository_full_name="owner/repo",
                action="closed",
                pull_request={
                    "number": 45,
                    "merged": True,
                    "head": {
                        "ref": "ai-fix/12-20260721",
                        "sha": "fixsha",
                    },
                },
            )

            session.refresh(issue)
            session.refresh(fix_pull_request)
            self.assertTrue(handled)
            self.assertEqual(fix_pull_request.status, FixPullRequestStatus.MERGED.value)
            self.assertIsNotNone(fix_pull_request.merged_at)
            self.assertEqual(issue.status, IssueStatus.RESOLVED.value)
            self.assertEqual(issue.fix_status, IssueFixStatus.FIX_MERGED.value)
        finally:
            session.close()


class _FakeRequest:
    def __init__(self, body: bytes, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def body(self):
        return self._body


def _signed_headers(body: bytes, event: str | None = None) -> dict[str, str]:
    signature = "sha256=" + hmac.new(
        WEBHOOK_SECRET.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    headers = {"X-Hub-Signature-256": signature}
    if event:
        headers["X-GitHub-Event"] = event
    return headers


if __name__ == "__main__":
    unittest.main()
