import unittest
from unittest.mock import Mock, patch

from app.ai import review_service
from app.schemas.fix_context import RelatedSymbol
from app.schemas.review_context import (
    ReviewContext,
    ReviewEnclosingSymbol,
    ReviewFileContext,
)
from app.services.diff_line_mapper import MultiFileDiffLineMapper
from app.services.repository_context_service import RepositoryContextService
from app.services.review_context_budget_manager import ReviewContextBudgetManager
from app.services.review_context_builder import ReviewContextBuilder


class ReviewContextBuilderTests(unittest.TestCase):
    def setUp(self):
        RepositoryContextService._cache.clear()

    def test_repository_and_enclosing_context_are_added_without_unrelated_files(self):
        calls = []
        contents = {
            "pyproject.toml": (
                "[project]\n"
                "dependencies = ['fastapi', 'sqlalchemy']\n"
                "[tool.pytest.ini_options]\n"
            ),
            "README.md": "FastAPI service using SQLAlchemy. Routes delegate work to services.",
            "app/service.py": (
                "from app.models import User\n\n"
                "def load_user(user_id: int) -> User:\n"
                "    return User.get(user_id)\n"
            ),
        }

        def fetcher(repository, file_path, ref, access_token):
            calls.append((file_path, ref))
            if file_path not in contents:
                raise RuntimeError("not found")
            return {"path": file_path, "sha": ref, "content": contents[file_path]}

        files = [
            {
                "filename": "app/service.py",
                "patch": "@@ -3,2 +3,2 @@\n def load_user(user_id: int) -> User:\n+    return User.get(user_id)",
            }
        ]
        annotated = MultiFileDiffLineMapper.from_files(files).annotated_diff()
        context = ReviewContextBuilder(file_fetcher=fetcher).build(
            repository="owner/repo",
            pull_request=_pull_request("sha-current"),
            source_commit_sha="sha-current",
            files=files,
            annotated_diff=annotated,
            existing_open_issues="- app/service.py:4 [medium/bug] Existing issue.",
            review_mode="incremental",
            access_token="token",
        )

        self.assertEqual(context.language, "Python")
        self.assertEqual(context.framework, "FastAPI")
        self.assertIn("SQLAlchemy", " ".join(context.architecture_summary))
        self.assertTrue(context.style_rules)
        self.assertEqual(context.source_commit_sha, "sha-current")
        self.assertEqual(context.review_mode, "incremental")
        self.assertIn("Existing issue", context.existing_open_issues)
        self.assertEqual([item.file_path for item in context.files], ["app/service.py"])
        self.assertEqual(context.files[0].enclosing_symbols[0].name, "load_user")
        self.assertIn("def load_user", context.files[0].enclosing_symbols[0].code)
        self.assertIn("from app.models import User", context.files[0].relevant_imports)
        self.assertNotIn(("app/unrelated.py", "sha-current"), calls)
        self.assertTrue(all(ref == "sha-current" for _, ref in calls))

    def test_context_from_an_older_commit_is_not_reused(self):
        def fetcher(repository, file_path, ref, access_token):
            if file_path == "app/service.py":
                symbol = "old_handler" if ref == "sha-old" else "new_handler"
                return {
                    "path": file_path,
                    "sha": ref,
                    "content": f"def {symbol}():\n    return '{ref}'\n",
                }
            if file_path == "pyproject.toml":
                return {"path": file_path, "sha": ref, "content": "[project]\ndependencies = []\n"}
            raise RuntimeError("not found")

        builder = ReviewContextBuilder(file_fetcher=fetcher)
        old_files = [{"filename": "app/service.py", "patch": "@@ -1,2 +1,2 @@\n def old_handler():\n+    return 'sha-old'"}]
        new_files = [{"filename": "app/service.py", "patch": "@@ -1,2 +1,2 @@\n def new_handler():\n+    return 'sha-new'"}]

        old = builder.build(
            "owner/repo", _pull_request("sha-old"), "sha-old", old_files,
            MultiFileDiffLineMapper.from_files(old_files).annotated_diff(), "None.", "full", "token"
        )
        new = builder.build(
            "owner/repo", _pull_request("sha-new"), "sha-new", new_files,
            MultiFileDiffLineMapper.from_files(new_files).annotated_diff(), "None.", "incremental", "token"
        )

        self.assertEqual(old.files[0].enclosing_symbols[0].name, "old_handler")
        self.assertEqual(new.files[0].enclosing_symbols[0].name, "new_handler")
        self.assertNotIn("sha-old", new.files[0].enclosing_symbols[0].code)

    def test_multiple_changed_files_retain_separate_context(self):
        def fetcher(repository, file_path, ref, access_token):
            if file_path in {"app/a.py", "app/b.py"}:
                name = file_path[-4]
                return {"path": file_path, "sha": ref, "content": f"def {name}():\n    return 1\n"}
            raise RuntimeError("not found")

        files = [
            {"filename": "app/a.py", "patch": "@@ -1,2 +1,2 @@\n def a():\n+    return 1"},
            {"filename": "app/b.py", "patch": "@@ -1,2 +1,2 @@\n def b():\n+    return 1"},
        ]
        context = ReviewContextBuilder(file_fetcher=fetcher).build(
            "owner/repo", _pull_request("sha"), "sha", files,
            MultiFileDiffLineMapper.from_files(files).annotated_diff(), "None.", "full", "token"
        )

        self.assertEqual([item.file_path for item in context.files], ["app/a.py", "app/b.py"])
        self.assertEqual(context.files[0].enclosing_symbols[0].name, "a")
        self.assertEqual(context.files[1].enclosing_symbols[0].name, "b")
        self.assertIn("FILE: app/a.py", context.files[0].annotated_diff)
        self.assertNotIn("FILE: app/b.py", context.files[0].annotated_diff)

    def test_direct_symbol_definition_from_another_changed_file_is_included(self):
        contents = {
            "app/service.py": (
                "from app.helpers import normalize\n\n"
                "def save(value):\n"
                "    return normalize(value)\n"
            ),
            "app/helpers.py": "def normalize(value):\n    return value.strip()\n",
        }

        def fetcher(repository, file_path, ref, access_token):
            if file_path not in contents:
                raise RuntimeError("not found")
            return {"path": file_path, "sha": ref, "content": contents[file_path]}

        files = [
            {"filename": "app/service.py", "patch": "@@ -3,2 +3,2 @@\n def save(value):\n+    return normalize(value)"},
            {"filename": "app/helpers.py", "patch": "@@ -1,2 +1,2 @@\n def normalize(value):\n+    return value.strip()"},
        ]
        context = ReviewContextBuilder(file_fetcher=fetcher).build(
            "owner/repo", _pull_request("sha"), "sha", files,
            MultiFileDiffLineMapper.from_files(files).annotated_diff(), "None.", "full", "token"
        )

        service_context = next(item for item in context.files if item.file_path == "app/service.py")
        self.assertEqual(service_context.related_symbols[0].name, "normalize")
        self.assertEqual(service_context.related_symbols[0].file_path, "app/helpers.py")


