import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session, joinedload

from app.ai.review_service import AIReviewServiceError
from app.db.models import FixCommit, Issue, PullRequest, Repository, Review
from app.github.github_service import post_pr_comment, reply_to_review_comment
from app.repositories.review_repository import get_latest_review_for_pull_request
from app.routes.fixes import (
    _build_commit_message,
    _build_preview_response,
    _github_pull_request,
    _preview_file_to_patched_file,
    _validate_issues_eligible_for_fix,
)
from app.schemas.output import FixCommitStatus
from app.services.fix_commit_tracking_service import (
    FixCommitAlreadyClaimedError,
    FixCommitTrackingService,
)
from app.services.fix_generation_service import FixGenerationService
from app.services.git_commit_service import GitCommitService, StaleHeadError

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

    if not AI_FIX_COMMAND_PATTERN.match(((payload.get("comment") or {}).get("body") or "")):
        return False

    repository = (payload.get("repository") or {}).get("full_name")
    pull_request_number = _pull_request_number_from_payload(payload, event)
    if not repository or not pull_request_number:
        return False

    response_target = _response_target_from_payload(payload, event)
    request_key = _request_key_from_payload(payload, event)

    try:
        command = _parse_fix_command(payload)
        if command is None:
            return False
        result_message = _run_fix_command(
            db=db,
            repository=repository,
            pull_request_number=pull_request_number,
            command=command,
            access_token=access_token,
            payload=payload,
            request_key=request_key,
        )
    except AIReviewServiceError as exc:
        db.rollback()
        logger.warning(
            "GitHub-native AI fix command failed error_type=%s retryable=%s: %s",
            exc.error_type,
            exc.retryable,
            exc,
        )
        result_message = _ai_failure_message(exc)
    except (ValueError, StaleHeadError) as exc:
        db.rollback()
        result_message = f"**AI Fix paused**\n\n{exc}"
    except Exception as exc:
        db.rollback()
        logger.exception("GitHub-native AI fix command failed")
        result_message = (
            "**AI Fix failed**\n\n"
            "An internal error prevented this command from completing. Check the worker "
            "logs and confirm whether GitHub accepted a commit before retrying."
        )

    _post_command_response(
        repository=repository,
        pull_request_number=pull_request_number,
        response_target=response_target,
        access_token=access_token,
        body=result_message,
    )
    return True


