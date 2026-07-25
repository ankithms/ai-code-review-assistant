from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class FixApplyMode(str, Enum):
    BRANCH_PR = "BRANCH_PR"
    DIRECT = "DIRECT"


class FixPullRequestStatus(str, Enum):
    PR_CREATED = "PR_CREATED"
    MERGED = "MERGED"
    CLOSED = "CLOSED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class IssueFixResponse(BaseModel):
    issue_id: int
    status: str
    file_path: str | None = None
    start_line: int | None = None
    end_line: int | None = None
    replacement_code: str | None = None
    explanation: str | None = None


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


class FixApplyRequest(BaseModel):
    issue_ids: list[int] | None = None
    mode: FixApplyMode = FixApplyMode.BRANCH_PR
    confirm: bool = False
    confirm_direct_commit: bool = False


class FixCommitResponse(BaseModel):
    id: int
    status: str
    mode: str
    branch_name: str | None = None
    github_commit_sha: str | None = None
    pull_request_url: str | None = None
    applied_issue_ids: list[int]
    created_at: datetime
    error_message: str | None = None

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
