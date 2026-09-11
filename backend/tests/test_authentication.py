import pytest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.authentication import SESSION_COOKIE_NAME, create_session
from app.db.models import Base, UserSession
from app.db.session import get_db
from app.main import app
from app.routes import auth


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_dashboard_api_requires_a_session():
    with _client() as (client, _db):
        repositories = client.get("/repositories")
        apply_fix = client.post(
            "/repositories/1/reviews/1/fixes/apply",
            json={"issue_ids": [], "confirm": True},
        )

    assert repositories.status_code == 401
    assert apply_fix.status_code == 401



@pytest.mark.parametrize("method,path", [
    ("GET", "/repositories/1/reviews"),
    ("GET", "/repositories/1/analytics"),
    ("POST", "/repositories/1/analytics/sync"),
    ("POST", "/repositories/1/reviews/1/fixes/generate"),
    ("POST", "/repositories/1/reviews/1/fixes/preview"),
    ("POST", "/repositories/1/reviews/1/fixes/apply"),
    ("PATCH", "/repositories/1/reviews/issues/1/status"),
])
def test_demo_visitors_cannot_access_live_api(method, path):
    with _client() as (client, _db):
        response = client.request(
            method, path,
            headers={"Referer": "http://localhost:3000/demo/"},
            json={"issue_ids": [], "confirm": True, "status": "RESOLVED"},
        )
    assert response.status_code == 401

def test_database_backed_session_authorizes_api_access_and_logout():
    with _client() as (client, db):
        token = create_session(db, "ankithms")
        client.cookies.set(SESSION_COOKIE_NAME, token)

        repositories = client.get("/repositories")
        session = client.get("/auth/session")
        logout = client.post("/auth/logout")
        after_logout = client.get("/repositories")

        stored_session = db.query(UserSession).one_or_none()

    assert repositories.status_code == 200
    assert session.json() == {"github_login": "ankithms"}
    assert logout.status_code == 204
    assert after_logout.status_code == 401
    assert stored_session is None


def test_oauth_callback_requires_state_and_never_returns_github_token():
    environment = {
        "GITHUB_CLIENT_ID": "client-id",
        "GITHUB_CLIENT_SECRET": "client-secret",
        "ALLOWED_GITHUB_USERS": "ankithms",
        "SESSION_COOKIE_SECURE": "false",
        "LOGIN_SUCCESS_REDIRECT": "/",
    }
    with _client() as (client, db), patch.dict("os.environ", environment, clear=False):
        login = client.get("/auth/github/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

        with (
            patch.object(auth.requests, "post", return_value=FakeResponse({"access_token": "github-token"})),
            patch.object(auth.requests, "get", return_value=FakeResponse({"login": "ankithms"})),
        ):
            callback = client.get(
                f"/auth/github/callback?code=oauth-code&state={state}",
                follow_redirects=False,
            )

        session = client.get("/auth/session")
        stored_session = db.query(UserSession).one()

    assert login.status_code == 307
    assert callback.status_code == 307
    assert callback.headers["location"] == "/"
    assert "github-token" not in callback.text
    assert session.json() == {"github_login": "ankithms"}
    assert stored_session.token_hash != "github-token"


def test_oauth_callback_can_redirect_to_the_configured_dashboard_origin():
    environment = {
        "GITHUB_CLIENT_ID": "client-id",
        "GITHUB_CLIENT_SECRET": "client-secret",
        "ALLOWED_GITHUB_USERS": "ankithms",
        "SESSION_COOKIE_SECURE": "false",
        "CORS_ALLOWED_ORIGINS": "http://localhost:5173",
        "LOGIN_SUCCESS_REDIRECT": "http://localhost:5173/",
    }
    with _client() as (client, _db), patch.dict("os.environ", environment, clear=False):
        login = client.get("/auth/github/login", follow_redirects=False)
        state = parse_qs(urlparse(login.headers["location"]).query)["state"][0]

        with (
            patch.object(auth.requests, "post", return_value=FakeResponse({"access_token": "github-token"})),
            patch.object(auth.requests, "get", return_value=FakeResponse({"login": "ankithms"})),
        ):
            callback = client.get(
                f"/auth/github/callback?code=oauth-code&state={state}",
                follow_redirects=False,
            )

    assert callback.status_code == 307
    assert callback.headers["location"] == "http://localhost:5173/"


def test_oauth_callback_rejects_mismatched_state():
    environment = {
        "GITHUB_CLIENT_ID": "client-id",
        "GITHUB_CLIENT_SECRET": "client-secret",
        "ALLOWED_GITHUB_USERS": "ankithms",
        "SESSION_COOKIE_SECURE": "false",
    }
    with _client() as (client, _db), patch.dict("os.environ", environment, clear=False):
        client.get("/auth/github/login", follow_redirects=False)
        response = client.get(
            "/auth/github/callback?code=oauth-code&state=incorrect-state",
            follow_redirects=False,
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid OAuth state"


def test_healthcheck_is_public_but_root_requires_a_session():
    with _client() as (client, _db), patch("app.main.redis_broker.client.ping", return_value=True):
        healthcheck = client.get("/healthz")
        root = client.get("/")

    assert healthcheck.json() == {"status": "ok"}
    assert root.status_code == 401


class _client:
    def __enter__(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)

        def override_get_db():
            yield self.db

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)
        return self.client, self.db

    def __exit__(self, exc_type, exc, traceback):
        app.dependency_overrides.clear()
        self.client.close()
        self.db.close()
        self.engine.dispose()
