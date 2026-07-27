import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.schemas.fix_context import (
    AdditionalEdit,
    CallSite,
    FixContext,
    GeneratedFix,
    RelatedFile,
    RelatedSymbol,
    TestContext,
)
from app.services.context_budget_manager import ContextBudgetManager
from app.services.fix_context_builder import FixContextBuilder
from app.services.fix_generation_service import FixGenerationService
from app.services.fix_verifier_service import FixVerifierService
from app.services.patch_service import PatchEdit, PatchService
from app.services.repository_context_service import RepositoryContextService
from app.services.symbol_context_service import SymbolContextService


class EnclosingSymbolBehaviourTests(unittest.TestCase):
    def test_complete_async_function_preserves_decorator_annotations_and_docstring(self):
        source = (
            "@trace(name='load')\n"
            "async def load_user(user_id: int) -> User:\n"
            "    \"\"\"Load one user.\"\"\"\n"
            "    user = await repository.get(user_id)\n"
            "    return user\n"
        )

        context = SymbolContextService().affected_file_context(
            "app/users.py", source, line_start=4, line_end=4
        )

        self.assertEqual(context.enclosing_symbol, "load_user")
        self.assertEqual(context.enclosing_symbol_type, "async_function")
        self.assertEqual(context.enclosing_symbol_start_line, 1)
        self.assertEqual(context.enclosing_symbol_end_line, 5)
        self.assertTrue(context.enclosing_code.startswith("@trace"))
        self.assertIn("async def load_user(user_id: int) -> User", context.enclosing_code)
        self.assertIn('"""Load one user."""', context.enclosing_code)

    def test_method_includes_complete_method_and_class_metadata(self):
        source = (
            "class UserService(BaseService):\n"
            "    repository: Repository = Repository()\n"
            "\n"
            "    @transactional\n"
            "    def save(self, user: User) -> None:\n"
            "        self.repository.add(user)\n"
        )

        context = SymbolContextService().affected_file_context(
            "app/users.py", source, line_start=6, line_end=6
        )

        self.assertEqual(context.enclosing_symbol, "save")
        self.assertEqual(context.enclosing_symbol_type, "method")
        self.assertEqual(context.enclosing_class_name, "UserService")
        self.assertEqual(context.enclosing_class_signature, "class UserService(BaseService)")
        self.assertIn("repository: Repository", "\n".join(context.enclosing_class_attributes))
        self.assertTrue(context.enclosing_code.startswith("    @transactional"))
        self.assertNotIn("class UserService", context.enclosing_code)

    def test_non_python_uses_window_without_claiming_enclosing_symbol(self):
        source = "\n".join(f"line {number}" for number in range(1, 100))

        context = SymbolContextService().affected_file_context(
            "src/app.ts", source, line_start=50, line_end=50
        )

        self.assertIsNone(context.enclosing_symbol)
        self.assertIsNone(context.enclosing_symbol_type)
        self.assertIsNone(context.enclosing_code)
        self.assertIn("50: line 50", context.surrounding_code)
        self.assertNotIn("1: line 1", context.surrounding_code)

    def test_builder_propagates_complete_enclosing_symbol(self):
        source = "def normalize(value: str) -> str:\n    cleaned = value.strip()\n    return cleaned\n"
        builder = _builder_for_source(source)

        context = builder.build(
            issue=_issue(line=2),
            repository="owner/enclosing",
            target_ref="sha-1",
            target_head_sha="sha-1",
            access_token="token",
            pull_request=_pull_request("sha-1"),
        )

        self.assertEqual(context.enclosing_symbol_name, "normalize")
        self.assertEqual(context.enclosing_symbol_type, "function")
        self.assertEqual(context.enclosing_symbol_start_line, 1)
        self.assertEqual(context.enclosing_symbol_end_line, 3)
        self.assertEqual(context.enclosing_code, source.rstrip())


