from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.pull_request_repositories import get_pull_requests_for_repository
from app.schemas.responses import PullRequestResponse

router = APIRouter(
    prefix="/repositories/{repository_id}/pull-requests",
    tags=["pull-requests"]
)


@router.get(
    "/",
    response_model=list[PullRequestResponse]
)
def get_pull_requests(
    repository_id: int,
    db: Session = Depends(get_db)
):
    return get_pull_requests_for_repository(db, repository_id)
