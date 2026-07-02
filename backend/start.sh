#!/bin/bash
set -e

echo "============================================"
echo "  Musically — API Server Startup"
echo "============================================"
echo ""

# Run database migrations
echo "Running database migrations..."
cd /app
alembic upgrade head
echo "Migrations complete."
echo ""

# Start FastAPI
echo "Starting FastAPI server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
