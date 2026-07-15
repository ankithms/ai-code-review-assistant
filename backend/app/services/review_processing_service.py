import logging
import os
import re

from app.ai.review_service import review_code
from app.db.database import SessionLocal
from app.db.models import Review
from app.github.github_service import (
    get_pr_files,
    get_pull_request,
    post_inline_comment,
    post_pr_comment,
)
from app.github.summary_formatter import format_review_summary
from app.repositories.review_job_repository import (
    SUCCESS,
    get_review_job,
    mark_review_job_failed,
    mark_review_job_running,
    mark_review_job_success,
)
from app.repositories.review_repository import save_review
from app.schemas.output import PullRequestSchema

logger = logging.getLogger(__name__)


def process_review_job(job_id: int) -> None:
    db = SessionLocal()
    job = None

    try:
        job = get_review_job(db, job_id)

        if job is None:
            logger.error("Review job %s was not found", job_id)
            return

        if job.status == SUCCESS:
            logger.info("Review job %s already completed", job_id)
            return

        mark_review_job_running(db, job)
        logger.info(
            "Started review job %s for %s PR #%s",
            job.id,
            job.repository,
            job.pull_request_number,
        )

        _process_pull_request_review(db, job)

        mark_review_job_success(db, job)
        logger.info("Completed review job %s", job.id)
    except Exception as exc:
        db.rollback()

        if job is not None:
            mark_review_job_failed(db, job, str(exc))

        logger.exception("Review job %s failed", job_id)
        raise
    finally:
        db.close()


def _process_pull_request_review(db, job) -> None:
    token = os.getenv("GITHUB_ACCESS_TOKEN")

    if not token:
        raise RuntimeError("GITHUB_ACCESS_TOKEN is not configured")

    existing_review = (
        db.query(Review)
        .filter(Review.commit_sha == job.commit_sha)
        .first()
    )

    files = get_pr_files(
        repository=job.repository,
        pull_request_number=job.pull_request_number,
        access_token=token,
    )

    if existing_review:
        logger.info(
            "Commit %s already has review %s; retrying GitHub comment posting",
            job.commit_sha,
            existing_review.id,
        )
        _post_github_comments(
            review=existing_review,
            files=files,
            files_reviewed=len(files),
            repository=job.repository,
            pull_request_number=job.pull_request_number,
            commit_sha=job.commit_sha,
            access_token=token,
        )
        return

    pull_request = get_pull_request(
        repository=job.repository,
        pull_request_number=job.pull_request_number,
        access_token=token,
    )

    full_diff = _build_diff(files)
    logger.info("Calling AI review service for job %s", job.id)

    try:
        ai_review = review_code(full_diff)
    except Exception as exc:
        logger.exception("AI review failed for job %s", job.id)
        _post_ai_failure_comment(
            repository=job.repository,
            pull_request_number=job.pull_request_number,
            access_token=token,
            error_message=str(exc),
        )
        raise

    logger.info(
        "AI review for job %s returned %s issues",
        job.id,
        len(ai_review.issues),
    )

    pr_schema = PullRequestSchema(
        github_pr_id=pull_request["id"],
        title=pull_request["title"],
        repository=job.repository,
        author=pull_request["user"]["login"],
    )

    _post_github_comments(
        review=ai_review,
        files=files,
        files_reviewed=len(files),
        repository=job.repository,
        pull_request_number=job.pull_request_number,
        commit_sha=job.commit_sha,
        access_token=token,
    )

    save_review(
        db=db,
        pr_data=pr_schema,
        review_data=ai_review,
        commit_sha=job.commit_sha,
    )


def _build_diff(files: list[dict]) -> str:
    full_diff = ""

    for file in files:
        patch = file.get("patch")

        if patch:
            full_diff += f"\n\nFILE: {file['filename']}\n"
            full_diff += patch

    return full_diff


def _get_file_entry_for_issue(
    files: list[dict],
    file_path: str,
) -> dict | None:
    normalized_request_path = file_path.replace('\\', '/').lstrip('/')

    for file in files:
        filename = file.get("filename")
        if not filename:
            continue
        normalized_filename = filename.replace('\\', '/')

        if normalized_filename == normalized_request_path:
            return file

    for file in files:
        filename = file.get("filename")
        if not filename:
            continue
        normalized_filename = filename.replace('\\', '/')
        if normalized_filename.endswith(normalized_request_path):
            return file

    for file in files:
        filename = file.get("filename")
        if not filename:
            continue
        normalized_filename = filename.replace('\\', '/')
        if normalized_request_path.endswith(normalized_filename):
            return file

    return None


