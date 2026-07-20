"""add incremental review job fields

Revision ID: f6b2c9a1d4e8
Revises: e1f8b725c934
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6b2c9a1d4e8'
down_revision: Union[str, Sequence[str], None] = 'e1f8b725c934'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('review_jobs', sa.Column('event_action', sa.String(length=40), nullable=True))
    op.add_column('review_jobs', sa.Column('base_commit_sha', sa.String(), nullable=True))
    op.add_column('review_jobs', sa.Column('head_commit_sha', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('review_jobs', 'head_commit_sha')
    op.drop_column('review_jobs', 'base_commit_sha')
    op.drop_column('review_jobs', 'event_action')
