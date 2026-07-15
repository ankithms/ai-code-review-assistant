# AI Code Review Assistant

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

Required environment variables:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/ai_code_review_assistant
REDIS_URL=redis://localhost:6379/0
GITHUB_ACCESS_TOKEN=...
GITHUB_WEBHOOK_SECRET=...
GOOGLE_API_KEY=...
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
