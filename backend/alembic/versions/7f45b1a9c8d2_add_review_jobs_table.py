"""add review jobs table

Revision ID: 7f45b1a9c8d2
Revises: a15ed06e84de
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f45b1a9c8d2'
down_revision: Union[str, Sequence[str], None] = 'a15ed06e84de'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'review_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('repository', sa.String(length=255), nullable=False),
        sa.Column('pull_request_number', sa.Integer(), nullable=False),
        sa.Column('commit_sha', sa.String(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_review_jobs_commit_sha'),
        'review_jobs',
        ['commit_sha'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_review_jobs_commit_sha'), table_name='review_jobs')
    op.drop_table('review_jobs')
