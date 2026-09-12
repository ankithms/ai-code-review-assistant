import hashlib
import hmac
import json
import os
import time
import unittest

import requests
from dotenv import load_dotenv

from app.authentication import SESSION_COOKIE_NAME


load_dotenv()

BASE_URL = os.getenv("LIVE_E2E_BASE_URL")
CONFIRMATION = os.getenv("LIVE_E2E_CONFIRM")
REPOSITORY = os.getenv("LIVE_E2E_REPOSITORY")
PR_NUMBER = os.getenv("LIVE_E2E_PR_NUMBER")
WEBHOOK_SECRET = os.getenv("GITHUB_WEBHOOK_SECRET", "")
GITHUB_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN", "")
SESSION_TOKEN = os.getenv("LIVE_E2E_SESSION_TOKEN", "")
GITHUB_API_BASE_URL = "https://api.github.com"


@unittest.skipUnless(
    BASE_URL and CONFIRMATION == "post-comments",
    "requires an explicitly confirmed live E2E environment",
)
class LiveReviewFlowEndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not REPOSITORY:
            raise RuntimeError("LIVE_E2E_REPOSITORY is required")
        if not PR_NUMBER or not PR_NUMBER.isdigit() or int(PR_NUMBER) < 1:
            raise RuntimeError("LIVE_E2E_PR_NUMBER must be a positive integer")
        if not GITHUB_TOKEN:
            raise RuntimeError("GITHUB_ACCESS_TOKEN is required")
        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("GOOGLE_API_KEY is required")
        if not WEBHOOK_SECRET:
            raise RuntimeError("GITHUB_WEBHOOK_SECRET is required")
        if not SESSION_TOKEN:
            raise RuntimeError("LIVE_E2E_SESSION_TOKEN is required")

        cls.pr_number = int(PR_NUMBER)
        cls.api = requests.Session()
        cls.api.cookies.set(SESSION_COOKIE_NAME, SESSION_TOKEN)
        cls.github_headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
        }
        cls._wait_for_api()

        response = requests.get(
            f"{GITHUB_API_BASE_URL}/repos/{REPOSITORY}/pulls/{cls.pr_number}",
            headers=cls.github_headers,
            timeout=15,
        )
        response.raise_for_status()
        cls.pull_request = response.json()

        if cls.pull_request.get("state") != "open":
            raise RuntimeError("the live E2E pull request must be open")

        title = (cls.pull_request.get("title") or "").lower()
        head_ref = ((cls.pull_request.get("head") or {}).get("ref") or "").lower()
        if "e2e" not in title and not head_ref.startswith("e2e/"):
            raise RuntimeError(
                "safety check failed: use an E2E title or an e2e/* source branch"
            )

    def test_real_github_and_model_review_flow(self):
        existing_issue_comment_ids = self._github_comment_ids("issues", "comments")
        existing_review_comment_ids = self._github_comment_ids("pulls", "comments")

        head_sha = self.pull_request["head"]["sha"]
        payload = {
            "action": "opened",
            "repository": {
                "full_name": REPOSITORY,
            },
            "pull_request": {
                "number": self.pr_number,
                "head": {
                    "sha": head_sha,
                },
            },
        }
        body = json.dumps(payload, separators=(",", ":")).encode()
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
            timeout=10,
        )
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["status"], "queued")

        repository, review = self._wait_for_review()
        detail_response = self.api.get(
            f"{BASE_URL}/repositories/{repository['id']}/reviews/{review['id']}",
            timeout=20,
        )
        self.assertEqual(detail_response.status_code, 200, detail_response.text)
        detail = detail_response.json()
        self.assertTrue(detail["summary"])
        self.assertGreater(
            len(detail["issues"]),
            0,
            "the sandbox PR must contain an intentional issue for comment verification",
        )

        new_issue_comments = self._new_github_comments(
            "issues",
            "comments",
            existing_issue_comment_ids,
        )
        new_review_comments = self._new_github_comments(
            "pulls",
            "comments",
            existing_review_comment_ids,
        )
        self.assertTrue(
            any(
                "AI Review Summary" in (comment.get("body") or "")
                for comment in new_issue_comments
            ),
            "the live run did not create its GitHub review summary comment",
        )
        self.assertTrue(
            new_review_comments or len(new_issue_comments) > 1,
            "the live run did not create an inline or fallback finding comment",
        )

        duplicate = self._wait_for_completed_duplicate(body, signature)
        self.assertEqual(duplicate["status"], "ignored")
        self.assertEqual(duplicate["reason"], "commit_already_reviewed")
        self.assertEqual(duplicate["review_id"], review["id"])

    @classmethod
    def _wait_for_api(cls):
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
        raise RuntimeError(f"live E2E API did not become ready: {last_error}")

    def _wait_for_review(self):
        deadline = time.monotonic() + 240
        last_state = None
        while time.monotonic() < deadline:
            repositories_response = self.api.get(
                f"{BASE_URL}/repositories",
                timeout=10,
            )
            repositories_response.raise_for_status()
            repository = next(
                (
                    item
                    for item in repositories_response.json()
                    if item["full_name"] == REPOSITORY
                ),
                None,
            )
            if repository:
                reviews_response = self.api.get(
                    f"{BASE_URL}/repositories/{repository['id']}/reviews",
                    timeout=10,
                )
                reviews_response.raise_for_status()
                reviews = reviews_response.json()
                if reviews:
                    return repository, reviews[0]
                last_state = "repository exists but its review is not saved yet"
            else:
                last_state = "repository has not been created yet"
            time.sleep(1)
        self.fail(f"live review did not complete within 240 seconds: {last_state}")

    def _github_comment_ids(self, resource, comment_resource):
        return {
            comment["id"]
            for comment in self._github_comments(resource, comment_resource)
        }

    def _new_github_comments(self, resource, comment_resource, existing_ids):
        return [
            comment
            for comment in self._github_comments(resource, comment_resource)
            if comment["id"] not in existing_ids
        ]

    def _github_comments(self, resource, comment_resource):
        response = requests.get(
            f"{GITHUB_API_BASE_URL}/repos/{REPOSITORY}/{resource}/{self.pr_number}/{comment_resource}",
            headers=self.github_headers,
            params={"per_page": 100},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

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
                timeout=10,
            )
            response.raise_for_status()
            last_payload = response.json()
            if last_payload.get("reason") == "commit_already_reviewed":
                return last_payload
            time.sleep(0.1)
        self.fail(f"live review job was not marked successful: {last_payload}")


if __name__ == "__main__":
    unittest.main()
