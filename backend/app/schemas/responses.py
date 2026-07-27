from datetime import datetime

from pydantic import BaseModel, computed_field

from app.schemas.output import IssueStatus
from app.schemas.fixes import FixCommitResponse, FixPullRequestResponse, IssueFixResponse


class IssueResponse(BaseModel):
    id: int
    severity: str
    category: str
    file: str | None = None
    line: int | None = None
    line_ref: str | None = None
    side: str | None = None
    start_line: int | None = None
    start_side: str | None = None
    old_line: int | None = None
    diff_hunk: str | None = None
    source_commit_sha: str | None = None
    comment: str
    status: IssueStatus
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    fix_status: str
    fix_file_path: str | None = None
    fix_start_line: int | None = None
    fix_end_line: int | None = None
    fix_replacement_code: str | None = None
    fix_explanation: str | None = None
    eligible_for_fix: bool
    fix_pr_number: int | None = None
    fix_pr_url: str | None = None
    fix_commit_sha: str | None = None
    fix_commit_url: str | None = None
    fix_branch: str | None = None
    fix_created_at: datetime | None = None
    fix_merged_at: datetime | None = None
    fix_closed_at: datetime | None = None

    model_config = {
        "from_attributes": True
    }

    @computed_field
    @property
    def fix(self) -> IssueFixResponse | None:
        if not self.fix_file_path:
            return None

        return IssueFixResponse(
            issue_id=self.id,
            status=self.fix_status,
            file_path=self.fix_file_path,
            start_line=self.fix_start_line,
            end_line=self.fix_end_line,
            replacement_code=self.fix_replacement_code,
            explanation=self.fix_explanation,
        )


class ReviewDetailResponse(BaseModel):
    id: int
    pr_id: int
    summary: str
    issues: list[IssueResponse]
    fix_pull_requests: list[FixPullRequestResponse]
    fix_commits: list[FixCommitResponse]

    model_config = {
        "from_attributes": True
    }


class TopProblematicFileResponse(BaseModel):
    file: str
    total_issues: int


class AnalyticsResponse(BaseModel):
    total_ai_reviews: int
    total_reviews: int
    total_pull_requests: int
    total_issues: int
    high_severity: int
    medium_severity: int
    low_severity: int
    open_issues: int
    resolved_issues: int
    ignored_issues: int
    bug_issues: int
    security_issues: int
    performance_issues: int
    readability_issues: int
    edge_case_issues: int
    top_problematic_files: list[TopProblematicFileResponse]
    average_issues_per_pull_request: float
    average_review_processing_time_seconds: float | None


class PullRequestResponse(BaseModel):
    id: int
    github_pr_id: int
    pull_request_number: int | None = None
    title: str
    repository: str
    author: str

    model_config = {
        "from_attributes": True
    }


class ReviewListResponse(BaseModel):
    id: int
    pr_id: int
    summary: str

    model_config = {
        "from_attributes": True
    }


class IssueStatusUpdateRequest(BaseModel):
    status: IssueStatus


class RepositoryResponse(BaseModel):
    id: int
    full_name: str

    model_config = {
        "from_attributes": True
    }
