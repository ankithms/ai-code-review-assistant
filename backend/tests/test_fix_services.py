import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai.review_service import AIReviewServiceError
from app.db.models import (
    Base,
    FixCommit,
    FixPullRequest,
    Issue,
    PullRequest,
    Repository,
    Review,
    ReviewJob,
)
from app.routes import fixes
from app.schemas.fixes import FixApplyRequest, FixPreviewFileResponse, FixPreviewResponse
from app.services import github_native_fix_service
from app.services.fix_generation_service import FixGenerationService, GeneratedFixSchema
from app.services.git_commit_service import (
    DirectCommitPermissionError,
    FixCommitResult,
    GitCommitService,
    StaleHeadError,
)
from app.services.patch_service import PatchEdit, PatchedFile, PatchService
from app.services.validation_service import ValidationService


class PatchServiceTests(unittest.TestCase):
    def test_applies_line_range_replacement_without_rewriting_whole_file(self):
        source = "a = 1\nb = 2\nc = 3\n"

        patched = PatchService().apply_edits(
            source=source,
            edits=[
                PatchEdit(
                    file_path="app.py",
                    start_line=2,
                    end_line=2,
                    replacement_code="b = 20",
                )
            ],
        )

        self.assertEqual(patched, "a = 1\nb = 20\nc = 3\n")

    def test_rejects_overlapping_edits(self):
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            PatchService().apply_edits(
                source="a\nb\nc\n",
                edits=[
                    PatchEdit("app.py", 1, 2, "x"),
                    PatchEdit("app.py", 2, 3, "y"),
                ],
            )

    def test_rejects_missing_target_lines(self):
        with self.assertRaisesRegex(ValueError, "no longer exist"):
            PatchService().apply_edits(
                source="a\n",
                edits=[
                    PatchEdit("app.py", 2, 2, "b"),
                ],
            )

    def test_normalizes_overindented_python_replacement_at_top_level(self):
        source = "repo = None\ndb.delete(repo)\n"

        patched = PatchService().apply_edits(
            source=source,
            edits=[
                PatchEdit(
                    file_path="calculator.py",
                    start_line=2,
                    end_line=2,
                    replacement_code="    if repo is not None:\n        db.delete(repo)",
                )
            ],
        )

        self.assertEqual(patched, "repo = None\nif repo is not None:\n    db.delete(repo)\n")
        self.assertFalse(ValidationService().validate_file("calculator.py", patched))

    def test_normalizes_unindented_python_replacement_inside_function(self):
        source = "def delete_repository(repo):\n    db.delete(repo)\n"

        patched = PatchService().apply_edits(
            source=source,
            edits=[
                PatchEdit(
                    file_path="calculator.py",
                    start_line=2,
                    end_line=2,
                    replacement_code="if repo is not None:\n    db.delete(repo)",
                )
            ],
        )

        self.assertEqual(
            patched,
            "def delete_repository(repo):\n    if repo is not None:\n        db.delete(repo)\n",
        )
        self.assertFalse(ValidationService().validate_file("calculator.py", patched))


class ValidationServiceTests(unittest.TestCase):
    def test_validates_python_syntax(self):
        errors = ValidationService().validate_file("app.py", "def broken(:\n    pass\n")

        self.assertTrue(errors)
        self.assertIn("Python syntax validation failed", errors[0])

    def test_validates_json_syntax(self):
        errors = ValidationService().validate_file("config.json", '{"broken": }')

        self.assertTrue(errors)
        self.assertIn("JSON validation failed", errors[0])


class FixGenerationServiceTests(unittest.TestCase):
    def test_temporary_provider_unavailability_is_wrapped_as_retryable(self):
        context = SimpleNamespace()
        service = FixGenerationService()
        unavailable_model = SimpleNamespace(
            invoke=Mock(
                side_effect=RuntimeError(
                    "503 UNAVAILABLE: This model is currently experiencing high demand."
                )
            )
        )

        with patch(
            "app.services.fix_generation_service.fix_model",
            unavailable_model,
        ), patch.object(service, "_build_prompt", return_value="fix prompt"):
            with self.assertRaises(AIReviewServiceError) as error:
                service._invoke_fix_model(context)

        self.assertTrue(error.exception.retryable)
        self.assertIn("AI fix generation service is temporarily unavailable", str(error.exception))
        self.assertIn("try the AI fix command again later", str(error.exception))

    def test_invalid_existing_python_fix_is_regenerated_before_saving(self):
        source = (
            'password = "123"\n'
            "\n"
            "def divide(a, b):\n"
            "    return a / b\n"
            "\n"
            "user = None\n"
            "\n"
            "print(user.name)\n"
            "\n"
            "\n"
            "def delete_repository(repo_id):\n"
            "    repo = db.query(Repository).first()\n"
            "    db.delete(repo)\n"
        )
        issue = SimpleNamespace(
            file="calculator.py",
            line=10,
            category="bug",
            severity="high",
            comment="Deletes the wrong repository.",
            impact="The wrong repository may be deleted.",
            fix_file_path="calculator.py",
            fix_start_line=10,
            fix_end_line=11,
            fix_replacement_code=(
                "    repo = db.query(Repository).filter_by(id=repo_id).first()\n"
                "    if repo:\n"
                "        db.delete(repo)"
            ),
            fix_explanation=None,
            fix_base_commit_sha="old",
            fix_file_sha="old-sha",
            fix_status="FIX_GENERATED",
        )
        db = SimpleNamespace(add=lambda *_args: None, commit=lambda: None)

        fix_model = SimpleNamespace(
            invoke=Mock(
                return_value=GeneratedFixSchema(
                    file_path="calculator.py",
                    start_line=12,
                    end_line=13,
                    replacement_code=(
                        "    repo = db.query(Repository).filter_by(id=repo_id).first()\n"
                        "    if repo:\n"
                        "        db.delete(repo)"
                    ),
                    explanation="Use the requested repository id and guard against missing rows.",
                )
            )
        )

        with (
            patch(
                "app.services.fix_generation_service.get_file_content",
                return_value={
                    "path": "calculator.py",
                    "sha": "file-sha",
                    "content": source,
                },
            ),
            patch(
                "app.services.fix_generation_service.fix_model",
                fix_model,
            ),
        ):
            FixGenerationService().generate_fixes(
                db=db,
                issues=[issue],
                repository="owner/repo",
                target_ref="head",
                target_head_sha="head",
                access_token="token",
            )

        self.assertEqual(fix_model.invoke.call_count, 1)
        self.assertEqual(issue.fix_start_line, 12)
        self.assertEqual(issue.fix_end_line, 13)

    def test_invalid_new_python_fix_is_retried_with_validation_feedback(self):
        source = (
            "def delete_repository(repo_id):\n"
            "    repo = db.query(Repository).first()\n"
            "    db.delete(repo)\n"
        )
        issue = SimpleNamespace(
            file="calculator.py",
            line=2,
            category="bug",
            severity="high",
            comment="Deletes the wrong repository.",
            impact="The wrong repository may be deleted.",
            fix_file_path=None,
            fix_start_line=None,
            fix_end_line=None,
            fix_replacement_code=None,
            fix_explanation=None,
            fix_base_commit_sha=None,
            fix_file_sha=None,
            fix_status="NO_FIX",
        )
        db = SimpleNamespace(add=lambda *_args: None, commit=lambda: None)

        fix_model = SimpleNamespace(
            invoke=Mock(
                side_effect=[
                    GeneratedFixSchema(
                        file_path="calculator.py",
                        start_line=1,
                        end_line=1,
                        replacement_code="    repo = db.query(Repository).filter_by(id=repo_id).first()",
                        explanation="Bad range.",
                    ),
                    GeneratedFixSchema(
                        file_path="calculator.py",
                        start_line=2,
                        end_line=3,
                        replacement_code=(
                            "    repo = db.query(Repository).filter_by(id=repo_id).first()\n"
                            "    if repo:\n"
                            "        db.delete(repo)"
                        ),
                        explanation="Good range.",
                    ),
                ]
            )
        )

        with (
            patch(
                "app.services.fix_generation_service.get_file_content",
                return_value={
                    "path": "calculator.py",
                    "sha": "file-sha",
                    "content": source,
                },
            ),
            patch(
                "app.services.fix_generation_service.fix_model",
                fix_model,
            ),
        ):
            FixGenerationService().generate_fixes(
                db=db,
                issues=[issue],
                repository="owner/repo",
                target_ref="head",
                target_head_sha="head",
                access_token="token",
            )

        self.assertEqual(fix_model.invoke.call_count, 2)
        self.assertEqual(issue.fix_start_line, 2)
        self.assertEqual(issue.fix_end_line, 3)


