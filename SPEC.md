# Musically — Project Specification

## Overview

A self-hosted Docker application (target: Unraid) called **Musically** that watches your LastFM listening, your Spotify playlists, and your existing music library to intelligently queue full albums for download from Qobuz, then automatically tags them with beets and drops them into your FLAC library at `\\NAS-01\music\library`. Also monitors a watch folder at `\\NAS-01\music\downloads` for manually acquired files.

## Design Language

**Cohere design system** via `getdesign`. Run this in the frontend directory:

```bash
npx getdesign@latest add cohere
```

This generates a `DESIGN.md` that Copilot (and other AI coding agents) can read to apply the Cohere visual language:
| Token | Value |
| --- | --- |
| **Primary / Near-Black** | `#17171c` — CTAs, footer, deep UI cards |
| **Accent / Coral** | `#ff7759` — highlights, active elements, swipe indicators |
| **Deep Green** | `#003c33` — dark mode panels, hero bands |
| **Background** | `#fafafa` — page backgrounds, light mode |
| **Display typeface** | CohereText (serif) — headings, album titles |
| **UI typeface** | Unica77 / system sans fallback — body, buttons, controls |
| **Aesthetic** | Vibrant gradients, data-rich dashboard, enterprise AI feel |

TailwindCSS should be configured with these tokens. The DESIGN.md will guide Copilot on component styling.

* * *

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Docker Compose (Unraid)                       │
│                                                                   │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────────────┐  │
│  │   Nginx     │──▶│  FastAPI      │──▶│  PostgreSQL           │  │
│  │  (port 80)  │   │  (API+Admin)  │   │  (or SQLite)          │  │
│  │  + React SPA│   └──────┬───────┘   └──────────────────────┘  │
│  └─────────────┘          │                                       │
│                           │                                       │
│                    ┌──────┴───────┐                               │
│                    │    Redis     │                               │
│                    │  (broker +   │                               │
│                    │   cache)     │                               │
│                    └──────┬───────┘                               │
│                           │                                       │
│                    ┌──────┴───────┐                               │
│                    │ Celery       │                               │
│                    │ Worker(s)    │                               │
│                    │ - download   │                               │
│                    │ - beets tag  │                               │
│                    │ - retries    │                               │
│                    │ - watch dir  │                               │
│                    └──────┬───────┘                               │
│                           │                                       │
│  ┌────────────────────────┼────────────────────────────────────┐ │
│  │  Mounted Volumes                                             │ │
│  │  /music          → /mnt/user/music       (NAS FLAC library)  │ │
│  │  /music/library  → /mnt/user/music/library (beets target)    │ │
│  │  /music/downloads→ /mnt/user/music/downloads (watch folder)  │ │
│  │  /downloads      → temp staging for Qobuz downloads          │ │
│  │  /config         → app config, beets config, DB              │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

* * *

## Tech Stack

| Layer | Technology | Why |
| --- | --- | --- |
| Backend API | FastAPI (Python 3.11+) | Async, Swagger docs built-in |
| Task Queue | Celery + Redis | Reliable background jobs with retries |
| Database | PostgreSQL (prod) / SQLite (dev) | SQLAlchemy abstracts both |
| Frontend | React + Vite + TailwindCSS + DESIGN.md (Cohere) | Swipeable mobile web, clean desktop list |
| Reverse Proxy | Nginx | Serves SPA, proxies `/api` |
| Tagger | beets CLI | MusicBrainz-powered, fully automatable |
| Downloads | User's Qobuz script | Adapted as importable Python module or subprocess |
| Design | `getdesign` Cohere theme | DESIGN.md for AI-assisted styling |

* * *

## Rule Engine (The Core Logic)

Runs on a configurable cron schedule (default: every 30 minutes).

