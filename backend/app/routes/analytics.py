from fastapi import (
    APIRouter,
    Depends,
)

from sqlalchemy.orm import Session

from app.db.session import get_db

from app.repositories.analytics_repository import (
    get_analytics,
)
from app.schemas.responses import AnalyticsResponse

router = APIRouter(
    prefix="/analytics",
    tags=["analytics"]
)


@router.get(
    "/",
    response_model=AnalyticsResponse
)
def analytics(
    db: Session = Depends(get_db)
):
    return get_analytics(db)