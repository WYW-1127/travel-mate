from fastapi import APIRouter

from app.agent.preferences import extract_preferences
from app.schemas.preferences import ExtractRequest, ExtractResult

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.post("/extract")
async def extract(req: ExtractRequest) -> ExtractResult:
    return ExtractResult(items=await extract_preferences(req.text))
