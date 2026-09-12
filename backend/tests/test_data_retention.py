from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Issue, Review
from app.services.data_retention_service import DataRetentionService


@pytest.fixture
def retention_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()


def _review(created_at: datetime) -> Review:
    return Review(
        created_at=created_at,
        summary="Sensitive summary",
        commit_sha="abc123",
        issues=[Issue(
            severity="high", category="security", file="private/auth.py",
            comment="Sensitive finding", impact="Sensitive impact",
            line_ref="L10-L12", diff_hunk="@@ secret source @@",
            fix_file_path="private/auth.py",
            fix_replacement_code="replacement source",
            fix_additional_edits='[{"replacement_code":"more source"}]',
            fix_explanation="Sensitive explanation",
        )],
    )


def test_retention_scrubs_source_then_review_content(retention_db):
    now = datetime(2026, 9, 11, tzinfo=UTC)
    source_only = _review(now - timedelta(days=31))
    fully_purged = _review(now - timedelta(days=366))
    recent = _review(now - timedelta(days=1))
    retention_db.add_all([source_only, fully_purged, recent])
    retention_db.commit()

    result = DataRetentionService(retention_db).apply(
        source_days=30, review_days=365, now=now
    )

    assert result.source_reviews_purged == 2
    assert result.review_records_purged == 1
    assert source_only.issues[0].diff_hunk is None
    assert source_only.issues[0].fix_replacement_code is None
    assert source_only.summary == "Sensitive summary"
    assert fully_purged.summary is None
    assert fully_purged.issues[0].comment is None
    assert fully_purged.issues[0].file is None
    assert fully_purged.issues[0].severity == "high"
    assert recent.issues[0].diff_hunk == "@@ secret source @@"


def test_dry_run_does_not_modify_or_commit(retention_db):
    now = datetime(2026, 9, 11, tzinfo=UTC)
    review = _review(now - timedelta(days=400))
    retention_db.add(review)
    retention_db.commit()

    result = DataRetentionService(retention_db).apply(
        source_days=30, review_days=365, now=now, dry_run=True
    )

    assert result.source_reviews_purged == 1
    assert result.review_records_purged == 1
    assert review.summary == "Sensitive summary"
    assert review.source_purged_at is None


@pytest.mark.parametrize("source_days,review_days", [(0, 365), (30, 0), (90, 30)])
def test_invalid_retention_windows_are_rejected(retention_db, source_days, review_days):
    with pytest.raises(ValueError):
        DataRetentionService(retention_db).apply(
            source_days=source_days, review_days=review_days
        )
