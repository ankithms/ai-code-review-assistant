import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import FixCommit, FixPullRequest, Issue, PullRequest, ReviewJob
from app.db.session import get_db
from app.github.github_service import get_file_content, get_pull_request
from app.repositories.review_repository import get_review_by_id_for_repository
from app.schemas.fixes import (
    FixApplyMode,
    FixApplyRequest,
    FixCommitResponse,
    FixGenerateRequest,
    FixGenerateResponse,
    FixPreviewFileResponse,
    FixPreviewRequest,
    FixPreviewResponse,
    IssueFixResponse,
)
from app.schemas.output import FixPullRequestStatus, IssueFixStatus
from app.services.fix_generation_service import FixGenerationService
from app.services.git_commit_service import GitCommitService
from app.services.patch_service import PatchEdit, PatchService
from app.services.validation_service import ValidationService

router = APIRouter(
    prefix="/repositories/{repository_id}/reviews/{review_id}/fixes",
    tags=["fixes"],
)
logger = logging.getLogger(__name__)


@router.post(
    "/generate",
    response_model=FixGenerateResponse,
)
def generate_review_fixes(
    repository_id: int,
    review_id: int,
    request: FixGenerateRequest,
    db: Session = Depends(get_db),
):
    token = _github_token()
    review = _get_review_or_404(db, repository_id, review_id)
    pull_request = _github_pull_request(db, review, token)
    issues = _select_issues(review, request.issue_ids)
    _validate_issues_eligible_for_fix(issues)

    FixGenerationService().generate_fixes(
        db=db,
        issues=issues,
        repository=review.pull_request.repository,
        target_ref=pull_request["head"]["sha"],
        target_head_sha=pull_request["head"]["sha"],
        access_token=token,
    )

    return FixGenerateResponse(
        review_id=review.id,
        target_head_sha=pull_request["head"]["sha"],
        fixes=[_issue_fix_response(issue) for issue in issues],
    )


@router.post(
    "/preview",
    response_model=FixPreviewResponse,
)
def preview_review_fixes(
    repository_id: int,
    review_id: int,
    request: FixPreviewRequest,
    db: Session = Depends(get_db),
):
    token = _github_token()
    review = _get_review_or_404(db, repository_id, review_id)
    issues = _select_issues(review, request.issue_ids)
    _validate_issues_eligible_for_fix(issues)

    return _build_preview_response(
        db=db,
        review=review,
        issues=issues,
        access_token=token,
    )


