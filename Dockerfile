FROM node:24-alpine AS frontend-build

WORKDIR /frontend

RUN npm install --global pnpm@11.3.0

COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY frontend/ ./

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN pnpm run build


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --yes --no-install-recommends nginx \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./
COPY deploy/render/nginx.conf /etc/nginx/nginx.conf.template
COPY deploy/render/start.sh /app/start-render.sh
COPY --from=frontend-build /frontend/dist /usr/share/nginx/html

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app"

CMD ["sh", "start-render.sh"]
