"""add automatic fix verification metadata

Revision ID: 4e2a9d7c1b6f
Revises: 8d4c1f2a9b7e
Create Date: 2026-07-31 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e2a9d7c1b6f"
down_revision: Union[str, Sequence[str], None] = "8d4c1f2a9b7e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("issues", sa.Column("fingerprint", sa.String(length=64), nullable=True))
    op.add_column(
        "issues",
        sa.Column("introduced_by_fix_commit_id", sa.Integer(), nullable=True),
    )
    op.execute("UPDATE issues SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    op.alter_column("issues", "created_at", nullable=False)
    op.create_foreign_key(
        "fk_issues_introduced_by_fix_commit_id",
        "issues",
        "fix_commits",
        ["introduced_by_fix_commit_id"],
        ["id"],
    )
    op.create_index("ix_issues_fingerprint", "issues", ["fingerprint"])
    op.create_index(
        "ix_issues_introduced_by_fix_commit_id",
        "issues",
        ["introduced_by_fix_commit_id"],
    )

    op.add_column(
        "fix_commits",
        sa.Column("verification_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("fix_commits", sa.Column("verification_summary", sa.Text(), nullable=True))
    op.add_column(
        "fix_commits",
        sa.Column("moved_issue_count", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "fix_commits",
        sa.Column("new_issue_count", sa.Integer(), server_default="0", nullable=False),
    )

    for name, column_type in (
        ("original_file", sa.String(length=255)),
        ("original_line", sa.Integer()),
        ("current_file", sa.String(length=255)),
        ("current_line", sa.Integer()),
        ("match_confidence", sa.String(length=20)),
        ("match_reason", sa.Text()),
    ):
        op.add_column("fix_commit_issues", sa.Column(name, column_type, nullable=True))
    op.execute(
        """
        UPDATE fix_commit_issues
        SET original_file = issues.file, original_line = issues.line
        FROM issues
        WHERE fix_commit_issues.issue_id = issues.id
        """
    )

    op.create_table(
        "issue_timeline_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("fix_commit_id", sa.Integer(), nullable=True),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"]),
        sa.ForeignKeyConstraint(["fix_commit_id"], ["fix_commits.id"]),
    )
    op.create_index(
        "ix_issue_timeline_events_issue_id", "issue_timeline_events", ["issue_id"]
    )
    op.create_index(
        "ix_issue_timeline_events_fix_commit_id",
        "issue_timeline_events",
        ["fix_commit_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_issue_timeline_events_fix_commit_id", table_name="issue_timeline_events"
    )
    op.drop_index("ix_issue_timeline_events_issue_id", table_name="issue_timeline_events")
    op.drop_table("issue_timeline_events")

    for name in (
        "match_reason",
        "match_confidence",
        "current_line",
        "current_file",
        "original_line",
        "original_file",
    ):
        op.drop_column("fix_commit_issues", name)

    for name in (
        "new_issue_count",
        "moved_issue_count",
        "verification_summary",
        "verification_completed_at",
    ):
        op.drop_column("fix_commits", name)

    op.drop_index("ix_issues_introduced_by_fix_commit_id", table_name="issues")
    op.drop_index("ix_issues_fingerprint", table_name="issues")
    op.drop_constraint(
        "fk_issues_introduced_by_fix_commit_id", "issues", type_="foreignkey"
    )
    op.drop_column("issues", "introduced_by_fix_commit_id")
    op.drop_column("issues", "fingerprint")
    op.drop_column("issues", "created_at")
