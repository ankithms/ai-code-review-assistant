import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.schemas.fix_context import FixContext, GeneratedFix, RelatedFile, RelatedSymbol
from app.services.context_budget_manager import ContextBudgetManager
from app.services.fix_context_builder import FixContextBuilder
from app.services.fix_generation_service import FixGenerationService
from app.services.fix_verifier_service import FixVerifierService
from app.services.repository_context_service import RepositoryContextService
from app.services.symbol_context_service import SymbolContextService
from app.services.test_context_service import TestContextService


class SymbolContextServiceTests(unittest.TestCase):
    def test_extracts_complete_enclosing_function_and_imports(self):
        source = (
            "import os\n"
            "from app.models import User\n"
            "\n"
            "class Service:\n"
            "    def load_user(self, user_id: int) -> User:\n"
            "        user = User(id=user_id)\n"
            "        return user\n"
        )

        context = SymbolContextService().affected_file_context(
            file_path="app/services/users.py",
            content=source,
            line_start=6,
            line_end=6,
        )

        self.assertEqual(context.enclosing_symbol, "load_user")
        self.assertIn("from app.models import User", context.imports)
        self.assertIn("def load_user", context.enclosing_code)
        self.assertIn("User", context.referenced_symbols)

    def test_extracts_class_context_when_issue_is_on_class_body(self):
        source = (
            "class Repository(BaseRepository):\n"
            "    table = 'repositories'\n"
            "\n"
            "    def get(self):\n"
            "        return self.table\n"
        )

        context = SymbolContextService().affected_file_context(
            file_path="app/repositories/repository.py",
            content=source,
            line_start=2,
            line_end=2,
        )

        self.assertEqual(context.enclosing_symbol, "Repository")
        self.assertIn("class Repository(BaseRepository):", context.enclosing_code)

    def test_retrieves_related_symbols_and_call_sites(self):
        files = {
            "app/service.py": (
                "from app.helpers import normalize\n"
                "\n"
                "def save(value):\n"
                "    return normalize(value)\n"
            ),
            "app/helpers.py": (
                "def normalize(value: str) -> str:\n"
                "    return value.strip()\n"
            ),
            "app/routes.py": (
                "from app.service import save\n"
                "\n"
                "def route():\n"
                "    return save(' x ')\n"
            ),
        }
        service = SymbolContextService()

        related = service.related_symbols(
            file_contents=files,
            referenced_symbols={"normalize"},
            target_file="app/service.py",
            changed_files={"app/helpers.py"},
        )
        call_sites = service.call_sites(
            file_contents=files,
            symbol_name="save",
            target_file="app/service.py",
            changed_files={"app/routes.py"},
        )

        self.assertEqual(related[0].name, "normalize")
        self.assertEqual(related[0].file_path, "app/helpers.py")
        self.assertEqual(call_sites[0].file_path, "app/routes.py")


class RepositoryAndBudgetContextTests(unittest.TestCase):
    def test_repository_context_is_summarised_and_cached_by_commit(self):
        fetcher = Mock(
            side_effect=lambda repository, file_path, ref, access_token: {
                "path": file_path,
                "sha": "sha",
                "content": {
                    "README.md": "FastAPI service using SQLAlchemy and Dramatiq.",
                    "pyproject.toml": "[project]\ndependencies = ['fastapi', 'sqlalchemy', 'pytest']\n",
                }.get(file_path, ""),
            }
        )
        service = RepositoryContextService(file_fetcher=fetcher)

        first = service.build_context("owner/repo", "abc", "token")
        second = service.build_context("owner/repo", "abc", "token")

        self.assertIs(first, second)
        self.assertEqual(first.language, "Python")
        self.assertEqual(first.framework, "FastAPI")
        self.assertIn("SQLAlchemy", " ".join(first.architecture_summary))

    def test_context_budget_prioritises_symbols_before_related_files(self):
        context = FixContext(
            repository_name="owner/repo",
            source_commit_sha="abc",
            issue_file="app.py",
            issue_line_start=1,
            issue_line_end=1,
            original_code="x = 1",
            surrounding_code="1: x = 1",
            current_file_content="x = 1",
            related_symbols=[
                RelatedSymbol(
                    name="helper",
                    kind="function",
                    file_path="helpers.py",
                    definition="def helper():\n    return 1",
                    relevance_score=5,
                )
            ],
            related_files=[
                RelatedFile(
                    file_path="large.py",
                    reason="low value",
                    content="x\n" * 1000,
                    relevance_score=1,
                )
            ],
        )

        fitted = ContextBudgetManager(max_tokens=500).fit(context)

        self.assertEqual(len(fitted.related_symbols), 1)
        self.assertEqual(fitted.related_files, [])


class TestContextServiceTests(unittest.TestCase):
    def test_collects_matching_changed_tests(self):
        tests = TestContextService(file_fetcher=Mock(side_effect=RuntimeError("not found"))).collect_tests(
            repository="owner/repo",
            ref="abc",
            access_token="token",
            affected_file="app/services/users.py",
            enclosing_symbol="load_user",
            known_file_contents={
                "backend/tests/test_users.py": "def test_load_user():\n    assert load_user(1)\n",
                "backend/tests/test_other.py": "def test_other(): pass\n",
            },
        )

        self.assertEqual([test.file_path for test in tests], ["backend/tests/test_users.py"])


