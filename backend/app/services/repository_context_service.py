import logging
import tomllib
from collections.abc import Callable

from app.github.github_service import get_file_content
from app.schemas.fix_context import RepositoryContext

logger = logging.getLogger(__name__)


CONFIG_PATHS = [
    "README.md",
    "CONTRIBUTING.md",
    "AGENTS.md",
    "CODE_STYLE.md",
    "pyproject.toml",
    "requirements.txt",
    "package.json",
    "tsconfig.json",
    ".eslintrc",
    ".eslintrc.json",
    ".prettierrc",
    "Dockerfile",
    "docker-compose.yml",
]


class RepositoryContextService:
    _cache: dict[tuple[str, str], RepositoryContext] = {}

    def __init__(
        self,
        file_fetcher: Callable[[str, str, str, str], dict] | None = None,
    ) -> None:
        self.file_fetcher = file_fetcher or get_file_content

    def build_context(
        self,
        repository: str,
        ref: str,
        access_token: str,
    ) -> RepositoryContext:
        cache_key = (repository, ref)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        files = self._fetch_config_files(repository, ref, access_token)
        context = RepositoryContext(
            language=self._detect_language(files),
            framework=self._detect_framework(files),
            architecture_summary=self._architecture_summary(files),
            style_rules=self._style_rules(files),
            repository_instructions=self._repository_instructions(files),
            files_considered=sorted(files),
        )
        self._cache[cache_key] = context
        return context

    def _fetch_config_files(
        self,
        repository: str,
        ref: str,
        access_token: str,
    ) -> dict[str, str]:
        files = {}
        for path in CONFIG_PATHS:
            try:
                payload = self.file_fetcher(
                    repository=repository,
                    file_path=path,
                    ref=ref,
                    access_token=access_token,
                )
            except Exception:
                continue

            content = payload.get("content")
            if content:
                files[path] = content

        return files

    def _detect_language(self, files: dict[str, str]) -> str | None:
        if "pyproject.toml" in files or "requirements.txt" in files:
            return "Python"
        if "package.json" in files or "tsconfig.json" in files:
            return "TypeScript" if "tsconfig.json" in files else "JavaScript"
        return None

    def _detect_framework(self, files: dict[str, str]) -> str | None:
        combined = "\n".join(files.values()).lower()
        if "fastapi" in combined:
            return "FastAPI"
        if "django" in combined:
            return "Django"
        if "flask" in combined:
            return "Flask"
        if '"react"' in combined or "@vitejs/plugin-react" in combined:
            return "React"
        return None

    def _architecture_summary(self, files: dict[str, str]) -> list[str]:
        summary = []
        readme = files.get("README.md", "")
        pyproject = files.get("pyproject.toml", "")
        package_json = files.get("package.json", "")

        if "FastAPI" in readme or "fastapi" in pyproject.lower():
            summary.append("FastAPI routes should stay thin and delegate work to services.")
        if "SQLAlchemy" in readme or "sqlalchemy" in pyproject.lower():
            summary.append("Database access uses SQLAlchemy models and sessions.")
        if "dramatiq" in readme.lower() or "dramatiq" in pyproject.lower():
            summary.append("Background processing uses Dramatiq workers.")
        if "react" in package_json.lower():
            summary.append("Frontend code uses React components and typed API responses.")

        return summary

    def _style_rules(self, files: dict[str, str]) -> list[str]:
        rules = []
        pyproject = files.get("pyproject.toml", "")
        if pyproject:
            rules.append("Use Python type hints consistently with the existing service code.")
            try:
                config = tomllib.loads(pyproject)
            except tomllib.TOMLDecodeError:
                config = {}
            if "pytest" in (config.get("tool") or {}):
                rules.append("Use pytest/unittest tests that mock external services.")
        if "CONTRIBUTING.md" in files:
            rules.append("Follow the repository contribution guidance.")
        if ".prettierrc" in files:
            rules.append("Preserve existing Prettier formatting.")
        return rules

    def _repository_instructions(self, files: dict[str, str]) -> list[str]:
        instructions = []
        for path in ("AGENTS.md", "CONTRIBUTING.md", "CODE_STYLE.md", "README.md"):
            content = files.get(path)
            if not content:
                continue
            excerpt = "\n".join(content.splitlines()[:80]).strip()
            if excerpt:
                instructions.append(f"{path}:\n{excerpt}")
        return instructions
