# =============================================================================
# Musically — Single Docker Image (Multi-stage)
# =============================================================================
# One image for all services:
#   - api:    supervisord (nginx + uvicorn via start.sh)
#   - worker: celery -A app.celery_app worker
#   - beat:   celery -A app.celery_app beat
#
# Image: ghcr.io/maxschramp/musically
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Build React SPA
# ---------------------------------------------------------------------------
FROM node:24-alpine AS frontend-builder

WORKDIR /app

# Install dependencies first (better layer caching)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# Copy frontend source and build
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Build Python dependencies (virtualenv)
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS backend-builder

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system build dependencies
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
# Stage 3 — Runtime (Python + Nginx + Supervisor)
# ---------------------------------------------------------------------------
FROM python:3.11-slim

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install runtime system dependencies
# - beets: music tagger
# - ffmpeg: audio processing
# - libmagic1: file type detection
# - nginx: reverse proxy + static file serving
# - supervisor: process manager (nginx + uvicorn)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        beets \
        ffmpeg \
        libmagic1 \
        nginx \
        supervisor \
        && rm -rf /var/lib/apt/lists/*

# Copy Python virtual environment from builder
COPY --from=backend-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy built React SPA from frontend builder
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx/default.conf /etc/nginx/conf.d/default.conf

# Copy supervisord configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy backend application code
COPY backend/ /app/
WORKDIR /app

# Create non-root user and set up directories
RUN groupadd -r musically && useradd -r -g musically -d /app musically && \
    mkdir -p /music /downloads /config /var/log/supervisor && \
    chown -R musically:musically /app /music /downloads /config /var/log/supervisor && \
    chown -R musically:musically /var/lib/nginx /var/log/nginx && \
    chown -R musically:musically /usr/share/nginx/html && \
    chmod +x /app/start.sh && \
    # Allow nginx to run as non-root (needs write access to /var/run for pid)
    mkdir -p /var/run/nginx && \
    chown -R musically:musically /var/run/nginx && \
    # Supervisor socket directory
    mkdir -p /var/run/supervisor && \
    chown -R musically:musically /var/run/supervisor

# Switch to non-root user
USER musically

# Healthcheck for the API service
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Default command: supervisord (nginx + uvicorn)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
