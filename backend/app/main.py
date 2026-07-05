import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.constants import DEFAULT_SETTINGS
from app.database import Base, async_session_factory, engine
from app.routers import api_router
from app.scheduler import run_sync_job, run_mb_enrichment_job, run_artwork_cache_job, run_download_dispatcher, run_cleanup_job, run_library_import_job

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create tables if SQLite, start scheduler, start watch folder.
    Shutdown: stop watch folder, dispose engine, shutdown scheduler."""
    settings = get_settings()
    if "sqlite" in settings.DATABASE_URL:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    # Start APScheduler for periodic sync
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_sync_job,
        IntervalTrigger(minutes=30),
        id="lastfm_sync",
        replace_existing=True,
    )
    scheduler.add_job(
        run_mb_enrichment_job,
        IntervalTrigger(minutes=5),
        id='mb_enrichment',
        replace_existing=True,
    )
    scheduler.add_job(
        run_artwork_cache_job,
        IntervalTrigger(minutes=3),
        id="artwork_cache",
        replace_existing=True,
    )
    scheduler.add_job(
        run_download_dispatcher,
        IntervalTrigger(minutes=2),
        id="download_dispatcher",
        replace_existing=True,
    )
    scheduler.add_job(
        run_cleanup_job,
        IntervalTrigger(hours=6),
        id="cleanup",
        replace_existing=True,
    )
    scheduler.add_job(
        run_library_import_job,
        IntervalTrigger(minutes=30),
        id="library_import",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler

    # Start watch folder service (best-effort — failure does not crash the API)
    app.state.watch_folder_service = None
    try:
        from app.services.watch_folder import WatchFolderService
        from app.services.beets import BeetsService
        from app.services.notifications import NotificationService

        beets_config = DEFAULT_SETTINGS.get(
            "beets_config_path", "/config/beets/config.yaml"
        )
        discord_url = settings.DISCORD_WEBHOOK_URL or DEFAULT_SETTINGS.get(
            "discord_webhook_url", ""
        )

        watch_folder_service = WatchFolderService(
            db_session_factory=async_session_factory,
            beets_service=BeetsService(config_path=beets_config),
            notification_service=NotificationService(
                webhook_url=discord_url or None
            ),
        )
        await watch_folder_service.start()
        app.state.watch_folder_service = watch_folder_service
        logger.info("Watch folder service initialized.")
    except Exception:
        logger.exception("Failed to start watch folder service")

    yield

    # Shutdown watch folder service
    watch_folder_svc = getattr(app.state, "watch_folder_service", None)
    if watch_folder_svc is not None:
        try:
            await watch_folder_svc.stop()
        except Exception:
            logger.exception("Error stopping watch folder service")

    app.state.scheduler.shutdown(wait=False)
    await engine.dispose()


app = FastAPI(
    title="Musically",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:*",
        "http://127.0.0.1:*",
        "http://*.local:*",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
