from fastapi import APIRouter, Depends, HTTPException
from app.repositories.review_repository import (
    get_all_reviews,
    get_issue_by_id,
    get_review_by_id,
    update_issue_status,
)
from app.schemas.responses import (
    IssueResponse,
    IssueStatusUpdateRequest,
    ReviewDetailResponse,
    ReviewListResponse,
)
from sqlalchemy.orm import Session
from app.db.session import get_db

router = APIRouter(
    prefix="/reviews",
    tags=["reviews"]
)


@router.get(
    "/",
    response_model=list[ReviewListResponse]
)
def get_reviews(
    db: Session = Depends(get_db)
):
    return get_all_reviews(db)


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse
)
def get_review(
    review_id: int,
    db: Session = Depends(get_db)
):
    return get_review_by_id(
        db,
        review_id
    )


@router.patch(
    "/issues/{issue_id}/status",
    response_model=IssueResponse,
)
def update_review_issue_status(
    issue_id: int,
    request: IssueStatusUpdateRequest,
    db: Session = Depends(get_db),
):
    issue = get_issue_by_id(db, issue_id)

    if issue is None:
        raise HTTPException(
            status_code=404,
            detail="Issue not found",
        )

    try:
        return update_issue_status(
            db=db,
            issue=issue,
            status=request.status,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc
