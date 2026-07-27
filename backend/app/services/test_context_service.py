from collections.abc import Callable
from pathlib import PurePosixPath

from app.github.github_service import get_file_content
from app.schemas.fix_context import TestContext


class TestContextService:
    __test__ = False

    def __init__(
        self,
        file_fetcher: Callable[[str, str, str, str], dict] | None = None,
    ) -> None:
        self.file_fetcher = file_fetcher or get_file_content

    def collect_tests(
        self,
        repository: str,
        ref: str,
        access_token: str,
        affected_file: str,
        enclosing_symbol: str | None,
        known_file_contents: dict[str, str],
        max_tests: int = 6,
    ) -> list[TestContext]:
        tests_by_path: dict[str, TestContext] = {}

        for file_path, content in known_file_contents.items():
            if self._is_test_file(file_path) and self._matches_context(
                file_path=file_path,
                content=content,
                affected_file=affected_file,
                enclosing_symbol=enclosing_symbol,
            ):
                tests_by_path[file_path] = TestContext(
                    file_path=file_path,
                    reason="Changed test file matches the affected file or symbol.",
                    content=content,
                    relevance_score=4,
                )

        for candidate in self._candidate_test_paths(affected_file):
            if candidate in tests_by_path:
                continue
            try:
                payload = self.file_fetcher(
                    repository=repository,
                    file_path=candidate,
                    ref=ref,
                    access_token=access_token,
                )
            except Exception:
                continue
            content = payload.get("content")
            if not content:
                continue
            tests_by_path[candidate] = TestContext(
                file_path=candidate,
                reason="Likely test file for the affected module.",
                content=content,
                relevance_score=3,
            )

        return sorted(
            tests_by_path.values(),
            key=lambda item: item.relevance_score,
            reverse=True,
        )[:max_tests]

    def _candidate_test_paths(self, affected_file: str) -> list[str]:
        path = PurePosixPath(affected_file)
        stem = path.stem
        candidates = [
            f"tests/test_{stem}.py",
            f"backend/tests/test_{stem}.py",
            str(path.with_name(f"test_{stem}.py")),
        ]
        if path.parent != PurePosixPath("."):
            candidates.append(str(path.parent / "tests" / f"test_{stem}.py"))
        return list(dict.fromkeys(candidates))

    def _is_test_file(self, file_path: str) -> bool:
        path = PurePosixPath(file_path)
        return path.name.startswith("test_") or "/tests/" in f"/{file_path}"

    def _matches_context(
        self,
        file_path: str,
        content: str,
        affected_file: str,
        enclosing_symbol: str | None,
    ) -> bool:
        affected_name = PurePosixPath(affected_file).stem
        test_name = PurePosixPath(file_path).stem
        if affected_name in test_name or affected_name in content:
            return True
        return bool(enclosing_symbol and enclosing_symbol in content)
