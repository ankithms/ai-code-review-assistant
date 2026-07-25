import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, PullRequest, Repository, Review, ReviewJob
from app.routes import fixes
from app.services import github_native_fix_service
from app.services.fix_generation_service import FixGenerationService, GeneratedFixSchema
from app.services.patch_service import PatchEdit, PatchService
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
    def test_apply_requires_explicit_confirmation(self):
        with self.assertRaises(HTTPException) as context:
            fixes.apply_review_fixes(
                repository_id=1,
                review_id=2,
                request=SimpleNamespace(
                    issue_ids=[3],
                    mode=SimpleNamespace(value="BRANCH_PR"),
                    confirm=False,
                    confirm_direct_commit=False,
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

    def test_active_fix_pull_request_makes_issue_ineligible(self):
        issue = SimpleNamespace(
            id=123,
            blocking_fix_pull_request=SimpleNamespace(github_pr_number=45),
        )

        with self.assertRaises(HTTPException) as context:
            fixes._validate_issues_eligible_for_fix([issue])

        self.assertEqual(context.exception.status_code, 400)
        self.assertIn("Issue 123 is already included in Fix PR #45", context.exception.detail)

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


class GithubNativeFixServiceTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