def is_github_native_fix_comment(payload: dict, event: str | None) -> bool:
    """Validate the cheap, local parts of a command before enqueueing it."""
    comment = payload.get("comment") or {}
    if not AI_FIX_COMMAND_PATTERN.match(comment.get("body") or ""):
        return False
    repository = (payload.get("repository") or {}).get("full_name")
    return bool(repository and _pull_request_number_from_payload(payload, event))


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
    request_key: str | None = None,
) -> str:
    pull_request_record = _get_pull_request_record(
        db=db,
        repository=repository,
        pull_request_number=pull_request_number,
    )
    if pull_request_record is None:
        raise ValueError("This pull request has not been reviewed by the AI assistant yet.")

    if request_key:
        duplicate = (
            db.query(FixCommit)
            .filter(FixCommit.request_key == request_key)
            .one_or_none()
        )
        if duplicate is not None:
            return _existing_request_message(duplicate)

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
    GitCommitService().validate_direct_commit_target(
        repository=repository,
        pull_request=pull_request,
        access_token=access_token,
    )
    target_head_sha = pull_request["head"]["sha"]
    commenter = ((payload.get("comment") or {}).get("user") or {}).get("login")
    tracking = FixCommitTrackingService()
    fix_commit, created = tracking.create_or_get(
        db,
        repository_id=pull_request_record.repository_id,
        pull_request_id=pull_request_record.id,
        review_id=review.id,
        issues=issues,
        source_head_sha=target_head_sha,
        source_branch=pull_request["head"]["ref"],
        requested_by=commenter,
        request_key=request_key,
        # Posting a new command is an explicit user retry. The tracking service
        # still deduplicates active/successful requests, but creates a new attempt
        # when the latest identical request is FAILED or STALE.
        retry=True,
    )
    if not created:
        return _existing_request_message(fix_commit)
    tracking.transition(db, fix_commit, FixCommitStatus.GENERATING)

    try:
        FixGenerationService().generate_fixes(
            db=db,
            issues=issues,
            repository=repository,
            target_ref=target_head_sha,
            target_head_sha=target_head_sha,
            access_token=access_token,
            pull_request=pull_request,
        )
    except Exception as exc:
        db.rollback()
        tracking.mark_failed(db, fix_commit, "Fix generation failed")
        raise
    tracking.mark_generated(db, fix_commit, issues)
    tracking.mark_validating(db, fix_commit)

    preview = _build_preview_response(
        db=db,
        review=review,
        issues=issues,
        access_token=access_token,
    )
    tracking.record_validation(db, fix_commit, preview)
    if not preview.valid:
        tracking.mark_failed(db, fix_commit, "No selected fix passed validation")
        errors = "\n".join(f"- {error}" for error in preview.errors)
        raise ValueError(f"Fix preview validation failed. No commit was created.\n\n{errors}")

    included_ids = set(preview.included_issue_ids)
    included_issues = [issue for issue in issues if issue.id in included_ids]
    if not included_issues:
        tracking.mark_failed(db, fix_commit, "No selected fix passed validation")
        raise ValueError("No selected fix passed validation. No commit was created.")

    commit_message = _build_commit_message(included_issues)
    pull_request = _github_pull_request(db, review, access_token)
    if pull_request["head"]["sha"] != fix_commit.source_head_sha:
        tracking.mark_stale(db, fix_commit)
        raise StaleHeadError("Pull Request changed during fix generation")
    try:
        tracking.mark_committing(db, fix_commit, commit_message)
    except FixCommitAlreadyClaimedError:
        return f"**This AI fix request is already being tracked:** `{fix_commit.status}`"

    try:
        result = GitCommitService().create_fix_commit(
            repository=repository,
            pull_request=pull_request,
            expected_head_sha=preview.target_head_sha,
            patched_files=[
                _preview_file_to_patched_file(file)
                for file in preview.files
                if file.valid and file.patched_content is not None
            ],
            access_token=access_token,
            commit_message=commit_message,
        )
    except StaleHeadError:
        tracking.mark_stale(db, fix_commit)
        raise
    except Exception as exc:
        tracking.mark_failed(db, fix_commit, str(exc))
        raise

    fix_commit.pull_request_url = pull_request.get("html_url")
    try:
        tracking.mark_committed(db, fix_commit, result)
    except Exception:
        logger.exception(
            "GitHub-native AI fix commit was pushed but lifecycle persistence failed: %s",
            result.commit_sha,
        )
        tracking.recover_after_push(
            db,
            fix_commit_id=fix_commit.id,
            result=result,
        )

    return (
        "**AI fixes committed to this Pull Request**\n\n"
        f"Commit: [{result.commit_sha[:7]}]({result.commit_url})\n\n"
        f"Message: `{commit_message.splitlines()[0]}`\n\n"
        f"Included issues: {', '.join(f'#{issue.id}' for issue in included_issues)}"
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


def _request_key_from_payload(payload: dict, event: str | None) -> str | None:
    repository = (payload.get("repository") or {}).get("full_name")
    comment_id = (payload.get("comment") or {}).get("id")
    if not repository or comment_id is None:
        return None
    return f"github:{repository}:{event or 'comment'}:{comment_id}"


def _existing_request_message(fix_commit: FixCommit) -> str:
    if fix_commit.generated_commit_sha:
        return (
            "**This AI fix request was already committed**\n\n"
            f"Commit: [{fix_commit.generated_commit_sha[:7]}]"
            f"({fix_commit.generated_commit_url})"
        )
    return f"**This AI fix request is already being tracked:** `{fix_commit.status}`"


def _ai_failure_message(exc: AIReviewServiceError) -> str:
    unchanged = "No code or branch was changed by this attempt."
    if exc.error_type == "timeout":
        return f"**AI Fix timed out**\n\n{exc} {unchanged}"
    if exc.error_type == "rate_limit":
        return f"**AI Fix rate limited**\n\n{exc} {unchanged}"
    if exc.error_type == "quota":
        return f"**AI Fix quota exhausted**\n\n{exc} {unchanged}"
    if exc.error_type == "capacity":
        return f"**AI Fix provider unavailable**\n\n{exc} {unchanged}"
    return (
        "**AI Fix failed**\n\n"
        "An internal error prevented the AI request from completing. "
        f"{unchanged} Check the worker logs before retrying."
    )


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
