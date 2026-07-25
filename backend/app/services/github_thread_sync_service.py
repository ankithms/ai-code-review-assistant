import json
import logging
from datetime import UTC, datetime
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.db.models import Issue, PullRequest, Review
from app.schemas.output import IssueFixStatus, IssueStatus

logger = logging.getLogger(__name__)

GITHUB_API_BASE_URL = "https://api.github.com"


def sync_issue_statuses_from_github(
    db: Session,
    repository_id: int,
    repository: str,
    access_token: str | None,
    pull_request_id: int | None = None,
) -> int:
    if not access_token:
        logger.warning("Skipping GitHub thread sync because no access token is configured")
        return 0

    pull_request_query = (
        db.query(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
    )
    if pull_request_id is not None:
        pull_request_query = pull_request_query.filter(PullRequest.id == pull_request_id)

    pull_requests = pull_request_query.all()

    thread_states: dict[str, dict[str, Any]] = {}
    if pull_requests:
        for pull_request in pull_requests:
            if pull_request.pull_request_number is None:
                logger.debug(
                    "Skipping GitHub thread sync for pull request %s because the pull request number is not available",
                    pull_request.id,
                )
                continue

            thread_states.update(
                _fetch_review_thread_states(
                    repository=repository,
                    access_token=access_token,
                    pull_request_number=pull_request.pull_request_number,
                )
            )

    if not thread_states:
        return 0

    issue_query = (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .filter(PullRequest.repository_id == repository_id)
        .filter(Issue.github_review_thread_id.isnot(None))
        .filter(Issue.fix_status != IssueFixStatus.FIX_MERGED.value)
        .filter(Issue.status != IssueStatus.IGNORED.value)
    )
    if pull_request_id is not None:
        issue_query = issue_query.filter(Review.pr_id == pull_request_id)

    issues = issue_query.all()

    synced_count = 0
    for issue in issues:
        state = thread_states.get(issue.github_review_thread_id)
        if state is None:
            continue

        resolved = bool(state.get("is_resolved"))
        desired_status = IssueStatus.RESOLVED if resolved else IssueStatus.OPEN
        if issue.status == desired_status.value and (resolved or issue.resolved_at is None):
            continue

        issue.status = desired_status.value
        if resolved:
            issue.resolved_at = datetime.now(UTC)
            issue.resolved_by = state.get("resolved_by")
        else:
            issue.resolved_at = None
            issue.resolved_by = None

        db.add(issue)
        synced_count += 1

    db.commit()
    return synced_count


def _fetch_review_thread_states(
    repository: str,
    access_token: str,
    pull_request_number: int | None,
) -> dict[str, dict[str, Any]]:
    owner, repo = _split_repository(repository)
    if not owner or not repo:
        logger.warning("Could not determine repository owner/name for GitHub thread sync: %s", repository)
        return {}

    if pull_request_number is None:
        logger.debug("Skipping GitHub thread sync because the pull request number is not available")
        return {}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    }
    payload = {
        "query": """
        query($owner: String!, $repo: String!, $prNumber: Int!) {
          repository(owner: $owner, name: $repo) {
            pullRequest(number: $prNumber) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  resolvedBy {
                    login
                  }
                }
              }
            }
          }
        }
        """,
        "variables": {
            "owner": owner,
            "repo": repo,
            "prNumber": pull_request_number,
        },
    }

    try:
        response = requests.post(
            f"{GITHUB_API_BASE_URL}/graphql",
            headers=headers,
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Failed to retrieve GitHub review thread states: %s", exc)
        return {}

    try:
        data = response.json()
    except ValueError:
        logger.warning("GitHub thread sync returned an invalid JSON payload")
        return {}

    if "errors" in data:
        logger.warning("GitHub thread sync returned GraphQL errors: %s", json.dumps(data.get("errors")))
        return {}

    payload_data = data.get("data") if isinstance(data, dict) else None
    repository_data = payload_data.get("repository") if isinstance(payload_data, dict) else None
    pull_request_data = repository_data.get("pullRequest") if isinstance(repository_data, dict) else None
    review_threads_data = pull_request_data.get("reviewThreads") if isinstance(pull_request_data, dict) else None
    nodes = review_threads_data.get("nodes") if isinstance(review_threads_data, dict) else []

    if not isinstance(nodes, list):
        return {}

    return {
        str(node.get("id")): {
            "is_resolved": bool(node.get("isResolved")) if isinstance(node, dict) else False,
            "resolved_by": _extract_resolved_by(node),
        }
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }


def _split_repository(repository: str) -> tuple[str | None, str | None]:
    if not repository:
        return None, None

    parts = repository.split("/", 1)
    if len(parts) != 2:
        return None, None

    return parts[0], parts[1]


def _extract_resolved_by(node: Any) -> str | None:
    if not isinstance(node, dict):
        return None

    resolved_by = node.get("resolvedBy")
    if not isinstance(resolved_by, dict):
        return None

    login = resolved_by.get("login")
    if not isinstance(login, str):
        return None

    return login


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
