"""add pull request branch metadata

Revision ID: 6c2d8a4f1e90
Revises: 5b7d9e1a3c42
Create Date: 2026-09-27 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6c2d8a4f1e90"
down_revision: Union[str, Sequence[str], None] = "5b7d9e1a3c42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pull_requests", sa.Column("source_branch", sa.String(length=255)))
    op.add_column("pull_requests", sa.Column("target_branch", sa.String(length=255)))
    op.add_column("pull_requests", sa.Column("source_repository", sa.String(length=255)))


def downgrade() -> None:
    op.drop_column("pull_requests", "source_repository")
    op.drop_column("pull_requests", "target_branch")
    op.drop_column("pull_requests", "source_branch")
