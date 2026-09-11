import logging
import os
import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from prometheus_client import Counter, Histogram, start_http_server


logger = logging.getLogger(__name__)

JOB_ATTEMPTS = Counter(
    "review_job_attempts_total",
    "Review job processing attempts by outcome.",
    ("outcome",),
)
JOB_FAILURES = Counter(
    "review_job_failures_total",
    "Review job failures by retryability and exception type.",
    ("retryable", "error_type"),
)
JOB_DURATION = Histogram(
    "review_job_duration_seconds",
    "Time spent processing a review job attempt.",
    buckets=(1, 5, 15, 30, 60, 120, 300, 600),
)
MODEL_INVOCATIONS = Counter(
    "ai_model_invocations_total",
    "AI model calls by provider, model, and outcome.",
    ("provider", "model", "outcome"),
)
MODEL_LATENCY = Histogram(
    "ai_model_latency_seconds",
    "AI model invocation latency.",
    ("provider", "model"),
    buckets=(0.25, 0.5, 1, 2, 5, 10, 20, 30, 60, 120),
)
MODEL_TOKENS = Counter(
    "ai_model_tokens_total",
    "Tokens reported by the AI provider.",
    ("provider", "model", "type"),
)
GITHUB_REQUESTS = Counter(
    "github_api_requests_total",
    "GitHub API operations by outcome and HTTP status.",
    ("operation", "outcome", "status"),
)
GITHUB_LATENCY = Histogram(
    "github_api_latency_seconds",
    "GitHub API operation latency.",
    ("operation",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 15),
)


def model_identity() -> tuple[str, str]:
    return (
        os.getenv("AI_PROVIDER", "gemini").strip().lower() or "unknown",
        os.getenv("AI_MODEL", "gemini-2.5-flash").strip() or "unknown",
    )


class ModelUsageCallback:
    """LangChain-compatible callback that records provider-reported token usage."""

    raise_error = False
    run_inline = True

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage = _extract_token_usage(response)
        provider, model = model_identity()
        for token_type, value in usage.items():
            if value > 0:
                MODEL_TOKENS.labels(provider, model, token_type).inc(value)

    def __getattr__(self, name: str):
        # Callback managers may emit lifecycle events we do not need.
        if name.startswith("on_"):
            return lambda *args, **kwargs: None
        raise AttributeError(name)


def _extract_token_usage(response: Any) -> dict[str, int]:
    totals = {"input": 0, "output": 0, "total": 0}
    metadata = getattr(response, "llm_output", None) or {}
    candidates = [metadata.get("token_usage"), metadata.get("usage_metadata")]

    for generation_group in getattr(response, "generations", []) or []:
        for generation in generation_group or []:
            message = getattr(generation, "message", None)
            candidates.append(getattr(message, "usage_metadata", None))
            response_metadata = getattr(message, "response_metadata", None) or {}
            candidates.append(response_metadata.get("token_usage"))
            candidates.append(response_metadata.get("usage_metadata"))

    for usage in candidates:
        if not isinstance(usage, dict):
            continue
        totals["input"] = max(totals["input"], _usage_int(usage, "input_tokens", "prompt_tokens"))
        totals["output"] = max(totals["output"], _usage_int(usage, "output_tokens", "completion_tokens"))
        totals["total"] = max(totals["total"], _usage_int(usage, "total_tokens"))

    if totals["total"] == 0:
        totals["total"] = totals["input"] + totals["output"]
    return totals


def _usage_int(usage: dict, *keys: str) -> int:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return 0


def monitor_github(operation: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapped(*args, **kwargs):
            started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                response = getattr(exc, "response", None)
                status = str(getattr(response, "status_code", "network_error"))
                GITHUB_REQUESTS.labels(operation, "failure", status).inc()
                logger.warning(
                    "GitHub API operation failed operation=%s status=%s error_type=%s",
                    operation,
                    status,
                    type(exc).__name__,
                )
                raise
            else:
                GITHUB_REQUESTS.labels(operation, "success", "2xx").inc()
                return result
            finally:
                GITHUB_LATENCY.labels(operation).observe(time.perf_counter() - started)

        return wrapped
    return decorator


def start_worker_metrics_server() -> None:
    raw_port = os.getenv("WORKER_METRICS_PORT")
    if not raw_port:
        return
    try:
        port = int(raw_port)
        start_http_server(port)
    except (ValueError, OSError):
        logger.exception("Failed to start worker metrics server port=%s", raw_port)
        raise
    logger.info("Worker Prometheus metrics listening on port %s", port)
