from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session, joinedload

from app.db.models import FixCommit, FixCommitIssue, Issue, PullRequest, Review
from app.schemas.output import FixCommitIssueStatus, FixCommitStatus, IssueStatus
from app.services.issue_matching_service import IssueMatchingService


MAX_AUTOMATIC_FIX_ATTEMPTS = 3

ACTIVE_FIX_COMMIT_STATUSES = {
    FixCommitStatus.REQUESTED.value,
    FixCommitStatus.GENERATING.value,
    FixCommitStatus.VALIDATING.value,
    FixCommitStatus.COMMITTING.value,
    FixCommitStatus.COMMITTED.value,
    FixCommitStatus.REVIEW_PENDING.value,
}

RETRYABLE_ISSUE_OUTCOMES = {
    FixCommitIssueStatus.STILL_OPEN.value,
    FixCommitIssueStatus.MOVED.value,
    FixCommitIssueStatus.FAILED_TO_VERIFY.value,
    FixCommitIssueStatus.FAILED.value,
    FixCommitIssueStatus.SKIPPED.value,
}


@dataclass(frozen=True)
class ExcludedFinding:
    issue: Issue
    reason: str
    manual_review: bool = False


@dataclass
class ActionableIssueSelection:
    selected: list[Issue] = field(default_factory=list)
    excluded: list[ExcludedFinding] = field(default_factory=list)
    canonical_count: int = 0

    @property
    def manual_review(self) -> list[ExcludedFinding]:
        return [finding for finding in self.excluded if finding.manual_review]


def get_current_actionable_issues_for_pull_request(
    db: Session,
    *,
    repository_id: int,
    pull_request_number: int,
    max_attempts: int = MAX_AUTOMATIC_FIX_ATTEMPTS,
) -> ActionableIssueSelection:
    """Collapse immutable review occurrences into current PR-level findings."""
    issues = (
        db.query(Issue)
        .join(Review)
        .join(PullRequest)
        .options(
            joinedload(Issue.review),
            joinedload(Issue.fix_pull_requests),
            joinedload(Issue.fix_commit_links).joinedload(FixCommitIssue.fix_commit),
        )
        .filter(
            PullRequest.repository_id == repository_id,
            PullRequest.pull_request_number == pull_request_number,
        )
        .order_by(Review.id.desc(), Issue.id.desc())
        .all()
    )

    families = _finding_families(issues)
    selection = ActionableIssueSelection(canonical_count=len(families))
    for family in families:
        current = family[0]
        latest_link = _latest_attempt_link(family)
        attempt_count = len({link.fix_commit_id for issue in family for link in issue.fix_commit_links})

        if any(issue.status == IssueStatus.IGNORED.value for issue in family):
            selection.excluded.append(ExcludedFinding(current, "explicitly ignored"))
            continue
        if latest_link is not None and latest_link.resolution_status == FixCommitIssueStatus.RESOLVED.value:
            selection.excluded.append(ExcludedFinding(current, "conclusively resolved by verification"))
            continue
        if current.status == IssueStatus.RESOLVED.value:
            selection.excluded.append(ExcludedFinding(current, "resolved"))
            continue
        if current.blocking_fix_pull_request is not None:
            selection.excluded.append(ExcludedFinding(current, "already included in an active fix pull request"))
            continue
        if latest_link is not None and _link_is_active(latest_link):
            selection.excluded.append(ExcludedFinding(current, "already being processed"))
            continue
        if attempt_count >= max_attempts:
            selection.excluded.append(
                ExcludedFinding(
                    current,
                    f"retry limit reached ({attempt_count}/{max_attempts})",
                    manual_review=True,
                )
            )
            continue

        # FIX_COMMITTED is deliberately not a blocker. The latest per-attempt
        # outcome is authoritative; retryable failures remain actionable.
        if latest_link is None or latest_link.resolution_status in RETRYABLE_ISSUE_OUTCOMES:
            selection.selected.append(current)
            continue
        if latest_link.status in RETRYABLE_ISSUE_OUTCOMES:
            selection.selected.append(current)
            continue

        selection.excluded.append(
            ExcludedFinding(current, f"latest fix attempt is {latest_link.status.lower()}")
        )

    return selection


def _finding_families(issues: list[Issue]) -> list[list[Issue]]:
    matcher = IssueMatchingService()
    by_id = {issue.id: issue for issue in issues}
    parent = {issue.id: issue.id for issue in issues}

    def find(issue_id: int) -> int:
        while parent[issue_id] != issue_id:
            parent[issue_id] = parent[parent[issue_id]]
            issue_id = parent[issue_id]
        return issue_id

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for issue in issues:
        for link in issue.fix_commit_links:
            if link.current_issue_id in by_id:
                union(issue.id, link.current_issue_id)

    for index, issue in enumerate(issues):
        for candidate in issues[index + 1 :]:
            if matcher.matches(issue, candidate):
                union(issue.id, candidate.id)

    grouped: dict[int, list[Issue]] = {}
    for issue in issues:  # Query order is newest first and is preserved per family.
        grouped.setdefault(find(issue.id), []).append(issue)
    return list(grouped.values())


def _latest_attempt_link(family: list[Issue]) -> FixCommitIssue | None:
    links = [link for issue in family for link in issue.fix_commit_links]
    if not links:
        return None
    return max(
        links,
        key=lambda link: (
            link.updated_at or link.created_at,
            link.fix_commit_id,
        ),
    )


def _link_is_active(link: FixCommitIssue) -> bool:
    return (
        link.resolution_status is None
        and link.fix_commit is not None
        and link.fix_commit.status in ACTIVE_FIX_COMMIT_STATUSES
        and link.status not in RETRYABLE_ISSUE_OUTCOMES
    )
