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


class IssueSchema(BaseModel):
    severity: SeverityEnum
    category: CategoryEnum
    file: str
    comment: str


class ReviewResponseSchema(BaseModel):
    summary: str
    issues: List[IssueSchema]


class PullRequestSchema(BaseModel):
    github_pr_id: int
    title: str
    repository: str
    author: str