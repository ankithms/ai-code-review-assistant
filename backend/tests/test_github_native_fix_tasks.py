from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Base, FixCommit, Issue, PullRequest, Repository, Review
from app.schemas.fixes import FixPreviewFileResponse, FixPreviewResponse
from app.schemas.output import FixCommitStatus, IssueStatus
from app.services import github_native_fix_service
from app.services.git_commit_service import FixCommitResult
from app.tasks import review_tasks


def test_fix_actor_creates_and_closes_its_own_database_session():
    db = Mock()
    payload = {"comment": {"body": "/ai-fix all"}}

    with (
        patch("app.db.database.SessionLocal", return_value=db),
        patch.dict("os.environ", {"GITHUB_ACCESS_TOKEN": "token"}),
        patch(
            "app.services.github_native_fix_service.handle_github_native_fix_comment"
        ) as handle,
    ):
        review_tasks.process_github_native_fix_command.fn(payload, "issue_comment")

    handle.assert_called_once_with(
        db=db,
        payload=payload,
        event="issue_comment",
        access_token="token",
    )
    db.close.assert_called_once_with()


def test_queued_command_commits_once_when_same_github_comment_is_delivered_twice():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = Session(engine)
    repository = Repository(full_name="owner/repo")
    pull_request_record = PullRequest(
        repository_ref=repository,
        repository="owner/repo",
        github_pr_id=99,
        pull_request_number=12,
        title="PR",
        author="octocat",
    )
    review = Review(pull_request=pull_request_record, summary="summary", commit_sha="head-1")
    issue = Issue(
        review=review,
        severity="high",
        category="bug",
        file="app.py",
        line=1,
        comment="Issue",
        status=IssueStatus.OPEN.value,
    )
    db.add_all([repository, pull_request_record, review, issue])
    db.commit()

    github_pr = {
        "state": "open",
        "html_url": "https://github.com/owner/repo/pull/12",
        "head": {
            "ref": "feature",
            "sha": "head-1",
            "repo": {"full_name": "owner/repo"},
        },
    }
    preview = FixPreviewResponse(
        review_id=review.id,
        target_branch="feature",
        target_head_sha="head-1",
        valid=True,
        errors=[],
        files=[
            FixPreviewFileResponse(
                file_path="app.py",
                original_sha="blob-1",
                valid=True,
                errors=[],
                patched_content="fixed = True\n",
            )
        ],
        fixes=[],
        included_issue_ids=[issue.id],
        excluded_issue_ids=[],
    )
    commit_result = FixCommitResult(
        branch_name="feature",
        commit_sha="fix-sha",
        commit_url="https://github.com/owner/repo/commit/fix-sha",
        commit_message="unused",
    )
    payload = {
        "repository": {"full_name": "owner/repo"},
        "issue": {"number": 12, "pull_request": {"url": "pull"}},
        "comment": {"id": 100, "body": "/ai-fix all", "user": {"login": "dev"}},
    }

    def generate(**kwargs):
        selected = kwargs["issues"][0]
        selected.fix_file_path = "app.py"
        selected.fix_start_line = 1
        selected.fix_end_line = 1
        selected.fix_replacement_code = "fixed = True"
        kwargs["db"].commit()

    with (
        patch.object(github_native_fix_service, "_github_pull_request", return_value=github_pr),
        patch.object(
            github_native_fix_service.GitCommitService,
            "validate_direct_commit_target",
        ),
        patch.object(
            github_native_fix_service.FixGenerationService,
            "generate_fixes",
            side_effect=generate,
        ),
        patch.object(github_native_fix_service, "_build_preview_response", return_value=preview),
        patch.object(
            github_native_fix_service.GitCommitService,
            "create_fix_commit",
            return_value=commit_result,
        ) as create_commit,
    ):
        first = github_native_fix_service._run_fix_command(
            db=db,
            repository="owner/repo",
            pull_request_number=12,
            command=github_native_fix_service.NativeFixCommand(target="all"),
            access_token="token",
            payload=payload,
            request_key="github:owner/repo:issue_comment:100",
        )
        duplicate = github_native_fix_service._run_fix_command(
            db=db,
            repository="owner/repo",
            pull_request_number=12,
            command=github_native_fix_service.NativeFixCommand(target="all"),
            access_token="token",
            payload=payload,
            request_key="github:owner/repo:issue_comment:100",
        )

    record = db.query(FixCommit).one()
    assert "AI fixes committed" in first
    assert "already committed" in duplicate
    assert record.status == FixCommitStatus.REVIEW_PENDING.value
    assert record.generated_commit_sha == "fix-sha"
    create_commit.assert_called_once()
    db.close()
