import requests

TIMEOUT_SECONDS = 15
GITHUB_API_BASE_URL = "https://api.github.com"


def _headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
    }


def _split_repository(repository):
    parts = repository.split("/", 1)
    if len(parts) != 2:
        return None, None

    return parts[0], parts[1]


def get_pull_request(
    repository,
    pull_request_number,
    access_token,
):
    response = requests.get(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pull_request_number}",
        headers=_headers(access_token),
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


def get_pr_files(
    repository,
    pull_request_number,
    access_token,
):

    response = requests.get(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pull_request_number}/files",
        headers=_headers(access_token),
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


def get_compare_files(
    repository,
    base_commit_sha,
    head_commit_sha,
    access_token,
):
    response = requests.get(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/compare/{base_commit_sha}...{head_commit_sha}",
        headers=_headers(access_token),
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json().get("files", [])


def post_pr_comment(
    repository,
    pull_request_number,
    access_token,
    body,
):

    response = requests.post(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/issues/{pull_request_number}/comments",
        headers=_headers(access_token),
        json={
            "body": body
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


def post_inline_comment(
    repository,
    pull_request_number,
    access_token,
    commit_id,
    file_path,
    line=None,
    position=None,
    side=None,
    start_line=None,
    start_side=None,
    body=None,
):
    payload = {
        "body": body,
        "commit_id": commit_id,
        "path": file_path,
    }

    if position is not None:
        payload["position"] = position
    elif line is not None:
        payload["line"] = line
        if side is not None:
            payload["side"] = side
        if start_line is not None:
            payload["start_line"] = start_line
        if start_side is not None:
            payload["start_side"] = start_side

    response = requests.post(
        f"{GITHUB_API_BASE_URL}/repos/{repository}/pulls/{pull_request_number}/comments",
        headers=_headers(access_token),
        json=payload,
        timeout=TIMEOUT_SECONDS,
    )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"GitHub inline comment failed: {response.status_code} {response.text}"
        ) from exc

    return response.json()


def get_review_thread_for_comment(
    repository,
    pull_request_number,
    access_token,
    comment_id,
):
    owner, repo = _split_repository(repository)
    if not owner or not repo or not comment_id:
        return None

    after = None
    while True:
        payload = {
            "query": """
            query($owner: String!, $repo: String!, $prNumber: Int!, $after: String) {
              repository(owner: $owner, name: $repo) {
                pullRequest(number: $prNumber) {
                  reviewThreads(first: 100, after: $after) {
                    pageInfo {
                      hasNextPage
                      endCursor
                    }
                    nodes {
                      id
                      comments(first: 100) {
                        nodes {
                          databaseId
                          id
                        }
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
                "after": after,
            },
        }

        response = requests.post(
            f"{GITHUB_API_BASE_URL}/graphql",
            headers={
                **_headers(access_token),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        data = response.json()

        if data.get("errors"):
            raise RuntimeError(f"GitHub review thread lookup failed: {data['errors']}")

        payload_data = data.get("data") if isinstance(data, dict) else None
        repository_data = payload_data.get("repository") if isinstance(payload_data, dict) else None
        pull_request_data = repository_data.get("pullRequest") if isinstance(repository_data, dict) else None
        review_threads = pull_request_data.get("reviewThreads") if isinstance(pull_request_data, dict) else None
        if not isinstance(review_threads, dict):
            return None

        nodes = review_threads.get("nodes") or []
        for thread in nodes:
            if not isinstance(thread, dict):
                continue
            comments = thread.get("comments", {}).get("nodes") or []
            for comment in comments:
                if not isinstance(comment, dict):
                    continue
                if comment.get("databaseId") == comment_id:
                    return {
                        "id": thread.get("id"),
                        "comment_node_id": comment.get("id"),
                    }

        page_info = review_threads.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            return None

        after = page_info.get("endCursor")
