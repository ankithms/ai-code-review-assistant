from fastapi import APIRouter, Depends, HTTPException
from app.repositories.review_repository import (
    get_issue_by_id_for_repository,
    get_review_by_id_for_repository,
    get_reviews_for_repository,
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
    prefix="/repositories/{repository_id}/reviews",
    tags=["reviews"]
)


@router.get(
    "/",
    response_model=list[ReviewListResponse]
)
def get_reviews(
    repository_id: int,
    db: Session = Depends(get_db)
):
    return get_reviews_for_repository(db, repository_id)


@router.get(
    "/{review_id}",
    response_model=ReviewDetailResponse
)
def get_review(
    repository_id: int,
    review_id: int,
    db: Session = Depends(get_db)
):
    review = get_review_by_id_for_repository(
        db=db,
        review_id=review_id,
        repository_id=repository_id,
    )

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Review not found",
        )

    return review


@router.patch(
    "/issues/{issue_id}/status",
    response_model=IssueResponse,
)
def update_review_issue_status(
    repository_id: int,
    issue_id: int,
    request: IssueStatusUpdateRequest,
    db: Session = Depends(get_db),
):
    issue = get_issue_by_id_for_repository(
        db=db,
        issue_id=issue_id,
        repository_id=repository_id,
    )

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
