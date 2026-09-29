#!/bin/sh

set -eu

alembic upgrade head

dramatiq app.tasks.review_tasks --processes 1 --threads 2 &
worker_pid=$!

uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-10000}" &
api_pid=$!

shutdown() {
    kill -TERM "$api_pid" "$worker_pid" 2>/dev/null || true
    wait "$api_pid" "$worker_pid" 2>/dev/null || true
}

trap 'shutdown; exit 0' INT TERM

while kill -0 "$api_pid" 2>/dev/null && kill -0 "$worker_pid" 2>/dev/null; do
    sleep 1
done

shutdown
exit 1
