"""complete direct fix commit lifecycle tracking

Revision ID: 8d4c1f2a9b7e
Revises: f2a9c7d4e6b1
Create Date: 2026-07-30 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d4c1f2a9b7e"
down_revision: Union[str, Sequence[str], None] = "f2a9c7d4e6b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_fix_commits_github_commit_sha", table_name="fix_commits")
    op.alter_column("fix_commits", "github_commit_sha", new_column_name="generated_commit_sha")
    op.alter_column("fix_commits", "github_commit_url", new_column_name="generated_commit_url")
    op.alter_column("fix_commits", "branch_name", new_column_name="source_branch")
    op.alter_column("fix_commits", "error_message", new_column_name="failure_reason")

    op.add_column("fix_commits", sa.Column("repository_id", sa.Integer(), nullable=True))
    op.add_column("fix_commits", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fix_commits", sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fix_commits", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fix_commits", sa.Column("resulting_head_sha", sa.String(), nullable=True))
    op.add_column("fix_commits", sa.Column("idempotency_key", sa.String(length=64), nullable=True))
    op.add_column(
        "fix_commits",
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column("fix_commits", sa.Column("validation_summary", sa.Text(), nullable=True))
    for name in (
        "requested_issue_count",
        "valid_issue_count",
        "skipped_issue_count",
        "resolved_issue_count",
        "remaining_issue_count",
        "failed_issue_count",
    ):
        op.add_column(
            "fix_commits",
            sa.Column(name, sa.Integer(), server_default="0", nullable=False),
        )

    op.execute(
        """
        UPDATE fix_commits
        SET repository_id = pull_requests.repository_id
        FROM pull_requests
        WHERE fix_commits.pull_request_id = pull_requests.id
        """
    )
    op.execute("UPDATE fix_commits SET updated_at = created_at WHERE updated_at IS NULL")
    op.execute(
        """
        UPDATE fix_commits
        SET source_head_sha = reviews.commit_sha
        FROM reviews
        WHERE fix_commits.review_id = reviews.id AND fix_commits.source_head_sha IS NULL
        """
    )
    op.execute("UPDATE fix_commits SET source_head_sha = 'unknown' WHERE source_head_sha IS NULL")
    op.execute("UPDATE fix_commits SET source_branch = 'unknown' WHERE source_branch IS NULL")
    op.execute(
        "UPDATE fix_commits SET resulting_head_sha = generated_commit_sha "
        "WHERE generated_commit_sha IS NOT NULL"
    )
    op.execute(
        "UPDATE fix_commits SET committed_at = created_at "
        "WHERE generated_commit_sha IS NOT NULL AND committed_at IS NULL"
    )
    op.execute("UPDATE fix_commits SET status = 'REVIEW_PENDING' WHERE status = 'SUCCESS'")
    op.execute("UPDATE fix_commits SET status = 'COMMITTING' WHERE status = 'PENDING'")
    op.execute(
        """
        UPDATE fix_commits
        SET requested_issue_count = counts.issue_count,
            valid_issue_count = CASE WHEN generated_commit_sha IS NULL THEN 0 ELSE counts.issue_count END
        FROM (
            SELECT fix_commit_id, COUNT(*) AS issue_count
            FROM fix_commit_issues
            GROUP BY fix_commit_id
        ) AS counts
        WHERE fix_commits.id = counts.fix_commit_id
        """
    )
    op.alter_column("fix_commits", "updated_at", nullable=False)
    op.alter_column("fix_commits", "source_head_sha", nullable=False)
    op.alter_column("fix_commits", "source_branch", nullable=False)
    op.create_foreign_key(
        "fk_fix_commits_repository_id",
        "fix_commits",
        "repositories",
        ["repository_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_fix_commits_identity_attempt",
        "fix_commits",
        ["idempotency_key", "attempt"],
    )
    op.create_index(
        "ix_fix_commits_generated_commit_sha",
        "fix_commits",
        ["generated_commit_sha"],
        unique=True,
    )
    op.create_index("ix_fix_commits_pull_request_id", "fix_commits", ["pull_request_id"])
    op.create_index("ix_fix_commits_source_head_sha", "fix_commits", ["source_head_sha"])
    op.create_index("ix_fix_commits_status", "fix_commits", ["status"])

    op.add_column("fix_commit_issues", sa.Column("current_issue_id", sa.Integer(), nullable=True))
    op.add_column(
        "fix_commit_issues",
        sa.Column("status", sa.String(length=30), server_default="REQUESTED", nullable=False),
    )
    op.add_column(
        "fix_commit_issues",
        sa.Column("generated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "fix_commit_issues",
        sa.Column("validated", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "fix_commit_issues",
        sa.Column("committed", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("fix_commit_issues", sa.Column("resolution_status", sa.String(length=30), nullable=True))
    op.add_column("fix_commit_issues", sa.Column("skip_reason", sa.Text(), nullable=True))
    op.add_column("fix_commit_issues", sa.Column("failure_reason", sa.Text(), nullable=True))
    op.add_column("fix_commit_issues", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fix_commit_issues", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE fix_commit_issues SET created_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP")
    op.execute(
        """
        UPDATE fix_commit_issues
        SET generated = true, validated = true, committed = true, status = 'COMMITTED'
        WHERE fix_commit_id IN (
            SELECT id FROM fix_commits WHERE generated_commit_sha IS NOT NULL
        )
        """
    )
    op.alter_column("fix_commit_issues", "created_at", nullable=False)
    op.alter_column("fix_commit_issues", "updated_at", nullable=False)
    op.create_foreign_key(
        "fk_fix_commit_issues_current_issue_id",
        "fix_commit_issues",
        "issues",
        ["current_issue_id"],
        ["id"],
    )
    op.create_index("ix_fix_commit_issues_fix_commit_id", "fix_commit_issues", ["fix_commit_id"])
    op.create_index("ix_fix_commit_issues_issue_id", "fix_commit_issues", ["issue_id"])

    op.add_column("reviews", sa.Column("fix_commit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_reviews_fix_commit_id", "reviews", "fix_commits", ["fix_commit_id"], ["id"]
    )
    op.create_index("ix_reviews_fix_commit_id", "reviews", ["fix_commit_id"])

    op.add_column("review_jobs", sa.Column("fix_commit_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_review_jobs_fix_commit_id",
        "review_jobs",
        "fix_commits",
        ["fix_commit_id"],
        ["id"],
    )
    op.create_index("ix_review_jobs_fix_commit_id", "review_jobs", ["fix_commit_id"])


def downgrade() -> None:
    op.drop_index("ix_review_jobs_fix_commit_id", table_name="review_jobs")
    op.drop_constraint("fk_review_jobs_fix_commit_id", "review_jobs", type_="foreignkey")
    op.drop_column("review_jobs", "fix_commit_id")
    op.drop_index("ix_reviews_fix_commit_id", table_name="reviews")
    op.drop_constraint("fk_reviews_fix_commit_id", "reviews", type_="foreignkey")
    op.drop_column("reviews", "fix_commit_id")

    op.drop_index("ix_fix_commit_issues_issue_id", table_name="fix_commit_issues")
    op.drop_index("ix_fix_commit_issues_fix_commit_id", table_name="fix_commit_issues")
    op.drop_constraint(
        "fk_fix_commit_issues_current_issue_id", "fix_commit_issues", type_="foreignkey"
    )
    for name in (
        "updated_at",
        "created_at",
        "failure_reason",
        "skip_reason",
        "resolution_status",
        "committed",
        "validated",
        "generated",
        "status",
        "current_issue_id",
    ):
        op.drop_column("fix_commit_issues", name)

    op.drop_index("ix_fix_commits_status", table_name="fix_commits")
    op.drop_index("ix_fix_commits_source_head_sha", table_name="fix_commits")
    op.drop_index("ix_fix_commits_pull_request_id", table_name="fix_commits")
    op.drop_index("ix_fix_commits_generated_commit_sha", table_name="fix_commits")
    op.drop_constraint("uq_fix_commits_identity_attempt", "fix_commits", type_="unique")
    op.drop_constraint("fk_fix_commits_repository_id", "fix_commits", type_="foreignkey")
    for name in (
        "failed_issue_count",
        "remaining_issue_count",
        "resolved_issue_count",
        "skipped_issue_count",
        "valid_issue_count",
        "requested_issue_count",
        "validation_summary",
        "attempt",
        "idempotency_key",
        "resulting_head_sha",
        "reviewed_at",
        "committed_at",
        "updated_at",
        "repository_id",
    ):
        op.drop_column("fix_commits", name)
    op.alter_column("fix_commits", "failure_reason", new_column_name="error_message")
    op.alter_column("fix_commits", "source_branch", new_column_name="branch_name")
    op.alter_column("fix_commits", "generated_commit_url", new_column_name="github_commit_url")
    op.alter_column("fix_commits", "generated_commit_sha", new_column_name="github_commit_sha")
    op.create_index(
        "ix_fix_commits_github_commit_sha",
        "fix_commits",
        ["github_commit_sha"],
        unique=False,
    )
