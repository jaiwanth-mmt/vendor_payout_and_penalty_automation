# syntax=docker/dockerfile:1
#
# Single production image for ECR / one-container deploy:
#   UI (Vite build) + API (uvicorn) on port 8000
#
#   docker build -t agentathon:local .
#
# Optional split targets still available: --target api | --target web

############################
# Frontend production build
############################
FROM node:20-bookworm-slim AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
# Same-origin /api (VITE_API_BASE_URL unset) — FastAPI serves the SPA in the final image.
RUN npm run build

############################
# API runtime (intermediate)
############################
FROM python:3.12-slim-bookworm AS api

COPY --from=ghcr.io/astral-sh/uv:0.11.3 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version README.md ./
RUN uv sync --frozen --no-install-project --no-cache

COPY backend ./backend
COPY main.py ./
COPY docker/api-entrypoint.sh /usr/local/bin/api-entrypoint.sh

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser \
    && mkdir -p /app/backend/.runtime \
    && chown -R appuser:appuser /app \
    && chmod +x /usr/local/bin/api-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"]

ENTRYPOINT ["/usr/local/bin/api-entrypoint.sh"]
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

############################
# Optional: nginx-only UI (needs a separate api service named "api")
############################
FROM nginx:1.27-alpine AS web

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1

############################
# Default: one image for ECR (API + UI)
############################
FROM api AS production

USER root
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
RUN chown -R appuser:appuser /app/frontend

# Entrypoint/CMD inherited from api. Listens on 8000.
