from fastapi import APIRouter

from app.routers.albums import router as albums_router
from app.routers.artists import router as artists_router
from app.routers.database import router as database_router
from app.routers.events import router as events_router
from app.routers.health import router as health_router
from app.routers.lastfm import router as lastfm_router
from app.routers.logs import router as logs_router
from app.routers.notifications import router as notifications_router
from app.routers.playlists import router as playlists_router
from app.routers.queue import router as queue_router
from app.routers.qobuz import router as qobuz_router
from app.routers.search import router as search_router
from app.routers.settings import router as settings_router
from app.routers.spotify import router as spotify_router
from app.routers.sync import router as sync_router
from app.routers.tasks import router as tasks_router

api_router = APIRouter(prefix="/api")

api_router.include_router(health_router, tags=["health"])
api_router.include_router(lastfm_router, tags=["lastfm"])
api_router.include_router(settings_router, tags=["settings"])
api_router.include_router(spotify_router, tags=["spotify"])
api_router.include_router(albums_router, tags=["albums"])
api_router.include_router(artists_router, tags=["artists"])
api_router.include_router(queue_router, tags=["queue"])
api_router.include_router(qobuz_router, tags=["qobuz"])
api_router.include_router(search_router, tags=["search"])
api_router.include_router(playlists_router, tags=["playlists"])
api_router.include_router(sync_router, tags=["sync"])
api_router.include_router(notifications_router, tags=["notifications"])
api_router.include_router(logs_router, tags=["logs"])
api_router.include_router(tasks_router, tags=["tasks"])
api_router.include_router(database_router, tags=["database"])
api_router.include_router(events_router, tags=["events"])