```
                    ┌─────────────────────────────┐
                    │  Sync Cycle Triggered        │
                    │  (cron or manual)            │
                    └─────────────┬───────────────┘
                                  │
         ┌────────────────────────┼────────────────────────┐
         ▼                        ▼                         ▼
   ┌──────────┐           ┌──────────────┐          ┌──────────────┐
   │ LastFM   │           │ Spotify API  │          │ MusicBrainz  │
   │ recent   │           │ seasonal +   │          │ check new    │
   │ tracks   │           │ discover     │          │ releases for │
   │ poll     │           │ playlists    │          │ subscribed   │
   └────┬─────┘           └──────┬───────┘          │ artists      │
        │                        │                  └──────┬───────┘
        ▼                        ▼                         ▼
   ┌──────────────────────────────────────────────────────────┐
   │                 Rule Evaluation                           │
   │                                                          │
   │  R1: Play count ≥ N on same album → QUEUE (auto)         │
   │  R2: Song on seasonal playlist → QUEUE (auto)            │
   │  R3: Play count ≥ N for artist → SUBSCRIBE artist        │
   │  R4: Already own ≥ N albums by artist → SUBSCRIBE artist │
   │  R5: Subscribed artist has new release → QUEUE (auto)    │
   │  R6: Song from discover playlists → QUEUE (manual)       │
   │  R7: File appears in watch folder → QUEUE (tag+move)     │
   │                                                          │
   │  ALL thresholds configurable in Settings.                │
   └──────────────────────────┬───────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     ┌─────────────────┐            ┌─────────────────┐
     │  Auto Queue      │            │  Manual Queue    │
     │  (downloaded     │            │  (swipe/approve  │
     │   immediately)   │            │   required)      │
     └────────┬────────┘            └────────┬────────┘
              │                               │
              └───────────────┬───────────────┘
                              ▼
                    ┌─────────────────┐
                    │  Download Worker │
                    │  Qobuz → beets   │
                    │  → /music/library│
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Discord Webhook │
                    │  Notification    │
                    └─────────────────┘
```

### Queue States

```
queued ──▶ downloading ──▶ downloaded
   │                          │
   ├──▶ stalled ──▶ (retry) ──┘
   │
   └──▶ rejected (manual queue only)
```

| Status | Meaning |
| --- | --- |
| `queued` | Waiting for worker to pick up |
| `downloading` | Worker is fetching from Qobuz |
| `downloaded` | Successfully downloaded and tagged by beets |
| `stalled` | Qobuz doesn't have it; retry schedule: 24h → 3d → 7d → 14d (configurable) |
| `rejected` | User swiped left / clicked reject (manual queue only) |

* * *

## Data Models

```python
# ── TrackPlay (from LastFM polling) ──
class TrackPlay:
    id: UUID
    track_name: str
    artist_name: str
    album_name: str
    album_mbid: str | None
    artist_mbid: str | None
    played_at: datetime
    created_at: datetime

# ── Album ──
class Album:
    id: UUID
    title: str
    artist_name: str
    album_mbid: str | None
    qobuz_id: str | None
    status: AlbumStatus          # queued | downloading | downloaded | stalled | rejected
    queue_type: QueueType        # auto | manual | watch_folder
    reason: str                  # "5+ plays", "in Winter 2025", "new release", "watch folder"
    play_count: int
    retry_count: int
    next_retry_at: datetime | None
    downloaded_at: datetime | None
    created_at: datetime

# ── Artist ──
class Artist:
    id: UUID
    name: str
    artist_mbid: str | None
    subscribed: bool
    subscription_source: str | None  # "auto_play_count" | "auto_library_size" | "manual"
    albums_in_library: int
    total_play_count: int
    last_mb_check: datetime | None
    created_at: datetime

# ── Playlist (synced from Spotify) ──
class Playlist:
    id: UUID
    spotify_id: str
    name: str
    playlist_type: PlaylistType  # seasonal | discover | other
    is_active: bool
    last_synced_at: datetime | None

# ── PlaylistTrack ──
class PlaylistTrack:
    id: UUID
    playlist_id: FK[Playlist]
    track_name: str
    artist_name: str
    album_name: str
    spotify_uri: str
    created_at: datetime

# ── Settings (key-value, comprehensive) ──
class Setting:
    key: str
    value: str       # JSON-typed
    description: str
    category: str    # "thresholds" | "scheduling" | "sources" | "library" | "notifications" | "api_keys" | "beets"
```

* * *

## API Endpoints

