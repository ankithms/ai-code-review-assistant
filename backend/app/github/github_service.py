import requests

TIMEOUT_SECONDS = 15
GITHUB_API_BASE_URL = "https://api.github.com"


def _headers(access_token):
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
    }


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
