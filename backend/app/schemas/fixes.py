import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class FixApplyMode(str, Enum):
    DIRECT = "DIRECT"


class FixPullRequestStatus(str, Enum):
    PR_CREATED = "PR_CREATED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class AdditionalEditResponse(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    original_code: str | None = None
    replacement_code: str
    reason: str


class IssueFixResponse(BaseModel):
    issue_id: int
    status: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    replacement_code: str | None = None
    explanation: str | None = None
    additional_edits: list[AdditionalEditResponse] = Field(default_factory=list)


class FixGenerateRequest(BaseModel):
    issue_ids: list[int] | None = None


class FixGenerateResponse(BaseModel):
    review_id: int
    target_head_sha: str
    fixes: list[IssueFixResponse]


class FixPreviewRequest(BaseModel):
    issue_ids: list[int] | None = None


class FixPreviewFileResponse(BaseModel):
    file_path: str
    original_sha: str
    valid: bool
    errors: list[str]
    patched_content: str | None = None


class FixPreviewResponse(BaseModel):
    review_id: int
    target_branch: str
    target_head_sha: str
    valid: bool
    errors: list[str]
    files: list[FixPreviewFileResponse]
    fixes: list[IssueFixResponse]
    included_issue_ids: list[int] = Field(default_factory=list)
    excluded_issue_ids: list[int] = Field(default_factory=list)


class FixApplyRequest(BaseModel):
    issue_ids: list[int] | None = None
    mode: FixApplyMode = FixApplyMode.DIRECT
    confirm: bool = False


class FixCommitResponse(BaseModel):
    id: int
    status: str
    mode: str
    branch_name: str | None = None
    github_commit_sha: str | None = None
    github_commit_url: str | None = None
    commit_message: str | None = None
    author: str | None = None
    repository: str | None = None
    pull_request_number: int | None = None
    validation_status: str
    pull_request_url: str | None = None
    applied_issue_ids: list[int]
    created_at: datetime
    error_message: str | None = None

    @field_validator("applied_issue_ids", mode="before")
    @classmethod
    def parse_applied_issue_ids(cls, value):
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return parsed if isinstance(parsed, list) else []
        return value

    model_config = {
        "from_attributes": True
    }


class FixPullRequestResponse(BaseModel):
    id: int
    status: str
    github_pr_number: int
    github_pr_url: str
    github_commit_sha: str | None = None
    github_commit_url: str | None = None
    fix_branch: str
    issue_ids: list[int]
    created_at: datetime
    merged_at: datetime | None = None
    closed_at: datetime | None = None