@router.post(
    "/apply",
    response_model=FixCommitResponse,
)
def apply_review_fixes(
    repository_id: int,
    review_id: int,
    request: FixApplyRequest,
    db: Session = Depends(get_db),
):
    if not request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Explicit confirmation is required before creating a branch, commit, or pull request.",
        )

    if request.mode == FixApplyMode.DIRECT and not request.confirm_direct_commit:
        raise HTTPException(
            status_code=400,
            detail="Direct commits require confirm_direct_commit=true.",
        )

    token = _github_token()
    review = _get_review_or_404(db, repository_id, review_id)
    issues = _select_issues(review, request.issue_ids)
    _validate_issues_eligible_for_fix(issues)
    preview = _build_preview_response(
        db=db,
        review=review,
        issues=issues,
        access_token=token,
    )

    if not preview.valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Fix preview validation failed. No commit was created.",
                "errors": preview.errors,
            },
        )

    fix_commit = FixCommit(
        review_id=review.id,
        pull_request_id=review.pull_request.id,
        status="PENDING",
        applied_issue_ids=json.dumps([issue.id for issue in issues]),
        mode=request.mode.value,
    )
    db.add(fix_commit)
    db.flush()

    try:
        result = GitCommitService().create_fix_commit(
            repository=review.pull_request.repository,
            base_branch=preview.target_branch,
            expected_head_sha=preview.target_head_sha,
            patched_files=[
                _preview_file_to_patched_file(file)
                for file in preview.files
                if file.valid and file.patched_content is not None
            ],
            access_token=token,
            pull_request_number=review.pull_request.pull_request_number,
            mode=request.mode.value,
        )
    except Exception as exc:
        fix_commit.status = "FAILED"
        fix_commit.error_message = str(exc)
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    fix_commit.status = "SUCCESS"
    fix_commit.github_commit_sha = result.commit_sha
    fix_commit.branch_name = result.branch_name
    fix_commit.pull_request_url = result.pull_request_url

    if request.mode == FixApplyMode.BRANCH_PR:
        fix_pull_request = FixPullRequest(
            repository_id=review.pull_request.repository_id,
            review_id=review.id,
            original_pull_request_id=review.pull_request.id,
            original_pr_number=review.pull_request.pull_request_number,
            source_commit_sha=preview.target_head_sha,
            fix_branch=result.branch_name,
            github_pr_number=result.pull_request_number,
            github_pr_url=result.pull_request_url,
            github_commit_sha=result.commit_sha,
            github_commit_url=result.commit_url,
            status=FixPullRequestStatus.PR_CREATED.value,
            issues=issues,
        )
        db.add(fix_pull_request)

    for issue in issues:
        issue.fix_status = (
            IssueFixStatus.FIX_PR_CREATED.value
            if request.mode == FixApplyMode.BRANCH_PR
            else IssueFixStatus.FIX_COMMITTED.value
        )
        db.add(issue)

    try:
        db.commit()
    except Exception:
        logger.exception(
            "GitHub Fix PR was created but database tracking persistence failed: pr=%s branch=%s commit=%s issues=%s",
            result.pull_request_number,
            result.branch_name,
            result.commit_sha,
            [issue.id for issue in issues],
        )
        db.rollback()
        raise
    db.refresh(fix_commit)

    return _fix_commit_response(fix_commit)


def _github_token() -> str:
    token = os.getenv("GITHUB_ACCESS_TOKEN")
    if not token:
        raise HTTPException(
            status_code=500,
            detail="GITHUB_ACCESS_TOKEN is not configured",
        )

    return token


def _get_review_or_404(
    db: Session,
    repository_id: int,
    review_id: int,
):
    review = get_review_by_id_for_repository(
        db=db,
        review_id=review_id,
        repository_id=repository_id,
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found")

    return review


def _github_pull_request(db: Session, review, access_token: str) -> dict:
    pull_request: PullRequest = review.pull_request
    pull_request_number = pull_request.pull_request_number
    if pull_request_number is None:
        pull_request_number = _backfill_pull_request_number(db, review)

    if pull_request_number is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Pull request number is missing for this review. "
                "Re-run the review from a GitHub webhook or backfill pull_request_number "
                "before generating fixes."
            ),
        )

    return get_pull_request(
        repository=pull_request.repository,
        pull_request_number=pull_request_number,
        access_token=access_token,
    )


def _backfill_pull_request_number(db: Session, review) -> int | None:
    pull_request: PullRequest = review.pull_request
    review_job = (
        db.query(ReviewJob)
        .filter(
            ReviewJob.repository == pull_request.repository,
            ReviewJob.commit_sha == review.commit_sha,
        )
        .order_by(ReviewJob.id.desc())
        .first()
    )
    if review_job is None:
        return None

    pull_request.pull_request_number = review_job.pull_request_number
    db.add(pull_request)
    db.commit()
    db.refresh(pull_request)
    return pull_request.pull_request_number


def _select_issues(review, issue_ids: list[int] | None) -> list[Issue]:
    issues = list(review.issues)
    if issue_ids:
        wanted_ids = set(issue_ids)
        issues = [issue for issue in issues if issue.id in wanted_ids]
        found_ids = {issue.id for issue in issues}
        missing_ids = wanted_ids - found_ids
        if missing_ids:
            raise HTTPException(
                status_code=404,
                detail=f"Issues not found in this review: {sorted(missing_ids)}",
            )

    if not issues:
        raise HTTPException(status_code=400, detail="No issues selected")

    return issues


def _validate_issues_eligible_for_fix(issues: list[Issue]) -> None:
    for issue in issues:
        blocking_fix_pull_request = issue.blocking_fix_pull_request
        if blocking_fix_pull_request:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Issue {issue.id} is already included in "
                    f"Fix PR #{blocking_fix_pull_request.github_pr_number}."
                ),
            )


