import ast
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from app.schemas.fix_context import CallSite, RelatedSymbol


class SourceLanguage(str, Enum):
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    JSX = "jsx"
    TYPESCRIPT = "typescript"
    TSX = "tsx"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SymbolExtractionResult:
    language: SourceLanguage
    parser_used: str
    extraction_succeeded: bool
    enclosing_symbol_name: str | None = None
    enclosing_symbol_type: str | None = None
    enclosing_symbol_start_line: int | None = None
    enclosing_symbol_end_line: int | None = None
    enclosing_code: str | None = None
    enclosing_class_name: str | None = None
    enclosing_class_signature: str | None = None
    enclosing_class_attributes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    referenced_symbols: set[str] = field(default_factory=set)
    definitions: list[RelatedSymbol] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    fallback_reason: str | None = None


@dataclass(frozen=True)
class AffectedFileContext:
    original_code: str
    surrounding_code: str
    enclosing_symbol: str | None
    enclosing_symbol_type: str | None
    enclosing_symbol_start_line: int | None
    enclosing_symbol_end_line: int | None
    enclosing_code: str | None
    enclosing_class_name: str | None
    enclosing_class_signature: str | None
    enclosing_class_attributes: list[str]
    imports: list[str]
    referenced_symbols: set[str] = field(default_factory=set)
    language: SourceLanguage = SourceLanguage.UNKNOWN
    parser_used: str = "text_window"
    extraction_succeeded: bool = False
    fallback_reason: str | None = None


