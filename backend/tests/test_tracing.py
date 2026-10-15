from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
from tracegrade import TraceGrade

from app import tracing
from app.ai.model_invocation import invoke_with_deadline


def setup_telemetry(monkeypatch, *, unavailable=False):
    snapshots = []
    def handle(request):
        import json
        from uuid import uuid4
        payload = json.loads(request.content)
        snapshots.append((request.url.path, payload))
        if unavailable:
            return httpx.Response(503)
        if request.url.path.endswith('/batch'):
            return httpx.Response(200, json={"accepted": [{"index": i, "id": ids[s['external_id']], "created": False} for i, s in enumerate(payload['spans'])], "errors": []})
        external_id = payload['external_id']
        ids.setdefault(external_id, str(uuid4()))
        return httpx.Response(201, json={"id": ids[external_id], **payload})
    ids = {}
    def create_client(*args, **kwargs):
        client = TraceGrade(*args, **kwargs)
        client._http.close()
        client._http = httpx.Client(base_url="http://test/api/v1/", transport=httpx.MockTransport(handle))
        return client
    monkeypatch.setenv('TRACEGRADE_API_KEY', 'test-key')
    monkeypatch.setattr(tracing, 'TraceGrade', create_client)
    return snapshots


def job(number=1):
    return SimpleNamespace(id=number, repository='owner/repo', pull_request_number=number, commit_sha='abc', event_action='opened')


def test_real_sdk_records_model_usage_and_parent_links(monkeypatch):
    snapshots = setup_telemetry(monkeypatch)
    class Model:
        async def ainvoke(self, value, config):
            for cb in config['callbacks']:
                cb.on_llm_end(SimpleNamespace(llm_output={'token_usage': {'prompt_tokens': 12, 'completion_tokens': 3}}, generations=[]))
            return {'summary': 'real response'}
    @tracing.trace_review
    def review(db, job):
        return invoke_with_deadline(Model(), 'review this diff')
    assert review(None, job()) == {'summary': 'real response'}
    starts = [p for path, p in snapshots if path.endswith('/spans')]
    assert [s['name'] for s in starts] == ['review pipeline', 'model review']
    assert starts[1]['parent_span_id'] is not None
    completed = [s for path, p in snapshots if path.endswith('/batch') for s in p['spans']]
    model = next(s for s in completed if s['name'] == 'model review')
    assert model['prompt_tokens'] == 12
    assert model['completion_tokens'] == 3
    assert model['output'] == {'summary': 'real response'}
    assert model['estimated_cost_usd'] is None
    assert tracing._current_trace.get() is None


def test_unavailable_telemetry_does_not_repeat_or_fail_review(monkeypatch):
    setup_telemetry(monkeypatch, unavailable=True)
    calls = []
    @tracing.trace_review
    def review(db, job):
        calls.append(job.id)
        return 'done'
    assert review(None, job()) == 'done'
    assert calls == [1]


def test_failure_records_sanitized_error_and_preserves_original(monkeypatch):
    snapshots = setup_telemetry(monkeypatch)
    error = ValueError('secret-provider-key')
    @tracing.trace_review
    def review(db, job):
        raise error
    with pytest.raises(ValueError) as exc:
        review(None, job())
    assert exc.value is error
    final_trace = [p for path, p in snapshots if path.endswith('/traces')][-1]
    assert final_trace['status'] == 'error'
    assert 'secret-provider-key' not in str(snapshots)
    assert tracing._current_trace.get() is None


def test_content_disabled_and_large_prompt_are_safe(monkeypatch):
    snapshots = setup_telemetry(monkeypatch)
    monkeypatch.setenv('TRACEGRADE_CAPTURE_CONTENT', 'false')
    class Model:
        def invoke(self, value):
            return 'output'
    @tracing.trace_review
    def review(db, job):
        return invoke_with_deadline(Model(), 'x' * 100_000)
    assert review(None, job()) == 'output'
    completed = [s for path, p in snapshots if path.endswith('/batch') for s in p['spans']]
    model = next(s for s in completed if s['kind'] == 'llm')
    assert model['input'] is None and model['output'] is None
    assert tracing._payload('😀' * 100_000)['truncated'] is True


def test_disabled_and_concurrent_traces(monkeypatch):
    snapshots = setup_telemetry(monkeypatch)
    @tracing.trace_review
    def review(db, job):
        return tracing._current_trace.get().id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda n: review(None, job(n)), [1, 2]))
    assert len(set(ids)) == 2
    assert tracing._current_trace.get() is None
    monkeypatch.delenv('TRACEGRADE_API_KEY')
    @tracing.trace_review
    def disabled(db, job):
        return 'no telemetry'
    count = len(snapshots)
    assert disabled(None, job()) == 'no telemetry'
    assert len(snapshots) == count


def test_usage_callback_runs_through_langchain_manager():
    from langchain_core.callbacks.manager import CallbackManager
    from langchain_core.outputs import LLMResult
    cb = tracing.TraceUsageCallback()
    manager = CallbackManager([cb])
    run = manager.on_llm_start({"name": "test"}, ["prompt"])[0]
    run.on_llm_end(LLMResult(generations=[[]], llm_output={"token_usage": {"prompt_tokens": 8, "completion_tokens": 2}}))
    assert cb.usage == {"input": 8, "output": 2}