def _build_preview_response(
    db: Session,
    review,
    issues: list[Issue],
    access_token: str,
) -> FixPreviewResponse:
    pull_request = _github_pull_request(db, review, access_token)
    target_branch = pull_request["head"]["ref"]
    target_head_sha = pull_request["head"]["sha"]
    errors = []
    edits = []
    file_contents = {}
    fixes = []

    for issue in issues:
        fixes.append(_issue_fix_response(issue))
        if not _issue_has_generated_fix(issue):
            errors.append(f"Issue {issue.id} does not have a generated fix")
            continue

        if not issue.fix_base_commit_sha or not issue.fix_file_sha:
            errors.append(f"Issue {issue.id} fix must be generated against the current branch before preview")
            continue

        if issue.fix_base_commit_sha and issue.fix_base_commit_sha != target_head_sha:
            errors.append(f"Issue {issue.id} fix was generated for an older branch HEAD")
            continue

        if issue.fix_file_path not in file_contents:
            file_contents[issue.fix_file_path] = get_file_content(
                repository=review.pull_request.repository,
                file_path=issue.fix_file_path,
                ref=target_head_sha,
                access_token=access_token,
            )

        file_content = file_contents[issue.fix_file_path]
        if issue.fix_file_sha and issue.fix_file_sha != file_content["sha"]:
            errors.append(f"{issue.fix_file_path} changed after fix generation")
            continue

        edits.append(
            PatchEdit(
                file_path=issue.fix_file_path,
                start_line=issue.fix_start_line,
                end_line=issue.fix_end_line,
                replacement_code=issue.fix_replacement_code,
                expected_file_sha=issue.fix_file_sha,
            )
        )

    preview_files = []
    try:
        patched_files = PatchService().build_patched_files(
            file_contents=file_contents,
            edits=edits,
        )
    except ValueError as exc:
        errors.append(str(exc))
        patched_files = []

    validation_service = ValidationService()
    for patched_file in patched_files:
        validation_errors = validation_service.validate_file(
            file_path=patched_file.file_path,
            content=patched_file.patched_content,
        )
        preview_files.append(
            FixPreviewFileResponse(
                file_path=patched_file.file_path,
                original_sha=patched_file.original_sha,
                valid=not validation_errors,
                errors=validation_errors,
                patched_content=patched_file.patched_content,
            )
        )
        errors.extend(validation_errors)

    return FixPreviewResponse(
        review_id=review.id,
        target_branch=target_branch,
        target_head_sha=target_head_sha,
        valid=not errors,
        errors=errors,
        files=preview_files,
        fixes=fixes,
    )


def _issue_has_generated_fix(issue: Issue) -> bool:
    return bool(
        issue.fix_file_path
        and issue.fix_start_line
        and issue.fix_end_line
        and issue.fix_replacement_code is not None
    )


def _issue_fix_response(issue: Issue) -> IssueFixResponse:
    return IssueFixResponse(
        issue_id=issue.id,
        status=issue.fix_status,
        file_path=issue.fix_file_path,
        start_line=issue.fix_start_line,
        end_line=issue.fix_end_line,
        replacement_code=issue.fix_replacement_code,
        explanation=issue.fix_explanation,
    )


def _preview_file_to_patched_file(file: FixPreviewFileResponse):
    from app.services.patch_service import PatchedFile

    return PatchedFile(
        file_path=file.file_path,
        original_sha=file.original_sha,
        patched_content=file.patched_content or "",
    )


def _fix_commit_response(fix_commit: FixCommit) -> FixCommitResponse:
    return FixCommitResponse(
        id=fix_commit.id,
        status=fix_commit.status,
        mode=fix_commit.mode,
        branch_name=fix_commit.branch_name,
        github_commit_sha=fix_commit.github_commit_sha,
        pull_request_url=fix_commit.pull_request_url,
        applied_issue_ids=json.loads(fix_commit.applied_issue_ids),
        created_at=fix_commit.created_at,
        error_message=fix_commit.error_message,
    )
