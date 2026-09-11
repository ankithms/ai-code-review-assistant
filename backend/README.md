# Monitoring

The API exposes Prometheus metrics at `/metrics/`. The Dramatiq worker exposes
its metrics on port `8001` inside the Compose network. Configure Prometheus to
scrape `backend:8000/metrics/` and `worker:8001/metrics`.
The included Compose stack does this automatically and makes Prometheus
available at `http://localhost:9090`; alert rules cover job failures, model p95
latency above 60 seconds, and a sustained GitHub API failure rate above 5%.

The application reports:

- `review_job_attempts_total`, `review_job_failures_total`, and
  `review_job_duration_seconds`
- `ai_model_invocations_total`, `ai_model_latency_seconds`, and
  `ai_model_tokens_total`
- `github_api_requests_total` and `github_api_latency_seconds`

Metrics use bounded labels only. Repository names, prompts, access tokens, and
exception messages are not included. Model token counters use the usage metadata
reported by the configured provider.