class FixRouteSafetyTests(unittest.TestCase):
    def test_single_issue_commit_message_is_consistent(self):
        message = fixes._build_commit_message([
            SimpleNamespace(comment="Null pointer handling.")
        ])

        self.assertEqual(
            message,
            "fix(ai): resolve null pointer handling\n\n"
            "Generated by AI Code Review Assistant.\n\n"
            "Addresses:\n- null pointer handling",
        )

    def test_generate_maps_temporary_ai_failure_to_service_unavailable(self):
        review = SimpleNamespace(
            id=2,
            pull_request=SimpleNamespace(repository="owner/repo"),
        )
        issue = SimpleNamespace(id=3)
        db = SimpleNamespace(rollback=Mock())
        provider_error = AIReviewServiceError(
            "AI fix generation service is temporarily unavailable.",
            retryable=True,
        )

        with (
            patch.object(fixes, "_github_token", return_value="token"),
            patch.object(fixes, "_get_review_or_404", return_value=review),
            patch.object(
                fixes,
                "_github_pull_request",
                return_value={"head": {"sha": "abc123"}},
            ),
            patch.object(fixes, "_select_issues", return_value=[issue]),
            patch.object(fixes, "_validate_issues_eligible_for_fix"),
            patch.object(fixes, "_ensure_direct_commit_allowed"),
            patch.object(
                fixes.FixGenerationService,
                "generate_fixes",
                side_effect=provider_error,
            ),
            self.assertRaises(HTTPException) as error,
        ):
            fixes.generate_review_fixes(
                repository_id=1,
                review_id=2,
                request=SimpleNamespace(issue_ids=[3]),
                db=db,
            )

        self.assertEqual(error.exception.status_code, 503)
        self.assertIn("temporarily unavailable", error.exception.detail)
        db.rollback.assert_called_once_with()

    def test_apply_requires_explicit_confirmation(self):
        with self.assertRaises(HTTPException) as context:
            fixes.apply_review_fixes(
                repository_id=1,
                review_id=2,
                request=SimpleNamespace(
                    issue_ids=[3],
                    confirm=False,
                ),
                db=SimpleNamespace(),
            )

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Explicit confirmation", context.exception.detail)

    def test_preview_rejects_stale_generated_fix(self):
        review = SimpleNamespace(
            id=1,
            pull_request=SimpleNamespace(
                repository="owner/repo",
                pull_request_number=12,
            ),
        )
        issue = SimpleNamespace(
            id=5,
            fix_status="FIX_GENERATED",
            fix_file_path="app.py",
            fix_start_line=1,
            fix_end_line=1,
            fix_replacement_code="value = 2",
            fix_explanation="Use the updated value.",
            fix_base_commit_sha="old-head",
            fix_file_sha="file-sha",
        )

        with (
            patch.object(
                fixes,
                "_github_pull_request",
                return_value={
                    "head": {
                        "ref": "feature",
                        "sha": "new-head",
                    }
                },
            ),
            patch.object(fixes, "get_file_content") as get_file_content,
        ):
            preview = fixes._build_preview_response(
                db=SimpleNamespace(),
                review=review,
                issues=[issue],
                access_token="token",
            )

        get_file_content.assert_not_called()
        self.assertFalse(preview.valid)
        self.assertIn("older branch HEAD", preview.errors[0])

    def test_preview_requires_generated_fix_metadata(self):
        review = SimpleNamespace(
            id=1,
            pull_request=SimpleNamespace(
                repository="owner/repo",
                pull_request_number=12,
            ),
        )
        issue = SimpleNamespace(
            id=5,
            fix_status="FIX_GENERATED",
            fix_file_path="app.py",
            fix_start_line=1,
            fix_end_line=1,
            fix_replacement_code="value = 2",
            fix_explanation="Use the updated value.",
            fix_base_commit_sha=None,
            fix_file_sha=None,
        )

        with patch.object(
            fixes,
            "_github_pull_request",
            return_value={
                "head": {
                    "ref": "feature",
                    "sha": "new-head",
                }
            },
        ):
            preview = fixes._build_preview_response(
                db=SimpleNamespace(),
                review=review,
                issues=[issue],
                access_token="token",
            )

        self.assertFalse(preview.valid)
        self.assertIn("must be generated", preview.errors[0])

    def test_preview_applies_additional_edits_atomically(self):
        review = SimpleNamespace(
            id=1,
            pull_request=SimpleNamespace(
                repository="owner/repo",
                pull_request_number=12,
            ),
        )
        issue = SimpleNamespace(
            id=5,
            fix_status="FIX_GENERATED",
            fix_file_path="app/service.py",
            fix_start_line=2,
            fix_end_line=2,
            fix_replacement_code="    return normalize(value)",
            fix_additional_edits=json.dumps(
                [
                    {
                        "file_path": "app/helpers.py",
                        "start_line": 1,
                        "end_line": 1,
                        "original_code": "def normalize(value):",
                        "replacement_code": "def normalize(value: str) -> str:",
                        "reason": "Keep helper signature explicit for the service fix.",
                    }
                ]
            ),
            fix_explanation="Normalize before returning.",
            fix_base_commit_sha="head",
            fix_file_sha="service-sha",
        )

        def file_content(repository, file_path, ref, access_token):
            if file_path == "app/service.py":
                return {
                    "path": file_path,
                    "sha": "service-sha",
                    "content": "def save(value):\n    return value\n",
                }
            return {
                "path": file_path,
                "sha": "helper-sha",
                "content": "def normalize(value):\n    return value.strip()\n",
            }

        with (
            patch.object(
                fixes,
                "_github_pull_request",
                return_value={
                    "head": {
                        "ref": "feature",
                        "sha": "head",
                    }
                },
            ),
            patch.object(fixes, "get_file_content", side_effect=file_content),
        ):
            preview = fixes._build_preview_response(
                db=SimpleNamespace(),
                review=review,
                issues=[issue],
                access_token="token",
            )

        self.assertTrue(preview.valid)
        self.assertEqual(
            sorted(file.file_path for file in preview.files),
            ["app/helpers.py", "app/service.py"],
        )
        self.assertEqual(preview.fixes[0].additional_edits[0].file_path, "app/helpers.py")

    def test_active_fix_pull_request_makes_issue_ineligible(self):
        issue = SimpleNamespace(
            id=123,
            blocking_fix_pull_request=SimpleNamespace(github_pr_number=45),
        )

        with self.assertRaises(HTTPException) as context:
            fixes._validate_issues_eligible_for_fix([issue])

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Issue 123 is already included in Fix PR #45", context.exception.detail)

    def test_committed_issue_cannot_generate_an_identical_fix_again(self):
        issue = SimpleNamespace(
            id=123,
            blocking_fix_pull_request=None,
            fix_status="FIX_COMMITTED",
        )

        with self.assertRaises(HTTPException) as context:
            fixes._validate_issues_eligible_for_fix([issue])

        self.assertIn("already has an AI fix commit", context.exception.detail)

    def test_preview_excludes_invalid_issue_and_keeps_valid_issue(self):
        review = SimpleNamespace(
            id=1,
            pull_request=SimpleNamespace(repository="owner/repo", pull_request_number=12),
        )
        valid_issue = _generated_issue(
            issue_id=1,
            file_path="good.py",
            replacement_code="value = 2",
            file_sha="good-sha",
        )
        invalid_issue = _generated_issue(
            issue_id=2,
            file_path="bad.py",
            replacement_code="def broken(:",
            file_sha="bad-sha",
        )

        def get_content(repository, file_path, ref, access_token):
            return {
                "path": file_path,
                "sha": "good-sha" if file_path == "good.py" else "bad-sha",
                "content": "value = 1\n",
            }

        with (
            patch.object(
                fixes,
                "_github_pull_request",
                return_value={"head": {"ref": "feature", "sha": "head"}},
            ),
            patch.object(fixes, "get_file_content", side_effect=get_content),
        ):
            preview = fixes._build_preview_response(
                db=SimpleNamespace(),
                review=review,
                issues=[valid_issue, invalid_issue],
                access_token="token",
            )

        self.assertTrue(preview.valid)
        self.assertEqual(preview.included_issue_ids, [1])
        self.assertEqual(preview.excluded_issue_ids, [2])
        self.assertEqual([file.file_path for file in preview.files], ["good.py"])

    def test_apply_creates_one_direct_commit_and_tracks_metadata_for_multiple_issues(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()
        repository = Repository(full_name="owner/repo")
        pull_request_record = PullRequest(
            repository_ref=repository,
            repository="owner/repo",
            github_pr_id=123,
            pull_request_number=42,
            title="Fix test",
            author="octocat",
        )
        review = Review(pull_request=pull_request_record, summary="summary", commit_sha="head")
        issues = [
            Issue(
                review=review,
                severity="high",
                category="bug",
                file=f"file-{index}.py",
                comment=comment,
                status="OPEN",
                fix_status="FIX_GENERATED",
            )
            for index, comment in enumerate(("Null pointer handling.", "Missing input validation."), 1)
        ]
        db.add_all([repository, pull_request_record, review, *issues])
        db.commit()
        preview = FixPreviewResponse(
            review_id=review.id,
            target_branch="feature",
            target_head_sha="head",
            valid=True,
            errors=[],
            files=[
                FixPreviewFileResponse(
                    file_path="app.py",
                    original_sha="file-sha",
                    valid=True,
                    errors=[],
                    patched_content="value = 2\n",
                )
            ],
            fixes=[],
            included_issue_ids=[issue.id for issue in issues],
            excluded_issue_ids=[],
        )
        result = FixCommitResult(
            branch_name="feature",
            commit_sha="fix-sha",
            commit_url="https://github.com/owner/repo/commit/fix-sha",
            commit_message="unused",
        )
        github_pr = {
            "state": "open",
            "html_url": "https://github.com/owner/repo/pull/42",
            "head": {"ref": "feature", "sha": "head", "repo": {"full_name": "owner/repo"}},
        }

        with (
            patch.object(fixes, "_github_token", return_value="token"),
            patch.object(fixes, "_get_review_or_404", return_value=review),
            patch.object(fixes, "_github_pull_request", return_value=github_pr),
            patch.object(fixes, "_build_preview_response", return_value=preview),
            patch.object(GitCommitService, "create_fix_commit", return_value=result) as create_commit,
        ):
            response = fixes.apply_review_fixes(
                repository_id=repository.id,
                review_id=review.id,
                request=FixApplyRequest(issue_ids=[issue.id for issue in issues], confirm=True),
                db=db,
            )

        self.assertEqual(create_commit.call_count, 1)
        self.assertEqual(response.github_commit_sha, "fix-sha")
        self.assertEqual(response.github_commit_url, result.commit_url)
        self.assertEqual(response.applied_issue_ids, [issue.id for issue in issues])
        self.assertEqual(response.validation_status, "PASSED")
        self.assertEqual(response.repository, "owner/repo")
        self.assertEqual(response.pull_request_number, 42)
        self.assertTrue(response.commit_message.startswith("fix(ai): resolve 2 review findings"))
        self.assertEqual(db.query(FixCommit).count(), 1)
        self.assertEqual(db.query(FixCommit).one().branch_name, "feature")
        self.assertEqual(db.query(FixPullRequest).count(), 0)
        db.close()

    def test_github_pull_request_backfills_missing_pr_number_from_review_job(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        repository = Repository(full_name="owner/repo")
        pull_request = PullRequest(
            repository_ref=repository,
            repository="owner/repo",
            github_pr_id=123,
            pull_request_number=None,
            title="Fix test",
            author="octocat",
        )
        review = Review(
            pull_request=pull_request,
            summary="summary",
            commit_sha="abc123",
        )
        review_job = ReviewJob(
            repository="owner/repo",
            pull_request_number=42,
            commit_sha="abc123",
            status="COMPLETED",
        )
        db.add_all([repository, pull_request, review, review_job])
        db.commit()

        with patch.object(
            fixes,
            "get_pull_request",
            return_value={"head": {"ref": "feature", "sha": "abc123"}},
        ) as get_pull_request:
            result = fixes._github_pull_request(db, review, "token")

        self.assertEqual(result["head"]["sha"], "abc123")
        self.assertEqual(pull_request.pull_request_number, 42)
        get_pull_request.assert_called_once_with(
            repository="owner/repo",
            pull_request_number=42,
            access_token="token",
        )

        db.close()

    def test_github_pull_request_returns_clear_error_when_pr_number_is_missing(self):
        review = SimpleNamespace(
            commit_sha="abc123",
            pull_request=SimpleNamespace(
                repository="owner/repo",
                pull_request_number=None,
            ),
        )
        db = SimpleNamespace(
            query=lambda *_args: SimpleNamespace(
                filter=lambda *_filters: SimpleNamespace(
                    order_by=lambda *_ordering: SimpleNamespace(first=lambda: None)
                )
            )
        )

        with (
            patch.object(fixes, "get_pull_request") as get_pull_request,
            self.assertRaises(HTTPException) as context,
        ):
            fixes._github_pull_request(db, review, "token")

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Pull request number is missing", context.exception.detail)
        get_pull_request.assert_not_called()


class GitCommitServiceTests(unittest.TestCase):
    def setUp(self):
        self.pull_request = {
            "state": "open",
            "head": {
                "ref": "feature/direct-fix",
                "sha": "head-sha",
                "repo": {"full_name": "owner/repo"},
            },
        }

    def test_creates_commit_on_existing_pr_branch_without_new_ref_or_pull_request(self):
        commit_message = (
            "fix(ai): resolve 2 review findings\n\n"
            "Generated by AI Code Review Assistant.\n\n"
            "Addresses:\n- null pointer handling\n- input validation"
        )
        with (
            patch("app.services.git_commit_service.get_repository", return_value={"permissions": {"push": True}}),
            patch("app.services.git_commit_service.get_branch", return_value={"protected": False}),
            patch("app.services.git_commit_service.get_ref", return_value={"object": {"sha": "head-sha"}}),
            patch("app.services.git_commit_service.get_git_commit", return_value={"tree": {"sha": "tree-base"}}),
            patch("app.services.git_commit_service.create_blob", return_value={"sha": "blob-sha"}),
            patch("app.services.git_commit_service.create_tree", return_value={"sha": "tree-new"}),
            patch(
                "app.services.git_commit_service.create_commit",
                return_value={"sha": "commit-sha", "html_url": "https://github.com/owner/repo/commit/commit-sha"},
            ) as create_commit,
            patch("app.services.git_commit_service.update_ref") as update_ref,
        ):
            result = GitCommitService().create_fix_commit(
                repository="owner/repo",
                pull_request=self.pull_request,
                expected_head_sha="head-sha",
                patched_files=[PatchedFile("app.py", "file-sha", "value = 2\n")],
                access_token="token",
                commit_message=commit_message,
            )

        self.assertEqual(result.branch_name, "feature/direct-fix")
        self.assertEqual(result.commit_sha, "commit-sha")
        create_commit.assert_called_once_with(
            repository="owner/repo",
            message=commit_message,
            tree_sha="tree-new",
            parent_sha="head-sha",
            access_token="token",
        )
        update_ref.assert_called_once_with(
            repository="owner/repo",
            branch_name="feature/direct-fix",
            sha="commit-sha",
            access_token="token",
            force=False,
        )

    def test_stale_head_aborts_before_creating_git_objects(self):
        with (
            patch("app.services.git_commit_service.get_repository", return_value={"permissions": {"push": True}}),
            patch("app.services.git_commit_service.get_branch", return_value={"protected": False}),
            patch("app.services.git_commit_service.get_ref", return_value={"object": {"sha": "new-head"}}),
            patch("app.services.git_commit_service.get_git_commit") as get_commit,
            self.assertRaises(StaleHeadError),
        ):
            GitCommitService().create_fix_commit(
                repository="owner/repo",
                pull_request=self.pull_request,
                expected_head_sha="head-sha",
                patched_files=[],
                access_token="token",
                commit_message="fix(ai): resolve review finding",
            )

        get_commit.assert_not_called()

    def test_permission_denied_is_reported(self):
        with (
            patch("app.services.git_commit_service.get_repository", return_value={"permissions": {"push": False}}),
            self.assertRaisesRegex(DirectCommitPermissionError, "does not have repository write access"),
        ):
            GitCommitService().validate_direct_commit_target(
                "owner/repo", self.pull_request, "token"
            )

    def test_fork_branch_is_rejected(self):
        pull_request = {
            **self.pull_request,
            "head": {
                **self.pull_request["head"],
                "repo": {"full_name": "contributor/repo"},
            },
        }
        with self.assertRaisesRegex(DirectCommitPermissionError, "fork branch"):
            GitCommitService().validate_direct_commit_target("owner/repo", pull_request, "token")

    def test_protected_branch_is_rejected(self):
        with (
            patch("app.services.git_commit_service.get_repository", return_value={"permissions": {"push": True}}),
            patch("app.services.git_commit_service.get_branch", return_value={"protected": True}),
            self.assertRaisesRegex(DirectCommitPermissionError, "Branch protection"),
        ):
            GitCommitService().validate_direct_commit_target(
                "owner/repo", self.pull_request, "token"
            )

    def test_base_like_source_branch_is_rejected(self):
        pull_request = {
            **self.pull_request,
            "head": {**self.pull_request["head"], "ref": "release/2026-07"},
        }
        with self.assertRaisesRegex(DirectCommitPermissionError, "Refusing to commit"):
            GitCommitService().validate_direct_commit_target("owner/repo", pull_request, "token")


class GithubNativeFixServiceTests(unittest.TestCase):
    def test_temporary_ai_failure_posts_retry_later_response(self):
        payload = {
            "repository": {"full_name": "owner/repo"},
            "issue": {
                "number": 42,
                "pull_request": {
                    "url": "https://api.github.com/repos/owner/repo/pulls/42",
                },
            },
            "comment": {"body": "/ai-fix all"},
        }
        provider_error = AIReviewServiceError(
            "AI fix generation service is temporarily unavailable.",
            retryable=True,
        )
        db = SimpleNamespace(rollback=Mock())

        with (
            patch.object(
                github_native_fix_service,
                "_run_fix_command",
                side_effect=provider_error,
            ),
            patch.object(
                github_native_fix_service,
                "_post_command_response",
            ) as post_response,
            patch.object(github_native_fix_service.logger, "exception") as log_exception,
        ):
            handled = github_native_fix_service.handle_github_native_fix_comment(
                db=db,
                payload=payload,
                event="issue_comment",
                access_token="token",
            )

        self.assertTrue(handled)
        response_body = post_response.call_args.kwargs["body"]
        self.assertIn("AI Fix temporarily unavailable", response_body)
        self.assertIn("No code or branch was changed", response_body)
        self.assertIn("run the `/ai-fix` command again later", response_body)
        db.rollback.assert_called_once_with()
        log_exception.assert_not_called()

    def test_parse_ai_fix_reply_command(self):
        command = github_native_fix_service._parse_fix_command({
            "comment": {
                "body": "/ai-fix",
            }
        })

        self.assertEqual(command.target, "reply")
        self.assertIsNone(command.issue_id)

    def test_parse_ai_fix_all_command(self):
        command = github_native_fix_service._parse_fix_command({
            "comment": {
                "body": "/ai-fix all",
            }
        })

        self.assertEqual(command.target, "all")
        self.assertIsNone(command.issue_id)

    def test_parse_ai_fix_issue_command(self):
        command = github_native_fix_service._parse_fix_command({
            "comment": {
                "body": "/ai-fix issue 123",
            }
        })

        self.assertEqual(command.target, "issue")
        self.assertEqual(command.issue_id, 123)

    def test_ignores_non_ai_fix_comment(self):
        self.assertIsNone(
            github_native_fix_service._parse_fix_command({
                "comment": {
                    "body": "Looks good to me",
                }
            })
        )

    def test_extracts_pr_number_from_issue_comment_payload(self):
        payload = {
            "issue": {
                "number": 42,
                "pull_request": {
                    "url": "https://api.github.com/repos/owner/repo/pulls/42",
                },
            }
        }

        self.assertEqual(
            github_native_fix_service._pull_request_number_from_payload(payload, "issue_comment"),
            42,
        )

    def test_reply_command_falls_back_to_matching_issue_location(self):
        review = SimpleNamespace(
            pr_id=1,
            issues=[
                SimpleNamespace(
                    id=10,
                    file="calculator.py",
                    line=11,
                    eligible_for_fix=True,
                )
            ],
        )
        payload = {
            "comment": {
                "in_reply_to_id": 999,
                "path": "calculator.py",
                "line": 11,
            }
        }

        class Query:
            def join(self, *_args):
                return self

            def options(self, *_args):
                return self

            def filter(self, *_args):
                return self

            def one_or_none(self):
                return None

        issues = github_native_fix_service._select_command_issues(
            db=SimpleNamespace(query=lambda *_args: Query()),
            review=review,
            command=github_native_fix_service.NativeFixCommand(target="reply"),
            payload=payload,
        )

        self.assertEqual([issue.id for issue in issues], [10])

    def test_response_falls_back_to_pr_comment_when_review_reply_fails(self):
        with (
            patch.object(
                github_native_fix_service,
                "reply_to_review_comment",
                side_effect=RuntimeError("reply failed"),
            ) as reply_to_review_comment,
            patch.object(github_native_fix_service, "post_pr_comment") as post_pr_comment,
            patch.object(github_native_fix_service.logger, "exception"),
        ):
            github_native_fix_service._post_command_response(
                repository="owner/repo",
                pull_request_number=12,
                response_target={
                    "kind": "review_reply",
                    "parent_comment_id": 99,
                },
                access_token="token",
                body="AI Fix failed",
            )

        reply_to_review_comment.assert_called_once()
        post_pr_comment.assert_called_once_with(
            repository="owner/repo",
            pull_request_number=12,
            access_token="token",
            body="AI Fix failed",
        )


def _generated_issue(
    issue_id: int,
    file_path: str,
    replacement_code: str,
    file_sha: str,
):
    return SimpleNamespace(
        id=issue_id,
        file=file_path,
        comment=f"Finding {issue_id}.",
        fix_status="FIX_GENERATED",
        fix_file_path=file_path,
        fix_start_line=1,
        fix_end_line=1,
        fix_replacement_code=replacement_code,
        fix_additional_edits=None,
        fix_explanation="Apply the safe change.",
        fix_base_commit_sha="head",
        fix_file_sha=file_sha,
    )


if __name__ == "__main__":
    unittest.main()
