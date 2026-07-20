import asyncio
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.routes import webhook


class GithubWebhookIncrementalTests(unittest.TestCase):
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
        request = _FakeRequest(json.dumps(payload).encode())

        class Query:
            def filter(self, *args):
                return self

            def first(self):
                return None

        db = SimpleNamespace(query=lambda model: Query())
        job = SimpleNamespace(id=42)

        with (
            patch.dict(os.environ, {"GITHUB_WEBHOOK_SECRET": ""}),
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


class _FakeRequest:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {}

    async def body(self):
        return self._body


if __name__ == "__main__":
    unittest.main()
