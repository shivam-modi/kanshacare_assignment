# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# curl for healthcheck convenience inside the container.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install shared first (changes less often → better layer caching), then the service.
COPY shared/ ./shared/
COPY services/ingestion/ ./services/ingestion/
RUN pip install ./shared ./services/ingestion

WORKDIR /app/services/ingestion

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

CMD ["uvicorn", "ingestion_app.main:app", "--host", "0.0.0.0", "--port", "8000"]
