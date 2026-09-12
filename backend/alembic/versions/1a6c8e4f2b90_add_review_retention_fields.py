"""add review retention fields

Revision ID: 1a6c8e4f2b90
Revises: c9a1d2e3f4b5
Create Date: 2026-09-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1a6c8e4f2b90"
down_revision: Union[str, Sequence[str], None] = "c9a1d2e3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "reviews",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column("reviews", sa.Column("source_purged_at", sa.DateTime(timezone=True)))
    op.add_column("reviews", sa.Column("data_purged_at", sa.DateTime(timezone=True)))
    op.create_index("ix_reviews_created_at", "reviews", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_reviews_created_at", table_name="reviews")
    op.drop_column("reviews", "data_purged_at")
    op.drop_column("reviews", "source_purged_at")
    op.drop_column("reviews", "created_at")
