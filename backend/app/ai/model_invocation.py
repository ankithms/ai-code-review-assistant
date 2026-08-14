import asyncio
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any


DEFAULT_AI_MODEL_DEADLINE_SECONDS = 120.0


class AIModelDeadlineExceeded(TimeoutError):
    pass


class _PersistentAsyncRunner:
    """Runs async model clients on one event loop for the worker's lifetime.

    Provider SDKs pool async HTTP connections and bind those connections to the
    event loop that created them. Creating and closing a loop around every call
    leaves the pooled client pointing at a closed loop on its next invocation.
    """

    def __init__(self) -> None:
        self._start_lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def run(self, coroutine, *, timeout_seconds: float):
        try:
            loop = self._ensure_started()
            future = asyncio.run_coroutine_threadsafe(coroutine, loop)
        except Exception:
            coroutine.close()
            raise

        try:
            # asyncio.wait_for enforces the actual model deadline. This outer
            # bound prevents a broken runner loop from blocking a worker forever.
            return future.result(timeout=timeout_seconds + 1.0)
        except FutureTimeoutError:
            future.cancel()
            raise AIModelDeadlineExceeded(
                f"AI model invocation exceeded its {timeout_seconds:g}-second deadline"
            ) from None

    def _ensure_started(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if (
                self._loop is not None
                and self._loop.is_running()
                and self._thread is not None
                and self._thread.is_alive()
            ):
                return self._loop

            ready = threading.Event()

            def run_event_loop() -> None:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._loop = loop
                ready.set()
                loop.run_forever()

            self._thread = threading.Thread(
                target=run_event_loop,
                name="ai-model-event-loop",
                daemon=True,
            )
            self._thread.start()
            if not ready.wait(timeout=5.0) or self._loop is None:
                raise RuntimeError("Failed to start the AI model event loop")
            return self._loop


_async_runner = _PersistentAsyncRunner()


def invoke_with_deadline(
    runnable,
    model_input: Any,
    *,
    timeout_seconds: float | None = None,
):
    deadline = timeout_seconds or _model_deadline_seconds()
    async_invoke = getattr(runnable, "ainvoke", None)
    if not callable(async_invoke):
        return runnable.invoke(model_input)

    async def invoke():
        return await asyncio.wait_for(
            async_invoke(
                model_input,
                automatic_function_calling={"disable": True},
            ),
            timeout=deadline,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(
            "invoke_with_deadline must be called outside an active asyncio event loop"
        )

    try:
        return _async_runner.run(invoke(), timeout_seconds=deadline)
    except AIModelDeadlineExceeded:
        raise
    except TimeoutError as exc:
        raise AIModelDeadlineExceeded(
            f"AI model invocation exceeded its {deadline:g}-second deadline"
        ) from exc


def _model_deadline_seconds() -> float:
    raw_value = os.getenv(
        "AI_MODEL_DEADLINE_SECONDS",
        str(DEFAULT_AI_MODEL_DEADLINE_SECONDS),
    )
    try:
        deadline = float(raw_value)
    except ValueError as exc:
        raise RuntimeError("AI_MODEL_DEADLINE_SECONDS must be a number") from exc

    if deadline <= 0:
        raise RuntimeError("AI_MODEL_DEADLINE_SECONDS must be greater than zero")
    return deadline
