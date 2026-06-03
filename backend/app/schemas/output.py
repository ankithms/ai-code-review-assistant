from pydantic import BaseModel
from typing import List

class IssueSchema(BaseModel):
    severity: str
    category: str
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