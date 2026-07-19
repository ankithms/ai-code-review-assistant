from pydantic import BaseModel

from app.schemas.output import IssueStatus


class IssueResponse(BaseModel):
    id: int
    severity: str
    category: str
    file: str | None = None
    comment: str
    status: IssueStatus

    model_config = {
        "from_attributes": True
    }


class ReviewDetailResponse(BaseModel):
    id: int
    pr_id: int
    summary: str
    issues: list[IssueResponse]

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
