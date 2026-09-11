import logging
import os
from fastapi import Depends, FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from app.authentication import require_authenticated_user
from app.db.session import get_db
from app.queue.broker import redis_broker
from app.routes.auth import router as auth_router
from app.routes.webhook import router as webhook_router
from app.routes.reviews import router as reviews_router
from app.routes.pull_requests import router as pull_request_router
from app.routes.analytics import router as analytics_router
from app.routes.fixes import router as fixes_router
from app.routes.fix_commits import router as fix_commits_router
from app.routes.repositories import router as repositories_router
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app


def _cors_allowed_origins() -> list[str]:
    configured_origins = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:3000",
    )
    origins = [
        origin.strip().rstrip("/")
        for origin in configured_origins.split(",")
        if origin.strip()
    ]
    return origins or ["http://localhost:5173", "http://localhost:3000"]


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

app = FastAPI(
    title="AI Code Review Assistant",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/metrics", make_asgi_app())

app.include_router(auth_router)
app.include_router(webhook_router)
app.include_router(repositories_router)
app.include_router(reviews_router)
app.include_router(fixes_router)
app.include_router(fix_commits_router)
app.include_router(pull_request_router)
app.include_router(analytics_router)

@app.get("/", dependencies=[Depends(require_authenticated_user)])
def root():
    return {
        "message": "AI Code Review Assistant Running"
    }


@app.get("/healthz", include_in_schema=False)
def healthz(db: Session = Depends(get_db)):
    checks = {"database": False, "redis": False}

    try:
        db.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception:
        logging.exception("Database readiness check failed")

    try:
        checks["redis"] = bool(redis_broker.client.ping())
    except Exception:
        logging.exception("Redis readiness check failed")

    if not all(checks.values()):
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unavailable", "checks": checks},
        )

    return {"status": "ok"}
