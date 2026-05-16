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
COPY services/alerts/ ./services/alerts/
RUN pip install ./shared ./services/alerts

WORKDIR /app/services/alerts

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8002/healthz || exit 1

CMD ["uvicorn", "alerts_app.main:app", "--host", "0.0.0.0", "--port", "8002"]
