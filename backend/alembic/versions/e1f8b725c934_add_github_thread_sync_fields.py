"""add github thread sync fields

Revision ID: e1f8b725c934
Revises: d4a62cf5b8e9
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f8b725c934'
down_revision: Union[str, Sequence[str], None] = 'd4a62cf5b8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('pull_requests', sa.Column('pull_request_number', sa.Integer(), nullable=True))
    op.add_column('issues', sa.Column('github_review_thread_id', sa.String(length=255), nullable=True))
    op.add_column('issues', sa.Column('github_comment_id', sa.BigInteger(), nullable=True))
    op.add_column('issues', sa.Column('github_comment_node_id', sa.String(length=255), nullable=True))
    op.add_column('issues', sa.Column('github_review_id', sa.BigInteger(), nullable=True))
    op.add_column('issues', sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('issues', sa.Column('resolved_by', sa.String(length=255), nullable=True))
    op.create_index(op.f('ix_issues_github_review_thread_id'), 'issues', ['github_review_thread_id'], unique=False)
    op.create_index(op.f('ix_issues_github_comment_id'), 'issues', ['github_comment_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_issues_github_comment_id'), table_name='issues')
    op.drop_index(op.f('ix_issues_github_review_thread_id'), table_name='issues')
    op.drop_column('issues', 'resolved_by')
    op.drop_column('issues', 'resolved_at')
    op.drop_column('issues', 'github_review_id')
    op.drop_column('issues', 'github_comment_node_id')
    op.drop_column('issues', 'github_comment_id')
    op.drop_column('issues', 'github_review_thread_id')
    op.drop_column('pull_requests', 'pull_request_number')
