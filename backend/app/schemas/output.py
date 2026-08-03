from pydantic import BaseModel, model_validator
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


class IssueFixStatus(str, Enum):
    NO_FIX = "NO_FIX"
    FIX_GENERATED = "FIX_GENERATED"
    FIX_COMMITTED = "FIX_COMMITTED"
    FIX_PR_CREATED = "FIX_PR_CREATED"
    FIX_MERGED = "FIX_MERGED"
    FIX_PR_CLOSED = "FIX_PR_CLOSED"


class FixCommitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GENERATING = "GENERATING"
    VALIDATING = "VALIDATING"
    COMMITTING = "COMMITTING"
    COMMITTED = "COMMITTED"
    REVIEW_PENDING = "REVIEW_PENDING"
    REVIEWED = "REVIEWED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    RESOLVED = "RESOLVED"
    FAILED = "FAILED"
    STALE = "STALE"


class FixCommitIssueStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GENERATED = "GENERATED"
    VALIDATED = "VALIDATED"
    SKIPPED = "SKIPPED"
    COMMITTED = "COMMITTED"
    RESOLVED = "RESOLVED"
    STILL_OPEN = "STILL_OPEN"
    MOVED = "MOVED"
    FAILED_TO_VERIFY = "FAILED_TO_VERIFY"
    FAILED = "FAILED"


class FixPullRequestStatus(str, Enum):
    PR_CREATED = "PR_CREATED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class IssueFixSchema(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    replacement_code: str
    explanation: str | None = None


class ReviewCommentSide(str, Enum):
    RIGHT = "RIGHT"
    LEFT = "LEFT"


class IssueSchema(BaseModel):
    severity: SeverityEnum
    category: CategoryEnum
    file: str | None = None
    file_path: str | None = None
    line_ref: str | None = None
    line: int | None = None
    side: ReviewCommentSide | None = None
    start_line: int | None = None
    start_side: ReviewCommentSide | None = None
    old_line: int | None = None
    diff_hunk: str | None = None
    source_commit_sha: str | None = None
    comment: str
    impact: str | None = None
    fix: IssueFixSchema | None = None
    github_review_thread_id: str | None = None
    github_comment_id: int | None = None
    github_comment_node_id: str | None = None
    github_review_id: int | None = None

    @model_validator(mode="after")
    def normalize_file_path(self):
        if self.file is None and self.file_path is not None:
            self.file = self.file_path
        if self.file_path is None and self.file is not None:
            self.file_path = self.file
        return self


class ReviewResponseSchema(BaseModel):
    summary: str
    issues: List[IssueSchema]


class PullRequestSchema(BaseModel):
    github_pr_id: int
    pull_request_number: int
    title: str
    repository: str
    author: str
