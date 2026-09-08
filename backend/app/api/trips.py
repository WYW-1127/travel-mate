from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from app.agent.chat_graph import chat_turn
from app.agent.replanner import replan_trip
from app.schemas.chat import ChatRequest
from app.schemas.events import ErrorEvent, StreamEvent, encode_event
from app.schemas.generate import GenerateRequest
from app.schemas.replan import ReplanRequest
from app.services.amap import AMapService
from app.services.gen_jobs import gen_jobs
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
    # 生成在后台任务里跑完：SSE 只是任务事件流的一个订阅者，
    # 客户端断线后凭 request_id 走 /gen-jobs/{rid}/replay 领回结果
    job = gen_jobs.start(req, glm=GLMService(thinking_effort=req.thinking_effort), amap=amap)
    return StreamingResponse(
        _sse(job.subscribe()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/gen-jobs/{rid}/replay")
async def gen_job_replay(rid: str) -> StreamingResponse:
    job = gen_jobs.get(rid)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": "生成任务不存在或已过期"})
    return StreamingResponse(
        _sse(job.subscribe()),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post("/gen-jobs/{rid}/cancel")
async def gen_job_cancel(rid: str) -> dict:
    gen_jobs.cancel(rid)
    return {"ok": True}


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