class PullRequestFilesCacheTests(unittest.TestCase):
    def setUp(self):
        FixContextBuilder._file_cache.clear()
        FixContextBuilder._pr_files_cache.clear()
        RepositoryContextService._cache.clear()

    def test_same_repository_pr_and_sha_reuses_cached_files(self):
        fetcher = Mock(return_value=[{"filename": "app.py", "patch": "+a"}])
        builder = FixContextBuilder(pr_files_fetcher=fetcher)

        first = builder._get_pr_files("owner/repo", {"number": 7}, "sha-a", "token")
        second = builder._get_pr_files("owner/repo", {"number": 7}, "sha-a", "token")

        self.assertIs(first, second)
        fetcher.assert_called_once()

    def test_new_head_sha_fetches_fresh_files_and_never_returns_stale_data(self):
        fetcher = Mock(
            side_effect=[
                [{"filename": "old.py", "patch": "+old"}],
                [{"filename": "new.py", "patch": "+new"}],
            ]
        )
        builder = FixContextBuilder(pr_files_fetcher=fetcher)

        old_files = builder._get_pr_files("owner/repo", {"number": 7}, "sha-a", "token")
        new_files = builder._get_pr_files("owner/repo", {"number": 7}, "sha-b", "token")

        self.assertEqual(old_files[0]["filename"], "old.py")
        self.assertEqual(new_files[0]["filename"], "new.py")
        self.assertEqual(fetcher.call_count, 2)

    def test_repositories_with_same_pr_number_do_not_collide(self):
        fetcher = Mock(
            side_effect=[
                [{"filename": "first.py"}],
                [{"filename": "second.py"}],
            ]
        )
        builder = FixContextBuilder(pr_files_fetcher=fetcher)

        first = builder._get_pr_files("owner/first", {"number": 7}, "sha", "token")
        second = builder._get_pr_files("owner/second", {"number": 7}, "sha", "token")

        self.assertNotEqual(first, second)
        self.assertEqual(fetcher.call_count, 2)

    def test_missing_sha_explicitly_bypasses_cache(self):
        fetcher = Mock(side_effect=[[{"filename": "one.py"}], [{"filename": "two.py"}]])
        builder = FixContextBuilder(pr_files_fetcher=fetcher)

        first = builder._get_pr_files("owner/repo", {"number": 7}, "", "token")
        second = builder._get_pr_files("owner/repo", {"number": 7}, "", "token")

        self.assertNotEqual(first, second)
        self.assertEqual(fetcher.call_count, 2)
        self.assertEqual(FixContextBuilder._pr_files_cache, {})

    def test_model_requested_file_is_fetched_once_for_same_sha(self):
        calls = []

        def file_fetcher(repository, file_path, ref, access_token):
            calls.append((file_path, ref))
            if file_path == "app/service.py":
                return {"path": file_path, "sha": "service", "content": "def save(value):\n    return value\n"}
            if file_path == "app/helpers.py":
                return {"path": file_path, "sha": "helper", "content": "def normalize(value):\n    return value.strip()\n"}
            raise RuntimeError("not found")

        builder = FixContextBuilder(
            file_fetcher=file_fetcher,
            pr_files_fetcher=Mock(return_value=[]),
        )
        arguments = dict(
            issue=_issue(line=2),
            repository="owner/requested-file",
            target_ref="sha-request",
            target_head_sha="sha-request",
            access_token="token",
            pull_request=_pull_request("sha-request"),
            missing_files=["app/helpers.py"],
        )

        builder.build(**arguments)
        builder.build(**arguments)

        self.assertEqual(calls.count(("app/helpers.py", "sha-request")), 1)


class ContextBudgetPriorityTests(unittest.TestCase):
    def test_enclosing_function_survives_lower_priority_context_removal(self):
        context = FixContext(
            repository_name="owner/repo",
            source_commit_sha="sha",
            issue_file="app.py",
            issue_line_start=2,
            issue_line_end=2,
            original_code="    return value",
            surrounding_code="1: def save(value):\n2:     return value",
            enclosing_symbol_name="save",
            enclosing_symbol_type="function",
            enclosing_symbol_start_line=1,
            enclosing_symbol_end_line=2,
            enclosing_code="def save(value):\n    return value",
            current_file_content="def save(value):\n" + "    value += 1\n" * 500,
            related_files=[RelatedFile(file_path="large.py", reason="low", content="x\n" * 1000)],
            tests=[TestContext(file_path="tests/test_app.py", reason="test", content="x\n" * 1000)],
            call_sites=[CallSite(file_path="route.py", line=1, symbol="save", code="save()", surrounding_code="x\n" * 1000)],
            related_symbols=[RelatedSymbol(name="helper", kind="function", file_path="helper.py", definition="x\n" * 1000)],
            repository_instructions=["instruction\n" * 1000],
        )

        fitted = ContextBudgetManager(max_tokens=700).fit(context)

        self.assertEqual(fitted.enclosing_code, context.enclosing_code)
        self.assertEqual(fitted.original_code, context.original_code)
        self.assertEqual(fitted.related_files, [])
        self.assertEqual(fitted.tests, [])
        self.assertEqual(fitted.call_sites, [])
        self.assertEqual(fitted.related_symbols, [])
        self.assertEqual(fitted.repository_instructions, [])
        self.assertIn("full_target_file", fitted.context_items_removed)


