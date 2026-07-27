import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.services.context_budget_manager import ContextBudgetManager
from app.services.fix_context_builder import FixContextBuilder
from app.services.fix_generation_service import FixGenerationService
from app.services.repository_context_service import RepositoryContextService
from app.services.symbol_context_service import SourceLanguage, SymbolContextService


class PythonCommonInterfaceTests(unittest.TestCase):
    def test_python_ast_uses_common_result_with_definitions_and_calls(self):
        source = (
            "from app.users import load\n\n"
            "@trace\n"
            "async def fetch(user_id: int) -> User:\n"
            "    return await load(user_id)\n"
        )

        result = SymbolContextService().extract_structural_context(
            "app/service.py", source, 5, 5
        )

        self.assertEqual(result.language, SourceLanguage.PYTHON)
        self.assertEqual(result.parser_used, "python_ast")
        self.assertTrue(result.extraction_succeeded)
        self.assertEqual(result.enclosing_symbol_name, "fetch")
        self.assertTrue(result.enclosing_code.startswith("@trace"))
        self.assertIn("from app.users import load", result.imports)
        self.assertIn("fetch", [definition.name for definition in result.definitions])
        self.assertIn("load", [call.symbol for call in result.call_sites])


class JavaScriptSymbolExtractionTests(unittest.TestCase):
    def setUp(self):
        self.service = SymbolContextService()

    def test_function_declaration_and_es_module_import(self):
        source = (
            "import client, { normalize as clean } from './client';\n\n"
            "export async function loadUser(id) {\n"
            "  return client.get(clean(id));\n"
            "}\n"
        )

        result = self.service.extract_structural_context("src/users.js", source, 4, 4)

        self.assertTrue(result.extraction_succeeded)
        self.assertEqual(result.language, SourceLanguage.JAVASCRIPT)
        self.assertEqual(result.parser_used, "tree_sitter_javascript")
        self.assertEqual(result.enclosing_symbol_name, "loadUser")
        self.assertEqual(result.enclosing_symbol_type, "async_function")
        self.assertEqual((result.enclosing_symbol_start_line, result.enclosing_symbol_end_line), (3, 5))
        self.assertTrue(result.enclosing_code.startswith("export async function loadUser"))
        self.assertIn("import client", result.imports[0])
        self.assertIn("clean", result.referenced_symbols)

    def test_arrow_function_and_commonjs_require(self):
        source = (
            "const helper = require('./helper');\n\n"
            "const save = (value) => {\n"
            "  const cleaned = helper.normalize(value);\n"
            "  return cleaned;\n"
            "};\n"
        )

        result = self.service.extract_structural_context("src/save.js", source, 4, 4)

        self.assertEqual(result.enclosing_symbol_name, "save")
        self.assertEqual(result.enclosing_symbol_type, "function")
        self.assertEqual((result.enclosing_symbol_start_line, result.enclosing_symbol_end_line), (3, 6))
        self.assertIn("const save =", result.enclosing_code)
        self.assertIn("require('./helper')", result.imports[0])

    def test_class_method_and_method_call_sites(self):
        source = (
            "class UserService {\n"
            "  constructor(repository) {\n"
            "    this.repository = repository;\n"
            "  }\n"
            "  async load(id) {\n"
            "    return this.repository.get(id);\n"
            "  }\n"
            "}\n\n"
            "new UserService().load(1);\n"
        )

        constructor = self.service.extract_structural_context("src/users.js", source, 3, 3)
        result = self.service.extract_structural_context("src/users.js", source, 6, 6)

        self.assertEqual(constructor.enclosing_symbol_name, "constructor")
        self.assertEqual(constructor.enclosing_symbol_type, "constructor")
        self.assertEqual(result.enclosing_symbol_name, "load")
        self.assertEqual(result.enclosing_symbol_type, "method")
        self.assertEqual(result.enclosing_class_name, "UserService")
        self.assertTrue(result.enclosing_code.startswith("  async load"))
        self.assertIn("get", [call.symbol for call in result.call_sites])
        self.assertIn("load", [call.symbol for call in result.call_sites])


