"""track direct fix commits

Revision ID: f2a9c7d4e6b1
Revises: 63a9e2b4c1f7
Create Date: 2026-07-28 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a9c7d4e6b1"
down_revision: Union[str, Sequence[str], None] = "63a9e2b4c1f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("fix_commits", sa.Column("github_commit_url", sa.Text(), nullable=True))
    op.add_column("fix_commits", sa.Column("commit_message", sa.Text(), nullable=True))
    op.add_column("fix_commits", sa.Column("source_head_sha", sa.String(), nullable=True))
    op.add_column(
        "fix_commits",
        sa.Column(
            "validation_status",
            sa.String(length=30),
            server_default="PASSED",
            nullable=False,
        ),
    )
    op.create_table(
        "fix_commit_issues",
        sa.Column("fix_commit_id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["fix_commit_id"], ["fix_commits.id"]),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"]),
        sa.PrimaryKeyConstraint("fix_commit_id", "issue_id"),
    )
    op.create_index(
        "ix_fix_commits_github_commit_sha",
        "fix_commits",
        ["github_commit_sha"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_fix_commits_github_commit_sha", table_name="fix_commits")
    op.drop_table("fix_commit_issues")
    op.drop_column("fix_commits", "validation_status")
    op.drop_column("fix_commits", "source_head_sha")
    op.drop_column("fix_commits", "commit_message")
    op.drop_column("fix_commits", "github_commit_url")
