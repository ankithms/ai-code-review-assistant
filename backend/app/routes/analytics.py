import logging
import os

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from sqlalchemy.orm import Session

from app.db.models import Repository
from app.db.session import get_db

from app.repositories.analytics_repository import (
    get_analytics,
)
from app.schemas.responses import AnalyticsResponse
from app.services.github_thread_sync_service import sync_issue_statuses_from_github

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/repositories/{repository_id}/analytics",
    tags=["analytics"]
)


@router.get(
    "",
    response_model=AnalyticsResponse
)
def analytics(
    repository_id: int,
    db: Session = Depends(get_db)
):
    return get_analytics(db, repository_id)


@router.post(
    "/sync",
    response_model=AnalyticsResponse
)
def sync_analytics(
    repository_id: int,
    db: Session = Depends(get_db)
):
    repository = (
        db.query(Repository)
        .filter(Repository.id == repository_id)
        .first()
    )

    if repository is None:
        raise HTTPException(
            status_code=404,
            detail="Repository not found",
        )

    try:
        sync_issue_statuses_from_github(
            db=db,
            repository_id=repository_id,
            repository=repository.full_name,
            access_token=os.getenv("GITHUB_ACCESS_TOKEN"),
        )
    except Exception:
        logger.exception(
            "GitHub issue status sync failed for repository %s",
            repository_id,
        )
        raise HTTPException(
            status_code=502,
            detail="GitHub issue status sync failed",
        )

    return get_analytics(db, repository_id)
