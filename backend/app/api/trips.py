from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.planner import generate_trip
from app.schemas.events import ErrorEvent, StreamEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.schemas.replan import ReplanRequest
from app.services.amap import AMapService
from app.services.glm import GLMService

router = APIRouter(prefix="/trips", tags=["trips"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def get_glm() -> GLMService:
    return GLMService()


def get_amap() -> AMapService:
    return AMapService()


def _sse(events: AsyncIterator[StreamEvent]) -> AsyncIterator[str]:
    async def wrapper():
        try:
            async for ev in events:
                yield encode_event(ev)
        except Exception as e:  # noqa: BLE001 —— SSE 连接不能裸断
            yield encode_event(ErrorEvent(code="INTERNAL", message=f"服务内部错误：{e}"))

    return wrapper()


@router.post("/generate")
async def generate(
    req: GenerateRequest,
    glm: GLMService = Depends(get_glm),
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(generate_trip(req, glm=glm, amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/replan")
async def replan(
    req: ReplanRequest,
    glm: GLMService = Depends(get_glm),
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(replan_trip(req, glm=glm, amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