def _get_diff_anchor_for_issue(
    files: list[dict],
    file_path: str,
    line_number: int,
) -> tuple[dict[str, int | str], int | None] | None:
    file_entry = _get_file_entry_for_issue(files, file_path)
    if not file_entry:
        logger.warning(
            "Could not locate file %s in PR file list",
            file_path,
        )
        return None

    patch = file_entry.get("patch")
    if not patch:
        return None

    return _map_new_line_to_diff_anchor(
        patch=patch,
        target_line=line_number,
    )


def _map_new_line_to_diff_anchor(
    patch: str,
    target_line: int,
) -> tuple[dict[str, int | str], int | None] | None:
    hunk_lines: list[dict[str, int | str]] = []
    new_line = 0
    position = 0

    for raw_line in patch.splitlines():
        if raw_line.startswith("@@"):
            anchor = _select_anchor_from_hunk(hunk_lines, target_line)
            if anchor:
                return anchor

            match = re.match(r"@@ -(?P<old_start>\d+)(?:,\d+)? \+(?P<new_start>\d+)(?:,\d+)? @@", raw_line)
            if not match:
                hunk_lines = []
                new_line = 0
                continue

            hunk_lines = []
            new_line = int(match.group("new_start"))
            continue

        if not raw_line:
            continue

        first_char = raw_line[0]

        if first_char == " ":
            position += 1
            hunk_lines.append(
                {
                    "line": new_line,
                    "side": "RIGHT",
                    "content": raw_line[1:],
                    "position": position,
                }
            )
            new_line += 1
        elif first_char == "+":
            position += 1
            hunk_lines.append(
                {
                    "line": new_line,
                    "side": "RIGHT",
                    "content": raw_line[1:],
                    "position": position,
                }
            )
            new_line += 1
        elif first_char == "-":
            position += 1
        else:
            position += 1

    return _select_anchor_from_hunk(hunk_lines, target_line)


def _select_anchor_from_hunk(
    hunk_lines: list[dict[str, int | str]],
    target_line: int,
) -> tuple[dict[str, int | str], int | None] | None:
    for index, hunk_line in enumerate(hunk_lines):
        if hunk_line["line"] != target_line:
            continue

        if str(hunk_line["content"]).strip():
            return (
                {
                    "line": hunk_line["line"],
                    "side": hunk_line["side"],
                },
                int(hunk_line["position"]),
            )

        for nearby_line in reversed(hunk_lines[:index]):
            if str(nearby_line["content"]).strip():
                return (
                    {
                        "start_line": nearby_line["line"],
                        "start_side": nearby_line["side"],
                        "line": hunk_line["line"],
                        "side": hunk_line["side"],
                    },
                    int(nearby_line["position"]),
                )

        for nearby_line in hunk_lines[index + 1:]:
            if str(nearby_line["content"]).strip():
                return (
                    {
                        "start_line": hunk_line["line"],
                        "start_side": hunk_line["side"],
                        "line": nearby_line["line"],
                        "side": nearby_line["side"],
                    },
                    int(nearby_line["position"]),
                )

        return None

    visible_lines = [
        hunk_line
        for hunk_line in hunk_lines
        if str(hunk_line["content"]).strip()
    ]
    if not visible_lines:
        return None

    nearest_line = min(
        visible_lines,
        key=lambda hunk_line: (
            abs(int(hunk_line["line"]) - target_line),
            int(hunk_line["line"]),
        ),
    )
    if abs(int(nearest_line["line"]) - target_line) > 2:
        logger.info(
            "No exact diff line %s found in hunk and the nearest visible line %s is too far away; skipping inline comment",
            target_line,
            nearest_line["line"],
        )
        return None

    logger.info(
        "No exact diff line %s found in hunk; anchoring inline comment to nearest visible line %s",
        target_line,
        nearest_line["line"],
    )
    return (
        {
            "line": nearest_line["line"],
            "side": nearest_line["side"],
        },
        int(nearest_line["position"]),
    )


