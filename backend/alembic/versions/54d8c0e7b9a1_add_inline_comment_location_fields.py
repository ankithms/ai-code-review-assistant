"""add inline comment location fields

Revision ID: 54d8c0e7b9a1
Revises: b4f1c9d8e2a6
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "54d8c0e7b9a1"
down_revision: Union[str, Sequence[str], None] = "b4f1c9d8e2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("line_ref", sa.String(length=50), nullable=True))
    op.add_column("issues", sa.Column("side", sa.String(length=10), nullable=True))
    op.add_column("issues", sa.Column("start_line", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("start_side", sa.String(length=10), nullable=True))
    op.add_column("issues", sa.Column("old_line", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("diff_hunk", sa.Text(), nullable=True))
    op.add_column("issues", sa.Column("source_commit_sha", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "source_commit_sha")
    op.drop_column("issues", "diff_hunk")
    op.drop_column("issues", "old_line")
    op.drop_column("issues", "start_side")
    op.drop_column("issues", "start_line")
    op.drop_column("issues", "side")
    op.drop_column("issues", "line_ref")
