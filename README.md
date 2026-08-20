# AI Code Review Assistant

[![CI](https://github.com/ankithms/ai-code-review-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/ankithms/ai-code-review-assistant/actions/workflows/ci.yml)

An AI-powered developer tool that automatically reviews GitHub pull requests, analyzes code diffs using Google's Gemini models, identifies potential bugs, security vulnerabilities, performance concerns, and code quality issues, then posts structured review feedback directly on the pull request.

## Features

* GitHub Pull Request webhook integration
* Automated code diff analysis
* AI-generated review comments using Gemini
* Structured issue categorization
* Security vulnerability detection
* Bug and edge-case identification
* PostgreSQL-backed review history
* Alembic database migrations
* FastAPI backend architecture
* Extensible review pipeline for future dashboard and analytics support

## Tech Stack

### Backend

* FastAPI
* Python
* SQLAlchemy
* PostgreSQL
* Alembic
* Pydantic

### AI

* Google Gemini 2.5 Flash
* LangChain

### Integrations

* GitHub Webhooks
* GitHub REST API

## Workflow

GitHub Pull Request → Webhook Trigger → Review Job → Redis Queue → Worker → Diff Extraction → AI Analysis → Database Storage → GitHub Review Comment

This project aims to streamline code reviews by providing instant AI-powered feedback to developers during the pull request process.

## Background Processing

Pull request webhooks are handled asynchronously. The FastAPI webhook endpoint validates the GitHub signature and payload, creates a `review_jobs` row, pushes the job to Redis through Dramatiq, and returns immediately. A separate worker process fetches the pull request details, runs the Gemini review, stores results, and posts GitHub comments.

`GITHUB_WEBHOOK_SECRET` is mandatory. The webhook endpoint fails closed with
HTTP 503 when verification is not configured and rejects missing or invalid
signatures with HTTP 401.

Required environment variables:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_code_review_assistant
REDIS_URL=redis://localhost:6379/0
# Optional: queue operations per million that run interrupted-message recovery.
# The application default is 100000 (10%) for prompt recovery in low-traffic queues.
DRAMATIQ_REDIS_MAINTENANCE_CHANCE=100000
GITHUB_ACCESS_TOKEN=...
GITHUB_WEBHOOK_SECRET=...
GOOGLE_API_KEY=...
# Optional hard deadline for one Gemini review/fix invocation.
AI_MODEL_DEADLINE_SECONDS=120
# Comma-separated browser origins allowed to call FastAPI directly.
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
```

Start from the checked-in template and replace all placeholder credentials:

```bash
cp backend/.env.example backend/.env
```

## Local Development

Run Redis:

```bash
redis-server
```

Run the backend:

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Run the worker in a separate terminal:

```bash
cd backend
uv run dramatiq app.tasks.review_tasks
```

Or run the full stack with Docker Compose:

```bash
docker compose up --build
```

The dashboard is then available at `http://localhost:3000`. Nginx serves the
single-page application and proxies `/api` requests to FastAPI; the backend is
also exposed directly at `http://localhost:8000` for webhook delivery and API
development.

Run and validate the frontend:

```bash
cd frontend
pnpm install
pnpm run dev

# In a validation terminal
pnpm run test
pnpm run lint
pnpm run build
```

The Vite development server uses `/api` and proxies it to
`VITE_DEV_API_TARGET`, which defaults to `http://localhost:8000`. Set
`VITE_API_BASE_URL` only when the browser must call a different public API URL.

## Continuous Integration

GitHub Actions runs on pull requests and pushes to `main`. The workflow installs
dependencies from the committed lockfiles, runs all backend tests, runs frontend
tests and lint, builds the production frontend, validates Docker Compose, and
builds the backend and frontend images. Live E2E tests remain opt-in and never
run in CI because they require explicit confirmation and real credentials.

## End-to-End Test

The isolated E2E stack exercises the real FastAPI endpoint, Alembic migrations,
PostgreSQL database, Redis queue, and a separate Dramatiq worker process. GitHub
and Gemini are replaced with deterministic test doubles, so the test never
changes a real repository or consumes model quota.

Run it from the repository root:

```bash
bash backend/scripts/run_e2e.sh
```

The runner starts isolated PostgreSQL and Redis containers, validates webhook
signature rejection, submits a signed pull-request webhook, waits for the
asynchronous review, checks the review and analytics APIs, verifies duplicate
delivery handling, and removes the E2E containers and volumes when it finishes.

### Live sandbox test

The live test uses the configured GitHub and Gemini credentials and posts real
review comments. It only accepts an open pull request whose title contains
`E2E` or whose source branch begins with `e2e/`. The pull request should include
an intentional reviewable issue so inline-comment behavior can be verified.

Run it only against a disposable sandbox pull request:

```bash
LIVE_E2E_REPOSITORY=owner/sandbox \
LIVE_E2E_PR_NUMBER=123 \
LIVE_E2E_CONFIRM=post-comments \
bash backend/scripts/run_live_e2e.sh
```

The runner refuses to start without the exact repository, pull-request number,
and confirmation value. Real comments created by the test are intentionally
left on the sandbox pull request as an audit trail.

If a disposable fixture PR does not exist, repository owners can provision one
with the configured GitHub token:

```bash
cd backend
LIVE_E2E_REPOSITORY=owner/sandbox \
LIVE_E2E_CONFIRM=provision-fixture \
uv run python scripts/provision_live_e2e_fixture.py
```

The provisioner refuses to overwrite its `e2e/live-review-fixture` branch. The
created PR is a draft and must never be merged because its defects are
intentional.
