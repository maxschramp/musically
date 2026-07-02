"""Logs router — stub endpoint returning empty log list."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/logs")
async def get_logs() -> dict:
    """Return application logs (placeholder)."""
    return {"items": [], "total": 0, "page": 1, "page_size": 50, "total_pages": 0}