def _post_github_comments(
    review,
    files: list[dict],
    files_reviewed: int,
    repository: str,
    pull_request_number: int,
    commit_sha: str,
    access_token: str,
) -> None:
    skipped_inline_comments = 0
    failed_inline_comments = 0

    for issue in review.issues:
        logger.info(
            "Processing issue: file=%s line=%s category=%s",
            issue.file,
            issue.line,
            issue.category,
        )

        if not issue.file or not issue.line:
            logger.warning(
                "Skipping issue without file/line: file=%s line=%s",
                issue.file,
                issue.line,
            )
            continue

        anchor_info = _get_diff_anchor_for_issue(
            files=files,
            file_path=issue.file,
            line_number=issue.line,
        )

        file_entry = _get_file_entry_for_issue(files, issue.file)
        actual_file_path = file_entry.get("filename") if file_entry else issue.file
        comment_body = _format_issue_comment_body(issue)

        comment_payload = {
            "repository": repository,
            "pull_request_number": pull_request_number,
            "access_token": access_token,
            "commit_id": commit_sha,
            "file_path": actual_file_path,
            "body": comment_body,
        }

        if anchor_info is None:
            skipped_inline_comments += 1
            logger.warning(
                "Skipping inline comment for %s:%s because the line could not be mapped to the PR diff",
                issue.file,
                issue.line,
            )
            _post_inline_fallback_comment(
                repository=repository,
                pull_request_number=pull_request_number,
                access_token=access_token,
                file_path=actual_file_path,
                line_number=issue.line,
                body=comment_body,
                reason="the line could not be mapped to the PR diff",
            )
            continue

        anchor, fallback_position = anchor_info
        comment_payload.update(anchor)

        logger.info(
            "Posting inline comment payload for %s:%s: %s",
            issue.file,
            issue.line,
            {k: v for k, v in comment_payload.items() if k not in {'access_token', 'body'}},
        )
        try:
            post_inline_comment(**comment_payload)
            logger.info(
                "Posted inline comment for %s:%s anchor=%s",
                issue.file,
                issue.line,
                anchor,
            )
        except Exception as exc:
            logger.warning(
                "Failed to post inline comment for %s:%s with anchor=%s; %s",
                issue.file,
                issue.line,
                anchor,
                exc,
            )
            if fallback_position is not None:
                fallback_payload = {
                    **comment_payload,
                    "position": fallback_position,
                }
                for key in ("line", "side", "start_line", "start_side"):
                    fallback_payload.pop(key, None)

                try:
                    post_inline_comment(**fallback_payload)
                    logger.info(
                        "Posted inline comment for %s:%s using fallback position=%s",
                        issue.file,
                        issue.line,
                        fallback_position,
                    )
                    continue
                except Exception as fallback_exc:
                    logger.warning(
                        "Failed to post inline fallback comment for %s:%s at position=%s; %s",
                        issue.file,
                        issue.line,
                        fallback_position,
                        fallback_exc,
                    )

            failed_inline_comments += 1
            _post_inline_fallback_comment(
                repository=repository,
                pull_request_number=pull_request_number,
                access_token=access_token,
                file_path=actual_file_path,
                line_number=issue.line,
                body=comment_body,
                reason="GitHub rejected the inline comment",
            )

    summary = format_review_summary(
        review=review,
        files_reviewed=files_reviewed,
    )

    post_pr_comment(
        repository=repository,
        pull_request_number=pull_request_number,
        access_token=access_token,
        body=summary,
    )
    logger.info(
        "Posted general review comment; skipped_inline_comments=%s failed_inline_comments=%s",
        skipped_inline_comments,
        failed_inline_comments,
    )


def _enum_value(value) -> str:
    if hasattr(value, "value"):
        return value.value

    return str(value)


def _format_category(category) -> str:
    return _enum_value(category).replace("_", " ").replace("-", " ").title()


def _format_issue_comment_body(issue) -> str:
    return (
        f"**{_enum_value(issue.severity).upper()}** "
        f"[{_format_category(issue.category)}] "
        f"{issue.comment}"
    )


def _post_inline_fallback_comment(
    repository: str,
    pull_request_number: int,
    access_token: str,
    file_path: str,
    line_number: int,
    body: str,
    reason: str,
) -> None:
    post_pr_comment(
        repository=repository,
        pull_request_number=pull_request_number,
        access_token=access_token,
        body=(
            "**AI Review Finding**\n\n"
            f"`{file_path}:{line_number}`\n\n"
            f"{body}\n\n"
            f"_Inline comment unavailable: {reason}._"
        ),
    )


def _post_ai_failure_comment(
    repository: str,
    pull_request_number: int,
    access_token: str,
    error_message: str,
) -> None:
    try:
        post_pr_comment(
            repository=repository,
            pull_request_number=pull_request_number,
            access_token=access_token,
            body=(
                "**AI Review Failed**\n\n"
                "The automated review service could not complete due to an internal error. "
                "Please check the backend logs and the AI provider configuration.\n\n"
                f"Error: {error_message}"
            ),
        )
        logger.info(
            "Posted AI failure summary comment for PR #%s",
            pull_request_number,
        )
    except Exception as exc:
        logger.exception(
            "Failed to post AI failure summary comment for PR #%s",
            pull_request_number,
        )
