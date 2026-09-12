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
* React dashboard with repository analytics and review history
* Public read-only demo at `/demo/` with illustrative findings and fix suggestions

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
# AI provider selection. Gemini is currently supported; additional providers can
# be added behind the provider factory without changing review or fix logic.
AI_PROVIDER=gemini
AI_MODEL=gemini-2.5-flash
# GitHub OAuth credentials for the single dashboard administrator.
GITHUB_CLIENT_ID=...
GITHUB_CLIENT_SECRET=...
ALLOWED_GITHUB_USERS=your-github-login
# Use false only for local HTTP development; HTTPS deployments must use true.
SESSION_COOKIE_SECURE=false
SESSION_MAX_AGE_SECONDS=28800
# Optional hard deadline for one AI review/fix invocation.
AI_MODEL_DEADLINE_SECONDS=120
# Comma-separated browser origins allowed to call FastAPI directly.
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000
SOURCE_SNIPPET_RETENTION_DAYS=30
REVIEW_DATA_RETENTION_DAYS=365
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
single-page application and proxies `/api` requests to FastAPI. The Compose
backend is internal-only; deliver GitHub webhooks through
`http://localhost:3000/api/webhooks/github`. Running FastAPI directly on port
8000 remains available for local API development.

## Dashboard authentication

The dashboard uses GitHub OAuth for a single configured administrator. Add the
OAuth callback URL for your deployment (for example,
`https://review.example.com/api/auth/github/callback`) to the GitHub OAuth app,
then set `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`, and
`ALLOWED_GITHUB_USERS`. The callback validates an OAuth state value, does not
return GitHub's OAuth token to the browser, and instead creates an opaque,
database-backed session cookie.

Set `SESSION_COOKIE_SECURE=true` for every HTTPS deployment. All review,
analytics, pull-request, repository, and AI-fix APIs require that session;
only the signed GitHub webhook and `/healthz` remain public.

If FastAPI is running directly on `http://localhost:8000`, set
`LOGIN_SUCCESS_REDIRECT=http://localhost:5173/` so the OAuth callback returns
to the Vite dashboard. That URL must have an origin listed in
`CORS_ALLOWED_ORIGINS`. With Docker Compose, leave it as `/`: Nginx receives
the callback under `/api` and redirects it to the dashboard on port 3000.

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

## Public resume demo

Open `/demo/` (locally, `http://localhost:5173/demo/`) or choose **Try demo**
on the sign-in screen. Visitors can browse analytics, PRs, reviews, sample code
diffs, and suggested replacements without signing in. Direct links such as
`/demo/reviews/1` work with the existing Vite and Nginx SPA fallback.

The demo is bundled with the frontend and works without the backend, GitHub,
or Gemini. Its Axios adapter only serves allowlisted sample GET responses;
writes and unknown paths fail locally with no network fallback. The live API
still requires a database-backed administrator session, including generation,
preview, apply, status updates, and analytics sync. The demo creates no session
and grants no backend permissions. Leaving the demo reloads the normal app.

Fixtures in `frontend/src/demo/data.ts` are **hand-authored illustrative data**,
not real model outputs, usage statistics, or verified fixes. The banner makes
this explicit. Replace them only with reviewed, sanitized public examples if
publishing actual results later. Never include private repository content or
credentials in bundled fixtures. Demo repository selection is stored separately
from the administrator's selection.

For a frontend-only preview, run `cd frontend && pnpm run dev` and visit
`http://localhost:5173/demo/`. No new credentials or database migrations are
needed. This change adds the demo route; it does not deploy the application.

## Data retention

Repository files and pull-request diffs are fetched for processing and are not
stored as complete files. The database does store the minimum excerpts needed to
show and apply a finding: diff hunks, suggested replacement code, and additional
edit payloads. By default these source-bearing fields are irreversibly set to
`NULL` 30 days after the review was created. After 365 days, the remaining
human-readable review content is also scrubbed: the summary, finding comment and
impact, fix explanation, file paths, and line reference.

Relational rows and non-content operational metadata remain after scrubbing so
foreign-key relationships, aggregate severity/category/status analytics,
idempotency, and GitHub audit identifiers continue to work. Purging the database
does not remove comments already posted to GitHub; those follow the repository's
GitHub retention policy. Backups and replicas must use expiry windows no longer
than the corresponding live-data windows.

The cleanup is an operator-scheduled job. Run it at least daily after applying
migrations:

```bash
cd backend
uv run python -m app.data_retention --dry-run
uv run python -m app.data_retention
```

Set `SOURCE_SNIPPET_RETENTION_DAYS` and `REVIEW_DATA_RETENTION_DAYS` to positive
day counts to change the defaults. The review window cannot be shorter than the
source window. Runs are idempotent. Legal holds are not implemented and require
suspending this job and preserving the relevant database and backups through an
external, access-controlled process.
