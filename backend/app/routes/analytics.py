import os

from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.orm import Session

from app.db.models import Repository
from app.db.session import get_db

from app.repositories.analytics_repository import (
    get_analytics,
)
from app.schemas.responses import AnalyticsResponse
from app.services.github_thread_sync_service import sync_issue_statuses_from_github

router = APIRouter(
    prefix="/repositories/{repository_id}/analytics",
    tags=["analytics"]
)


@router.get(
    "/",
    response_model=AnalyticsResponse
)
def analytics(
    repository_id: int,
    db: Session = Depends(get_db)
):
    repository = (
        db.query(Repository)
        .filter(Repository.id == repository_id)
        .first()
    )
    if repository:
        sync_issue_statuses_from_github(
            db=db,
            repository_id=repository_id,
            repository=repository.full_name,
            access_token=os.getenv("GITHUB_ACCESS_TOKEN"),
        )

    return get_analytics(db, repository_id)
