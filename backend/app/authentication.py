import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import UserSession
from app.db.session import get_db


SESSION_COOKIE_NAME = "ai_code_review_session"
OAUTH_STATE_COOKIE_NAME = "ai_code_review_oauth_state"


@dataclass(frozen=True)
class AuthenticatedUser:
    github_login: str


def create_session(db: Session, github_login: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    db.query(UserSession).filter(UserSession.expires_at <= now).delete(
        synchronize_session=False
    )
    db.add(
        UserSession(
            token_hash=_token_hash(token),
            github_login=github_login,
            expires_at=now + timedelta(seconds=session_max_age_seconds()),
            last_seen_at=now,
        )
    )
    db.commit()
    return token


def revoke_session(db: Session, token: str | None) -> None:
    if not token:
        return

    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == _token_hash(token))
        .first()
    )
    if session is not None:
        db.delete(session)
        db.commit()


def require_authenticated_user(
    request: Request,
    db: Session = Depends(get_db),
) -> AuthenticatedUser:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication is required")

    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == _token_hash(token))
        .first()
    )
    if session is None or _is_expired(session.expires_at):
        if session is not None:
            db.delete(session)
            db.commit()
        raise HTTPException(status_code=401, detail="Session is invalid or expired")

    session.last_seen_at = datetime.now(UTC)
    db.commit()
    return AuthenticatedUser(github_login=session.github_login)


def allowed_github_users() -> set[str]:
    return {
        user.strip().lower()
        for user in os.getenv("ALLOWED_GITHUB_USERS", "").split(",")
        if user.strip()
    }


def session_cookie_secure() -> bool:
    return _boolean_environment("SESSION_COOKIE_SECURE", default=True)


def session_max_age_seconds() -> int:
    raw_value = os.getenv("SESSION_MAX_AGE_SECONDS", "28800")
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError("SESSION_MAX_AGE_SECONDS must be an integer") from exc
    if value <= 0:
        raise RuntimeError("SESSION_MAX_AGE_SECONDS must be greater than zero")
    return value


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _is_expired(expires_at: datetime) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def _boolean_environment(name: str, *, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
