import argparse
import os

from app.db.database import SessionLocal
from app.services.data_retention_service import DataRetentionService


def _positive_days(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if value < 1:
        raise SystemExit(f"{name} must be at least 1")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply review-data retention policy")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_days = _positive_days("SOURCE_SNIPPET_RETENTION_DAYS", 30)
    review_days = _positive_days("REVIEW_DATA_RETENTION_DAYS", 365)
    if review_days < source_days:
        raise SystemExit("REVIEW_DATA_RETENTION_DAYS cannot be shorter than SOURCE_SNIPPET_RETENTION_DAYS")

    with SessionLocal() as db:
        result = DataRetentionService(db).apply(
            source_days=source_days,
            review_days=review_days,
            dry_run=args.dry_run,
        )
    mode = "would purge" if args.dry_run else "purged"
    print(
        f"{mode} source from {result.source_reviews_purged} reviews; "
        f"{mode} review content from {result.review_records_purged} reviews"
    )


if __name__ == "__main__":
    main()