class SymbolContextService:
    _symbol_index_cache: dict[str, list[RelatedSymbol]] = {}

    def affected_file_context(
        self,
        file_path: str,
        content: str,
        line_start: int,
        line_end: int | None = None,
        repository_language: str | None = None,
    ) -> AffectedFileContext:
        line_end = line_end or line_start
        result = self.extract_structural_context(
            file_path=file_path,
            content=content,
            line_start=line_start,
            line_end=line_end,
            repository_language=repository_language,
        )
        return self._affected_context_from_result(
            content=content,
            line_start=line_start,
            line_end=line_end,
            result=result,
        )

    def detect_language(
        self,
        file_path: str,
        repository_language: str | None = None,
    ) -> SourceLanguage:
        suffix = PurePosixPath(file_path).suffix.lower()
        by_extension = {
            ".py": SourceLanguage.PYTHON,
            ".js": SourceLanguage.JAVASCRIPT,
            ".mjs": SourceLanguage.JAVASCRIPT,
            ".cjs": SourceLanguage.JAVASCRIPT,
            ".jsx": SourceLanguage.JSX,
            ".ts": SourceLanguage.TYPESCRIPT,
            ".mts": SourceLanguage.TYPESCRIPT,
            ".cts": SourceLanguage.TYPESCRIPT,
            ".tsx": SourceLanguage.TSX,
        }
        if suffix in by_extension:
            return by_extension[suffix]

        normalized = (repository_language or "").lower()
        if normalized == "python":
            return SourceLanguage.PYTHON
        if normalized == "javascript":
            return SourceLanguage.JAVASCRIPT
        if normalized == "typescript":
            return SourceLanguage.TYPESCRIPT
        return SourceLanguage.UNKNOWN

    def extract_structural_context(
        self,
        file_path: str,
        content: str,
        line_start: int,
        line_end: int,
        repository_language: str | None = None,
    ) -> SymbolExtractionResult:
        language = self.detect_language(file_path, repository_language)
        if language == SourceLanguage.PYTHON:
            return self._python_extraction_result(
                file_path=file_path,
                content=content,
                line_start=line_start,
                line_end=line_end,
            )
        if language in {
            SourceLanguage.JAVASCRIPT,
            SourceLanguage.JSX,
            SourceLanguage.TYPESCRIPT,
            SourceLanguage.TSX,
        }:
            return self._tree_sitter_extraction_result(
                file_path=file_path,
                content=content,
                line_start=line_start,
                line_end=line_end,
                language=language,
            )
        return SymbolExtractionResult(
            language=language,
            parser_used="text_window",
            extraction_succeeded=False,
            fallback_reason=f"Unsupported file extension: {PurePosixPath(file_path).suffix or 'none'}",
        )

    def affected_file_contexts(
        self,
        file_path: str,
        content: str,
        line_ranges: list[tuple[int, int]],
        repository_language: str | None = None,
    ) -> list[AffectedFileContext]:
        if not line_ranges:
            return []
        language = self.detect_language(file_path, repository_language)
        if language in {
            SourceLanguage.JAVASCRIPT,
            SourceLanguage.JSX,
            SourceLanguage.TYPESCRIPT,
            SourceLanguage.TSX,
        }:
            parser, parser_used, parser_error = self._tree_sitter_parser(language)
            source_bytes = content.encode("utf-8")
            try:
                tree = parser.parse(source_bytes) if parser is not None else None
            except Exception as exc:
                tree = None
                parser_error = f"Tree-sitter parsing failed: {exc}"
            if tree is None or tree.root_node.has_error:
                reason = parser_error or "Tree-sitter reported incomplete or malformed syntax"
                return [
                    self._window_context(
                        content,
                        line_start,
                        line_end,
                        language=language,
                        parser_used=parser_used,
                        fallback_reason=reason,
                    )
                    for line_start, line_end in line_ranges
                ]
            contexts = [
                self._affected_context_from_result(
                    content,
                    line_start,
                    line_end,
                    self._tree_sitter_extraction_result_from_tree(
                        file_path=file_path,
                        content=content,
                        line_start=line_start,
                        line_end=line_end,
                        language=language,
                        parser_used=parser_used,
                        tree=tree,
                        source_bytes=source_bytes,
                    ),
                )
                for line_start, line_end in line_ranges
            ]
            return self._deduplicate_contexts(contexts)
        if language != SourceLanguage.PYTHON:
            return [
                self.affected_file_context(
                    file_path,
                    content,
                    line_start,
                    line_end,
                    repository_language=repository_language,
                )
                for line_start, line_end in line_ranges
            ]

        try:
            tree = ast.parse(content)
        except SyntaxError:
            return [
                self._window_context(
                    content,
                    line_start,
                    line_end,
                    language=SourceLanguage.PYTHON,
                    parser_used="python_ast",
                    fallback_reason="Python syntax parsing failed",
                )
                for line_start, line_end in line_ranges
            ]

        contexts = []
        for line_start, line_end in line_ranges:
            context = self._python_affected_file_context_from_tree(
                content=content,
                tree=tree,
                line_start=line_start,
                line_end=line_end,
            )
            contexts.append(context)
        return self._deduplicate_contexts(contexts)

    def _deduplicate_contexts(
        self,
        contexts: list[AffectedFileContext],
    ) -> list[AffectedFileContext]:
        deduplicated = []
        seen_symbols = set()
        for context in contexts:
            identity = (
                context.enclosing_symbol,
                context.enclosing_symbol_start_line,
                context.enclosing_symbol_end_line,
                context.fallback_reason,
            )
            if identity in seen_symbols:
                continue
            seen_symbols.add(identity)
            deduplicated.append(context)
        return deduplicated

    def related_symbols(
        self,
        file_contents: dict[str, str],
        referenced_symbols: set[str],
        target_file: str,
        changed_files: set[str] | None = None,
        max_symbols: int = 10,
    ) -> list[RelatedSymbol]:
        if not referenced_symbols:
            return []

        changed_files = changed_files or set()
        index = self.build_symbol_index(file_contents)
        matches = []
        for symbol in index:
            if symbol.name not in referenced_symbols:
                continue

            score = 2.0
            if symbol.file_path == target_file:
                score += 3
            if symbol.file_path in changed_files:
                score += 1.5
            matches.append(symbol.model_copy(update={"relevance_score": score}))

        return sorted(matches, key=lambda item: item.relevance_score, reverse=True)[:max_symbols]

    def call_sites(
        self,
        file_contents: dict[str, str],
        symbol_name: str | None,
        target_file: str,
        changed_files: set[str] | None = None,
        max_call_sites: int = 8,
    ) -> list[CallSite]:
        if not symbol_name:
            return []

        changed_files = changed_files or set()
        calls = []
        for file_path, content in file_contents.items():
            language = self.detect_language(file_path)
            if language in {
                SourceLanguage.JAVASCRIPT,
                SourceLanguage.JSX,
                SourceLanguage.TYPESCRIPT,
                SourceLanguage.TSX,
            }:
                result = self.extract_structural_context(
                    file_path,
                    content,
                    line_start=1,
                    line_end=1,
                )
                if result.extraction_succeeded:
                    for call in result.call_sites:
                        if call.symbol != symbol_name:
                            continue
                        calls.append(
                            call.model_copy(
                                update={
                                    "relevance_score": self._call_site_score(
                                        file_path,
                                        target_file,
                                        changed_files,
                                    )
                                }
                            )
                        )
                    continue
                calls.extend(self._text_call_sites(file_path, content, symbol_name))
                continue
            if language != SourceLanguage.PYTHON:
                calls.extend(self._text_call_sites(file_path, content, symbol_name))
                continue

            try:
                tree = ast.parse(content)
            except SyntaxError:
                calls.extend(self._text_call_sites(file_path, content, symbol_name))
                continue

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if self._call_name(node.func) != symbol_name:
                    continue
                line = getattr(node, "lineno", None)
                if not line:
                    continue
                calls.append(
                    CallSite(
                        file_path=file_path,
                        line=line,
                        symbol=symbol_name,
                        code=self._line_at(content, line),
                        surrounding_code=self._line_window(content, line, line, 5),
                        relevance_score=self._call_site_score(file_path, target_file, changed_files),
                    )
                )

        return sorted(calls, key=lambda item: item.relevance_score, reverse=True)[:max_call_sites]

    def build_symbol_index(self, file_contents: dict[str, str]) -> list[RelatedSymbol]:
        cache_key = self._content_cache_key(file_contents)
        cached = self._symbol_index_cache.get(cache_key)
        if cached is not None:
            return cached

        symbols = []
        for file_path, content in file_contents.items():
            language = self.detect_language(file_path)
            if language == SourceLanguage.PYTHON:
                symbols.extend(self._python_symbols(file_path, content))
            elif language in {
                SourceLanguage.JAVASCRIPT,
                SourceLanguage.JSX,
                SourceLanguage.TYPESCRIPT,
                SourceLanguage.TSX,
            }:
                result = self.extract_structural_context(
                    file_path,
                    content,
                    line_start=1,
                    line_end=1,
                )
                if result.extraction_succeeded:
                    symbols.extend(result.definitions)

        self._symbol_index_cache[cache_key] = symbols
        return symbols

    def _python_affected_file_context(
        self,
        content: str,
        line_start: int,
        line_end: int,
    ) -> AffectedFileContext:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._window_context(
                content,
                line_start,
                line_end,
                language=SourceLanguage.PYTHON,
                parser_used="python_ast",
                fallback_reason="Python syntax parsing failed",
            )

        return self._python_affected_file_context_from_tree(
            content=content,
            tree=tree,
            line_start=line_start,
            line_end=line_end,
        )

    def _python_extraction_result(
        self,
        file_path: str,
        content: str,
        line_start: int,
        line_end: int,
    ) -> SymbolExtractionResult:
        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return SymbolExtractionResult(
                language=SourceLanguage.PYTHON,
                parser_used="python_ast",
                extraction_succeeded=False,
                fallback_reason=f"Python syntax parsing failed: {exc.msg}",
            )

        affected = self._python_affected_file_context_from_tree(
            content=content,
            tree=tree,
            line_start=line_start,
            line_end=line_end,
        )
        return SymbolExtractionResult(
            language=SourceLanguage.PYTHON,
            parser_used="python_ast",
            extraction_succeeded=True,
            enclosing_symbol_name=affected.enclosing_symbol,
            enclosing_symbol_type=affected.enclosing_symbol_type,
            enclosing_symbol_start_line=affected.enclosing_symbol_start_line,
            enclosing_symbol_end_line=affected.enclosing_symbol_end_line,
            enclosing_code=affected.enclosing_code,
            enclosing_class_name=affected.enclosing_class_name,
            enclosing_class_signature=affected.enclosing_class_signature,
            enclosing_class_attributes=affected.enclosing_class_attributes,
            imports=affected.imports,
            referenced_symbols=affected.referenced_symbols,
            definitions=self._python_symbols_from_tree(file_path, content, tree),
            call_sites=self._python_call_sites_from_tree(file_path, content, tree),
        )

    def _python_affected_file_context_from_tree(
        self,
        content: str,
        tree: ast.AST,
        line_start: int,
        line_end: int,
    ) -> AffectedFileContext:

        enclosing_nodes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and getattr(node, "lineno", 0) <= line_start
            and getattr(node, "end_lineno", 0) >= line_end
        ]
        enclosing_nodes.sort(key=lambda node: (node.end_lineno - node.lineno, node.lineno))
        enclosing_node = enclosing_nodes[0] if enclosing_nodes else None
        enclosing_class = self._containing_class(tree, enclosing_node)

        imports = [
            ast.get_source_segment(content, node) or self._line_at(content, node.lineno)
            for node in tree.body
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]

        referenced_symbols = self._referenced_symbols(enclosing_node or tree)
        original_code = self._plain_line_range(content, line_start, line_end)
        surrounding_code = self._line_window(content, line_start, line_end, 30)
        enclosing_code = self._source_for_node(content, enclosing_node) if enclosing_node else None
        enclosing_name = self._symbol_name(enclosing_node) if enclosing_node else None
        enclosing_type = self._enclosing_symbol_type(enclosing_node, enclosing_class)
        enclosing_start_line = self._node_start_line(enclosing_node) if enclosing_node else None
        enclosing_end_line = getattr(enclosing_node, "end_lineno", None)

        return AffectedFileContext(
            original_code=original_code,
            surrounding_code=surrounding_code,
            enclosing_symbol=enclosing_name,
            enclosing_symbol_type=enclosing_type,
            enclosing_symbol_start_line=enclosing_start_line,
            enclosing_symbol_end_line=enclosing_end_line,
            enclosing_code=enclosing_code,
            enclosing_class_name=self._symbol_name(enclosing_class),
            enclosing_class_signature=self._signature(enclosing_class),
            enclosing_class_attributes=self._class_attributes(content, enclosing_class),
            imports=imports,
            referenced_symbols=referenced_symbols,
            language=SourceLanguage.PYTHON,
            parser_used="python_ast",
            extraction_succeeded=True,
        )

    def _affected_context_from_result(
        self,
        content: str,
        line_start: int,
        line_end: int,
        result: SymbolExtractionResult,
    ) -> AffectedFileContext:
        if not result.extraction_succeeded:
            return self._window_context(
                content,
                line_start,
                line_end,
                language=result.language,
                parser_used=result.parser_used,
                fallback_reason=result.fallback_reason,
            )
        return AffectedFileContext(
            original_code=self._plain_line_range(content, line_start, line_end),
            surrounding_code=self._line_window(content, line_start, line_end, 30),
            enclosing_symbol=result.enclosing_symbol_name,
            enclosing_symbol_type=result.enclosing_symbol_type,
            enclosing_symbol_start_line=result.enclosing_symbol_start_line,
            enclosing_symbol_end_line=result.enclosing_symbol_end_line,
            enclosing_code=result.enclosing_code,
            enclosing_class_name=result.enclosing_class_name,
            enclosing_class_signature=result.enclosing_class_signature,
            enclosing_class_attributes=result.enclosing_class_attributes,
            imports=result.imports,
            referenced_symbols=result.referenced_symbols,
            language=result.language,
            parser_used=result.parser_used,
            extraction_succeeded=True,
        )

    def _window_context(
        self,
        content: str,
        line_start: int,
        line_end: int,
        language: SourceLanguage = SourceLanguage.UNKNOWN,
        parser_used: str = "text_window",
        fallback_reason: str | None = None,
    ) -> AffectedFileContext:
        return AffectedFileContext(
            original_code=self._plain_line_range(content, line_start, line_end),
            surrounding_code=self._line_window(content, line_start, line_end, 30),
            enclosing_symbol=None,
            enclosing_symbol_type=None,
            enclosing_symbol_start_line=None,
            enclosing_symbol_end_line=None,
            enclosing_code=None,
            enclosing_class_name=None,
            enclosing_class_signature=None,
            enclosing_class_attributes=[],
            imports=[],
            referenced_symbols=set(),
            language=language,
            parser_used=parser_used,
            extraction_succeeded=False,
            fallback_reason=fallback_reason,
        )

    def _containing_class(
        self,
        tree: ast.AST,
        enclosing_node: ast.AST | None,
    ) -> ast.ClassDef | None:
        if enclosing_node is None:
            return None
        if isinstance(enclosing_node, ast.ClassDef):
            return enclosing_node

        classes = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)
            and node.lineno <= getattr(enclosing_node, "lineno", 0)
            and node.end_lineno >= getattr(enclosing_node, "end_lineno", 0)
        ]
        classes.sort(key=lambda node: (node.end_lineno - node.lineno, node.lineno))
        return classes[0] if classes else None

    def _enclosing_symbol_type(
        self,
        node: ast.AST | None,
        enclosing_class: ast.ClassDef | None,
    ) -> str | None:
        if isinstance(node, ast.ClassDef):
            return "class"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and enclosing_class is not None:
            return "method"
        if isinstance(node, ast.AsyncFunctionDef):
            return "async_function"
        if isinstance(node, ast.FunctionDef):
            return "function"
        return None

    def _node_start_line(self, node: ast.AST) -> int:
        decorator_lines = [
            getattr(decorator, "lineno", node.lineno)
            for decorator in getattr(node, "decorator_list", [])
        ]
        return min([node.lineno, *decorator_lines])

    def _source_for_node(self, content: str, node: ast.AST) -> str:
        return self._plain_line_range(
            content,
            self._node_start_line(node),
            getattr(node, "end_lineno", node.lineno),
        )

    def _class_attributes(self, content: str, node: ast.ClassDef | None) -> list[str]:
        if node is None:
            return []

        attributes = []
        for child in node.body:
            if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                continue
            source = ast.get_source_segment(content, child)
            if source:
                attributes.append(source)
        return attributes

    def _python_symbols(self, file_path: str, content: str) -> list[RelatedSymbol]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []
        return self._python_symbols_from_tree(file_path, content, tree)

    def _python_symbols_from_tree(
        self,
        file_path: str,
        content: str,
        tree: ast.AST,
    ) -> list[RelatedSymbol]:
        symbols = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            definition = ast.get_source_segment(content, node)
            if not definition:
                continue
            symbols.append(
                RelatedSymbol(
                    name=node.name,
                    kind=self._node_kind(node),
                    file_path=file_path,
                    signature=self._signature(node),
                    definition=definition,
                    docstring=ast.get_docstring(node),
                    start_line=node.lineno,
                    end_line=node.end_lineno,
                )
            )
        return symbols

    def _python_call_sites_from_tree(
        self,
        file_path: str,
        content: str,
        tree: ast.AST,
    ) -> list[CallSite]:
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            symbol = self._call_name(node.func)
            line = getattr(node, "lineno", None)
            if not symbol or not line:
                continue
            calls.append(
                CallSite(
                    file_path=file_path,
                    line=line,
                    symbol=symbol,
                    code=self._line_at(content, line),
                    surrounding_code=self._line_window(content, line, line, 5),
                )
            )
        return calls

    def _tree_sitter_extraction_result(
        self,
        file_path: str,
        content: str,
        line_start: int,
        line_end: int,
        language: SourceLanguage,
    ) -> SymbolExtractionResult:
        parser, parser_used, parser_error = self._tree_sitter_parser(language)
        if parser is None:
            return SymbolExtractionResult(
                language=language,
                parser_used=parser_used,
                extraction_succeeded=False,
                fallback_reason=parser_error or "Tree-sitter parser is unavailable",
            )

        source_bytes = content.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:
            return SymbolExtractionResult(
                language=language,
                parser_used=parser_used,
                extraction_succeeded=False,
                fallback_reason=f"Tree-sitter parsing failed: {exc}",
            )
        if tree.root_node.has_error:
            return SymbolExtractionResult(
                language=language,
                parser_used=parser_used,
                extraction_succeeded=False,
                fallback_reason="Tree-sitter reported incomplete or malformed syntax",
            )

        return self._tree_sitter_extraction_result_from_tree(
            file_path=file_path,
            content=content,
            line_start=line_start,
            line_end=line_end,
            language=language,
            parser_used=parser_used,
            tree=tree,
            source_bytes=source_bytes,
        )

    def _tree_sitter_extraction_result_from_tree(
        self,
        file_path: str,
        content: str,
        line_start: int,
        line_end: int,
        language: SourceLanguage,
        parser_used: str,
        tree: Any,
        source_bytes: bytes,
    ) -> SymbolExtractionResult:
        enclosing_node = self._ts_enclosing_symbol(
            tree.root_node,
            line_start,
            line_end,
        )
        symbol_node = self._ts_symbol_container(enclosing_node) if enclosing_node else None
        enclosing_class = self._ts_containing_class(enclosing_node)
        enclosing_scope = enclosing_class or self._ts_containing_function_scope(
            enclosing_node,
            source_bytes,
        )
        name = self._ts_symbol_name(enclosing_node, source_bytes)
        symbol_type = self._ts_symbol_type(
            enclosing_node,
            name,
            language,
            source_bytes,
            enclosing_class,
        )
        if enclosing_scope is None and symbol_type == "component":
            enclosing_scope = enclosing_node
        code = self._ts_code_with_decorators(symbol_node or enclosing_node, source_bytes)
        start_node = symbol_node or enclosing_node
        decorated_start = self._ts_decorated_start_node(start_node)

        return SymbolExtractionResult(
            language=language,
            parser_used=parser_used,
            extraction_succeeded=True,
            enclosing_symbol_name=name,
            enclosing_symbol_type=symbol_type,
            enclosing_symbol_start_line=(decorated_start.start_point.row + 1) if decorated_start else None,
            enclosing_symbol_end_line=(start_node.end_point.row + 1) if start_node else None,
            enclosing_code=code or None,
            enclosing_class_name=(
                self._ts_name_field(enclosing_class, source_bytes)
                if enclosing_class
                else self._ts_symbol_name(enclosing_scope, source_bytes)
            ),
            enclosing_class_signature=self._ts_signature(
                self._ts_symbol_container(enclosing_scope),
                source_bytes,
            ),
            enclosing_class_attributes=(
                self._ts_class_attributes(enclosing_class, source_bytes)
                if enclosing_class
                else self._ts_component_metadata(enclosing_scope, source_bytes)
            ),
            imports=self._ts_imports(tree.root_node, source_bytes),
            referenced_symbols=self._ts_referenced_symbols(enclosing_node or tree.root_node, source_bytes),
            definitions=self._ts_definitions(file_path, tree.root_node, source_bytes),
            call_sites=self._ts_call_sites(file_path, content, tree.root_node, source_bytes),
        )

    def _tree_sitter_parser(
        self,
        language: SourceLanguage,
    ) -> tuple[Any | None, str, str | None]:
        parser_used = f"tree_sitter_{language.value}"
        try:
            from tree_sitter import Language, Parser

            if language in {SourceLanguage.JAVASCRIPT, SourceLanguage.JSX}:
                import tree_sitter_javascript

                grammar = tree_sitter_javascript.language()
            else:
                import tree_sitter_typescript

                grammar = (
                    tree_sitter_typescript.language_tsx()
                    if language == SourceLanguage.TSX
                    else tree_sitter_typescript.language_typescript()
                )
            return Parser(Language(grammar)), parser_used, None
        except (ImportError, OSError, TypeError, ValueError) as exc:
            return None, parser_used, f"Tree-sitter parser unavailable: {exc}"

    def _walk_ts(self, node: Any):
        yield node
        for child in node.children:
            yield from self._walk_ts(child)

    def _ts_enclosing_symbol(self, root: Any, line_start: int, line_end: int) -> Any | None:
        symbol_types = {
            "function_declaration",
            "generator_function_declaration",
            "function_expression",
            "arrow_function",
            "method_definition",
            "class_declaration",
            "abstract_class_declaration",
        }
        start_row = max(0, line_start - 1)
        end_row = max(start_row, line_end - 1)
        candidates = [
            node
            for node in self._walk_ts(root)
            if node.type in symbol_types
            and node.start_point.row <= start_row
            and node.end_point.row >= end_row
        ]
        candidates.sort(key=lambda node: (node.end_byte - node.start_byte, node.start_byte))
        return candidates[0] if candidates else None

    def _ts_symbol_container(self, node: Any | None) -> Any | None:
        if node is None:
            return None
        if node.parent and node.parent.type == "export_statement":
            return node.parent
        if node.type not in {"arrow_function", "function_expression"}:
            return node
        parent = node.parent
        if parent and parent.type == "variable_declarator":
            parent = parent.parent or parent
            if parent.parent and parent.parent.type == "export_statement":
                parent = parent.parent
            return parent
        if parent and parent.type in {"arguments", "argument_list"}:
            call = parent.parent
            if call and call.type == "call_expression":
                statement = call.parent
                return statement if statement and statement.type == "expression_statement" else call
        return node

    def _ts_symbol_name(self, node: Any | None, source: bytes) -> str | None:
        if node is None:
            return None
        name = self._ts_name_field(node, source)
        if name:
            return name
        if node.type in {"arrow_function", "function_expression"}:
            parent = node.parent
            if parent and parent.type == "variable_declarator":
                return self._ts_text(parent.child_by_field_name("name"), source)
            if parent and parent.type in {"arguments", "argument_list"}:
                call = parent.parent
                function = call.child_by_field_name("function") if call else None
                call_name = self._ts_text(function, source)
                if call_name:
                    return f"{call_name} callback"
            current = parent
            while current is not None:
                if current.type == "jsx_attribute":
                    name_node = current.child_by_field_name("name")
                    if name_node is None:
                        name_node = next(
                            (
                                child
                                for child in current.named_children
                                if child.type in {"property_identifier", "identifier"}
                            ),
                            None,
                        )
                    attribute_name = self._ts_text(name_node, source)
                    if attribute_name:
                        return f"{attribute_name} handler"
                    break
                current = current.parent
        return None

    def _ts_symbol_type(
        self,
        node: Any | None,
        name: str | None,
        language: SourceLanguage,
        source: bytes,
        enclosing_class: Any | None,
    ) -> str | None:
        if node is None:
            return None
        if node.type in {"class_declaration", "abstract_class_declaration"}:
            signature = self._ts_signature(node, source) or ""
            return "component" if "Component" in signature else "class"
        if node.type == "method_definition":
            return "constructor" if name == "constructor" else "method"
        if name and name.endswith(" callback"):
            return "callback"
        if name and name.startswith("use") and len(name) > 3 and name[3].isupper():
            return "hook"
        if (
            name
            and name[:1].isupper()
            and self._ts_contains_jsx(node)
        ):
            return "component"
        if name and (name.startswith("handle") or name.startswith("on")):
            return "event_handler"
        node_text = self._ts_text(node, source).lstrip()
        if node_text.startswith("async ") or " async " in node_text[:40]:
            return "async_function" if enclosing_class is None else "method"
        return "function"

    def _ts_containing_class(self, node: Any | None) -> Any | None:
        current = node.parent if node else None
        while current is not None:
            if current.type in {"class_declaration", "abstract_class_declaration"}:
                return current
            current = current.parent
        return None

    def _ts_containing_function_scope(self, node: Any | None, source: bytes) -> Any | None:
        current = node.parent if node else None
        function_types = {
            "function_declaration",
            "generator_function_declaration",
            "function_expression",
            "arrow_function",
        }
        while current is not None:
            if current.type in function_types and self._ts_symbol_name(current, source):
                return current
            current = current.parent
        return None

    def _ts_name_field(self, node: Any | None, source: bytes) -> str | None:
        if node is None:
            return None
        return self._ts_text(node.child_by_field_name("name"), source) or None

    def _ts_text(self, node: Any | None, source: bytes) -> str:
        if node is None:
            return ""
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _ts_decorated_start_node(self, node: Any | None) -> Any | None:
        if node is None:
            return None
        start = node
        sibling = node.prev_named_sibling
        while sibling is not None and sibling.type == "decorator":
            start = sibling
            sibling = sibling.prev_named_sibling
        return start

    def _ts_code_with_decorators(self, node: Any | None, source: bytes) -> str:
        if node is None:
            return ""
        start = self._ts_decorated_start_node(node) or node
        if node.type in {"arrow_function", "function_expression"}:
            return source[start.start_byte:node.end_byte].decode("utf-8", errors="replace")
        line_start = source.rfind(b"\n", 0, start.start_byte) + 1
        return source[line_start:node.end_byte].decode("utf-8", errors="replace")

    def _ts_signature(self, node: Any | None, source: bytes) -> str | None:
        text = self._ts_text(node, source).strip()
        if not text:
            return None
        lines = [line for line in text.splitlines() if not line.lstrip().startswith("@")]
        if not lines:
            return None
        first_line = lines[0]
        if "{" in first_line:
            return first_line.split("{", 1)[0].rstrip()
        return first_line

    def _ts_class_attributes(self, node: Any | None, source: bytes) -> list[str]:
        if node is None:
            return []
        body = node.child_by_field_name("body")
        if body is None:
            return []
        attribute_types = {
            "field_definition",
            "public_field_definition",
            "property_signature",
            "required_parameter",
        }
        return [
            self._ts_text(child, source)
            for child in body.children
            if child.type in attribute_types and self._ts_text(child, source)
        ]

    def _ts_component_metadata(self, node: Any | None, source: bytes) -> list[str]:
        if node is None:
            return []
        relevant_hooks = ("useState", "useEffect", "useMemo", "useCallback", "useRef")
        metadata = []
        for child in self._walk_ts(node):
            if child.type not in {"lexical_declaration", "variable_declaration"}:
                continue
            text = self._ts_text(child, source)
            if any(hook in text for hook in relevant_hooks):
                metadata.append(text)
        return list(dict.fromkeys(metadata))

    def _ts_imports(self, root: Any, source: bytes) -> list[str]:
        imports = []
        for node in self._walk_ts(root):
            if node.type == "import_statement":
                imports.append(self._ts_text(node, source))
                continue
            if node.type != "call_expression":
                continue
            function = node.child_by_field_name("function")
            if self._ts_text(function, source) != "require":
                continue
            container = node
            while container.parent and container.parent.type not in {"program", "statement_block"}:
                container = container.parent
            imports.append(self._ts_text(container, source))
        return list(dict.fromkeys(item for item in imports if item))

    def _ts_referenced_symbols(self, node: Any, source: bytes) -> set[str]:
        reference_types = {
            "identifier",
            "type_identifier",
            "property_identifier",
            "shorthand_property_identifier",
        }
        return {
            self._ts_text(child, source)
            for child in self._walk_ts(node)
            if child.type in reference_types and self._ts_text(child, source)
        }

    def _ts_definitions(self, file_path: str, root: Any, source: bytes) -> list[RelatedSymbol]:
        definitions = []
        seen = set()
        direct_types = {
            "function_declaration": "function",
            "generator_function_declaration": "function",
            "class_declaration": "class",
            "abstract_class_declaration": "class",
            "interface_declaration": "interface",
            "type_alias_declaration": "type_alias",
            "enum_declaration": "enum",
            "method_definition": "method",
        }
        for node in self._walk_ts(root):
            definition_node = node
            kind = direct_types.get(node.type)
            name = self._ts_name_field(node, source) if kind else None
            if kind and node.parent and node.parent.type == "export_statement":
                definition_node = node.parent
            if node.type == "variable_declarator":
                name = self._ts_text(node.child_by_field_name("name"), source)
                value = node.child_by_field_name("value")
                if not name or value is None:
                    continue
                kind = "function" if value.type in {"arrow_function", "function_expression"} else "constant"
                definition_node = node.parent or node
                if definition_node.parent and definition_node.parent.type == "export_statement":
                    definition_node = definition_node.parent
            if not name or not kind:
                continue
            identity = (name, definition_node.start_byte, definition_node.end_byte)
            if identity in seen:
                continue
            seen.add(identity)
            definition = self._ts_text(definition_node, source)
            definitions.append(
                RelatedSymbol(
                    name=name,
                    kind=kind,
                    file_path=file_path,
                    signature=self._ts_signature(definition_node, source),
                    definition=definition,
                    start_line=definition_node.start_point.row + 1,
                    end_line=definition_node.end_point.row + 1,
                )
            )
        return definitions

    def _ts_call_sites(
        self,
        file_path: str,
        content: str,
        root: Any,
        source: bytes,
    ) -> list[CallSite]:
        calls = []
        for node in self._walk_ts(root):
            symbol = None
            if node.type == "call_expression":
                function_text = self._ts_text(node.child_by_field_name("function"), source)
                symbol = function_text.rsplit(".", 1)[-1]
            elif node.type in {"jsx_opening_element", "jsx_self_closing_element"}:
                name_node = node.child_by_field_name("name")
                symbol = self._ts_text(name_node, source)
            if not symbol:
                continue
            line = node.start_point.row + 1
            calls.append(
                CallSite(
                    file_path=file_path,
                    line=line,
                    symbol=symbol,
                    code=self._line_at(content, line),
                    surrounding_code=self._line_window(content, line, line, 5),
                )
            )
        return calls

    def _ts_contains_jsx(self, node: Any) -> bool:
        return any(child.type.startswith("jsx_") for child in self._walk_ts(node))

    def _referenced_symbols(self, node: ast.AST) -> set[str]:
        names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
                names.add(child.id)
            elif isinstance(child, ast.Call):
                call_name = self._call_name(child.func)
                if call_name:
                    names.add(call_name)
            elif isinstance(child, ast.Attribute):
                names.add(child.attr)
        return names

    def _signature(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.ClassDef):
            bases = [ast.unparse(base) for base in node.bases]
            return f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            returns = f" -> {ast.unparse(node.returns)}" if node.returns else ""
            return f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"
        return None

    def _call_name(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    def _symbol_name(self, node: ast.AST | None) -> str | None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return node.name
        return None

    def _node_kind(self, node: ast.AST) -> str:
        if isinstance(node, ast.AsyncFunctionDef):
            return "async_function"
        if isinstance(node, ast.FunctionDef):
            return "function"
        return "class"

    def _line_window(
        self,
        content: str,
        line_start: int,
        line_end: int,
        padding: int,
    ) -> str:
        lines = content.splitlines()
        start = max(1, line_start - padding)
        end = min(len(lines), line_end + padding)
        return "\n".join(
            f"{line_number}: {lines[line_number - 1]}"
            for line_number in range(start, end + 1)
        )

    def _line_at(self, content: str, line_number: int) -> str:
        lines = content.splitlines()
        if line_number < 1 or line_number > len(lines):
            return ""
        return lines[line_number - 1]

    def _plain_line_range(self, content: str, line_start: int, line_end: int) -> str:
        lines = content.splitlines()
        start = max(1, line_start)
        end = min(len(lines), line_end)
        if end < start:
            return ""
        return "\n".join(lines[start - 1:end])

    def _text_call_sites(
        self,
        file_path: str,
        content: str,
        symbol_name: str,
    ) -> list[CallSite]:
        pattern = re.compile(rf"\b{re.escape(symbol_name)}\s*\(")
        calls = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not pattern.search(line):
                continue
            calls.append(
                CallSite(
                    file_path=file_path,
                    line=line_number,
                    symbol=symbol_name,
                    code=line,
                    surrounding_code=self._line_window(content, line_number, line_number, 5),
                )
            )
        return calls

    def _call_site_score(
        self,
        file_path: str,
        target_file: str,
        changed_files: set[str],
    ) -> float:
        score = 1.0
        if file_path == target_file:
            score += 1
        if file_path in changed_files:
            score += 2
        if "/tests/" in file_path or file_path.startswith("tests/"):
            score += 1
        return score

    def _content_cache_key(self, file_contents: dict[str, str]) -> str:
        digest = hashlib.sha256()
        for file_path in sorted(file_contents):
            digest.update(file_path.encode())
            digest.update(b"\0")
            digest.update(file_contents[file_path].encode(errors="ignore"))
            digest.update(b"\0")
        return digest.hexdigest()