class FixValidationBehaviourTests(unittest.TestCase):
    def test_original_code_mismatch_is_rejected(self):
        context = _minimal_context("value = load()\n")
        fix = GeneratedFix(
            file_path="app.py",
            start_line=1,
            end_line=1,
            original_code="value = other()",
            replacement_code="value = safe_load()",
        )

        errors = FixGenerationService()._validate_generated_fix_against_context(fix, context)

        self.assertIn("Generated fix original_code does not match", errors[0])

    def test_original_code_validation_uses_untrimmed_source_after_budgeting(self):
        context = _minimal_context("value = load()\n")
        context.current_file_content = (
            "Full target file omitted from prompt due context budget.\n1: value = load()"
        )
        context.validation_file_content = "value = load()\n"
        fix = GeneratedFix(
            file_path="app.py",
            start_line=1,
            end_line=1,
            original_code="value = load()",
            replacement_code="value = load() or None",
        )

        errors = FixGenerationService()._validate_generated_fix_against_context(fix, context)

        self.assertEqual(errors, [])

    def test_prompt_does_not_repeat_identical_numbered_surrounding_code(self):
        context = _minimal_context("def save():\n    return 1\n")
        context.enclosing_code = "def save():\n    return 1"
        context.surrounding_code = "1: def save():\n2:     return 1"

        formatted = FixGenerationService()._format_surrounding_code(context)

        self.assertIn("not repeated", formatted)

    def test_oversized_edit_is_rejected(self):
        context = _minimal_context("\n".join("value = 1" for _ in range(150)))
        result = FixVerifierService().verify(
            context,
            GeneratedFix(file_path="app.py", start_line=1, end_line=121, replacement_code="value = 2"),
        )

        self.assertFalse(result.approved)
        self.assertIn("larger than expected", result.reason)

    def test_multi_file_additional_edits_are_validated_atomically(self):
        context = _minimal_context("value = load()\n").model_copy(
            update={
                "related_files": [
                    RelatedFile(file_path="helper.py", reason="related", content="flag = False\n")
                ]
            }
        )
        fix = GeneratedFix(
            file_path="app.py",
            start_line=1,
            end_line=1,
            original_code="value = load()",
            replacement_code="value = safe_load()",
            additional_edits=[
                AdditionalEdit(
                    file_path="helper.py",
                    start_line=1,
                    end_line=1,
                    original_code="flag = stale",
                    replacement_code="flag = True",
                    reason="Enable safe loading",
                )
            ],
        )

        errors = FixGenerationService()._validate_generated_fix_against_context(fix, context)

        self.assertEqual(len(errors), 1)
        self.assertIn("helper.py", errors[0])


