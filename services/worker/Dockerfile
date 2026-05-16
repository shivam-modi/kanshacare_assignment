# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY shared/ ./shared/
COPY services/worker/ ./services/worker/
RUN pip install ./shared ./services/worker

WORKDIR /app/services/worker

EXPOSE 8003

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8003/healthz || exit 1

# Phase 1: only the health sidecar runs. Phase 5 will add an arq worker process
# (on Fly via [processes], or locally via a separate compose service).
CMD ["uvicorn", "worker_app.main:app", "--host", "0.0.0.0", "--port", "8003"]
