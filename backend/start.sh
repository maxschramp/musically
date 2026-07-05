#!/bin/bash
set -e

echo "============================================"
echo "  Musically — API Server Startup"
echo "============================================"
echo ""

# Find the PostgreSQL binary directory (version-independent).
# Debian installs postgres under /usr/lib/postgresql/<version>/bin/
PG_BIN=$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | head -1)
if [ -z "$PG_BIN" ]; then
    echo "ERROR: PostgreSQL installation not found."
    exit 1
fi
export PATH="$PG_BIN:$PATH"

# ---------------------------------------------------------------------------
# 1. Fix volume mount permissions
# ---------------------------------------------------------------------------
echo "Fixing volume permissions..."
mkdir -p /config /music /downloads
chown musically:musically /config /music /downloads 2>/dev/null || true
# Ensure postgres data dirs exist and have correct ownership
mkdir -p /config/postgres /config/redis /run/postgresql
chown -R postgres:postgres /config/postgres /run/postgresql 2>/dev/null || true
chown musically:musically /config/redis 2>/dev/null || true
echo "Permissions OK."
echo ""

# ---------------------------------------------------------------------------
# 2. Initialize PostgreSQL cluster (first run only)
# ---------------------------------------------------------------------------
if [ ! -f /config/postgres/PG_VERSION ]; then
    echo "Initializing PostgreSQL cluster in /config/postgres..."
    su - postgres -c "PATH=$PG_BIN:\$PATH initdb -D /config/postgres --auth=trust"
    echo "Cluster initialized."
fi

# ---------------------------------------------------------------------------
# 3. Wait for PostgreSQL to be ready
# ---------------------------------------------------------------------------
echo "Waiting for PostgreSQL..."
for i in $(seq 1 30); do
    if su - postgres -c "PATH=$PG_BIN:\$PATH pg_isready -h /run/postgresql" 2>/dev/null; then
        echo "PostgreSQL is ready."
        break
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 4. Create database user and database (idempotent)
# ---------------------------------------------------------------------------
echo "Ensuring database and user exist..."
su - postgres -c "PATH=$PG_BIN:\$PATH psql -h /run/postgresql -tc \"SELECT 1 FROM pg_roles WHERE rolname='musically'\" | grep -q 1 || createuser -h /run/postgresql -s musically" 2>/dev/null || true
su - postgres -c "PATH=$PG_BIN:\$PATH psql -h /run/postgresql -tc \"SELECT 1 FROM pg_database WHERE datname='musically'\" | grep -q 1 || createdb -h /run/postgresql -O musically musically" 2>/dev/null || true
echo "Database ready."
echo ""

# ---------------------------------------------------------------------------
# 5. Run Alembic migrations as musically user
# ---------------------------------------------------------------------------
echo "Running database migrations..."
cd /app
HOME=/app su -m musically -c "cd /app && alembic upgrade head"
echo "Migrations complete."
echo ""

# ---------------------------------------------------------------------------
# 6. Start FastAPI as musically user
# ---------------------------------------------------------------------------
echo "Starting FastAPI server..."
exec env HOME=/app su -m musically -c "cd /app && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"
