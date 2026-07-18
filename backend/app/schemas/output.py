from pydantic import BaseModel
from typing import List
from enum import Enum


class SeverityEnum(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class CategoryEnum(str, Enum):
    security = "security"
    bug = "bug"
    performance = "performance"
    readability = "readability"
    edge_case = "edge_case"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    IGNORED = "IGNORED"


class IssueSchema(BaseModel):
    severity: SeverityEnum
    category: CategoryEnum
    file: str
    line: int | None = None
    comment: str
    impact: str | None = None


class ReviewResponseSchema(BaseModel):
    summary: str
    issues: List[IssueSchema]


class PullRequestSchema(BaseModel):
    github_pr_id: int
    title: str
    repository: str
    author: str
