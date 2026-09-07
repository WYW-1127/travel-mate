from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.chat_agent import chat_turn
from app.agent.planner import generate_trip
from app.agent.replanner import replan_trip
from app.schemas.chat import ChatRequest
from app.schemas.events import ErrorEvent, StreamEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.schemas.replan import ReplanRequest
from app.services.amap import AMapService
from app.services.glm import GLMService

router = APIRouter(prefix="/trips", tags=["trips"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


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
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    # thinking_effort 是逐请求档位，GLMService 必须按请求构造，不能走单例依赖
    return StreamingResponse(
        _sse(generate_trip(req, glm=GLMService(thinking_effort=req.thinking_effort), amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/replan")
async def replan(
    req: ReplanRequest,
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(replan_trip(req, glm=GLMService(thinking_effort=req.thinking_effort), amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/chat")
async def chat(
    req: ChatRequest,
    amap: AMapService = Depends(get_amap),
) -> StreamingResponse:
    return StreamingResponse(
        _sse(chat_turn(req, glm=GLMService(thinking_effort=req.thinking_effort), amap=amap)),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