class TypeScriptSymbolExtractionTests(unittest.TestCase):
    def setUp(self):
        self.service = SymbolContextService()

    def test_generic_typed_function_interface_type_alias_and_enum_definitions(self):
        source = (
            "interface Entity { id: string }\n"
            "type EntityId = Entity['id'];\n"
            "enum State { Ready, Pending }\n\n"
            "export function identity<T extends Entity>(value: T): T {\n"
            "  return value;\n"
            "}\n"
        )

        result = self.service.extract_structural_context("src/types.ts", source, 6, 6)

        self.assertEqual(result.language, SourceLanguage.TYPESCRIPT)
        self.assertEqual(result.enclosing_symbol_name, "identity")
        self.assertIn("identity<T extends Entity>(value: T): T", result.enclosing_code)
        definitions = {(item.name, item.kind) for item in result.definitions}
        self.assertIn(("Entity", "interface"), definitions)
        self.assertIn(("EntityId", "type_alias"), definitions)
        self.assertIn(("State", "enum"), definitions)
        self.assertIn(("identity", "function"), definitions)

    def test_decorated_class_method_preserves_decorator_modifiers_and_types(self):
        source = (
            "@sealed\n"
            "class Repository<T> {\n"
            "  @transactional\n"
            "  public async save(value: T): Promise<T> {\n"
            "    return value;\n"
            "  }\n"
            "}\n"
        )

        result = self.service.extract_structural_context("src/repository.ts", source, 5, 5)

        self.assertEqual(result.enclosing_symbol_name, "save")
        self.assertEqual(result.enclosing_symbol_type, "method")
        self.assertEqual(result.enclosing_symbol_start_line, 3)
        self.assertTrue(result.enclosing_code.startswith("  @transactional"))
        self.assertIn("public async save(value: T): Promise<T>", result.enclosing_code)
        self.assertEqual(result.enclosing_class_name, "Repository")
        self.assertEqual(result.enclosing_class_signature, "class Repository<T>")


class ReactSymbolExtractionTests(unittest.TestCase):
    def setUp(self):
        self.service = SymbolContextService()

    def test_jsx_function_component_and_event_handler(self):
        source = (
            "import React from 'react';\n\n"
            "export function Button({ label }) {\n"
            "  const handleClick = () => onSelect(label);\n"
            "  return <button onClick={handleClick}><Icon />{label}</button>;\n"
            "}\n"
        )

        component = self.service.extract_structural_context("src/Button.jsx", source, 5, 5)
        handler = self.service.extract_structural_context("src/Button.jsx", source, 4, 4)

        self.assertEqual(component.enclosing_symbol_name, "Button")
        self.assertEqual(component.enclosing_symbol_type, "component")
        self.assertIn("<button", component.enclosing_code)
        self.assertIn("Icon", [call.symbol for call in component.call_sites])
        self.assertEqual(handler.enclosing_symbol_name, "handleClick")
        self.assertEqual(handler.enclosing_symbol_type, "event_handler")

    def test_react_class_component_is_recognized(self):
        source = (
            "class Panel extends React.Component {\n"
            "  render() {\n"
            "    return <section>{this.props.children}</section>;\n"
            "  }\n"
            "}\n"
        )

        result = self.service.extract_structural_context("src/Panel.jsx", source, 1, 1)

        self.assertEqual(result.enclosing_symbol_name, "Panel")
        self.assertEqual(result.enclosing_symbol_type, "component")
        self.assertIn("render()", result.enclosing_code)

    def test_tsx_component_props_interface_and_state_are_available(self):
        source = (
            "import { useState } from 'react';\n"
            "interface Props { label: string }\n\n"
            "export const Button = ({ label }: Props) => {\n"
            "  const [count, setCount] = useState(0);\n"
            "  return <button onClick={() => setCount(count + 1)}>{label}</button>;\n"
            "};\n"
        )

        result = self.service.extract_structural_context("src/Button.tsx", source, 5, 5)

        self.assertEqual(result.language, SourceLanguage.TSX)
        self.assertEqual(result.enclosing_symbol_name, "Button")
        self.assertEqual(result.enclosing_symbol_type, "component")
        self.assertIn("useState", result.enclosing_code)
        self.assertIn(("Props", "interface"), {(item.name, item.kind) for item in result.definitions})

    def test_custom_hook_and_use_effect_callback(self):
        source = (
            "import { useEffect } from 'react';\n\n"
            "export function useRefresh(refresh) {\n"
            "  useEffect(() => {\n"
            "    refresh();\n"
            "  }, [refresh]);\n"
            "}\n"
        )

        hook = self.service.extract_structural_context("src/useRefresh.tsx", source, 3, 3)
        callback = self.service.extract_structural_context("src/useRefresh.tsx", source, 5, 5)

        self.assertEqual(hook.enclosing_symbol_name, "useRefresh")
        self.assertEqual(hook.enclosing_symbol_type, "hook")
        self.assertEqual(callback.enclosing_symbol_name, "useEffect callback")
        self.assertEqual(callback.enclosing_symbol_type, "callback")
        self.assertTrue(callback.enclosing_code.strip().startswith("useEffect("))