```
# ── Auth / Health ──
GET    /api/health
GET    /api/stats

# ── Queue ──
GET    /api/queue                       # ?status=&type=&page=&limit=&sort=
GET    /api/queue/:id
POST   /api/queue/:id/approve
POST   /api/queue/:id/reject
POST   /api/queue/:id/retry
POST   /api/queue/bulk-approve          # { ids: [...] }
POST   /api/queue/bulk-reject

# ── Albums (downloaded) ──
GET    /api/albums                      # ?artist=&search=&sort=&page=&limit=
GET    /api/albums/:id

# ── Artists ──
GET    /api/artists                     # ?subscribed=&search=&page=
GET    /api/artists/:id
POST   /api/artists/:id/subscribe
POST   /api/artists/:id/unsubscribe
GET    /api/artists/:id/albums

# ── Playlists ──
GET    /api/playlists
PUT    /api/playlists/:id
POST   /api/playlists/refresh

# ── Sync ──
POST   /api/sync/trigger
GET    /api/sync/history                # ?page=&limit=

# ── Settings ──
GET    /api/settings                    # ?category=
PUT    /api/settings                    # { "key": "value", ... }

# ── Notifications ──
POST   /api/notifications/test

# ── Logs ──
GET    /api/logs                        # ?level=&page=&limit=
```

* * *

## Frontend Pages & Features

| Page | Desktop View | Mobile View | Key Interactions |
| --- | --- | --- | --- |
| **Dashboard** | Stats cards grid, recent activity feed, quick approve/reject | Stacked cards | View library stats, sync status, last download |
| **Queue** | Filterable table with bulk actions | Simplified list with swipe actions | Approve/reject, sort by reason/date |
| **Swipe** | Card stack with buttons | Full-screen Tinder-style card stack | Swipe right=approve, left=reject, tap for details |
| **Library** | Searchable, sortable grid of album art | Responsive grid | Browse, search, click for album detail |
| **Artists** | Table of subscribed/tracked artists | Simplified list | Subscribe/unsubscribe, view albums |
| **Settings** | Tabbed form with categories | Same, touch-optimized | Edit all config, connect Spotify, test webhook |

### Swipe Card Design (Cohere-styled)

Each card shows:

*   Album cover art (Cover Art Archive, fallback to Spotify)
    
*   Artist — Album Title (CohereText serif for title)
    
*   Release year badge
    
*   Reason tag: "You played this 7×", "In Winter 2025", "New from Radiohead"
    
*   Current status indicator
    
*   Coral accent for approve action, muted for reject
    

* * *

## Settings (Comprehensive — All Configurable via UI)

```python
DEFAULT_SETTINGS = {
    # ── Thresholds ──
    "album_play_threshold": 5,
    "artist_subscribe_play_threshold": 20,
    "library_albums_subscribe_threshold": 3,

    # ── Scheduling ──
    "sync_interval_minutes": 30,
    "new_release_check_hours": 12,
    "watch_folder_check_seconds": 60,
    "stalled_retry_intervals_hours": [24, 72, 168, 336],
    "backfill_days": 30,
    "max_backfill_albums": 100,

    # ── Sources (enabled/disabled) ──
    "lastfm_enabled": True,
    "spotify_enabled": True,
    "qobuz_enabled": True,
    "musicbrainz_enabled": True,
    "watch_folder_enabled": True,

    # ── Spotify playlists ──
    "spotify_seasonal_playlist_pattern": "Winter|Summer|Fall",
    "spotify_discover_playlist_names": ["Release Radar", "Pitchfork Selects"],
    "spotify_auto_sync_playlists": True,

    # ── Library paths ──
    "music_library_directory": "/music/library",
    "music_downloads_watch_directory": "/music/downloads",
    "qobuz_temp_download_directory": "/downloads",
    "beets_config_path": "/config/beets/config.yaml",

    # ── beets naming scheme ──
    "beets_path_format": "$albumartist/$album/$disc-$track $artist - $title",
    "beets_import_quiet": True,
    "beets_import_copy": False,          # False = move (we're on same filesystem)
    "beets_import_write": True,
    "beets_import_autotag": True,

    # ── Notifications ──
    "discord_webhook_url": "",
    "notify_on_download": True,
    "notify_on_queued_manual": True,
    "notify_on_stalled": True,
    "notify_on_error": True,
    "notify_on_watch_folder": True,

    # ── API Keys ──
    "lastfm_api_key": "",
    "spotify_client_id": "",
    "spotify_client_secret": "",
    "qobuz_email": "",
    "qobuz_password_encrypted": "",      # Encrypted at rest

    # ── Rate Limiting ──
    "lastfm_rate_limit_rps": 4.5,
    "spotify_rate_limit_rpm": 150,
    "musicbrainz_rate_limit_rps": 0.9,
    "qobuz_rate_limit_rps": 2.0,
}
```

