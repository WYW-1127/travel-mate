from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "glm_configured": s.has_glm,
        "amap_configured": s.has_amap,
    }
