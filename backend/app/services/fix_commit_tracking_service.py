import hashlib
import json
import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.db.models import FixCommit, FixCommitIssue, Issue, Review
from app.schemas.output import (
    FixCommitIssueStatus,
    FixCommitStatus,
    IssueFixStatus,
    IssueStatus,
)


logger = logging.getLogger(__name__)


class FixCommitAlreadyClaimedError(RuntimeError):
    """Another request already advanced this tracking record to commit creation."""


FINAL_STATUSES = {
    FixCommitStatus.RESOLVED.value,
    FixCommitStatus.PARTIALLY_RESOLVED.value,
    FixCommitStatus.REVIEWED.value,
}
RETRYABLE_STATUSES = {
    FixCommitStatus.FAILED.value,
    FixCommitStatus.STALE.value,
}
ALLOWED_TRANSITIONS = {
    FixCommitStatus.REQUESTED.value: {
        FixCommitStatus.GENERATING.value,
        FixCommitStatus.VALIDATING.value,
        FixCommitStatus.FAILED.value,
        FixCommitStatus.STALE.value,
    },
    FixCommitStatus.GENERATING.value: {
        FixCommitStatus.VALIDATING.value,
        FixCommitStatus.FAILED.value,
        FixCommitStatus.STALE.value,
    },
    FixCommitStatus.VALIDATING.value: {
        FixCommitStatus.COMMITTING.value,
        FixCommitStatus.FAILED.value,
        FixCommitStatus.STALE.value,
    },
    FixCommitStatus.COMMITTING.value: {
        FixCommitStatus.COMMITTED.value,
        FixCommitStatus.FAILED.value,
        FixCommitStatus.STALE.value,
    },
    FixCommitStatus.COMMITTED.value: {FixCommitStatus.REVIEW_PENDING.value},
    FixCommitStatus.REVIEW_PENDING.value: {
        FixCommitStatus.REVIEW_PENDING.value,
        FixCommitStatus.REVIEWED.value,
    },
    # Historical rows are normalized by the migration, but allowing this makes
    # an in-flight deployment safe while old workers drain.
    "SUCCESS": {FixCommitStatus.REVIEW_PENDING.value},
}


