import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Iterator


_LOG_CONTEXT: ContextVar[dict[str, object]] = ContextVar(
    "log_context",
    default={},
)


class StructuredFormatter(logging.Formatter):
    """Render application logs as one-line JSON with review-job context."""

    def format(self, record: logging.LogRecord) -> str:
        context = _LOG_CONTEXT.get()
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in ("job_id", "repository", "pull_request_number", "commit_sha"):
            value = getattr(record, field, context.get(field))
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, separators=(",", ":"))


def configure_logging(level: int = logging.INFO) -> None:
    """Configure both API and worker processes with the same JSON log format."""
    root = logging.getLogger()
    root.setLevel(level)
    formatter = StructuredFormatter()

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)
        return

    for handler in root.handlers:
        handler.setFormatter(formatter)


@contextmanager
def logging_context(**values: object) -> Iterator[None]:
    """Attach values to every log record emitted in the current execution context."""
    context = {**_LOG_CONTEXT.get(), **values}
    token = _LOG_CONTEXT.set(context)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)
