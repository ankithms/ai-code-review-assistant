import hashlib
import hmac
import json
import os
import time
import unittest

import requests

from app.authentication import SESSION_COOKIE_NAME


BASE_URL = os.getenv("E2E_BASE_URL")
WEBHOOK_SECRET = os.getenv("E2E_WEBHOOK_SECRET", "")
SESSION_TOKEN = os.getenv("E2E_SESSION_TOKEN", "")


@unittest.skipUnless(BASE_URL, "requires the isolated Docker E2E stack")
class ReviewFlowEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SESSION_TOKEN:
            raise RuntimeError("E2E_SESSION_TOKEN is required")
        cls.api = requests.Session()
        cls.api.cookies.set(SESSION_COOKIE_NAME, SESSION_TOKEN)
        deadline = time.monotonic() + 30
        last_error = None

        while time.monotonic() < deadline:
            try:
                response = requests.get(f"{BASE_URL}/readyz", timeout=2)
                if response.status_code == 200:
                    return
                last_error = f"API returned HTTP {response.status_code}"
            except requests.RequestException as exc:
                last_error = str(exc)
            time.sleep(0.25)

        raise RuntimeError(f"E2E API did not become ready: {last_error}")

    def test_webhook_is_processed_and_exposed_through_the_api(self):
        payload = {
            "action": "opened",
            "repository": {
                "full_name": "e2e/code-review-fixture",
            },
            "pull_request": {
                "number": 7,
                "head": {
                    "sha": "e2e-head-sha",
                },
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode()

        rejected = requests.post(
            f"{BASE_URL}/webhooks/github",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": "sha256=invalid",
            },
            timeout=5,
        )
        self.assertEqual(rejected.status_code, 401)

        signature = "sha256=" + hmac.new(
            WEBHOOK_SECRET.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        accepted = requests.post(
            f"{BASE_URL}/webhooks/github",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
            },
            timeout=5,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "queued")
        job_id = accepted.json()["job_id"]

        repository, review = self._wait_for_review()
        repository_id = repository["id"]

        detail = self.api.get(
            f"{BASE_URL}/repositories/{repository_id}/reviews/{review['id']}",
            timeout=5,
        )
        self.assertEqual(detail.status_code, 200, detail.text)
        detail_payload = detail.json()
        self.assertEqual(detail_payload["summary"], "E2E review completed successfully.")
        self.assertEqual(len(detail_payload["issues"]), 1)
        self.assertEqual(detail_payload["issues"][0]["file"], "src/pricing.py")
        self.assertEqual(detail_payload["issues"][0]["line"], 2)
        self.assertEqual(detail_payload["issues"][0]["status"], "OPEN")

        analytics = self.api.get(
            f"{BASE_URL}/repositories/{repository_id}/analytics",
            timeout=5,
        )
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["total_ai_reviews"], 1)
        self.assertEqual(analytics.json()["total_issues"], 1)
        self.assertEqual(analytics.json()["medium_severity"], 1)

        duplicate = self._wait_for_completed_duplicate(body, signature)
        self.assertEqual(duplicate["status"], "ignored")
        self.assertEqual(duplicate["reason"], "commit_already_reviewed")
        self.assertEqual(duplicate["review_id"], review["id"])
        self.assertGreater(job_id, 0)

    def _wait_for_review(self):
        deadline = time.monotonic() + 30
        last_state = None

        while time.monotonic() < deadline:
            repositories_response = self.api.get(
                f"{BASE_URL}/repositories",
                timeout=5,
            )
            repositories_response.raise_for_status()
            repositories = repositories_response.json()
            repository = next(
                (
                    item
                    for item in repositories
                    if item["full_name"] == "e2e/code-review-fixture"
                ),
                None,
            )
            if repository:
                reviews_response = self.api.get(
                    f"{BASE_URL}/repositories/{repository['id']}/reviews",
                    timeout=5,
                )
                reviews_response.raise_for_status()
                reviews = reviews_response.json()
                if reviews:
                    return repository, reviews[0]
                last_state = "repository exists but its review is not saved yet"
            else:
                last_state = "repository has not been created yet"

            time.sleep(0.25)

        self.fail(f"review pipeline did not complete within 30 seconds: {last_state}")

    def _wait_for_completed_duplicate(self, body, signature):
        deadline = time.monotonic() + 10
        last_payload = None

        while time.monotonic() < deadline:
            response = requests.post(
                f"{BASE_URL}/webhooks/github",
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "X-GitHub-Event": "pull_request",
                    "X-Hub-Signature-256": signature,
                },
                timeout=5,
            )
            response.raise_for_status()
            last_payload = response.json()
            if last_payload.get("reason") == "commit_already_reviewed":
                return last_payload
            time.sleep(0.1)

        self.fail(f"review job was not marked successful: {last_payload}")


if __name__ == "__main__":
    unittest.main()
