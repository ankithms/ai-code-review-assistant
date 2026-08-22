#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.e2e.yml"
PROJECT_NAME="ai-code-review-assistant-e2e"
BACKEND_DIR="${PROJECT_DIR}/backend"

export DATABASE_URL="postgresql://code_review_e2e:code_review_e2e@127.0.0.1:55432/code_review_e2e"
export REDIS_URL="redis://127.0.0.1:56379/0"
export GITHUB_WEBHOOK_SECRET="e2e-webhook-secret"
export GOOGLE_API_KEY="e2e-model-key-not-used"
export E2E_BASE_URL="http://127.0.0.1:18000"
export E2E_WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-${BACKEND_DIR}/.uv-cache}"

api_pid=""
worker_pid=""

cleanup() {
  status=$?
  trap - EXIT
  set +e

  if [[ -n "${worker_pid}" ]]; then
    kill "${worker_pid}" 2>/dev/null
    wait "${worker_pid}" 2>/dev/null
  fi
  if [[ -n "${api_pid}" ]]; then
    kill "${api_pid}" 2>/dev/null
    wait "${api_pid}" 2>/dev/null
  fi

  docker compose \
    --project-name "${PROJECT_NAME}" \
    --file "${COMPOSE_FILE}" \
    down --volumes --remove-orphans

  exit "${status}"
}

trap cleanup EXIT

docker compose \
  --project-name "${PROJECT_NAME}" \
  --file "${COMPOSE_FILE}" \
  up --detach --wait

(
  cd "${BACKEND_DIR}"
  uv run alembic upgrade head
)

export E2E_SESSION_TOKEN="$(
  cd "${BACKEND_DIR}"
  uv run python -c 'from app.authentication import create_session; from app.db.session import SessionLocal; db = SessionLocal(); print(create_session(db, "e2e-admin")); db.close()'
)"

cd "${BACKEND_DIR}"

GITHUB_ACCESS_TOKEN="" uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 18000 &
api_pid=$!

GITHUB_ACCESS_TOKEN="e2e-github-token-not-used" \
  uv run dramatiq tests.e2e.fake_review_worker \
  --processes 1 \
  --threads 1 &
worker_pid=$!

uv run python -m unittest tests.e2e.test_review_flow -v
