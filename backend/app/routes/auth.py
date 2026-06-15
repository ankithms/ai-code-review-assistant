import os
from urllib.parse import urlencode

import requests

from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")


@router.get("/github/login")
def github_login():
    if not GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_CLIENT_ID is not configured",
        )

    query = urlencode({
        "client_id": GITHUB_CLIENT_ID,
        "scope": "repo",
    })
    github_auth_url = f"https://github.com/login/oauth/authorize?{query}"

    return RedirectResponse(github_auth_url)


@router.get("/github/callback")
def github_callback(code: str):
    if not GITHUB_CLIENT_ID or not GITHUB_CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth credentials are not configured",
        )

    token_url = "https://github.com/login/oauth/access_token"

    try:
        response = requests.post(
            token_url,
            headers={
                "Accept": "application/json"
            },
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="GitHub token exchange failed",
        ) from exc

    token_payload = response.json()
    access_token = token_payload.get("access_token")

    if not access_token:
        raise HTTPException(
            status_code=400,
            detail=token_payload.get("error_description", "GitHub did not return an access token"),
        )

    try:
        user_response = requests.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}"
            },
            timeout=15,
        )
        user_response.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail="GitHub user lookup failed",
        ) from exc

    github_user = user_response.json()

    return {
        "access_token": access_token,
        "github_user": github_user
    }
