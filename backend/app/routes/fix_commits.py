from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.db.models import FixCommit
from app.db.session import get_db
from app.routes.fixes import _fix_commit_response
from app.schemas.fixes import FixCommitResponse


router = APIRouter(
    prefix="/repositories/{repository_id}",
    tags=["fix-commits"],
)


@router.get("/fix-commits/{fix_commit_id}", response_model=FixCommitResponse)
def get_fix_commit(
    repository_id: int,
    fix_commit_id: int,
    db: Session = Depends(get_db),
):
    record = _fix_commit_query(db, repository_id).filter(FixCommit.id == fix_commit_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail="Fix commit not found")
    return _fix_commit_response(record)


@router.get(
    "/pull-requests/{pull_request_id}/fix-commits",
    response_model=list[FixCommitResponse],
)
def get_pull_request_fix_commits(
    repository_id: int,
    pull_request_id: int,
    db: Session = Depends(get_db),
):
    records = (
        _fix_commit_query(db, repository_id)
        .filter(FixCommit.pull_request_id == pull_request_id)
        .order_by(FixCommit.created_at.desc(), FixCommit.id.desc())
        .all()
    )
    return [_fix_commit_response(record) for record in records]


def _fix_commit_query(db: Session, repository_id: int):
    return (
        db.query(FixCommit)
        .options(
            joinedload(FixCommit.issue_links),
            joinedload(FixCommit.follow_up_review),
            joinedload(FixCommit.pull_request),
        )
        .filter(FixCommit.repository_id == repository_id)
    )