class FixGenerationEndToEndTests(unittest.TestCase):
    def setUp(self):
        FixContextBuilder._file_cache.clear()
        FixContextBuilder._pr_files_cache.clear()
        RepositoryContextService._cache.clear()

    def test_issue_to_context_model_validation_and_patch_application(self):
        target = (
            "from app.helpers import normalize\n\n"
            "def save(value: str) -> str:\n"
            "    cleaned = normalize(value)\n"
            "    return cleaned\n"
        )
        contents = {
            "app/service.py": target,
            "app/helpers.py": "def normalize(value: str) -> str:\n    return value.strip()\n",
            "tests/test_service.py": "def test_save():\n    assert save(' x ') == 'x'\n",
            "pyproject.toml": "[project]\ndependencies = ['pytest']\n",
        }

        def fetcher(repository, file_path, ref, access_token):
            if file_path not in contents:
                raise RuntimeError("not found")
            return {"path": file_path, "sha": f"sha-{file_path}", "content": contents[file_path]}

        builder = FixContextBuilder(
            file_fetcher=fetcher,
            pr_files_fetcher=Mock(
                return_value=[
                    {"filename": "app/service.py", "patch": "@@ -3,3 +3,3 @@\n def save(value):\n     cleaned = normalize(value)\n+    return cleaned"},
                    {"filename": "app/helpers.py", "patch": "+def normalize(value):"},
                    {"filename": "tests/test_service.py", "patch": "+def test_save():"},
                ]
            ),
        )
        issue = _issue(line=5)
        issue.fix_additional_edits = None
        db = SimpleNamespace(add=lambda *_args: None, commit=lambda: None)
        captured_prompt = {}

        def invoke(messages):
            captured_prompt["value"] = messages[1][1]
            return GeneratedFix(
                issue_id=issue.id,
                file_path=issue.file,
                start_line=5,
                end_line=5,
                original_code="    return cleaned",
                replacement_code="return cleaned.strip()",
                explanation="Normalize the returned value.",
            )

        with (
            patch(
                "app.services.fix_generation_service.get_file_content",
                return_value={"path": issue.file, "sha": "target-sha", "content": target},
            ),
            patch("app.services.fix_generation_service.fix_model", SimpleNamespace(invoke=invoke)),
        ):
            FixGenerationService(context_builder=builder).generate_fixes(
                db=db,
                issues=[issue],
                repository="owner/e2e",
                target_ref="head-sha",
                target_head_sha="head-sha",
                access_token="token",
                pull_request=_pull_request("head-sha"),
            )

        self.assertIn("Complete code:\ndef save(value: str) -> str:", captured_prompt["value"])
        self.assertEqual(issue.fix_status, "FIX_GENERATED")
        self.assertIsNone(issue.fix_additional_edits)

        patched = PatchService().build_patched_files(
            file_contents={issue.file: {"sha": "target-sha", "content": target}},
            edits=[
                PatchEdit(
                    file_path=issue.fix_file_path,
                    start_line=issue.fix_start_line,
                    end_line=issue.fix_end_line,
                    replacement_code=issue.fix_replacement_code,
                )
            ],
        )
        self.assertEqual([item.file_path for item in patched], ["app/service.py"])
        self.assertIn("    return cleaned.strip()", patched[0].patched_content)


def _issue(line: int):
    return SimpleNamespace(
        id=17,
        file="app/service.py",
        line=line,
        start_line=None,
        category="bug",
        severity="medium",
        comment="The returned value is not normalized.",
        impact="Whitespace can leak into persisted data.",
        diff_hunk=None,
        fix_file_path=None,
        fix_start_line=None,
        fix_end_line=None,
        fix_replacement_code=None,
        fix_explanation=None,
        fix_base_commit_sha=None,
        fix_file_sha=None,
        fix_status="NO_FIX",
    )


def _pull_request(head_sha: str):
    return {
        "number": 12,
        "title": "Normalize values",
        "body": "Keeps stored values normalized.",
        "head": {"sha": head_sha, "ref": "feature"},
        "base": {"ref": "main", "repo": {"default_branch": "main"}},
    }


def _builder_for_source(source: str) -> FixContextBuilder:
    def fetcher(repository, file_path, ref, access_token):
        if file_path == "app/service.py":
            return {"path": file_path, "sha": "file-sha", "content": source}
        raise RuntimeError("not found")

    return FixContextBuilder(
        file_fetcher=fetcher,
        pr_files_fetcher=Mock(return_value=[{"filename": "app/service.py", "patch": "@@ -2 +2 @@\n+changed"}]),
    )


def _minimal_context(content: str) -> FixContext:
    return FixContext(
        repository_name="owner/repo",
        source_commit_sha="sha",
        issue_file="app.py",
        issue_line_start=1,
        issue_line_end=1,
        original_code=content.splitlines()[0],
        surrounding_code=f"1: {content.splitlines()[0]}",
        current_file_content=content,
    )


if __name__ == "__main__":
    unittest.main()
