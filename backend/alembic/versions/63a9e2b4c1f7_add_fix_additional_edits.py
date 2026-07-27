"""add fix additional edits

Revision ID: 63a9e2b4c1f7
Revises: 54d8c0e7b9a1
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "63a9e2b4c1f7"
down_revision: Union[str, Sequence[str], None] = "54d8c0e7b9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("fix_additional_edits", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "fix_additional_edits")
