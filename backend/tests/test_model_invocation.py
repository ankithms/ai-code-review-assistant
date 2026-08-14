import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ai.model_invocation import AIModelDeadlineExceeded, invoke_with_deadline


class LoopBoundRunnable:
    def __init__(self):
        self.loop = None
        self.loop_ids = []

    async def ainvoke(self, value, **kwargs):
        current_loop = asyncio.get_running_loop()
        if self.loop is not None and current_loop is not self.loop:
            raise RuntimeError("Event loop is closed")
        self.loop = current_loop
        self.loop_ids.append(id(current_loop))
        await asyncio.sleep(0)
        return value


def test_repeated_async_invocations_reuse_a_live_event_loop():
    runnable = LoopBoundRunnable()

    assert invoke_with_deadline(runnable, "first", timeout_seconds=1) == "first"
    assert invoke_with_deadline(runnable, "second", timeout_seconds=1) == "second"

    assert runnable.loop_ids[0] == runnable.loop_ids[1]
    assert runnable.loop is not None
    assert runnable.loop.is_running()
    assert not runnable.loop.is_closed()


def test_worker_threads_submit_model_calls_to_the_same_event_loop():
    runnable = LoopBoundRunnable()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda value: invoke_with_deadline(
                    runnable,
                    value,
                    timeout_seconds=1,
                ),
                ("one", "two"),
            )
        )

    assert results == ["one", "two"]
    assert len(set(runnable.loop_ids)) == 1


def test_async_invocation_deadline_still_cancels_slow_calls():
    class SlowRunnable:
        async def ainvoke(self, value, **kwargs):
            await asyncio.sleep(1)
            return value

    with pytest.raises(AIModelDeadlineExceeded, match="0.01-second deadline"):
        invoke_with_deadline(SlowRunnable(), "late", timeout_seconds=0.01)


def test_sync_runnable_does_not_start_or_require_an_event_loop():
    class SyncRunnable:
        def invoke(self, value):
            return value.upper()

    assert invoke_with_deadline(SyncRunnable(), "ok", timeout_seconds=1) == "OK"
