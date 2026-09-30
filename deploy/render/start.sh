#!/bin/sh

set -eu

listen_port=${PORT:-10000}
case "$listen_port" in
    *[!0-9]* | "")
        echo "PORT must be a number" >&2
        exit 1
        ;;
esac

sed "s/__PORT__/$listen_port/g" \
    /etc/nginx/nginx.conf.template > /tmp/nginx.conf

alembic upgrade head

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
api_pid=$!

attempt=0
until python -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/livez", timeout=1)' \
    >/dev/null 2>&1; do
    if ! kill -0 "$api_pid" 2>/dev/null; then
        wait "$api_pid"
        exit 1
    fi

    attempt=$((attempt + 1))
    if [ "$attempt" -ge 120 ]; then
        echo "FastAPI did not become healthy within 120 seconds" >&2
        kill -TERM "$api_pid" 2>/dev/null || true
        wait "$api_pid" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

dramatiq app.tasks.review_tasks --processes 1 --threads 2 &
worker_pid=$!

nginx -c /tmp/nginx.conf -g 'daemon off;' &
nginx_pid=$!

shutdown() {
    kill -TERM "$nginx_pid" "$api_pid" "$worker_pid" 2>/dev/null || true
    wait "$nginx_pid" "$api_pid" "$worker_pid" 2>/dev/null || true
}

trap 'shutdown; exit 0' INT TERM

while kill -0 "$nginx_pid" 2>/dev/null \
    && kill -0 "$api_pid" 2>/dev/null \
    && kill -0 "$worker_pid" 2>/dev/null; do
    sleep 1
done

shutdown
exit 1
