import logging
import os
import re
from types import SimpleNamespace

from app.ai.review_service import review_code
from app.db.database import SessionLocal
from app.db.models import PullRequest, Review
from app.github.github_service import (
    get_review_thread_for_comment,
    get_compare_files,
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
from app.repositories.repository_repository import get_or_create_repository
from app.repositories.review_repository import (
    get_latest_review_for_pull_request,
    get_open_issues_for_pull_request,
    save_review,
)
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

    files = _get_files_for_review(job, token)

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

    pr_schema = PullRequestSchema(
        github_pr_id=pull_request["id"],
        pull_request_number=job.pull_request_number,
        title=pull_request["title"],
        repository=job.repository,
        author=pull_request["user"]["login"],
    )
    pull_request_record = _ensure_pull_request_record(
        db=db,
        repository_full_name=pr_schema.repository,
        pull_request_number=pr_schema.pull_request_number,
        github_pr_id=pr_schema.github_pr_id,
        title=pr_schema.title,
        author=pr_schema.author,
    )
    open_issues = get_open_issues_for_pull_request(
        db=db,
        repository_id=pull_request_record.repository_id,
        github_pr_id=pr_schema.github_pr_id,
        pull_request_number=job.pull_request_number,
    )

    full_diff = _build_diff(files)
    if not full_diff.strip():
        logger.info(
            "Skipping AI review for job %s because there are no reviewable changed files",
            job.id,
        )
        save_review(
            db=db,
            pr_data=pr_schema,
            review_data=SimpleNamespace(
                summary="No reviewable changed files were found.",
                issues=[],
            ),
            commit_sha=job.commit_sha,
        )
        return

    logger.info("Calling AI review service for job %s", job.id)

    try:
        ai_review = review_code(
            full_diff,
            existing_issues_context=_format_existing_issue_context(open_issues),
            incremental=_is_incremental_review_job(job),
        )
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

    previous_review = get_latest_review_for_pull_request(
        db=db,
        github_pr_id=pull_request["id"],
        repository_id=None,
        pull_request_number=job.pull_request_number,
        exclude_commit_sha=job.commit_sha,
    )
    issues_to_post = _filter_duplicate_issues(
        new_issues=ai_review.issues,
        previous_issues=_combine_previous_issue_context(
            previous_review.issues if previous_review else [],
            open_issues,
        ),
    )
    if len(issues_to_post) != len(ai_review.issues):
        logger.info(
            "Filtered %s duplicate issues for PR #%s",
            len(ai_review.issues) - len(issues_to_post),
            job.pull_request_number,
        )

    if not issues_to_post:
        logger.info(
            "Skipping GitHub comment posting for PR #%s because all issues were already present in a previous review",
            job.pull_request_number,
        )
        save_review(
            db=db,
            pr_data=pr_schema,
            review_data=_review_with_issues(ai_review, []),
            commit_sha=job.commit_sha,
        )
        return

    _post_github_comments(
        review=_review_with_issues(ai_review, issues_to_post),
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
        review_data=_review_with_issues(ai_review, issues_to_post),
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


def _get_files_for_review(job, access_token: str) -> list[dict]:
    if _is_incremental_review_job(job):
        logger.info(
            "Fetching incremental diff for PR #%s between %s and %s",
            job.pull_request_number,
            job.base_commit_sha,
            job.head_commit_sha or job.commit_sha,
        )
        files = get_compare_files(
            repository=job.repository,
            base_commit_sha=job.base_commit_sha,
            head_commit_sha=job.head_commit_sha or job.commit_sha,
            access_token=access_token,
        )
    else:
        logger.info(
            "Fetching full PR diff for %s PR #%s action=%s",
            job.repository,
            job.pull_request_number,
            getattr(job, "event_action", None) or "unknown",
        )
        files = get_pr_files(
            repository=job.repository,
            pull_request_number=job.pull_request_number,
            access_token=access_token,
        )

    return _filter_reviewable_files(files)


def _is_incremental_review_job(job) -> bool:
    return (
        getattr(job, "event_action", None) == "synchronize"
        and bool(getattr(job, "base_commit_sha", None))
        and bool(getattr(job, "head_commit_sha", None) or getattr(job, "commit_sha", None))
    )


def _filter_reviewable_files(files: list[dict]) -> list[dict]:
    reviewable_files = []

    for file in files:
        if file.get("status") == "removed":
            continue

        if not file.get("patch"):
            continue

        reviewable_files.append(file)

    return reviewable_files


def _format_existing_issue_context(issues) -> str:
    if not issues:
        return "None."

    lines = []
    for issue in issues:
        category = _enum_value(getattr(issue, "category", ""))
        severity = _enum_value(getattr(issue, "severity", ""))
        file_path = getattr(issue, "file", None) or "unknown file"
        line_number = getattr(issue, "line", None)
        location = f"{file_path}:{line_number}" if line_number else file_path
        problem, _, impact, _ = _split_issue_comment_sections(getattr(issue, "comment", ""))
        impact = getattr(issue, "impact", None) or impact
        context = f"- {location} [{severity}/{category}] {problem}"
        if impact:
            context += f" Impact: {impact}"
        lines.append(context)

    return "\n".join(lines)


def _combine_previous_issue_context(previous_issues, open_issues):
    combined_issues = []
    seen_issue_ids = set()

    for issue in [*previous_issues, *open_issues]:
        issue_id = getattr(issue, "id", None)
        if issue_id is not None:
            if issue_id in seen_issue_ids:
                continue
            seen_issue_ids.add(issue_id)

        combined_issues.append(issue)

    return combined_issues


def _review_with_issues(review, issues):
    if hasattr(review, "model_copy"):
        return review.model_copy(update={"issues": issues})

    return SimpleNamespace(
        summary=getattr(review, "summary", ""),
        issues=issues,
    )


def _ensure_pull_request_record(
    db,
    repository_full_name: str,
    pull_request_number: int,
    github_pr_id: int,
    title: str,
    author: str,
) -> PullRequest:
    repository = get_or_create_repository(db, repository_full_name)
    pull_request = (
        db.query(PullRequest)
        .filter(PullRequest.github_pr_id == github_pr_id)
        .one_or_none()
    )

    if pull_request is None:
        pull_request = PullRequest(github_pr_id=github_pr_id)
        db.add(pull_request)

    pull_request.repository_id = repository.id
    pull_request.pull_request_number = pull_request_number
    pull_request.title = title
    pull_request.repository = repository_full_name
    pull_request.author = author
    db.flush()

    return pull_request


def _filter_duplicate_issues(
    new_issues,
    previous_issues,
):
    filtered_issues = []

    for issue in new_issues:
        if _is_duplicate_issue(issue, previous_issues):
            logger.info(
                "Skipping duplicate issue: file=%s line=%s category=%s",
                issue.file,
                issue.line,
                issue.category,
            )
            continue

        filtered_issues.append(issue)

    return filtered_issues


def _is_duplicate_issue(issue, previous_issues) -> bool:
    for previous_issue in previous_issues:
        if _issues_match(issue, previous_issue):
            return True

    return False


def _issues_match(issue, previous_issue) -> bool:
    if _normalize_path(issue.file) != _normalize_path(previous_issue.file):
        return False

    if _enum_value(issue.category) != _enum_value(previous_issue.category):
        return False

    similarity = _issue_text_similarity(issue, previous_issue)

    if _lines_are_nearby(issue.line, previous_issue.line):
        return similarity >= 0.55

    return similarity >= 0.82


def _issue_text_similarity(issue, previous_issue) -> float:
    issue_text = _issue_root_cause_text(issue)
    previous_text = _issue_root_cause_text(previous_issue)
    issue_tokens = _tokenize_for_similarity(issue_text)
    previous_tokens = _tokenize_for_similarity(previous_text)

    if not issue_tokens or not previous_tokens:
        return 0

    return len(issue_tokens & previous_tokens) / len(issue_tokens | previous_tokens)


def _issue_root_cause_text(issue) -> str:
    problem, _, impact, _ = _split_issue_comment_sections(issue.comment)
    structured_impact = getattr(issue, "impact", None)
    if structured_impact:
        impact = structured_impact

    return " ".join(part for part in (problem, impact) if part)


def _tokenize_for_similarity(text: str) -> set[str]:
    stop_words = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "because",
        "being",
        "by",
        "can",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "or",
        "that",
        "the",
        "this",
        "to",
        "will",
        "with",
    }
    tokens = set(re.findall(r"[a-z0-9_]+", text.lower()))
    return {token for token in tokens if len(token) > 2 and token not in stop_words}


def _lines_are_nearby(line, previous_line) -> bool:
    if line is None or previous_line is None:
        return False

    return abs(line - previous_line) <= 8


def _normalize_path(file_path: str | None) -> str:
    if not file_path:
        return ""

    return file_path.replace("\\", "/").lstrip("/")


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
            response = post_inline_comment(**comment_payload)
            _attach_github_inline_metadata(
                issue=issue,
                response=response,
                repository=repository,
                pull_request_number=pull_request_number,
                access_token=access_token,
            )
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
                    response = post_inline_comment(**fallback_payload)
                    _attach_github_inline_metadata(
                        issue=issue,
                        response=response,
                        repository=repository,
                        pull_request_number=pull_request_number,
                        access_token=access_token,
                    )
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


def _attach_github_inline_metadata(
    issue,
    response,
    repository: str,
    pull_request_number: int,
    access_token: str,
) -> None:
    if not isinstance(response, dict):
        return

    comment_id = response.get("id")
    issue.github_comment_id = comment_id
    issue.github_comment_node_id = response.get("node_id")
    issue.github_review_id = response.get("pull_request_review_id")

    thread_id = (
        (response.get("pull_request_review_thread") or {}).get("id")
        or response.get("pull_request_review_thread_id")
    )
    if thread_id:
        issue.github_review_thread_id = str(thread_id)
        return

    if not comment_id or not response.get("pull_request_review_id"):
        return

    try:
        thread = get_review_thread_for_comment(
            repository=repository,
            pull_request_number=pull_request_number,
            access_token=access_token,
            comment_id=comment_id,
        )
    except Exception as exc:
        logger.warning(
            "Posted inline comment %s but could not resolve its GitHub review thread: %s",
            comment_id,
            exc,
        )
        return

    if not thread:
        logger.warning(
            "Posted inline comment %s but no matching GitHub review thread was found",
            comment_id,
        )
        return

    issue.github_review_thread_id = thread.get("id")
    issue.github_comment_node_id = thread.get("comment_node_id") or issue.github_comment_node_id


def _enum_value(value) -> str:
    if hasattr(value, "value"):
        return value.value

    return str(value)


def _format_category(category) -> str:
    return _enum_value(category).replace("_", " ").replace("-", " ").title()


def _format_issue_comment_body(issue) -> str:
    problem, suggested_fix, impact, example = _split_issue_comment_sections(issue.comment)
    impact = getattr(issue, "impact", None) or impact
    parts = [_format_issue_header(issue)]

    parts.extend(["", problem])

    if suggested_fix:
        parts.extend(["", "Suggested Fix:", suggested_fix])

    if impact:
        parts.extend(["", "Impact:", impact])

    if example:
        parts.extend(["", "Example:", f"```\n{example}\n```"])

    return "\n".join(parts)


def _format_issue_header(issue) -> str:
    severity = _enum_value(issue.severity)
    severity_markers = {
        "high": "🔴",
        "medium": "🟠",
        "low": "🟡",
    }

    marker = severity_markers.get(severity.lower(), "⚪")
    return f"{marker} {severity.upper()} · {_format_category(issue.category)}"


def _split_issue_comment_sections(comment: str) -> tuple[str, str | None, str | None, str | None]:
    normalized_comment = comment.strip()
    matches = list(
        re.finditer(
            r"(?P<label>Suggested\s+Fix|Impact|Example):",
            normalized_comment,
            flags=re.IGNORECASE,
        )
    )

    if not matches:
        return normalized_comment, None, None, None

    problem = normalized_comment[:matches[0].start()].strip()
    sections = {
        "suggested fix": None,
        "impact": None,
        "example": None,
    }

    for index, match in enumerate(matches):
        section_start = match.end()
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(normalized_comment)
        label = " ".join(match.group("label").lower().split())
        sections[label] = normalized_comment[section_start:section_end].strip()

    return problem, sections["suggested fix"], sections["impact"], sections["example"]


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
