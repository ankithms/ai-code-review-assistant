import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.ai.review_service import AIReviewServiceError
from app.db.models import FixCommit, Issue, PullRequest, ReviewJob
from app.db.session import get_db
from app.github.github_service import get_file_content, get_pull_request
from app.repositories.review_repository import get_review_by_id_for_repository
from app.schemas.fixes import (
    AdditionalEditResponse,
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
from app.schemas.output import IssueFixStatus
from app.services.fix_generation_service import FixGenerationService
from app.services.git_commit_service import DirectCommitError, GitCommitService
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
    _ensure_direct_commit_allowed(
        repository=review.pull_request.repository,
        pull_request=pull_request,
        access_token=token,
    )
    issues = _select_issues(review, request.issue_ids)
    _validate_issues_eligible_for_fix(issues)

    try:
        FixGenerationService().generate_fixes(
            db=db,
            issues=issues,
            repository=review.pull_request.repository,
            target_ref=pull_request["head"]["sha"],
            target_head_sha=pull_request["head"]["sha"],
            access_token=token,
            pull_request=pull_request,
        )
    except AIReviewServiceError as exc:
        db.rollback()
        headers = (
            {"Retry-After": str(exc.retry_after_seconds)}
            if exc.retry_after_seconds is not None
            else None
        )
        raise HTTPException(
            status_code=503 if exc.retryable else 429,
            detail=str(exc),
            headers=headers,
        ) from exc

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
    pull_request = _github_pull_request(db, review, token)
    _ensure_direct_commit_allowed(
        repository=review.pull_request.repository,
        pull_request=pull_request,
        access_token=token,
    )
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
            detail="Explicit confirmation is required before committing to the pull request branch.",
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

    if not preview.valid or not preview.included_issue_ids:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "No selected fix passed validation. No commit was created.",
                "errors": preview.errors,
            },
        )

    included_issue_ids = set(preview.included_issue_ids)
    included_issues = [issue for issue in issues if issue.id in included_issue_ids]
    pull_request = _github_pull_request(db, review, token)
    commit_message = _build_commit_message(included_issues)
    fix_commit = FixCommit(
        review_id=review.id,
        pull_request_id=review.pull_request.id,
        status="PENDING",
        applied_issue_ids=json.dumps([issue.id for issue in included_issues]),
        mode=FixApplyMode.DIRECT.value,
        created_by="AI Code Review Assistant",
        source_head_sha=preview.target_head_sha,
        commit_message=commit_message,
        validation_status="PASSED",
        issues=included_issues,
    )
    db.add(fix_commit)
    db.commit()
    db.refresh(fix_commit)

    try:
        result = GitCommitService().create_fix_commit(
            repository=review.pull_request.repository,
            pull_request=pull_request,
            expected_head_sha=preview.target_head_sha,
            patched_files=[
                _preview_file_to_patched_file(file)
                for file in preview.files
                if file.valid and file.patched_content is not None
            ],
            access_token=token,
            commit_message=commit_message,
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
    fix_commit.github_commit_url = result.commit_url
    fix_commit.branch_name = result.branch_name
    fix_commit.pull_request_url = pull_request.get("html_url")

    for issue in included_issues:
        issue.fix_status = IssueFixStatus.FIX_COMMITTED.value
        db.add(issue)

    try:
        db.commit()
    except Exception:
        logger.exception(
            "GitHub AI fix commit was created but database tracking persistence failed: branch=%s commit=%s issues=%s",
            result.branch_name,
            result.commit_sha,
            [issue.id for issue in included_issues],
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


def _ensure_direct_commit_allowed(
    repository: str,
    pull_request: dict,
    access_token: str,
) -> None:
    try:
        GitCommitService().validate_direct_commit_target(
            repository=repository,
            pull_request=pull_request,
            access_token=access_token,
        )
    except DirectCommitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
        if getattr(issue, "fix_status", None) == IssueFixStatus.FIX_COMMITTED.value:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Issue {issue.id} already has an AI fix commit. "
                    "Wait for the synchronize review before generating another fix."
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
    accepted_edits = []
    included_issue_ids = []
    excluded_issue_ids = []
    file_contents = {}
    fixes = []

    for issue in issues:
        fixes.append(_issue_fix_response(issue))
        issue_errors = []
        if not _issue_has_generated_fix(issue):
            issue_errors.append("does not have a generated fix")

        if not issue_errors and (not issue.fix_base_commit_sha or not issue.fix_file_sha):
            issue_errors.append("fix must be generated against the current branch before preview")

        if not issue_errors and issue.fix_base_commit_sha != target_head_sha:
            issue_errors.append("fix was generated for an older branch HEAD")

        if not issue_errors and issue.fix_file_path not in file_contents:
            try:
                file_contents[issue.fix_file_path] = get_file_content(
                    repository=review.pull_request.repository,
                    file_path=issue.fix_file_path,
                    ref=target_head_sha,
                    access_token=access_token,
                )
            except Exception as exc:
                issue_errors.append(f"could not fetch {issue.fix_file_path}: {exc}")

        file_content = file_contents.get(issue.fix_file_path)
        if not issue_errors and issue.fix_file_sha != file_content["sha"]:
            issue_errors.append(f"{issue.fix_file_path} changed after fix generation")

        issue_edits = [] if issue_errors else [_primary_patch_edit(issue)]
        for additional_edit in _additional_fix_edits(issue) if not issue_errors else []:
            if additional_edit.file_path not in file_contents:
                try:
                    file_contents[additional_edit.file_path] = get_file_content(
                        repository=review.pull_request.repository,
                        file_path=additional_edit.file_path,
                        ref=target_head_sha,
                        access_token=access_token,
                    )
                except Exception as exc:
                    issue_errors.append(
                        f"{additional_edit.file_path} could not be fetched for additional fix edit: {exc}"
                    )
                    continue

            original_code = _extract_line_range(
                file_contents[additional_edit.file_path]["content"],
                additional_edit.start_line,
                additional_edit.end_line,
            )
            if (
                additional_edit.original_code is not None
                and additional_edit.original_code.strip("\n") != original_code.strip("\n")
            ):
                issue_errors.append(
                    f"{additional_edit.file_path} changed after additional fix generation"
                )
                continue

            issue_edits.append(
                PatchEdit(
                    file_path=additional_edit.file_path,
                    start_line=additional_edit.start_line,
                    end_line=additional_edit.end_line,
                    replacement_code=additional_edit.replacement_code,
                )
            )

        if not issue_errors:
            try:
                candidate_files = PatchService().build_patched_files(
                    file_contents=file_contents,
                    edits=[*accepted_edits, *issue_edits],
                )
                validation_service = ValidationService()
                for candidate_file in candidate_files:
                    issue_errors.extend(
                        validation_service.validate_file(
                            file_path=candidate_file.file_path,
                            content=candidate_file.patched_content,
                        )
                    )
            except ValueError as exc:
                issue_errors.append(str(exc))

        if issue_errors:
            excluded_issue_ids.append(issue.id)
            errors.extend(f"Issue {issue.id} excluded: {error}" for error in issue_errors)
            continue

        accepted_edits.extend(issue_edits)
        included_issue_ids.append(issue.id)

    preview_files = []
    try:
        patched_files = PatchService().build_patched_files(
            file_contents=file_contents,
            edits=accepted_edits,
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
        valid=bool(included_issue_ids) and not any(file.errors for file in preview_files),
        errors=errors,
        files=preview_files,
        fixes=fixes,
        included_issue_ids=included_issue_ids,
        excluded_issue_ids=excluded_issue_ids,
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
        additional_edits=_additional_fix_edits(issue),
    )


def _primary_patch_edit(issue: Issue) -> PatchEdit:
    return PatchEdit(
        file_path=issue.fix_file_path,
        start_line=issue.fix_start_line,
        end_line=issue.fix_end_line,
        replacement_code=issue.fix_replacement_code,
        expected_file_sha=issue.fix_file_sha,
    )


def _additional_fix_edits(issue: Issue) -> list[AdditionalEditResponse]:
    raw_edits = getattr(issue, "fix_additional_edits", None)
    if not raw_edits:
        return []
    try:
        payload = json.loads(raw_edits)
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    edits = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            edits.append(AdditionalEditResponse(**item))
        except ValueError:
            continue
    return edits


def _extract_line_range(
    file_content: str,
    start_line: int,
    end_line: int,
) -> str:
    lines = file_content.splitlines()
    if start_line < 1 or end_line > len(lines) or end_line < start_line:
        return ""
    return "\n".join(lines[start_line - 1:end_line])


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
        github_commit_url=fix_commit.github_commit_url,
        commit_message=fix_commit.commit_message,
        author=fix_commit.created_by,
        repository=fix_commit.repository,
        pull_request_number=fix_commit.pull_request_number,
        validation_status=fix_commit.validation_status,
        pull_request_url=fix_commit.pull_request_url,
        applied_issue_ids=json.loads(fix_commit.applied_issue_ids),
        created_at=fix_commit.created_at,
        error_message=fix_commit.error_message,
    )


def _build_commit_message(issues: list[Issue]) -> str:
    if len(issues) == 1:
        subject = f"fix(ai): resolve {_issue_commit_label(issues[0])}"
    else:
        subject = f"fix(ai): resolve {len(issues)} review findings"

    addresses = "\n".join(f"- {_issue_commit_label(issue)}" for issue in issues)
    return (
        f"{subject}\n\n"
        "Generated by AI Code Review Assistant.\n\n"
        f"Addresses:\n{addresses}"
    )


def _issue_commit_label(issue: Issue) -> str:
    comment = (getattr(issue, "comment", None) or "review finding").strip()
    first_line = comment.splitlines()[0].strip().lstrip("#*- ")
    for marker in ("Impact:", "Suggested fix:", "Fix:"):
        first_line = first_line.split(marker, 1)[0].strip()
    first_sentence = first_line.split(". ", 1)[0].rstrip(".")
    if len(first_sentence) > 60:
        first_sentence = first_sentence[:57].rstrip() + "..."
    return first_sentence.lower() or "review finding"
