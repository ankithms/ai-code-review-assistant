import os
import secrets
from urllib.parse import urlencode, urlparse

import requests

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from app.authentication import (
    OAUTH_STATE_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    allowed_github_users,
    create_session,
    require_authenticated_user,
    revoke_session,
    session_cookie_secure,
    session_max_age_seconds,
)
from app.db.session import get_db

load_dotenv()

router = APIRouter(
    prefix="/auth",
    tags=["auth"]
)

@router.get("/github/login")
def github_login():
    client_id, _ = _github_oauth_credentials()
    if not client_id:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_CLIENT_ID is not configured",
        )

    state = secrets.token_urlsafe(32)
    query = urlencode({
        "client_id": client_id,
        "scope": "read:user",
        "state": state,
    })
    github_auth_url = f"https://github.com/login/oauth/authorize?{query}"
    response = RedirectResponse(github_auth_url)
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=600,
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
    )
    return response


@router.get("/github/callback")
def github_callback(
    code: str,
    state: str,
    request: Request,
    db: Session = Depends(get_db),
):
    client_id, client_secret = _github_oauth_credentials()
    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth credentials are not configured",
        )

    expected_state = request.cookies.get(OAUTH_STATE_COOKIE_NAME)
    if not expected_state or not secrets.compare_digest(expected_state, state):
        raise HTTPException(status_code=400, detail="Invalid OAuth state")

    token_url = "https://github.com/login/oauth/access_token"

    try:
        response = requests.post(
            token_url,
            headers={
                "Accept": "application/json"
            },
            data={
                "client_id": client_id,
                "client_secret": client_secret,
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
    github_login = str(github_user.get("login") or "").strip()
    configured_users = allowed_github_users()
    if not configured_users:
        raise HTTPException(
            status_code=503,
            detail="ALLOWED_GITHUB_USERS is not configured",
        )
    if github_login.lower() not in configured_users:
        raise HTTPException(status_code=403, detail="GitHub user is not authorized")

    session_token = create_session(db, github_login)
    response = RedirectResponse(_login_success_redirect())
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=session_max_age_seconds(),
        httponly=True,
        secure=session_cookie_secure(),
        samesite="lax",
    )
    response.delete_cookie(OAUTH_STATE_COOKIE_NAME)
    return response


@router.get("/session")
def current_session(user=Depends(require_authenticated_user)):
    return {"github_login": user.github_login}


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    db: Session = Depends(get_db),
    _user=Depends(require_authenticated_user),
):
    revoke_session(db, request.cookies.get(SESSION_COOKIE_NAME))
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


def _github_oauth_credentials() -> tuple[str | None, str | None]:
    return os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")


def _login_success_redirect() -> str:
    redirect = os.getenv("LOGIN_SUCCESS_REDIRECT", "/").strip()
    if redirect.startswith("/") and not redirect.startswith("//"):
        return redirect

    parsed = urlparse(redirect)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    allowed_origins = {
        value.strip().rstrip("/")
        for value in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if value.strip()
    }
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or origin not in allowed_origins
    ):
        raise RuntimeError(
            "LOGIN_SUCCESS_REDIRECT must be a local path or an origin in CORS_ALLOWED_ORIGINS"
        )
    return redirect
