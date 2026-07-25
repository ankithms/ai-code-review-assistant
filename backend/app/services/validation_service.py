import ast
import json


class ValidationService:
    def validate_file(
        self,
        file_path: str,
        content: str,
    ) -> list[str]:
        suffix = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

        if suffix == "py":
            return self._validate_python(file_path, content)

        if suffix == "json":
            return self._validate_json(file_path, content)

        if suffix in {"yaml", "yml"}:
            return self._validate_yaml(file_path, content)

        return []

    def _validate_python(self, file_path: str, content: str) -> list[str]:
        try:
            ast.parse(content)
        except SyntaxError as exc:
            return [f"{file_path}: Python syntax validation failed: {exc.msg}"]

        return []

    def _validate_json(self, file_path: str, content: str) -> list[str]:
        try:
            json.loads(content)
        except json.JSONDecodeError as exc:
            return [f"{file_path}: JSON validation failed: {exc.msg}"]

        return []

    def _validate_yaml(self, file_path: str, content: str) -> list[str]:
        try:
            import yaml
        except ImportError:
            return [f"{file_path}: YAML validation is unavailable because PyYAML is not installed"]

        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return [f"{file_path}: YAML validation failed: {exc}"]

        return []