class ReviewContextPromptAndBudgetTests(unittest.TestCase):
    def test_review_prompt_contains_repository_pr_file_and_open_issue_context(self):
        context = _review_context()
        fake_model = _FakeModel()

        with patch.object(review_service, "model", fake_model):
            self.assertEqual(
                review_service.review_code(
                    context.annotated_diff,
                    existing_issues_context=context.existing_open_issues,
                    incremental=True,
                    review_context=context,
                ),
                "ok",
            )

        prompt = fake_model.prompt
        self.assertIn("Language: Python", prompt)
        self.assertIn("Framework: FastAPI", prompt)
        self.assertIn("Routes delegate work to services", prompt)
        self.assertIn("Use Python type hints", prompt)
        self.assertIn("HEAD SHA: sha-current", prompt)
        self.assertIn("Path: app/service.py", prompt)
        self.assertIn("Complete code:\ndef load_user", prompt)
        self.assertIn("Existing nullable dereference", prompt)
        self.assertIn("FILE: app/service.py", prompt)

    def test_review_context_stays_within_configured_budget_by_removing_optional_data(self):
        context = _review_context().model_copy(deep=True)
        context.repository_instructions = ["repository instruction\n" * 500]
        context.files[0].related_symbols = [
            RelatedSymbol(
                name="large_helper",
                kind="function",
                file_path="app/helpers.py",
                definition="value = 1\n" * 1000,
            )
        ]

        fitted = ReviewContextBudgetManager(max_tokens=1000).fit(context)

        self.assertLessEqual(fitted.context_token_estimate, 1000)
        self.assertEqual(fitted.repository_instructions, [])
        self.assertEqual(fitted.files[0].related_symbols, [])
        self.assertIn("FILE: app/service.py", fitted.annotated_diff)


def _review_context() -> ReviewContext:
    annotated_diff = (
        "FILE: app/service.py\n"
        "[line_ref=L1 | new_file_line=4 | old_file_line=- | ADDED] return User.get(user_id)"
    )
    return ReviewContext(
        repository_name="owner/repo",
        language="Python",
        framework="FastAPI",
        architecture_summary=["Routes delegate work to services."],
        style_rules=["Use Python type hints."],
        pull_request_number=12,
        pull_request_title="Load users",
        pull_request_description="Adds user loading.",
        source_branch="feature",
        target_branch="main",
        source_commit_sha="sha-current",
        changed_files=["app/service.py"],
        annotated_diff=annotated_diff,
        files=[
            ReviewFileContext(
                file_path="app/service.py",
                language="Python",
                annotated_diff=annotated_diff,
                relevant_imports=["from app.models import User"],
                enclosing_symbols=[
                    ReviewEnclosingSymbol(
                        name="load_user",
                        symbol_type="function",
                        start_line=3,
                        end_line=4,
                        code="def load_user(user_id: int) -> User:\n    return User.get(user_id)",
                    )
                ],
            )
        ],
        existing_open_issues="- app/service.py:4 [medium/bug] Existing nullable dereference.",
        review_mode="incremental",
    )


def _pull_request(head_sha: str):
    return {
        "number": 12,
        "title": "Load users",
        "body": "Adds user loading.",
        "head": {"sha": head_sha, "ref": "feature"},
        "base": {
            "ref": "main",
            "repo": {"description": "User API", "default_branch": "main"},
        },
    }


class _FakeModel:
    def __init__(self):
        self.prompt = None

    def invoke(self, prompt):
        self.prompt = prompt
        return "ok"


if __name__ == "__main__":
    unittest.main()
