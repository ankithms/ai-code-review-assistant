"""add GitHub fix command request key

Revision ID: 5b7d9e1a3c42
Revises: 1a6c8e4f2b90
Create Date: 2026-09-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "5b7d9e1a3c42"
down_revision: Union[str, Sequence[str], None] = "1a6c8e4f2b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fix_commits", sa.Column("request_key", sa.String(length=255)))
    op.create_index(
        "ix_fix_commits_request_key",
        "fix_commits",
        ["request_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_fix_commits_request_key", table_name="fix_commits")
    op.drop_column("fix_commits", "request_key")
