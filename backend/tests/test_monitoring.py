from types import SimpleNamespace
import pytest
import requests
from prometheus_client import generate_latest

from app.ai.model_invocation import invoke_with_deadline
from app.monitoring import ModelUsageCallback, monitor_github


def test_model_invocation_exports_latency_and_outcome():
    class SyncRunnable:
        def invoke(self, value, **kwargs):
            return "review"

    assert invoke_with_deadline(SyncRunnable(), "prompt", timeout_seconds=1) == "review"

    metrics = generate_latest().decode()
    assert 'ai_model_invocations_total{model="gemini-2.5-flash",outcome="success",provider="gemini"}' in metrics
    assert "ai_model_latency_seconds_count" in metrics


def test_model_usage_callback_accepts_common_provider_metadata():
    callback = ModelUsageCallback()
    callback.on_llm_end(
        SimpleNamespace(
            llm_output={
                "token_usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 4,
                    "total_tokens": 14,
                }
            },
            generations=[],
        )
    )

    metrics = generate_latest().decode()
    assert 'ai_model_tokens_total{model="gemini-2.5-flash",provider="gemini",type="input"}' in metrics
    assert 'ai_model_tokens_total{model="gemini-2.5-flash",provider="gemini",type="output"}' in metrics
    assert 'ai_model_tokens_total{model="gemini-2.5-flash",provider="gemini",type="total"}' in metrics


def test_github_failures_include_operation_and_http_status():
    response = requests.Response()
    response.status_code = 429
    error = requests.HTTPError(response=response)

    @monitor_github("rate_limited_test")
    def failing_operation():
        raise error

    with pytest.raises(requests.HTTPError):
        failing_operation()

    metrics = generate_latest().decode()
    assert 'github_api_requests_total{operation="rate_limited_test",outcome="failure",status="429"}' in metrics
