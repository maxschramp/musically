# =============================================================================
# Musically — Backend Dockerfile (FastAPI + Celery)
# =============================================================================
# Multi-stage build: slim builder → slim runtime.
# This image is used by three services:
#   - api:    uvicorn app.main:app
#   - worker: celery -A app.celery_app worker
#   - beat:   celery -A app.celery_app beat
#
# Each service overrides the CMD in docker-compose.yml or override.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Builder: install system deps and Python packages
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system build dependencies
# - beets: music tagger (via apt, includes dependencies like ffmpeg)
# - ffmpeg: audio processing
# - gcc/g++/libffi-dev: needed to compile some Python packages
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        beets \
        ffmpeg \
        gcc \
        g++ \
        libffi-dev \
        libssl-dev \
        && rm -rf /var/lib/apt/lists/*

# Create a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — Runtime: slim production image
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime system dependencies only (no build tools)
# - beets: music tagger
# - ffmpeg: audio processing
# - libmagic1: file type detection
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        beets \
        ffmpeg \
        libmagic1 \
        && rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r musically && useradd -r -g musically -d /app musically

# Create app directories
RUN mkdir -p /app /music /downloads /config && \
    chown -R musically:musically /app /music /downloads /config

WORKDIR /app

# Copy backend application code
COPY backend/ .

# Make startup script executable
RUN chmod +x /app/start.sh

# Ensure the non-root user owns the app code
RUN chown -R musically:musically /app

# Switch to non-root user
USER musically

# Healthcheck for the API service
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default command (api service). Worker and beat override this.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
