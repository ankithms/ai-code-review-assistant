import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Repository
from app.db.session import get_db
from app.repositories.review_repository import (
    get_issue_by_id_for_repository,
    get_review_by_id_for_repository,
    get_reviews_for_repository,
    update_issue_status,
)
from app.services.github_thread_sync_service import sync_issue_statuses_from_github
from app.schemas.responses import (
    IssueResponse,
    IssueStatusUpdateRequest,
    ReviewDetailResponse,
    ReviewListResponse,
)

router = APIRouter(
    prefix="/repositories/{repository_id}/reviews",
    tags=["reviews"]
)
logger = logging.getLogger(__name__)


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

    repository = (
        db.query(Repository)
        .filter(Repository.id == repository_id)
        .first()
    )
    if repository:
        try:
            sync_issue_statuses_from_github(
                db=db,
                repository_id=repository_id,
                repository=repository.full_name,
                access_token=os.getenv("GITHUB_ACCESS_TOKEN"),
                pull_request_id=review.pr_id,
            )
        except Exception:
            logger.exception(
                "GitHub issue status sync failed for repository %s review %s",
                repository_id,
                review_id,
            )
        else:
            review = get_review_by_id_for_repository(
                db=db,
                review_id=review_id,
                repository_id=repository_id,
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
