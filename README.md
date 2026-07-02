# Musically 🎵

**Self-hosted music library automation.** Musically watches your LastFM listening history, Spotify playlists, and existing music library to intelligently queue full albums for download from Qobuz, automatically tags them with beets, and drops them into your FLAC library.

> Built for Unraid NAS. Runs anywhere Docker Compose runs.

## Features

- 🔍 **Smart discovery** — Polls LastFM, Spotify, and MusicBrainz to find music you'll love
- 📥 **Auto-download** — Queues albums from Qobuz based on configurable rules
- 🏷️ **Auto-tagging** — Uses beets (MusicBrainz) to tag FLACs perfectly
- 📊 **Dashboard** — Swipeable mobile web UI built with React + Cohere design system
- 🔔 **Discord notifications** — Get notified when downloads complete
- 📂 **Watch folder** — Drop files into a folder and they're tagged + sorted automatically

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) v2+
- A [Qobuz](https://www.qobuz.com/) account (for downloads)
- A [LastFM](https://www.last.fm/) account (for listening history)
- Optional: [Spotify](https://developer.spotify.com/) API credentials (for playlist integration)
- Optional: [Discord](https://discord.com/) webhook URL (for notifications)

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/your-username/musically.git
cd musically

# 2. Create your environment file
cp .env.example .env

# 3. Edit .env with your credentials and settings
#    At minimum, set: SECRET_KEY, DB_PASSWORD, QOBUZ_EMAIL, QOBUZ_PASSWORD

# 4. Start all services
docker compose up -d

# 5. Open the web UI
#    http://localhost:8080
```

The app will be available at **http://localhost:8080**. API docs are at **http://localhost:8080/docs** (Swagger) and **http://localhost:8080/redoc**.

## Development Mode

For local development with hot-reload:

```bash
# Uses docker-compose.override.yml automatically
docker compose up -d

# Or explicitly specify both files
docker compose -f docker-compose.yml -f docker-compose.override.yml up
```

In dev mode:
- **Frontend**: Vite dev server with HMR on port **5173**
- **Backend**: Uvicorn with `--reload` (auto-restarts on code changes)
- **Database**: SQLite (no PostgreSQL container needed)
- **Source mounts**: `backend/` and `frontend/src/` are mounted into containers

Access the dev frontend directly at **http://localhost:5173** or through Nginx at **http://localhost:8080**.

## Architecture

```
Nginx (port 8080) → serves React SPA + proxies /api → FastAPI:8000
FastAPI → PostgreSQL:5432 (prod) / SQLite (dev) + Redis:6379
Celery Worker + Beat → Redis broker → shared DB
```

See [SPEC.md](SPEC.md) for the full architecture, data models, and rule engine design.

## Services

| Service | Image | Role |
|---------|-------|------|
| `nginx` | Custom (nginx:1.25-alpine + React build) | Reverse proxy + SPA |
| `api` | Custom (python:3.11-slim + FastAPI) | REST API backend |
| `worker` | Custom (same as api) | Celery background tasks |
| `beat` | Custom (same as api) | Celery periodic scheduler |
| `db` | postgres:16-alpine | PostgreSQL database (prod) |
| `redis` | redis:7-alpine | Message broker + cache |

## Configuration

All configuration is via environment variables in `.env`. See [`.env.example`](.env.example) for a complete reference.

### Key settings

| Variable | Description |
|----------|-------------|
| `SECRET_KEY` | Encryption key for sensitive settings at rest |
| `DB_PASSWORD` | PostgreSQL password (production only) |
| `APP_PORT` | Port for the web UI (default: 8080) |
| `QOBUZ_EMAIL` / `QOBUZ_PASSWORD` | Qobuz account credentials |
| `LASTFM_API_KEY` / `LASTFM_USERNAME` | LastFM integration |
| `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` | Spotify integration |
| `DISCORD_WEBHOOK_URL` | Discord notification webhook |

## Volumes

| Container Path | Purpose |
|---------------|---------|
| `/music` | Your FLAC music library (NAS mount in production) |
| `/downloads` | Temporary staging for Qobuz downloads |
| `/config` | beets configuration + app settings |

## Unraid Installation

Musically is designed to run on Unraid via Docker Compose. An Unraid Community Apps template is included for easy setup.

### Prerequisites

- Unraid 6.12+ with Docker and Docker Compose installed
- A music share at `/mnt/user/music` (or adjust paths in `docker-compose.yml`)
- An appdata share at `/mnt/user/appdata/musically` (created automatically)

### Setup Steps

```bash
# 1. Place the project on your Unraid server (e.g., in /mnt/user/appdata/musically/)
cd /mnt/user/appdata/musically

# 2. Create your environment file
cp .env.example .env

# 3. Edit .env with your credentials
#    At minimum, fill in:
#    - SECRET_KEY     (generate with: openssl rand -hex 32)
#    - DB_PASSWORD    (choose a strong database password)
#    - QOBUZ_EMAIL    (your Qobuz account email)
#    - QOBUZ_PASSWORD (your Qobuz account password)
nano .env

# 4. Create required directories
mkdir -p /mnt/user/appdata/musically/data/downloads
mkdir -p /mnt/user/appdata/musically/data/postgres
mkdir -p /mnt/user/appdata/musically/data/redis

# 5. Start all services
docker compose up -d

# 6. Check logs
docker compose logs -f
```

### Unraid Community Apps Template

The template file `unraid/musically.xml` provides one-click installation from the Unraid web UI.

**1. Copy the template file to the correct location**

Place your `musically.xml` file into the following directory on your Unraid server's USB boot drive:

```
/boot/config/plugins/dockerMan/templates-user/
```

You can do this via:

- **Unraid Web UI** → click the **Terminal** icon (`>_`) in the top right, then run:
  ```bash
  cp /path/to/musically.xml /boot/config/plugins/dockerMan/templates-user/
  ```
- **SSH** into your server and copy the file there.
- **SMB/Network share** — access the `flash` share (your USB boot drive) and navigate to `config/plugins/dockerMan/templates-user/` to paste the file.

**2. Add the container in the Unraid Web UI**

1. Go to the **Docker** tab in your Unraid web GUI.
2. Click **Add Container**.
3. In the **Template** dropdown, select **musically** (the template you just added).
4. Fill in the configuration fields (paths, ports, variables, etc.) as needed.
5. Click **Apply**.

**Volume Mappings:**

| Host Path | Container Path | Purpose |
|-----------|---------------|---------|
| `/mnt/user/music` | `/music` | Your FLAC music library |
| `/mnt/user/appdata/musically/downloads` | `/downloads` | Qobuz download staging |
| `/mnt/user/appdata/musically/config` | `/config` | beets config + app settings |
| `/mnt/user/appdata/musically/data/postgres` | `/var/lib/postgresql/data` | PostgreSQL database |
| `/mnt/user/appdata/musically/data/redis` | `/data` | Redis data |

### Auto-Updates

Musically includes [Watchtower](https://containrrr.dev/watchtower/) for automatic container updates. It checks for new images every 24 hours and only updates containers labeled with `com.centurylinklabs.watchtower.enable=true`. To disable auto-updates, remove the `watchtower` service from `docker-compose.yml`.

### Accessing the Web UI

After starting, open your browser to:
```
http://[your-unraid-ip]:8080
```

API documentation is available at:
- Swagger UI: `http://[your-unraid-ip]:8080/docs`
- ReDoc: `http://[your-unraid-ip]:8080/redoc`

## License

This project is for personal use. See LICENSE file for details.