* * *

## Download Pipeline (Celery Task)

```
1. Worker picks up Album (status=queued) from queue
2. Set status → downloading
3. Qobuz lookup:
   a. Search by artist + album title (via user's adapted Qobuz script)
   b. If found → download FLACs to /downloads/<uuid>/
   c. If NOT found → set status=stalled, schedule retry, notify Discord
4. beets import:
   a. Run: beet import -q -l /config/beets/config.yaml /downloads/<uuid>/
   b. On success → files moved to /music/library per naming scheme
   c. On failure → log, move to manual review queue, notify
5. Set status → downloaded, set downloaded_at
6. Discord notification: "✅ Musically: Artist — Album downloaded"
7. Update Artist.albums_in_library count
```

### Watch Folder Pipeline (Separate Celery Task)

```
1. File system watcher (watchdog) detects new files in /music/downloads
2. For each new file/folder:
   a. Deduplicate: check if album already in library
   b. If new → create Album entry (queue_type=watch_folder, status=queued)
   c. Run beets import directly (skip Qobuz download)
   d. On success → move to /music/library, notify
   e. On failure → leave in place, notify, mark for manual review
```

* * *

## Qobuz Script Integration

The user will provide source code for their existing Qobuz download script. The `app/services/qobuz.py` service should be built as a flexible wrapper:

```python
# app/services/qobuz.py

class QobuzService:
    """Wraps the user's Qobuz download script."""

    def __init__(self, config: QobuzConfig):
        self.email = config.email
        self.password = decrypt(config.password_encrypted)
        self.token: str | None = None
        self.token_expiry: datetime | None = None

    async def search_album(self, artist: str, album: str) -> QobuzAlbum | None:
        """Search Qobuz for an album. Returns None if not found."""
        ...

    async def download_album(
        self,
        qobuz_id: str,
        dest_dir: Path
    ) -> bool:
        """Download FLACs to dest_dir. Returns True on success."""
        ...

    async def refresh_token(self) -> None:
        """Refresh the Qobuz auth token."""
        ...
```

The script can be called either:

*   **As subprocess**: `subprocess.run(["python", "qobuz_dl.py", ...])`
    
*   **As import**: Direct Python import if the script is refactored into a module
    

Both paths should be supported via a strategy pattern so the user can choose.

* * *

## API Keys & Rate Limits

