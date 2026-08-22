from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.authentication import require_authenticated_user
from app.db.session import get_db
from app.repositories.repository_repository import get_repositories
from app.schemas.responses import RepositoryResponse


router = APIRouter(
    prefix="/repositories",
    tags=["repositories"],
    dependencies=[Depends(require_authenticated_user)],
)


@router.get(
    "",
    response_model=list[RepositoryResponse],
)
def repositories(
    db: Session = Depends(get_db),
):
    return get_repositories(db)
