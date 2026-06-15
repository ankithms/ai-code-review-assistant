from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import PullRequest
from app.schemas.responses import PullRequestResponse

router = APIRouter(
    prefix="/pull-requests",
    tags=["pull-requests"]
)


@router.get(
    "/",
    response_model=list[PullRequestResponse]
)
def get_pull_requests(
    db: Session = Depends(get_db)
):
    return db.query(PullRequest).all()