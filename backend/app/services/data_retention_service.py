from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.db.models import Review


@dataclass(frozen=True)
class RetentionResult:
    source_reviews_purged: int = 0
    review_records_purged: int = 0


class DataRetentionService:
    """Irreversibly removes stored content while retaining relational audit rows."""

    def __init__(self, db: Session):
        self.db = db

    def apply(
        self,
        *,
        source_days: int,
        review_days: int,
        now: datetime | None = None,
        dry_run: bool = False,
    ) -> RetentionResult:
        if source_days < 1 or review_days < 1:
            raise ValueError("retention periods must be at least one day")
        if review_days < source_days:
            raise ValueError("review retention cannot be shorter than source retention")

        now = now or datetime.now(UTC)
        source_cutoff = now - timedelta(days=source_days)
        review_cutoff = now - timedelta(days=review_days)

        candidates = (
            self.db.query(Review)
            .options(joinedload(Review.issues))
            .filter(
                Review.created_at < source_cutoff,
                Review.data_purged_at.is_(None),
            )
            .all()
        )
        expired_review_ids = {
            review_id
            for (review_id,) in (
                self.db.query(Review.id)
                .filter(
                    Review.created_at < review_cutoff,
                    Review.data_purged_at.is_(None),
                )
                .all()
            )
        }
        source_count = sum(review.source_purged_at is None for review in candidates)
        review_count = len(expired_review_ids)

        if dry_run:
            return RetentionResult(source_count, review_count)

        for review in candidates:
            if review.source_purged_at is None:
                for issue in review.issues:
                    issue.diff_hunk = None
                    issue.fix_replacement_code = None
                    issue.fix_additional_edits = None
                review.source_purged_at = now

            if review.id in expired_review_ids:
                review.summary = None
                for issue in review.issues:
                    issue.comment = None
                    issue.impact = None
                    issue.fix_explanation = None
                    issue.file = None
                    issue.fix_file_path = None
                    issue.line_ref = None
                review.data_purged_at = now

        self.db.commit()
        return RetentionResult(source_count, review_count)
