import json
import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.ai.review_service import AIReviewServiceError
from app.db.models import FixCommit, FixPullRequest, Issue, PullRequest, Repository, Review
from app.github.github_service import post_pr_comment, reply_to_review_comment
from app.repositories.review_repository import get_latest_review_for_pull_request
from app.routes.fixes import (
    _build_preview_response,
    _github_pull_request,
    _preview_file_to_patched_file,
    _validate_issues_eligible_for_fix,
)
from app.schemas.output import FixPullRequestStatus, IssueFixStatus
from app.services.fix_generation_service import FixGenerationService
from app.services.git_commit_service import GitCommitService

logger = logging.getLogger(__name__)

AI_FIX_COMMAND_PATTERN = re.compile(r"^\s*/ai-fix(?:\s+(?P<target>[^\n\r]+))?\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class NativeFixCommand:
    target: str
    issue_id: int | None = None


def handle_github_native_fix_comment(
    db: Session,
    payload: dict,
    event: str | None,
    access_token: str | None,
) -> bool:
    if not access_token:
        logger.warning("Skipping GitHub-native AI fix command because no access token is configured")
        return False

    command = _parse_fix_command(payload)
    if command is None:
        return False

    repository = (payload.get("repository") or {}).get("full_name")
    pull_request_number = _pull_request_number_from_payload(payload, event)
    if not repository or not pull_request_number:
        return False

    response_target = _response_target_from_payload(payload, event)

    try:
        result_message = _run_fix_command(
            db=db,
            repository=repository,
            pull_request_number=pull_request_number,
            command=command,
            access_token=access_token,
            payload=payload,
        )
    except AIReviewServiceError as exc:
        db.rollback()
        logger.warning(
            "GitHub-native AI fix command could not reach the AI provider "
            "retryable=%s: %s",
            exc.retryable,
            exc,
        )
        if exc.retryable:
            result_message = (
                "**AI Fix temporarily unavailable**\n\n"
                "The AI provider is currently busy. No code or branch was changed. "
                "Please run the `/ai-fix` command again later."
            )
        else:
            result_message = (
                "**AI Fix paused**\n\n"
                f"{exc}"
            )
    except Exception as exc:
        logger.exception("GitHub-native AI fix command failed")
        result_message = (
            "**AI Fix failed**\n\n"
            f"{exc}"
        )

    _post_command_response(
        repository=repository,
        pull_request_number=pull_request_number,
        response_target=response_target,
        access_token=access_token,
        body=result_message,
    )
    return True


def _parse_fix_command(payload: dict) -> NativeFixCommand | None:
    comment = payload.get("comment") or {}
    body = comment.get("body") or ""
    match = AI_FIX_COMMAND_PATTERN.match(body)
    if not match:
        return None

    raw_target = (match.group("target") or "").strip()
    if not raw_target:
        return NativeFixCommand(target="reply")

    normalized_target = raw_target.lower()
    if normalized_target in {"all", "open"}:
        return NativeFixCommand(target="all")

    issue_match = re.match(r"(?:issue\s+)?#?(?P<issue_id>\d+)$", normalized_target)
    if issue_match:
        return NativeFixCommand(
            target="issue",
            issue_id=int(issue_match.group("issue_id")),
        )

    raise ValueError("Unsupported AI fix command. Use `/ai-fix`, `/ai-fix all`, or `/ai-fix <issue-id>`.")


def _run_fix_command(
    db: Session,
    repository: str,
    pull_request_number: int,
    command: NativeFixCommand,
    access_token: str,
    payload: dict,
) -> str:
    pull_request_record = _get_pull_request_record(
        db=db,
        repository=repository,
        pull_request_number=pull_request_number,
    )
    if pull_request_record is None:
        raise ValueError("This pull request has not been reviewed by the AI assistant yet.")

    review = get_latest_review_for_pull_request(
        db=db,
        repository_id=pull_request_record.repository_id,
        pull_request_number=pull_request_number,
    )
    if review is None:
        raise ValueError("No AI review was found for this pull request.")

    issues = _select_command_issues(
        db=db,
        review=review,
        command=command,
        payload=payload,
    )
    if not issues:
        raise ValueError("No eligible AI findings were found for this command.")

    _validate_issues_eligible_for_fix(issues)
    pull_request = _github_pull_request(db, review, access_token)
    target_head_sha = pull_request["head"]["sha"]

    FixGenerationService().generate_fixes(
        db=db,
        issues=issues,
        repository=repository,
        target_ref=target_head_sha,
        target_head_sha=target_head_sha,
        access_token=access_token,
    )

    preview = _build_preview_response(
        db=db,
        review=review,
        issues=issues,
        access_token=access_token,
    )
    if not preview.valid:
        errors = "\n".join(f"- {error}" for error in preview.errors)
        raise ValueError(f"Fix preview validation failed. No Fix PR was created.\n\n{errors}")

    commenter = ((payload.get("comment") or {}).get("user") or {}).get("login")
    fix_commit = FixCommit(
        review_id=review.id,
        pull_request_id=review.pull_request.id,
        status="PENDING",
        applied_issue_ids=json.dumps([issue.id for issue in issues]),
        mode="BRANCH_PR",
        created_by=commenter,
    )
    db.add(fix_commit)
    db.flush()

    try:
        result = GitCommitService().create_fix_commit(
            repository=repository,
            base_branch=preview.target_branch,
            expected_head_sha=preview.target_head_sha,
            patched_files=[
                _preview_file_to_patched_file(file)
                for file in preview.files
                if file.valid and file.patched_content is not None
            ],
            access_token=access_token,
            pull_request_number=pull_request_number,
            mode="BRANCH_PR",
        )
    except Exception as exc:
        fix_commit.status = "FAILED"
        fix_commit.error_message = str(exc)
        db.commit()
        raise

    fix_commit.status = "SUCCESS"
    fix_commit.github_commit_sha = result.commit_sha
    fix_commit.branch_name = result.branch_name
    fix_commit.pull_request_url = result.pull_request_url

    fix_pull_request = FixPullRequest(
        repository_id=review.pull_request.repository_id,
        review_id=review.id,
        original_pull_request_id=review.pull_request.id,
        original_pr_number=pull_request_number,
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
        issue.fix_status = IssueFixStatus.FIX_PR_CREATED.value
        db.add(issue)

    db.commit()

    return (
        "**AI Fix PR created**\n\n"
        f"Created Fix PR: {result.pull_request_url}\n\n"
        f"Included issues: {', '.join(f'#{issue.id}' for issue in issues)}"
    )


def _select_command_issues(
    db: Session,
    review: Review,
    command: NativeFixCommand,
    payload: dict,
) -> list[Issue]:
    if command.target == "all":
        return [issue for issue in review.issues if issue.eligible_for_fix]

    if command.target == "issue" and command.issue_id is not None:
        issue = (
            db.query(Issue)
            .join(Review)
            .join(PullRequest)
            .options(joinedload(Issue.fix_pull_requests))
            .filter(
                Issue.id == command.issue_id,
                PullRequest.id == review.pr_id,
            )
            .one_or_none()
        )
        return [issue] if issue is not None and issue.eligible_for_fix else []

    parent_comment_id = (payload.get("comment") or {}).get("in_reply_to_id")
    if parent_comment_id is None:
        raise ValueError("Reply `/ai-fix` to an AI review comment, or use `/ai-fix all`.")

    issue = (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .options(joinedload(Issue.fix_pull_requests))
        .filter(
            Issue.github_comment_id == parent_comment_id,
            PullRequest.id == review.pr_id,
        )
        .one_or_none()
    )
    if issue is not None and issue.eligible_for_fix:
        return [issue]

    issue = _find_issue_by_comment_location(review, payload)
    return [issue] if issue is not None and issue.eligible_for_fix else []


def _find_issue_by_comment_location(review: Review, payload: dict) -> Issue | None:
    comment = payload.get("comment") or {}
    comment_path = _normalize_path(comment.get("path"))
    comment_line = comment.get("line") or comment.get("original_line")
    if not comment_path or comment_line is None:
        return None

    matching_issues = [
        issue
        for issue in review.issues
        if (
            issue.eligible_for_fix
            and _normalize_path(issue.file) == comment_path
            and issue.line is not None
        )
    ]
    if not matching_issues:
        return None

    nearest_issue = min(
        matching_issues,
        key=lambda issue: abs(int(issue.line) - int(comment_line)),
    )
    if abs(int(nearest_issue.line) - int(comment_line)) > 3:
        return None

    return nearest_issue


def _get_pull_request_record(
    db: Session,
    repository: str,
    pull_request_number: int,
) -> PullRequest | None:
    return (
        db.query(PullRequest)
        .join(Repository)
        .filter(
            Repository.full_name == repository,
            PullRequest.pull_request_number == pull_request_number,
        )
        .one_or_none()
    )


def _pull_request_number_from_payload(payload: dict, event: str | None) -> int | None:
    if event == "issue_comment":
        issue = payload.get("issue") or {}
        if not issue.get("pull_request"):
            return None
        return issue.get("number")

    pull_request = payload.get("pull_request") or {}
    return pull_request.get("number")


def _response_target_from_payload(payload: dict, event: str | None) -> dict:
    comment = payload.get("comment") or {}
    if event == "pull_request_review_comment":
        return {
            "kind": "review_reply",
            "parent_comment_id": comment.get("in_reply_to_id") or comment.get("id"),
        }

    return {"kind": "pr_comment"}


def _post_command_response(
    repository: str,
    pull_request_number: int,
    response_target: dict,
    access_token: str,
    body: str,
) -> None:
    if response_target.get("kind") == "review_reply" and response_target.get("parent_comment_id"):
        try:
            reply_to_review_comment(
                repository=repository,
                pull_request_number=pull_request_number,
                parent_comment_id=response_target["parent_comment_id"],
                access_token=access_token,
                body=body,
            )
            return
        except Exception:
            logger.exception(
                "Failed to reply to GitHub review comment %s; falling back to PR comment",
                response_target["parent_comment_id"],
            )

    post_pr_comment(
        repository=repository,
        pull_request_number=pull_request_number,
        access_token=access_token,
        body=body,
    )


def _normalize_path(file_path: str | None) -> str:
    if not file_path:
        return ""

    return file_path.replace("\\", "/").lstrip("/")
