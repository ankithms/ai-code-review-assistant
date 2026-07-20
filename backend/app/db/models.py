from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base
from datetime import UTC, datetime

from app.schemas.output import IssueStatus

Base = declarative_base()


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


class Repository(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True)
    full_name = Column(String(255), nullable=False, unique=True, index=True)

    pull_requests = relationship(
        "PullRequest",
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
    impact = Column(Text)
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
