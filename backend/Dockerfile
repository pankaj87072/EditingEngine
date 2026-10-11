# ─────────────────────────────────────────────────────────────────────────────
# AutoVideoGen — Dockerfile
# Multi-stage build: deps → runtime
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# Install system deps: FFmpeg + fonts for subtitle rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fonts-liberation \
    fonts-dejavu \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Dependencies layer (cached unless requirements.txt changes) ───────────────
FROM base AS deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ── Runtime layer ─────────────────────────────────────────────────────────────
FROM deps AS runtime
COPY . .

# Create data directories
RUN mkdir -p data/uploads data/outputs

# Non-root user for security
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
