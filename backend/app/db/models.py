from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
    Table,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base
from datetime import UTC, datetime

from app.schemas.output import FixPullRequestStatus, IssueFixStatus, IssueStatus

Base = declarative_base()


fix_pull_request_issues = Table(
    "fix_pull_request_issues",
    Base.metadata,
    Column("fix_pull_request_id", ForeignKey("fix_pull_requests.id"), primary_key=True),
    Column("issue_id", ForeignKey("issues.id"), primary_key=True),
)

fix_commit_issues = Table(
    "fix_commit_issues",
    Base.metadata,
    Column("fix_commit_id", ForeignKey("fix_commits.id"), primary_key=True),
    Column("issue_id", ForeignKey("issues.id"), primary_key=True),
)


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True)
    repository_id = Column(
        Integer,
        ForeignKey("repositories.id"),
    )
    github_pr_id = Column(BigInteger, unique=True)
    pull_request_number = Column(Integer)
    title = Column(String(500))
    repository = Column(String(255))
    author = Column(String(255))

    repository_ref = relationship(
        "Repository",
        back_populates="pull_requests",
    )

    reviews = relationship(
        "Review",
        back_populates="pull_request"
    )

    fix_pull_requests = relationship(
        "FixPullRequest",
        back_populates="original_pull_request",
    )

    fix_commits = relationship(
        "FixCommit",
        back_populates="pull_request",
    )


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(255), nullable=False, unique=True, index=True)

    pull_requests = relationship(
        "PullRequest",
        back_populates="repository_ref",
    )

    fix_pull_requests = relationship(
        "FixPullRequest",
        back_populates="repository_ref",
    )


class Review(Base):
    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True)

    pr_id = Column(
        Integer,
        ForeignKey("pull_requests.id")
    )

    summary = Column(Text)
    commit_sha = Column(String, nullable=False)

    pull_request = relationship(
        "PullRequest",
        back_populates="reviews"
    )

    issues = relationship(
        "Issue",
        back_populates="review"
    )

    fix_pull_requests = relationship(
        "FixPullRequest",
        back_populates="review",
    )

    fix_commits = relationship(
        "FixCommit",
        back_populates="review",
    )


