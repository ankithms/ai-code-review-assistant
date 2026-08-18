import base64
import json
import os
from urllib.parse import quote

import requests
from dotenv import load_dotenv


GITHUB_API_BASE_URL = "https://api.github.com"
BRANCH_NAME = "e2e/live-review-fixture"
FIXTURE_PATH = "e2e_fixtures/unsafe_discount.py"
FIXTURE_CONTENT = '''"""Intentionally unsafe code used only by the live E2E review test."""


def find_user(connection, username: str):
    query = f"SELECT * FROM users WHERE username = '{username}'"
    return connection.execute(query).fetchone()


def discounted_price(price: float, discount_percent: float) -> float:
    return price - discount_percent
'''


def _request(method, path, token, **kwargs):
    response = requests.request(
        method,
        f"{GITHUB_API_BASE_URL}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20,
        **kwargs,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"GitHub {method} {path} failed with HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )
    return response.json()


def main():
    load_dotenv()

    if os.getenv("LIVE_E2E_CONFIRM") != "provision-fixture":
        raise RuntimeError(
            "refusing fixture creation: set LIVE_E2E_CONFIRM=provision-fixture"
        )

    repository = os.getenv("LIVE_E2E_REPOSITORY")
    if not repository or repository.count("/") != 1:
        raise RuntimeError("LIVE_E2E_REPOSITORY must use owner/repository format")

    token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_ACCESS_TOKEN is required")

    repository_data = _request("GET", f"/repos/{repository}", token)
    default_branch = repository_data["default_branch"]
    encoded_branch = quote(BRANCH_NAME, safe="")

    branch_check = requests.get(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/git/ref/heads/{encoded_branch}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        timeout=20,
    )
    if branch_check.status_code == 200:
        raise RuntimeError(
            f"refusing to overwrite existing branch {repository}:{BRANCH_NAME}"
        )
    if branch_check.status_code != 404:
        raise RuntimeError(
            f"could not check fixture branch: HTTP {branch_check.status_code} "
            f"{branch_check.text[:500]}"
        )

    base_ref = _request(
        "GET",
        f"/repos/{repository}/git/ref/heads/{quote(default_branch, safe='')}",
        token,
    )
    _request(
        "POST",
        f"/repos/{repository}/git/refs",
        token,
        json={
            "ref": f"refs/heads/{BRANCH_NAME}",
            "sha": base_ref["object"]["sha"],
        },
    )
    commit = _request(
        "PUT",
        f"/repos/{repository}/contents/{FIXTURE_PATH}",
        token,
        json={
            "message": "add intentionally unsafe live E2E fixture",
            "content": base64.b64encode(FIXTURE_CONTENT.encode()).decode(),
            "branch": BRANCH_NAME,
        },
    )
    pull_request = _request(
        "POST",
        f"/repos/{repository}/pulls",
        token,
        json={
            "title": "E2E: exercise live AI review pipeline",
            "head": BRANCH_NAME,
            "base": default_branch,
            "draft": True,
            "body": (
                "Disposable live E2E fixture for the AI review pipeline.\n\n"
                "The added file intentionally contains security and calculation defects. "
                "Do not merge this pull request."
            ),
        },
    )

    print(
        json.dumps(
            {
                "repository": repository,
                "branch": BRANCH_NAME,
                "commit_sha": commit["commit"]["sha"],
                "pull_request_number": pull_request["number"],
                "pull_request_url": pull_request["html_url"],
            }
        )
    )


if __name__ == "__main__":
    main()

