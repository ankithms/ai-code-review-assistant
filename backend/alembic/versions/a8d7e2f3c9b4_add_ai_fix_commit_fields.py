"""add ai fix commit fields

Revision ID: a8d7e2f3c9b4
Revises: f6b2c9a1d4e8
Create Date: 2026-07-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a8d7e2f3c9b4'
down_revision: Union[str, Sequence[str], None] = 'f6b2c9a1d4e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('issues', sa.Column('fix_file_path', sa.String(length=255), nullable=True))
    op.add_column('issues', sa.Column('fix_start_line', sa.Integer(), nullable=True))
    op.add_column('issues', sa.Column('fix_end_line', sa.Integer(), nullable=True))
    op.add_column('issues', sa.Column('fix_replacement_code', sa.Text(), nullable=True))
    op.add_column('issues', sa.Column('fix_explanation', sa.Text(), nullable=True))
    op.add_column(
        'issues',
        sa.Column(
            'fix_status',
            sa.String(length=30),
            server_default='NO_FIX',
            nullable=False,
        ),
    )
    op.add_column('issues', sa.Column('fix_base_commit_sha', sa.String(), nullable=True))
    op.add_column('issues', sa.Column('fix_file_sha', sa.String(), nullable=True))

    op.create_table(
        'fix_commits',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('review_id', sa.Integer(), nullable=False),
        sa.Column('pull_request_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('github_commit_sha', sa.String(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('applied_issue_ids', sa.Text(), nullable=False),
        sa.Column('branch_name', sa.String(length=255), nullable=True),
        sa.Column('pull_request_url', sa.Text(), nullable=True),
        sa.Column('mode', sa.String(length=30), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['pull_request_id'], ['pull_requests.id']),
        sa.ForeignKeyConstraint(['review_id'], ['reviews.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'fix_pull_requests',
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
        sa.ForeignKeyConstraint(['original_pull_request_id'], ['pull_requests.id']),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id']),
        sa.ForeignKeyConstraint(['review_id'], ['reviews.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('repository_id', 'github_pr_number', name='uq_fix_pull_requests_repository_pr_number'),
    )
    op.create_index(
        op.f('ix_fix_pull_requests_fix_branch'),
        'fix_pull_requests',
        ['fix_branch'],
        unique=False,
    )
    op.create_table(
        'fix_pull_request_issues',
        sa.Column('fix_pull_request_id', sa.Integer(), nullable=False),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['fix_pull_request_id'], ['fix_pull_requests.id']),
        sa.ForeignKeyConstraint(['issue_id'], ['issues.id']),
        sa.PrimaryKeyConstraint('fix_pull_request_id', 'issue_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('fix_pull_request_issues')
    op.drop_index(op.f('ix_fix_pull_requests_fix_branch'), table_name='fix_pull_requests')
    op.drop_table('fix_pull_requests')
    op.drop_table('fix_commits')
    op.drop_column('issues', 'fix_file_sha')
    op.drop_column('issues', 'fix_base_commit_sha')
    op.drop_column('issues', 'fix_status')
    op.drop_column('issues', 'fix_explanation')
    op.drop_column('issues', 'fix_replacement_code')
    op.drop_column('issues', 'fix_end_line')
    op.drop_column('issues', 'fix_start_line')
    op.drop_column('issues', 'fix_file_path')
