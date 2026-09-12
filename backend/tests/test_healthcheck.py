from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app


def test_liveness_returns_ok_without_dependency_checks():
    with patch("app.main.redis_broker.client.ping") as redis_ping:
        response = TestClient(app).get("/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    redis_ping.assert_not_called()


def test_readiness_returns_ok_when_database_and_redis_are_ready():
    db = Mock()
    app.dependency_overrides[get_db] = lambda: db

    try:
        with patch("app.main.redis_broker.client.ping", return_value=True):
            response = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    db.execute.assert_called_once()


def test_readiness_returns_503_when_database_is_unavailable():
    db = Mock()
    db.execute.side_effect = RuntimeError("database unavailable")
    app.dependency_overrides[get_db] = lambda: db

    try:
        with patch("app.main.redis_broker.client.ping", return_value=True):
            response = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": False, "redis": True},
    }


def test_readiness_returns_503_when_redis_is_unavailable():
    db = Mock()
    app.dependency_overrides[get_db] = lambda: db

    try:
        with patch(
            "app.main.redis_broker.client.ping",
            side_effect=RuntimeError("redis unavailable"),
        ):
            response = TestClient(app).get("/readyz")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "checks": {"database": True, "redis": False},
    }
