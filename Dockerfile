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
# - postgresql: database (self-contained, no external DB needed)
# - redis-server: message broker for Celery tasks
# - supervisor: process manager (postgres + redis + nginx + uvicorn)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        beets \
        ffmpeg \
        libmagic1 \
        nginx \
        openssl \
        postgresql \
        redis-server \
        supervisor \
        && rm -rf /var/lib/apt/lists/*

# Copy Python virtual environment from builder
COPY --from=backend-builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy built React SPA from frontend builder
COPY --from=frontend-builder /app/dist /usr/share/nginx/html

# Copy nginx configuration
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY nginx/default.ssl.conf /etc/nginx/ssl/default.ssl.conf

# Remove default nginx site (conflicts with our config on port 80)
RUN rm -f /etc/nginx/sites-enabled/default

# Copy supervisord configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Copy entrypoint script (generates self-signed SSL cert for LAN HTTPS)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Build metadata for the bootup banner
ARG BUILD_DATE=unknown
ARG BUILD_REF=dev
ENV BUILD_DATE=${BUILD_DATE}
ENV BUILD_REF=${BUILD_REF}

# Copy backend application code
COPY backend/ /app/
WORKDIR /app

# Create non-root user and set up directories
RUN groupadd -r musically && useradd -r -g musically -d /app musically && \
    mkdir -p /music /downloads /config /app/data /var/log/supervisor && \
    mkdir -p /config/postgres /config/redis /run/postgresql && \
    mkdir -p /config/ssl /etc/nginx/ssl && \
    chown -R musically:musically /app /music /downloads /config /var/log/supervisor && \
    chown -R musically:musically /var/lib/nginx /var/log/nginx && \
    chown -R musically:musically /usr/share/nginx/html && \
    # PostgreSQL needs its data dir owned by the postgres user (UID/GID match)
    chown -R postgres:postgres /config/postgres /run/postgresql && \
    chmod 700 /config/postgres && \
    chmod +x /app/start.sh && \
    # Allow nginx to run as non-root (needs write access to /var/run for pid)
    mkdir -p /var/run/nginx && \
    chown -R musically:musically /var/run/nginx && \
    # Supervisor socket directory
    mkdir -p /var/run/supervisor && \
    chown -R musically:musically /var/run/supervisor

# Healthcheck for the API service
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Entrypoint: generates self-signed SSL cert for LAN HTTPS on first run
ENTRYPOINT ["/entrypoint.sh"]

# Default command: supervisord (nginx + uvicorn)
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
