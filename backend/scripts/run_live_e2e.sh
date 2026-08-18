#!/usr/bin/env bash

set -euo pipefail

if [[ "${LIVE_E2E_CONFIRM:-}" != "post-comments" ]]; then
  echo "Refusing live E2E: set LIVE_E2E_CONFIRM=post-comments." >&2
  exit 2
fi
if [[ -z "${LIVE_E2E_REPOSITORY:-}" ]]; then
  echo "Refusing live E2E: set LIVE_E2E_REPOSITORY=owner/repository." >&2
  exit 2
fi
if [[ ! "${LIVE_E2E_PR_NUMBER:-}" =~ ^[1-9][0-9]*$ ]]; then
  echo "Refusing live E2E: set LIVE_E2E_PR_NUMBER to a positive integer." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.e2e.yml"
PROJECT_NAME="ai-code-review-assistant-live-e2e"
BACKEND_DIR="${PROJECT_DIR}/backend"

export DATABASE_URL="postgresql://code_review_e2e:code_review_e2e@127.0.0.1:55432/code_review_e2e"
export REDIS_URL="redis://127.0.0.1:56379/0"
export GITHUB_WEBHOOK_SECRET="live-e2e-local-webhook-secret"
export LIVE_E2E_BASE_URL="http://127.0.0.1:18001"
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

cd "${BACKEND_DIR}"

uv run uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 18001 &
api_pid=$!

uv run dramatiq app.tasks.review_tasks \
  --processes 1 \
  --threads 1 &
worker_pid=$!

uv run python -m unittest tests.e2e.test_live_review_flow -v

