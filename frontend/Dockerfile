# =============================================================================
# Musically — Frontend Dockerfile (Development)
# =============================================================================
# Used by docker-compose.override.yml for local dev with Vite HMR.
#
# Production builds are handled by the nginx/Dockerfile multi-stage build,
# which compiles the React SPA and serves it directly from Nginx.
#
# This Dockerfile targets the `dev` stage which keeps node_modules and
# runs `npm run dev` for hot-reload development.
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1 — Base: install dependencies
# ---------------------------------------------------------------------------
FROM node:24-alpine AS base

WORKDIR /app

# Install dependencies (cached layer)
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

# ---------------------------------------------------------------------------
# Stage 2 — Dev: Vite dev server with HMR
# ---------------------------------------------------------------------------
FROM base AS dev

WORKDIR /app

# Copy the full frontend source (overlayed by volume mounts in compose)
COPY frontend/ .

EXPOSE 5173

# Vite dev server — --host 0.0.0.0 makes it accessible from outside the container
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
