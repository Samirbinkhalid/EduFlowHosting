# ── Stage 1: dependency install ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Copy dependency manifests first (layer cache — only invalidated when deps change)
COPY pyproject.toml uv.lock* ./

# Install dependencies into an isolated venv inside the image
RUN uv sync --frozen --no-dev --no-install-project

# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install ffmpeg (required by ffmpeg-python for audio extraction)
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Pre-create persistent data dir and ephemeral TUS staging dir.
# /data is expected to be a named volume mount; creating it here ensures
# the directory exists even if the volume is not mounted (e.g. local dev).
RUN mkdir -p /data /app/uploads /tmp/tus_uploads

# Copy the venv from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY app/ ./app/

# Copy UI static files served by FastAPI
COPY ui/ ./ui/

# Put the venv on PATH so uvicorn / project scripts are found
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8090

# Uvicorn called directly — no uv needed at runtime
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8090", \
     "--workers", "4", \
     "--proxy-headers", \
     "--forwarded-allow-ips", "*"]
