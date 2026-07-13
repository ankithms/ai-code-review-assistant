import requests

TIMEOUT_SECONDS = 15


def get_pr_files(files_url, access_token):

    response = requests.get(
        files_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json"
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()


def post_pr_comment(comments_url, access_token, body):

    response = requests.post(
        comments_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json"
        },
        json={
            "body": body
        },
        timeout=TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return response.json()

def post_inline_comment(
    comments_url,
    access_token,
    commit_id,
    file_path,
    line,
    body,
):
    response = requests.post(
        comments_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
        },
        json={
            "body": body,
            "commit_id": commit_id,
            "path": file_path,
            "line": line,
        },
        timeout=TIMEOUT_SECONDS,
    )

    response.raise_for_status()

    return response.json()