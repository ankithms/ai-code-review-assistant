from sqlalchemy import (
    BigInteger,
    Column,
    Integer,
    String,
    Text,
    ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True)
    github_pr_id = Column(BigInteger, unique=True)
    title = Column(String(500))
    repository = Column(String(255))
    author = Column(String(255))

    reviews = relationship(
        "Review",
        back_populates="pull_request"
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

    review = relationship(
        "Review",
        back_populates="issues"
    )