class MultiLanguageFallbackTests(unittest.TestCase):
    def setUp(self):
        self.service = SymbolContextService()

    def test_unsupported_extension_uses_explicit_text_fallback(self):
        context = self.service.affected_file_context("src/main.go", "package main\nfunc main() {}\n", 2, 2)

        self.assertFalse(context.extraction_succeeded)
        self.assertEqual(context.language, SourceLanguage.UNKNOWN)
        self.assertEqual(context.parser_used, "text_window")
        self.assertIsNone(context.enclosing_symbol)
        self.assertIn("Unsupported file extension", context.fallback_reason)

    def test_repository_metadata_is_used_when_extension_is_unknown(self):
        self.assertEqual(
            self.service.detect_language("src/template.inc", repository_language="TypeScript"),
            SourceLanguage.TYPESCRIPT,
        )

    def test_malformed_typescript_uses_fallback_without_claiming_symbol(self):
        context = self.service.affected_file_context(
            "src/app.ts",
            "function broken(value: string {\n  return value;\n",
            2,
            2,
        )

        self.assertFalse(context.extraction_succeeded)
        self.assertEqual(context.parser_used, "tree_sitter_typescript")
        self.assertIsNone(context.enclosing_symbol)
        self.assertIn("malformed", context.fallback_reason)
        self.assertIn("2:   return value;", context.surrounding_code)

    def test_parser_unavailable_uses_fallback(self):
        with patch.object(
            self.service,
            "_tree_sitter_parser",
            return_value=(None, "tree_sitter_javascript", "parser unavailable in test"),
        ):
            context = self.service.affected_file_context(
                "src/app.js", "function load() {\n  return 1;\n}\n", 2, 2
            )

        self.assertFalse(context.extraction_succeeded)
        self.assertIsNone(context.enclosing_code)
        self.assertEqual(context.fallback_reason, "parser unavailable in test")


class MultiLanguagePipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        FixContextBuilder._file_cache.clear()
        FixContextBuilder._pr_files_cache.clear()
        RepositoryContextService._cache.clear()

    def test_tsx_context_reaches_fix_context_prompt_and_survives_budgeting(self):
        source = (
            "import { useState } from 'react';\n"
            "interface Props { initial: number }\n\n"
            "export const Counter = ({ initial }: Props) => {\n"
            "  const [count, setCount] = useState(initial);\n"
            "  return <button onClick={() => setCount(count + 1)}>{count}</button>;\n"
            "};\n"
        )

        def fetcher(repository, file_path, ref, access_token):
            if file_path == "src/Counter.tsx":
                return {"path": file_path, "sha": "file-sha", "content": source}
            raise RuntimeError("not found")

        issue = SimpleNamespace(
            id=41,
            file="src/Counter.tsx",
            line=6,
            start_line=None,
            category="bug",
            severity="medium",
            comment="The counter can update from stale state.",
            impact="Rapid clicks can lose updates.",
            diff_hunk=None,
        )
        builder = FixContextBuilder(
            file_fetcher=fetcher,
            pr_files_fetcher=Mock(
                return_value=[
                    {
                        "filename": "src/Counter.tsx",
                        "patch": "@@ -4,3 +4,3 @@\n export const Counter = ({ initial }: Props) => {\n   const [count, setCount] = useState(initial);\n+  return <button onClick={() => setCount(count + 1)}>{count}</button>;",
                    }
                ]
            ),
        )
        context = builder.build(
            issue=issue,
            repository="owner/react",
            target_ref="head-sha",
            target_head_sha="head-sha",
            access_token="token",
            pull_request={
                "number": 9,
                "title": "Counter",
                "head": {"sha": "head-sha", "ref": "counter"},
                "base": {"ref": "main", "repo": {"default_branch": "main"}},
            },
        )

        fitted = ContextBudgetManager(max_tokens=1200).fit(
            context.model_copy(
                update={
                    "current_file_content": source + ("// unrelated\n" * 1000),
                    "repository_instructions": ["long instruction\n" * 500],
                }
            )
        )
        prompt = FixGenerationService()._build_prompt(fitted)

        self.assertEqual(context.structural_language, "tsx")
        self.assertEqual(context.structural_parser_used, "tree_sitter_tsx")
        self.assertTrue(context.structural_extraction_succeeded)
        self.assertEqual(context.enclosing_symbol_name, "onClick handler")
        self.assertEqual(context.enclosing_symbol_type, "event_handler")
        self.assertEqual(context.enclosing_class_name, "Counter")
        self.assertIn("useState", "\n".join(context.enclosing_class_attributes))
        self.assertIn("() => setCount", fitted.enclosing_code)
        self.assertIn("Parser: tree_sitter_tsx", prompt)
        self.assertIn("Complete code:\n() => setCount", prompt)
        self.assertIn("Enclosing class/component: Counter", prompt)

    def test_javascript_and_typescript_context_reach_fix_context_and_prompt(self):
        cases = [
            (
                "src/save.js",
                "export const save = (value) => {\n  return value.trim();\n};\n",
                2,
                "javascript",
                "tree_sitter_javascript",
                "save",
            ),
            (
                "src/save.ts",
                "export function save<T extends string>(value: T): string {\n  return value.trim();\n}\n",
                2,
                "typescript",
                "tree_sitter_typescript",
                "save",
            ),
        ]
        for file_path, source, line, language, parser, symbol in cases:
            with self.subTest(file_path=file_path):
                repository = f"owner/{language}"

                def fetcher(repository, file_path: str, ref, access_token):
                    if file_path == case_file_path:
                        return {"path": file_path, "sha": "file-sha", "content": source}
                    raise RuntimeError("not found")

                case_file_path = file_path

                issue = SimpleNamespace(
                    id=52,
                    file=file_path,
                    line=line,
                    start_line=None,
                    category="bug",
                    severity="medium",
                    comment="Value handling is incorrect.",
                    impact="The result can be wrong.",
                    diff_hunk=None,
                )
                context = FixContextBuilder(
                    file_fetcher=fetcher,
                    pr_files_fetcher=Mock(
                        return_value=[
                            {"filename": file_path, "patch": "@@ -1,2 +1,2 @@\n declaration\n+changed"}
                        ]
                    ),
                ).build(
                    issue=issue,
                    repository=repository,
                    target_ref="head",
                    target_head_sha="head",
                    access_token="token",
                    pull_request={"number": 3, "head": {"sha": "head"}},
                )
                prompt = FixGenerationService()._build_prompt(context)

                self.assertEqual(context.structural_language, language)
                self.assertEqual(context.structural_parser_used, parser)
                self.assertEqual(context.enclosing_symbol_name, symbol)
                self.assertIn("return value.trim()", context.enclosing_code)
                self.assertIn(f"Parser: {parser}", prompt)
                self.assertIn("return value.trim()", prompt)

    def test_javascript_symbol_index_and_call_site_discovery_use_tree_sitter(self):
        files = {
            "src/helper.js": "export function normalize(value) { return value.trim(); }\n",
            "src/service.js": "import { normalize } from './helper';\nexport const save = (value) => normalize(value);\n",
            "src/route.js": "import { save } from './service';\nsave(' x ');\n",
        }

        related = SymbolContextService().related_symbols(
            files,
            referenced_symbols={"normalize"},
            target_file="src/service.js",
            changed_files=set(files),
        )
        calls = SymbolContextService().call_sites(
            files,
            symbol_name="save",
            target_file="src/service.js",
            changed_files=set(files),
        )

        self.assertEqual(related[0].name, "normalize")
        self.assertEqual(related[0].file_path, "src/helper.js")
        self.assertEqual(calls[0].file_path, "src/route.js")


if __name__ == "__main__":
    unittest.main()
