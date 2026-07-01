# Musically — Project Guidelines

## Code Style

### Python (backend/)
- Python 3.11+ with full type hints (`str | None`, `list[dict]`, etc.)
- `async`/`await` for all FastAPI endpoints and external API calls
- Pydantic v2 for settings and schemas
- SQLAlchemy 2.0+ with async session
- Ruff for linting + formatting (config in `pyproject.toml`)
- pytest + pytest-asyncio for tests; aim for >80% coverage on services

### TypeScript / React (frontend/)
- TypeScript strict mode
- React functional components with hooks; no class components
- TanStack Query (React Query v5) for all server state
- TailwindCSS with Cohere design tokens (see `frontend/DESIGN.md`)
- Components handle loading, empty, and error states
- Mobile-first responsive design (breakpoints: 375px, 768px, 1280px)

## Architecture

See `SPEC.md` for the full architecture. Key points:
- **Nginx** reverse-proxies `/api` → FastAPI and serves the React SPA
- **Celery + Redis** for async task queue (download, tag, watch folder)
- **Rule engine** evaluates on cron schedule; thresholds are configurable
- **beets CLI** called as subprocess for tagging
- **Qobuz downloader** adapted from `Reference Code/minimal-downloader.py`
- Target deployment: Docker Compose on Unraid

## Build and Test

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt
pytest

# Frontend
cd frontend
npm install
npm run dev        # development server
npm run build      # production build
npm run lint       # ESLint + Prettier

# Full stack (Docker)
docker compose up -d
```

## Conventions

### Git
- Branch naming: `feature/<name>`, `fix/<name>`, `chore/<name>`
- Commit messages: conventional commits (`feat:`, `fix:`, `chore:`, `docs:`)
- PRs require a description and link to the task plan from the PM agent

### File Organization
- Backend: follow the structure in `musically-backend.agent.md`
- Frontend: follow the structure in `musically-frontend.agent.md`
- Infrastructure: follow the structure in `musically-infra.agent.md`

### API Design
- RESTful endpoints under `/api/v1/`
- OpenAPI docs auto-generated at `/docs` (Swagger) and `/redoc`
- Pydantic models for all request/response schemas

### Environment
- All secrets via environment variables (never committed)
- `.env.example` documents all required vars; copy to `.env` for local dev
- Qobuz credentials, LastFM/Spotify API keys, Discord webhook URL, DB URL, Redis URL