class FixCommitTrackingService:
    """Owns persistence for the direct AI-fix commit lifecycle."""

    def create_or_get(
        self,
        db: Session,
        *,
        repository_id: int,
        pull_request_id: int,
        review_id: int,
        issues: list[Issue],
        source_head_sha: str,
        source_branch: str,
        requested_by: str | None = None,
        retry: bool = False,
    ) -> tuple[FixCommit, bool]:
        issue_ids = sorted(issue.id for issue in issues)
        identity = self.identity(
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            source_head_sha=source_head_sha,
            issue_ids=issue_ids,
        )
        existing = (
            db.query(FixCommit)
            .options(joinedload(FixCommit.issue_links))
            .filter(FixCommit.idempotency_key == identity)
            .order_by(FixCommit.attempt.desc(), FixCommit.id.desc())
            .first()
        )
        if existing is not None and (existing.status not in RETRYABLE_STATUSES or not retry):
            return existing, False

        attempt = (existing.attempt + 1) if existing is not None else 1
        record = FixCommit(
            repository_id=repository_id,
            pull_request_id=pull_request_id,
            review_id=review_id,
            created_by=requested_by or "AI Code Review Assistant",
            status=FixCommitStatus.REQUESTED.value,
            source_head_sha=source_head_sha,
            source_branch=source_branch,
            idempotency_key=identity,
            attempt=attempt,
            requested_issue_count=len(issue_ids),
            applied_issue_ids=json.dumps(issue_ids),
            validation_status="PENDING",
            mode="DIRECT",
            issue_links=[
                FixCommitIssue(
                    issue_id=issue_id,
                    status=FixCommitIssueStatus.REQUESTED.value,
                )
                for issue_id in issue_ids
            ],
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            concurrent = (
                db.query(FixCommit)
                .options(joinedload(FixCommit.issue_links))
                .filter(
                    FixCommit.idempotency_key == identity,
                    FixCommit.attempt == attempt,
                )
                .one()
            )
            return concurrent, False
        db.refresh(record)
        return record, True

    @staticmethod
    def identity(
        *,
        repository_id: int,
        pull_request_id: int,
        source_head_sha: str,
        issue_ids: list[int],
    ) -> str:
        payload = ":".join(
            [
                str(repository_id),
                str(pull_request_id),
                source_head_sha,
                ",".join(str(issue_id) for issue_id in sorted(issue_ids)),
            ]
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def transition(
        self,
        db: Session,
        record: FixCommit,
        status: FixCommitStatus,
        *,
        commit: bool = True,
    ) -> FixCommit:
        allowed = ALLOWED_TRANSITIONS.get(record.status, set())
        if status.value != record.status and status.value not in allowed:
            raise ValueError(
                f"Invalid fix commit status transition: {record.status} -> {status.value}"
            )
        record.status = status.value
        record.updated_at = datetime.now(UTC)
        db.add(record)
        if commit:
            db.commit()
            db.refresh(record)
        return record

    def mark_generated(
        self,
        db: Session,
        record: FixCommit,
        issues: list[Issue],
    ) -> FixCommit:
        issue_by_id = {issue.id: issue for issue in issues}
        for link in record.issue_links:
            issue = issue_by_id.get(link.issue_id)
            generated = bool(
                issue
                and issue.fix_file_path
                and issue.fix_start_line
                and issue.fix_end_line
                and issue.fix_replacement_code is not None
            )
            link.generated = generated
            link.status = (
                FixCommitIssueStatus.GENERATED.value
                if generated
                else FixCommitIssueStatus.SKIPPED.value
            )
            if not generated:
                link.skip_reason = (
                    getattr(issue, "fix_explanation", None)
                    or "Fix generation did not produce a usable edit"
                )
            db.add(link)
        record.skipped_issue_count = sum(
            link.status == FixCommitIssueStatus.SKIPPED.value for link in record.issue_links
        )
        record.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(record)
        return record

    def mark_validating(self, db: Session, record: FixCommit) -> FixCommit:
        return self.transition(db, record, FixCommitStatus.VALIDATING)

    def record_validation(self, db: Session, record: FixCommit, preview) -> FixCommit:
        included = set(preview.included_issue_ids)
        excluded = set(preview.excluded_issue_ids)
        per_issue_errors: dict[int, list[str]] = {issue_id: [] for issue_id in excluded}
        for error in preview.errors:
            if not error.startswith("Issue ") or " excluded: " not in error:
                continue
            prefix, reason = error.split(" excluded: ", 1)
            try:
                issue_id = int(prefix.removeprefix("Issue "))
            except ValueError:
                continue
            per_issue_errors.setdefault(issue_id, []).append(reason)

        for link in record.issue_links:
            if link.issue_id in included:
                link.generated = True
                link.validated = True
                link.status = FixCommitIssueStatus.VALIDATED.value
                link.skip_reason = None
            elif link.issue_id in excluded:
                link.validated = False
                link.status = FixCommitIssueStatus.SKIPPED.value
                reasons = per_issue_errors.get(link.issue_id) or ["Generated edit failed validation"]
                link.skip_reason = "; ".join(reasons)[:2000]
            db.add(link)

        record.skipped_issue_count = len(excluded)
        record.applied_issue_ids = json.dumps(sorted(included))
        record.validation_status = "PASSED" if preview.valid else "FAILED"
        record.validation_summary = "; ".join(preview.errors)[:4000] or None
        record.updated_at = datetime.now(UTC)
        db.commit()
        db.refresh(record)
        return record

    def mark_committing(self, db: Session, record: FixCommit, commit_message: str) -> FixCommit:
        now = datetime.now(UTC)
        updated = (
            db.query(FixCommit)
            .filter(
                FixCommit.id == record.id,
                FixCommit.status == FixCommitStatus.VALIDATING.value,
            )
            .update(
                {
                    FixCommit.status: FixCommitStatus.COMMITTING.value,
                    FixCommit.commit_message: commit_message,
                    FixCommit.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        db.commit()
        db.refresh(record)
        if updated != 1:
            raise FixCommitAlreadyClaimedError(
                f"Fix commit {record.id} is already {record.status}"
            )
        return record

    def mark_committed(self, db: Session, record: FixCommit, result) -> FixCommit:
        if record.status != FixCommitStatus.COMMITTING.value:
            raise ValueError(
                f"Invalid fix commit status transition: {record.status} -> COMMITTED"
            )
        now = datetime.now(UTC)
        record.generated_commit_sha = result.commit_sha
        record.generated_commit_url = result.commit_url
        record.resulting_head_sha = result.commit_sha
        record.source_branch = result.branch_name
        record.committed_at = now
        record.status = FixCommitStatus.COMMITTED.value
        record.updated_at = now
        for link in record.issue_links:
            if link.validated:
                link.committed = True
                link.status = FixCommitIssueStatus.COMMITTED.value
                issue = link.issue
                if issue is not None:
                    issue.fix_status = IssueFixStatus.FIX_COMMITTED.value
                    db.add(issue)
            db.add(link)
        record.valid_issue_count = sum(link.committed for link in record.issue_links)
        db.add(record)
        db.commit()
        db.refresh(record)
        return self.transition(db, record, FixCommitStatus.REVIEW_PENDING)

    def recover_after_push(
        self,
        db: Session,
        *,
        fix_commit_id: int,
        result,
    ) -> FixCommit:
        """Retry local persistence after GitHub has already accepted the branch update."""
        db.rollback()
        record = db.query(FixCommit).filter(FixCommit.id == fix_commit_id).one()
        if record.status == FixCommitStatus.COMMITTING.value:
            return self.mark_committed(db, record, result)
        if record.status == FixCommitStatus.COMMITTED.value:
            record.generated_commit_sha = record.generated_commit_sha or result.commit_sha
            record.generated_commit_url = record.generated_commit_url or result.commit_url
            record.resulting_head_sha = record.resulting_head_sha or result.commit_sha
            record.committed_at = record.committed_at or datetime.now(UTC)
            db.commit()
            db.refresh(record)
            return self.transition(db, record, FixCommitStatus.REVIEW_PENDING)
        if record.status == FixCommitStatus.REVIEW_PENDING.value:
            return record
        raise ValueError(
            f"Cannot recover pushed fix commit {record.id} from status {record.status}"
        )

    def mark_failed(
        self,
        db: Session,
        record: FixCommit,
        reason: str,
    ) -> FixCommit:
        record.status = FixCommitStatus.FAILED.value
        record.failure_reason = self._concise(reason)
        record.failed_issue_count = 0
        for link in record.issue_links:
            if link.committed or link.status == FixCommitIssueStatus.SKIPPED.value:
                continue
            link.status = FixCommitIssueStatus.FAILED.value
            link.failure_reason = record.failure_reason
            record.failed_issue_count += 1
            db.add(link)
        record.updated_at = datetime.now(UTC)
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def mark_stale(self, db: Session, record: FixCommit) -> FixCommit:
        reason = "Pull Request changed during fix generation"
        record.status = FixCommitStatus.STALE.value
        record.failure_reason = reason
        for link in record.issue_links:
            if link.committed:
                continue
            link.status = FixCommitIssueStatus.FAILED.value
            link.failure_reason = reason
            db.add(link)
        record.failed_issue_count = sum(not link.committed for link in record.issue_links)
        record.updated_at = datetime.now(UTC)
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def match_synchronize_commit(
        self,
        db: Session,
        *,
        repository_full_name: str,
        pull_request_number: int,
        commit_sha: str,
    ) -> FixCommit | None:
        record = (
            db.query(FixCommit)
            .filter(FixCommit.generated_commit_sha == commit_sha)
            .first()
        )
        if record is not None and (
            record.pull_request is None
            or record.pull_request.repository != repository_full_name
            or record.pull_request.pull_request_number != pull_request_number
        ):
            return None
        if record is not None and record.status not in FINAL_STATUSES | RETRYABLE_STATUSES:
            self.transition(db, record, FixCommitStatus.REVIEW_PENDING)
        return record

    def complete_review(
        self,
        db: Session,
        *,
        record: FixCommit,
        review: Review,
        new_issues,
        issues_match,
    ) -> FixCommit:
        now = datetime.now(UTC)
        review.fix_commit_id = record.id
        record.status = FixCommitStatus.REVIEWED.value
        record.reviewed_at = now
        record.failure_reason = None
        record.updated_at = now
        db.add_all([record, review])
        db.commit()
        db.refresh(record)

        resolved_count = 0
        remaining_count = 0

        for link in record.issue_links:
            if not link.committed:
                continue
            issue = link.issue
            recurring = next(
                (new_issue for new_issue in new_issues if issues_match(new_issue, issue)),
                None,
            )
            issue.fix_status = IssueFixStatus.FIX_COMMITTED.value
            if recurring is None:
                link.status = FixCommitIssueStatus.RESOLVED.value
                link.resolution_status = FixCommitIssueStatus.RESOLVED.value
                issue.status = IssueStatus.RESOLVED.value
                issue.resolved_at = issue.resolved_at or now
                issue.resolved_by = f"AI Fix Commit {record.generated_commit_sha[:7]}"
                resolved_count += 1
            else:
                link.status = FixCommitIssueStatus.STILL_OPEN.value
                link.resolution_status = FixCommitIssueStatus.STILL_OPEN.value
                link.current_issue_id = issue.id
                issue.status = IssueStatus.OPEN.value
                issue.resolved_at = None
                issue.resolved_by = None
                remaining_count += 1
            db.add_all([link, issue])

        record.resolved_issue_count = resolved_count
        record.remaining_issue_count = remaining_count
        if record.valid_issue_count and resolved_count == record.valid_issue_count:
            record.status = FixCommitStatus.RESOLVED.value
        elif resolved_count and remaining_count:
            record.status = FixCommitStatus.PARTIALLY_RESOLVED.value
        else:
            record.status = FixCommitStatus.REVIEWED.value
        record.updated_at = now
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    def record_review_failure(self, db: Session, fix_commit_id: int, reason: str) -> None:
        record = db.query(FixCommit).filter(FixCommit.id == fix_commit_id).first()
        if record is None or record.status in FINAL_STATUSES:
            return
        record.status = FixCommitStatus.REVIEW_PENDING.value
        record.failure_reason = f"Follow-up review failed: {self._concise(reason)}"
        record.updated_at = datetime.now(UTC)
        db.commit()

    @staticmethod
    def _concise(reason: str) -> str:
        return " ".join(str(reason).split())[:2000]
