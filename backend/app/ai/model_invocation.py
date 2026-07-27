import asyncio
import os
from typing import Any


DEFAULT_AI_MODEL_DEADLINE_SECONDS = 120.0


class AIModelDeadlineExceeded(TimeoutError):
    pass


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
        return asyncio.run(invoke())
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