| Service | Key Setup | Rate Limit | Notes |
| --- | --- | --- | --- |
| **LastFM** | [Get API key](https://www.last.fm/api/account/create) | ~5 req/sec | Poll with `from` timestamp cursor to avoid dupes |
| **Spotify** | [Developer Dashboard](https://developer.spotify.com/dashboard) | ~180 req/min | OAuth PKCE for reading private playlists. `spotipy` handles token refresh |
| **MusicBrainz** | No key required | 1 req/sec | beets handles internally. Direct calls use rate-limited decorator |
| **Qobuz** | Existing auth (provided by user) | Unknown | Token refresh logic in wrapper |
| **Discord** | Create webhook in server settings | 30 req/min | Trivially within limits |

### Spotify OAuth Note

Since you're reading your own private playlists:

1.  Settings page has "Connect Spotify" button
    
2.  Redirects to Spotify auth (PKCE flow)
    
3.  Refresh token stored in DB (encrypted)
    
4.  Auto-refreshes access token as needed
    

* * *

## Directory Structure

```
musically/
├── docker-compose.yml
├── .env.example
├── .dockerignore
├── README.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── config.py              # Pydantic BaseSettings from env + DB settings
│   │   ├── database.py
│   │   │
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── album.py
│   │   │   ├── artist.py
│   │   │   ├── track_play.py
│   │   │   ├── playlist.py
│   │   │   ├── playlist_track.py
│   │   │   └── setting.py
│   │   │
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── album.py
│   │   │   ├── artist.py
│   │   │   ├── queue.py
│   │   │   └── settings.py
│   │   │
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── albums.py
│   │   │   ├── artists.py
│   │   │   ├── queue.py
│   │   │   ├── playlists.py
│   │   │   ├── sync.py
│   │   │   ├── settings.py
│   │   │   ├── notifications.py
│   │   │   └── logs.py
│   │   │
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── lastfm.py
│   │   │   ├── spotify.py
│   │   │   ├── qobuz.py           # Flexible wrapper for user's script
│   │   │   ├── beets.py
│   │   │   ├── musicbrainz.py
│   │   │   ├── downloader.py      # Celery task: full pipeline
│   │   │   ├── watch_folder.py    # File system watcher service
│   │   │   ├── rules.py           # Rule engine
│   │   │   └── notifications.py   # Discord webhook
│   │   │
│   │   ├── scheduler.py           # APScheduler cron triggers
│   │   └── celery_app.py
│   │
│   └── tests/
│
├── frontend/
│   ├── Dockerfile
│   ├── DESIGN.md                  # Generated by: npx getdesign@latest add cohere
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts         # Extended with Cohere tokens from DESIGN.md
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api/
│       │   └── client.ts
│       ├── pages/
│       │   ├── Dashboard.tsx
│       │   ├── Queue.tsx
│       │   ├── Swipe.tsx
│       │   ├── Library.tsx
│       │   ├── Artists.tsx
│       │   └── Settings.tsx
│       ├── components/
│       │   ├── Layout.tsx
│       │   ├── Navbar.tsx
│       │   ├── Sidebar.tsx
│       │   ├── AlbumCard.tsx
│       │   ├── SwipeDeck.tsx
│       │   ├── QueueTable.tsx
│       │   ├── StatsCard.tsx
│       │   ├── SettingsForm.tsx
│       │   ├── ConfirmModal.tsx
│       │   ├── Badge.tsx
│       │   └── EmptyState.tsx
│       ├── hooks/
│       │   ├── useSwipe.ts
│       │   ├── useApi.ts
│       │   └── useMediaQuery.ts   # Detect mobile vs desktop
│       └── utils/
│           └── format.ts
│
├── nginx/
│   ├── Dockerfile
│   └── default.conf
│
└── config/                        # Mounted as /config in containers
    ├── beets/
    │   └── config.yaml            # beets config with user's naming scheme
    └── app.env                    # Optional env overrides
```

* * *

## docker-compose.yml

```yaml
version: "3.8"

services:
  api:
    build: ./backend
    container_name: musically-api
    environment:
      - DATABASE_URL=postgresql://musically:${DB_PASSWORD}@db:5432/musically
      - REDIS_URL=redis://redis:6379/0
      - MUSIC_DIR=/music
      - DOWNLOADS_DIR=/downloads
      - CONFIG_DIR=/config
    volumes:
      - /mnt/user/music:/music           # NAS music share
      - ./data/downloads:/downloads      # Temp Qobuz download staging
      - ./config:/config                 # beets config + app settings
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped

  worker:
    build: ./backend
    container_name: musically-worker
    command: celery -A app.celery_app worker --loglevel=info --concurrency=2
    environment:
      - DATABASE_URL=postgresql://musically:${DB_PASSWORD}@db:5432/musically
      - REDIS_URL=redis://redis:6379/0
      - MUSIC_DIR=/music
      - DOWNLOADS_DIR=/downloads
      - CONFIG_DIR=/config
    volumes:
      - /mnt/user/music:/music
      - ./data/downloads:/downloads
      - ./config:/config
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped

  beat:
    build: ./backend
    container_name: musically-beat
    command: celery -A app.celery_app beat --loglevel=info
    environment:
      - DATABASE_URL=postgresql://musically:${DB_PASSWORD}@db:5432/musically
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    container_name: musically-db
    environment:
      POSTGRES_USER: musically
      POSTGRES_PASSWORD: ${DB_PASSWORD}
      POSTGRES_DB: musically
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U musically"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: musically-redis
    volumes:
      - ./data/redis:/data
    restart: unless-stopped

  nginx:
    build: ./nginx
    container_name: musically-nginx
    ports:
      - "${APP_PORT:-8080}:80"
    depends_on:
      - api
    restart: unless-stopped
```

* * *

## Implementation Phases (For Copilot)

### Phase 1 — Skeleton + Database

1.  Scaffold FastAPI app with health endpoint
    
2.  Set up SQLAlchemy models + Alembic migrations for all tables
    
3.  Docker Compose with all services running
    
4.  Settings CRUD endpoints (full category support)
    
5.  Run `npx getdesign@latest add cohere` in frontend
    
6.  Scaffold React app with TailwindCSS extended from DESIGN.md
    
7.  Basic shell: Layout, Navbar, routing, Settings page
    

### Phase 2 — LastFM Integration

1.  LastFM API client (`user.getRecentTracks`)
    
2.  Play aggregation (count plays per album, per artist)
    
3.  APScheduler that polls every N minutes
    
4.  TrackPlay model populated
    
5.  Backfill: process last 30 days on first run
    

### Phase 3 — Qobuz + beets Pipeline

1.  Qobuz service — flexible wrapper (subprocess + import strategy)
    
2.  beets service wrapper (`beet import -q`)
    
3.  Celery task: full download → tag → move pipeline
    
4.  Album queue with auto/manual split
    
5.  Stalled detection + configurable retry scheduling
    
6.  Discord webhook notifications
    

### Phase 4 — Watch Folder

1.  `watchdog`-based file system watcher on `/music/downloads`
    
2.  Deduplication against library
    
3.  Auto-tag via beets, move to library
    
4.  Manual review queue for failed imports
    

### Phase 5 — Rule Engine

1.  R1: Play count threshold → auto queue
    
2.  R2: Seasonal playlist match → auto queue
    
3.  R3: Artist play threshold → subscribe
    
4.  R4: Library size threshold → subscribe
    
5.  R5: Subscribed artist new releases → auto queue
    
6.  R6: Discover playlists → manual queue
    
7.  All thresholds pulled from Settings table at evaluation time
    

### Phase 6 — Spotify Integration

1.  Spotify OAuth PKCE flow (Settings page button)
    
2.  Playlist sync (find seasonal by regex, discover by name list)
    
3.  Track-to-album deduplication
    

### Phase 7 — Frontend Polish

1.  Queue page — filterable table with bulk approve/reject
    
2.  Swipe page — mobile-first touch card stack (react-tinder-card or custom)
    
3.  Library page — searchable album art grid
    
4.  Artists page — subscribe/unsubscribe management
    
5.  Dashboard — stats cards with Cohere styling
    
6.  Responsive: swipe UI on mobile, table UI on desktop
    

### Phase 8 — Polish & Hardening

1.  Rate limiting decorators for all external API calls
    
2.  Qobuz token expiry detection + auto-refresh
    
3.  Download failure recovery
    
4.  Duplicate album detection (normalized artist+album matching)
    
5.  beets import failure → manual review queue
    
6.  API key encryption at rest
    
7.  Comprehensive logging
    

* * *

## Potential Pitfalls

| Issue | Mitigation |
| --- | --- |
| LastFM doesn't always return MBIDs | Fall back to artist+album name matching; use MB search API |
| Qobuz token expires mid-download | Catch auth errors, refresh token, retry once |
| beets interactive prompts | `-q` flag + `import.quiet: yes` + manual review for tough matches |
| Spotify playlist names change | Explicit playlist selection in Settings (dropdown from synced list) |
| Duplicate albums across rules | Normalize `(artist_name, album_name)` before inserting |
| MusicBrainz rate limit | `@rate_limit(calls=1, per_seconds=1.1)` decorator |
| First run processing too much history | `backfill_days: 30` + `max_backfill_albums: 100` settings |
| Watch folder picks up incomplete transfers | Wait for file stability (no writes for N seconds) before processing |
| Qobuz script changes over time | Strategy pattern in QobuzService — swap implementation without touching pipeline |