class Issue(Base):
    __tablename__ = "issues"

    id = Column(Integer, primary_key=True)

    review_id = Column(
        Integer,
        ForeignKey("reviews.id")
    )

    severity = Column(String(20))
    category = Column(String(50))
    file = Column(String(255))
    comment = Column(Text)
    line = Column(Integer)
    line_ref = Column(String(50))
    side = Column(String(10))
    start_line = Column(Integer)
    start_side = Column(String(10))
    old_line = Column(Integer)
    diff_hunk = Column(Text)
    source_commit_sha = Column(String)
    impact = Column(Text)
    fix_file_path = Column(String(255))
    fix_start_line = Column(Integer)
    fix_end_line = Column(Integer)
    fix_replacement_code = Column(Text)
    fix_additional_edits = Column(Text)
    fix_explanation = Column(Text)
    fix_status = Column(
        String(30),
        nullable=False,
        default=IssueFixStatus.NO_FIX.value,
        server_default=IssueFixStatus.NO_FIX.value,
    )
    fix_base_commit_sha = Column(String)
    fix_file_sha = Column(String)
    github_review_thread_id = Column(String(255))
    github_comment_id = Column(BigInteger)
    github_comment_node_id = Column(String(255))
    github_review_id = Column(BigInteger)
    resolved_at = Column(DateTime(timezone=True))
    resolved_by = Column(String(255))
    status = Column(
        String(20),
        nullable=False,
        default=IssueStatus.OPEN.value,
        server_default=IssueStatus.OPEN.value,
    )

    review = relationship(
        "Review",
        back_populates="issues"
    )

    fix_pull_requests = relationship(
        "FixPullRequest",
        secondary=fix_pull_request_issues,
        back_populates="issues",
    )

    fix_commits = relationship(
        "FixCommit",
        secondary=fix_commit_issues,
        back_populates="issues",
    )

    @property
    def blocking_fix_pull_request(self):
        blocking_statuses = {
            FixPullRequestStatus.PR_CREATED.value,
            FixPullRequestStatus.MERGED.value,
        }
        matching_pull_requests = [
            fix_pull_request
            for fix_pull_request in self.fix_pull_requests
            if fix_pull_request.status in blocking_statuses
        ]

        return sorted(
            matching_pull_requests,
            key=lambda fix_pull_request: fix_pull_request.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[0] if matching_pull_requests else None

    @property
    def latest_fix_pull_request(self):
        if not self.fix_pull_requests:
            return None

        return sorted(
            self.fix_pull_requests,
            key=lambda fix_pull_request: fix_pull_request.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[0]

    @property
    def latest_fix_commit(self):
        successful_commits = [
            fix_commit
            for fix_commit in self.fix_commits
            if fix_commit.status == "SUCCESS"
        ]
        return sorted(
            successful_commits,
            key=lambda fix_commit: fix_commit.created_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[0] if successful_commits else None

    @property
    def eligible_for_fix(self):
        return (
            self.status == IssueStatus.OPEN.value
            and self.blocking_fix_pull_request is None
            and self.fix_status != IssueFixStatus.FIX_COMMITTED.value
        )

    @property
    def fix_pr_number(self):
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.github_pr_number if fix_pull_request else None

    @property
    def fix_pr_url(self):
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.github_pr_url if fix_pull_request else None

    @property
    def fix_commit_sha(self):
        fix_commit = self.latest_fix_commit
        if fix_commit:
            return fix_commit.github_commit_sha
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.github_commit_sha if fix_pull_request else None

    @property
    def fix_commit_url(self):
        fix_commit = self.latest_fix_commit
        if fix_commit:
            return fix_commit.github_commit_url
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.github_commit_url if fix_pull_request else None

    @property
    def fix_branch(self):
        fix_commit = self.latest_fix_commit
        if fix_commit:
            return fix_commit.branch_name
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.fix_branch if fix_pull_request else None

    @property
    def fix_created_at(self):
        fix_commit = self.latest_fix_commit
        if fix_commit:
            return fix_commit.created_at
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.created_at if fix_pull_request else None

    @property
    def fix_merged_at(self):
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.merged_at if fix_pull_request else None

    @property
    def fix_closed_at(self):
        fix_pull_request = self.latest_fix_pull_request
        return fix_pull_request.closed_at if fix_pull_request else None


class ReviewJob(Base):
    __tablename__ = "review_jobs"

    id = Column(Integer, primary_key=True)
    repository = Column(String(255), nullable=False)
    pull_request_number = Column(Integer, nullable=False)
    commit_sha = Column(String, nullable=False, index=True)
    event_action = Column(String(40))
    base_commit_sha = Column(String)
    head_commit_sha = Column(String)
    status = Column(String(20), nullable=False, default="PENDING")
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    error_message = Column(Text)


class FixCommit(Base):
    __tablename__ = "fix_commits"

    id = Column(Integer, primary_key=True)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)
    pull_request_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    created_by = Column(String(255))
    github_commit_sha = Column(String, index=True)
    github_commit_url = Column(Text)
    commit_message = Column(Text)
    source_head_sha = Column(String)
    validation_status = Column(String(30), nullable=False, default="PASSED")
    status = Column(String(30), nullable=False)
    applied_issue_ids = Column(Text, nullable=False)
    branch_name = Column(String(255))
    pull_request_url = Column(Text)
    mode = Column(String(30), nullable=False)
    error_message = Column(Text)

    review = relationship(
        "Review",
        back_populates="fix_commits",
    )
    pull_request = relationship(
        "PullRequest",
        back_populates="fix_commits",
    )
    issues = relationship(
        "Issue",
        secondary=fix_commit_issues,
        back_populates="fix_commits",
    )

    @property
    def repository(self):
        return self.pull_request.repository if self.pull_request else None

    @property
    def author(self):
        return self.created_by

    @property
    def pull_request_number(self):
        return self.pull_request.pull_request_number if self.pull_request else None

    @property
    def issue_ids(self):
        return [issue.id for issue in self.issues]


class FixPullRequest(Base):
    __tablename__ = "fix_pull_requests"

    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    review_id = Column(Integer, ForeignKey("reviews.id"), nullable=False)
    original_pull_request_id = Column(Integer, ForeignKey("pull_requests.id"), nullable=False)
    original_pr_number = Column(Integer, nullable=False)
    source_commit_sha = Column(String, nullable=False)
    fix_branch = Column(String(255), nullable=False)
    github_pr_number = Column(Integer, nullable=False)
    github_pr_url = Column(Text, nullable=False)
    github_commit_sha = Column(String)
    github_commit_url = Column(Text)
    status = Column(
        String(30),
        nullable=False,
        default=FixPullRequestStatus.PR_CREATED.value,
        server_default=FixPullRequestStatus.PR_CREATED.value,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    merged_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    failure_message = Column(Text)

    repository_ref = relationship(
        "Repository",
        back_populates="fix_pull_requests",
    )
    review = relationship(
        "Review",
        back_populates="fix_pull_requests",
    )
    original_pull_request = relationship(
        "PullRequest",
        back_populates="fix_pull_requests",
    )
    issues = relationship(
        "Issue",
        secondary=fix_pull_request_issues,
        back_populates="fix_pull_requests",
    )

    @property
    def issue_ids(self):
        return [issue.id for issue in self.issues]
