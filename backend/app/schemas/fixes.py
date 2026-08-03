import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from app.schemas.output import FixCommitIssueStatus, FixCommitStatus


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
    retry: bool = False


class FixGenerateResponse(BaseModel):
    review_id: int
    target_head_sha: str
    fixes: list[IssueFixResponse]
    fix_commit_id: int
    status: FixCommitStatus


class FixPreviewRequest(BaseModel):
    issue_ids: list[int] | None = None
    fix_commit_id: int | None = None


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
    fix_commit_id: int | None = None
    status: FixCommitStatus | None = None


class FixApplyRequest(BaseModel):
    issue_ids: list[int] | None = None
    fix_commit_id: int | None = None
    mode: FixApplyMode = FixApplyMode.DIRECT
    confirm: bool = False
    retry: bool = False


class IssueTimelineEventResponse(BaseModel):
    event: str
    details: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class FixCommitIssueResponse(BaseModel):
    issue_id: int
    current_issue_id: int | None = None
    status: FixCommitIssueStatus
    generated: bool
    validated: bool
    committed: bool
    resolution_status: str | None = None
    original_file: str | None = None
    original_line: int | None = None
    current_file: str | None = None
    current_line: int | None = None
    match_confidence: str | None = None
    match_reason: str | None = None
    skip_reason: str | None = None
    failure_reason: str | None = None
    timeline: list[IssueTimelineEventResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class FixCommitNewIssueResponse(BaseModel):
    id: int
    severity: str
    category: str
    file: str | None = None
    line: int | None = None
    comment: str

    model_config = {"from_attributes": True}


class FixCommitResponse(BaseModel):
    id: int
    status: str
    mode: str
    repository_id: int | None = None
    pull_request_id: int
    review_id: int
    follow_up_review_id: int | None = None
    source_branch: str | None = None
    source_head_sha: str | None = None
    resulting_head_sha: str | None = None
    generated_commit_sha: str | None = None
    generated_commit_url: str | None = None
    branch_name: str | None = None
    github_commit_sha: str | None = None
    github_commit_url: str | None = None
    commit_message: str | None = None
    author: str | None = None
    repository: str | None = None
    pull_request_number: int | None = None
    validation_status: str
    validation_summary: str | None = None
    pull_request_url: str | None = None
    applied_issue_ids: list[int]
    requested_issue_count: int = 0
    valid_issue_count: int = 0
    skipped_issue_count: int = 0
    resolved_issue_count: int = 0
    remaining_issue_count: int = 0
    moved_issue_count: int = 0
    new_issue_count: int = 0
    failed_issue_count: int = 0
    issues: list[FixCommitIssueResponse] = Field(default_factory=list)
    resolved_issues: list[FixCommitIssueResponse] = Field(default_factory=list)
    remaining_issues: list[FixCommitIssueResponse] = Field(default_factory=list)
    moved_issues: list[FixCommitIssueResponse] = Field(default_factory=list)
    failed_to_verify_issues: list[FixCommitIssueResponse] = Field(default_factory=list)
    new_issues: list[FixCommitNewIssueResponse] = Field(default_factory=list)
    verification_status: str = "PENDING"
    verification_completed_at: datetime | None = None
    verification_summary: str | None = None
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None = None
    reviewed_at: datetime | None = None
    failure_reason: str | None = None
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
