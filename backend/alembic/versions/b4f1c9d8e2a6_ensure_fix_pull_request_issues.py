"""ensure fix pull request issues join table

Revision ID: b4f1c9d8e2a6
Revises: a8d7e2f3c9b4
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'b4f1c9d8e2a6'
down_revision: Union[str, Sequence[str], None] = 'a8d7e2f3c9b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = 'fix_pull_request_issues'
FIX_PULL_REQUESTS_TABLE_NAME = 'fix_pull_requests'
FIX_BRANCH_INDEX_NAME = 'ix_fix_pull_requests_fix_branch'
ISSUE_INDEX_NAME = 'ix_fix_pull_request_issues_issue_id'


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if FIX_PULL_REQUESTS_TABLE_NAME not in tables:
        op.create_table(
            FIX_PULL_REQUESTS_TABLE_NAME,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('repository_id', sa.Integer(), nullable=False),
            sa.Column('review_id', sa.Integer(), nullable=False),
            sa.Column('original_pull_request_id', sa.Integer(), nullable=False),
            sa.Column('original_pr_number', sa.Integer(), nullable=False),
            sa.Column('source_commit_sha', sa.String(), nullable=False),
            sa.Column('fix_branch', sa.String(length=255), nullable=False),
            sa.Column('github_pr_number', sa.Integer(), nullable=False),
            sa.Column('github_pr_url', sa.Text(), nullable=False),
            sa.Column('github_commit_sha', sa.String(), nullable=True),
            sa.Column('github_commit_url', sa.Text(), nullable=True),
            sa.Column('status', sa.String(length=30), server_default='PR_CREATED', nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('merged_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('failure_message', sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ['original_pull_request_id'],
                ['pull_requests.id'],
                name='fk_fix_pull_requests_original_pull_request_id',
            ),
            sa.ForeignKeyConstraint(
                ['repository_id'],
                ['repositories.id'],
                name='fk_fix_pull_requests_repository_id',
            ),
            sa.ForeignKeyConstraint(
                ['review_id'],
                ['reviews.id'],
                name='fk_fix_pull_requests_review_id',
            ),
            sa.PrimaryKeyConstraint('id', name='pk_fix_pull_requests'),
            sa.UniqueConstraint(
                'repository_id',
                'github_pr_number',
                name='uq_fix_pull_requests_repository_pr_number',
            ),
        )

    fix_pull_request_indexes = {
        index['name']
        for index in inspect(bind).get_indexes(FIX_PULL_REQUESTS_TABLE_NAME)
    }
    if FIX_BRANCH_INDEX_NAME not in fix_pull_request_indexes:
        op.create_index(
            FIX_BRANCH_INDEX_NAME,
            FIX_PULL_REQUESTS_TABLE_NAME,
            ['fix_branch'],
            unique=False,
        )

    tables = set(inspect(bind).get_table_names())
    if TABLE_NAME not in tables:
        op.create_table(
            TABLE_NAME,
            sa.Column('fix_pull_request_id', sa.Integer(), nullable=False),
            sa.Column('issue_id', sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ['fix_pull_request_id'],
                ['fix_pull_requests.id'],
                name='fk_fix_pull_request_issues_fix_pull_request_id',
            ),
            sa.ForeignKeyConstraint(
                ['issue_id'],
                ['issues.id'],
                name='fk_fix_pull_request_issues_issue_id',
            ),
            sa.PrimaryKeyConstraint(
                'fix_pull_request_id',
                'issue_id',
                name='pk_fix_pull_request_issues',
            ),
        )

    indexes = {
        index['name']
        for index in inspect(bind).get_indexes(TABLE_NAME)
    }
    if ISSUE_INDEX_NAME not in indexes:
        op.create_index(
            ISSUE_INDEX_NAME,
            TABLE_NAME,
            ['issue_id'],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if TABLE_NAME not in tables:
        return

    indexes = {
        index['name']
        for index in inspector.get_indexes(TABLE_NAME)
    }
    if ISSUE_INDEX_NAME in indexes:
        op.drop_index(ISSUE_INDEX_NAME, table_name=TABLE_NAME)