class FixGenerationContextIntegrationTests(unittest.TestCase):
    def test_insufficient_context_is_retried_once_with_requested_files(self):
        source = "def save(value):\n    return value\n"
        issue = SimpleNamespace(
            id=7,
            file="app/service.py",
            line=2,
            start_line=None,
            category="bug",
            severity="medium",
            comment="Needs normalization.",
            impact="Whitespace is persisted.",
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

        class CapturingBuilder:
            def __init__(self):
                self.calls = []

            def build(self, **kwargs):
                self.calls.append(kwargs)
                return FixContext(
                    repository_name=kwargs["repository"],
                    source_commit_sha=kwargs["target_head_sha"],
                    issue_id=issue.id,
                    issue_file=issue.file,
                    issue_line_start=2,
                    issue_line_end=2,
                    original_code="    return value",
                    surrounding_code="1: def save(value):\n2:     return value",
                    current_file_content=source,
                    missing_files_requested=kwargs.get("missing_files") or [],
                )

        builder = CapturingBuilder()
        fix_model = SimpleNamespace(
            invoke=Mock(
                side_effect=[
                    GeneratedFix(
                        requires_more_context=True,
                        missing_files=["app/helpers.py"],
                        insufficient_context_reason="Need normalize helper.",
                    ),
                    GeneratedFix(
                        issue_id=7,
                        file_path="app/service.py",
                        start_line=2,
                        end_line=2,
                        original_code="    return value",
                        replacement_code="    return value.strip()",
                    ),
                ]
            )
        )

        with (
            patch(
                "app.services.fix_generation_service.get_file_content",
                return_value={"path": "app/service.py", "sha": "sha", "content": source},
            ),
            patch("app.services.fix_generation_service.fix_model", fix_model),
        ):
            FixGenerationService(context_builder=builder).generate_fixes(
                db=db,
                issues=[issue],
                repository="owner/repo",
                target_ref="head",
                target_head_sha="head",
                access_token="token",
            )

        self.assertEqual(fix_model.invoke.call_count, 2)
        self.assertEqual(builder.calls[1]["missing_files"], ["app/helpers.py"])
        self.assertEqual(issue.fix_replacement_code, "    return value.strip()")

    def test_hallucinated_import_is_rejected_by_verifier(self):
        context = FixContext(
            repository_name="owner/repo",
            source_commit_sha="abc",
            issue_file="app.py",
            issue_line_start=1,
            issue_line_end=1,
            original_code="value = load()",
            surrounding_code="1: value = load()",
            current_file_content="value = load()\n",
            imports=["from app.services import load"],
        )
        result = FixVerifierService().verify(
            context,
            GeneratedFix(
                file_path="app.py",
                start_line=1,
                end_line=1,
                replacement_code="value = RepositoryService.load()",
                imports_required=["from app.repositories import RepositoryService"],
            ),
        )

        self.assertFalse(result.approved)
        self.assertIn("Required imports", result.reason)


class FixContextBuilderTests(unittest.TestCase):
    def test_builder_includes_target_file_pr_diff_and_previous_error(self):
        def fetcher(repository, file_path, ref, access_token):
            contents = {
                "app/service.py": "import os\n\ndef save(value):\n    return value\n",
                "app/helpers.py": "def normalize(value):\n    return value.strip()\n",
                "tests/test_service.py": "def test_save():\n    assert save('x') == 'x'\n",
                "pyproject.toml": "[project]\ndependencies = ['fastapi', 'pytest']\n",
            }
            if file_path not in contents:
                raise RuntimeError("missing")
            return {"path": file_path, "sha": "sha", "content": contents[file_path]}

        builder = FixContextBuilder(
            file_fetcher=fetcher,
            pr_files_fetcher=Mock(
                return_value=[
                    {
                        "filename": "app/service.py",
                        "patch": "@@ def save(value):\n-    return value\n+    return value",
                    },
                    {"filename": "app/helpers.py", "patch": "+def normalize(value):"},
                ]
            ),
        )
        issue = SimpleNamespace(
            id=1,
            file="app/service.py",
            line=4,
            start_line=None,
            category="bug",
            severity="medium",
            comment="Does not normalize.",
            impact="Bad data.",
            diff_hunk=None,
        )

        context = builder.build(
            issue=issue,
            repository="owner/repo",
            target_ref="head",
            target_head_sha="head",
            access_token="token",
            pull_request={
                "number": 12,
                "title": "Normalize input",
                "body": "Adds save flow.",
                "head": {"sha": "head", "ref": "feature"},
                "base": {"ref": "main", "repo": {"default_branch": "main"}},
            },
            previous_fix=GeneratedFix(file_path="app/service.py", start_line=4, end_line=4, replacement_code="bad"),
            validation_errors=["NameError: normalize is not imported"],
        )

        self.assertEqual(context.pull_request_number, 12)
        self.assertIn("@@ def save", context.relevant_diff)
        self.assertEqual(context.previous_validation_errors, ["NameError: normalize is not imported"])
        self.assertIn("import os", context.imports)
