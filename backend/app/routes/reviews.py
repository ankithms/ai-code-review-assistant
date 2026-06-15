from fastapi import APIRouter, Depends
from app.db.database import SessionLocal
from app.db.models import Review
from app.repositories.review_repository import get_all_reviews, get_review_by_id
from app.schemas.responses import ReviewDetailResponse, ReviewListResponse
from sqlalchemy.orm import Session, joinedload
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