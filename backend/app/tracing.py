"""Optional, bounded TraceGrade telemetry for the review worker."""
import json
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps

from tracegrade import TraceGrade

from app.monitoring import ModelUsageCallback, _extract_token_usage, model_identity

logger = logging.getLogger(__name__)
_current_trace = ContextVar("review_trace", default=None)


def _payload(value):
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded.encode("utf-8")) > 60_000:
        return {"preview": encoded.encode("utf-8")[:50_000].decode("utf-8", errors="ignore"),
                "truncated": True}
    return json.loads(encoded)


@contextmanager
def _safe_context(context):
    try:
        entered = context.__enter__()
    except Exception:
        logger.warning("TraceGrade context could not start")
        yield None
        return
    try:
        yield entered
    except BaseException as exc:
        # Store only the exception class; provider errors can contain credentials.
        sanitized = RuntimeError(type(exc).__name__)
        try:
            context.__exit__(RuntimeError, sanitized, None)
        except Exception:
            logger.warning("TraceGrade error snapshot could not be delivered")
        raise
    else:
        try:
            context.__exit__(None, None, None)
        except Exception:
            logger.warning("TraceGrade completion could not be delivered")


def trace_review(func):
    @wraps(func)
    def wrapped(db, job):
        key = os.getenv("TRACEGRADE_API_KEY", "").strip()
        if not key:
            return func(db, job)
        try:
            client = TraceGrade(
                key,
                base_url=os.getenv("TRACEGRADE_API_URL", "http://localhost:8000/api/v1"),
                timeout=1.0,
                max_retries=0,
            )
        except Exception:
            logger.warning("TraceGrade client could not be initialized")
            return func(db, job)
        trace = None
        try:
            context = client.trace("AI Code Review", attributes={
                "job_id": job.id,
                "repository": job.repository,
                "pull_request_number": job.pull_request_number,
                "commit_sha": job.commit_sha,
                "review_mode": "incremental" if getattr(job, "event_action", None) == "synchronize" else "full",
            })
        except Exception:
            client.close()
            logger.warning("TraceGrade trace could not be initialized")
            return func(db, job)
        try:
            with _safe_context(context) as trace:
                token = _current_trace.set(trace)
                try:
                    with operation("review pipeline"):
                        return func(db, job)
                finally:
                    _current_trace.reset(token)
        finally:
            try:
                trace_id = trace.id if trace is not None else None
                client.close()
                if client.delivery_errors:
                    logger.warning("TraceGrade delivery failed errors=%s", len(client.delivery_errors))
                elif trace_id:
                    logger.info("TraceGrade review trace_id=%s", trace_id)
            except Exception:
                logger.warning("TraceGrade client could not close")
    return wrapped


@contextmanager
def operation(name, **kwargs):
    trace = _current_trace.get()
    if trace is None:
        yield None
        return
    try:
        context = trace.span(name, **kwargs)
    except Exception:
        logger.warning("TraceGrade span could not be initialized")
        yield None
        return
    with _safe_context(context) as span:
        yield span


def traced_operation(name):
    def decorate(func):
        @wraps(func)
        def wrapped(*args, **kwargs):
            with operation(name):
                return func(*args, **kwargs)
        return wrapped
    return decorate


class TraceUsageCallback(ModelUsageCallback):
    def __init__(self):
        self.usage = None

    def on_llm_end(self, response, **kwargs):
        usage = _extract_token_usage(response)
        if any(usage.values()):
            if self.usage is None:
                self.usage = {"input": 0, "output": 0}
            self.usage["input"] += usage["input"]
            self.usage["output"] += usage["output"]


@contextmanager
def model_call(model_input):
    provider, model = model_identity()
    capture = os.getenv("TRACEGRADE_CAPTURE_CONTENT", "true").lower() == "true"
    callback = TraceUsageCallback()
    with operation("model review", kind="llm", model=model, attributes={"provider": provider}) as span:
        if span is not None and capture:
            try:
                span.set_input(_payload(model_input))
            except Exception:
                logger.warning("TraceGrade model input could not be recorded")
        def record(result):
            if span is not None:
                try:
                    if capture:
                        span.set_output(_payload(result))
                    if callback.usage is not None:
                        span.set_usage(prompt_tokens=callback.usage["input"], completion_tokens=callback.usage["output"])
                except Exception:
                    logger.warning("TraceGrade model metadata could not be recorded")
        yield callback, record
