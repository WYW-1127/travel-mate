import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable

from pydantic import ValidationError

from app.agent.prompts import trip_draft_messages
from app.agent.validator import validate_trip
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
)
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Activity, ActivityType, Location, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService
from app.tools.poi import search_poi

MAX_ATTEMPTS = 3  # 首次 + 2 次带反馈重试
CONCURRENCY = 5


async def enrich_activities(
    activities: list[Activity],
    destination: str,
    service: AMapService,
    put: Callable[[ProgressEvent], Awaitable[None]],
) -> None:
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0
    total = len(activities)

    async def one(act: Activity) -> None:
        nonlocal done
        async with sem:
            if act.type != ActivityType.transport:
                loc = await search_poi(destination, act.name, service)
                act.location = loc or Location(name=act.name, resolved=False)
            done += 1
            await put(
                ProgressEvent(
                    stage=ProgressStage.enrich,
                    message=f"正在定位地点（{done}/{total}）",
                )
            )

    await asyncio.gather(*(one(a) for a in activities))


def draft_to_trip(draft: dict, req: GenerateRequest) -> Trip:
    data = {
        **draft,
        "destination": req.destination,
        "startDate": req.start_date,
        "travelers": req.travelers.model_dump(by_alias=True),
        "budgetLimit": req.budget_limit,
        "version": 1,
    }
    return Trip.model_validate(data)


async def generate_trip(
    req: GenerateRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService()
    amap = amap or AMapService()
    feedback: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if attempt == 1:
                yield ProgressEvent(
                    stage=ProgressStage.analyze, message="正在分析旅行需求"
                )
            else:
                yield ProgressEvent(
                    stage=ProgressStage.validate,
                    message=f"发现 {len(feedback)} 个问题，正在修正（第 {attempt - 1} 次重试）",
                )
            yield ProgressEvent(
                stage=ProgressStage.plan,
                message=f"正在规划 {req.destination} {req.days} 天行程",
            )
            system, user = trip_draft_messages(req, feedback)
            try:
                draft = await glm.chat_json(system, user)
            except GLMError as e:
                yield ErrorEvent(code="GLM_ERROR", message=str(e))
                return

            try:
                trip = draft_to_trip(draft, req)
            except ValidationError as e:
                feedback = [f"行程 JSON 结构不合法：{e.errors()[:3]}"]
                continue

            yield ProgressEvent(
                stage=ProgressStage.enrich, message="正在定位行程中的地点"
            )
            queue: asyncio.Queue[ProgressEvent] = asyncio.Queue()
            enrich_task = asyncio.create_task(
                enrich_activities(
                    [a for d in trip.days for a in d.activities],
                    req.destination,
                    amap,
                    queue.put,
                )
            )
            # 轮询转发富化进度（事件 <100 个，10ms 开销可忽略）
            while not enrich_task.done() or not queue.empty():
                if queue.empty() and not enrich_task.done():
                    await asyncio.sleep(0.01)
                    continue
                while not queue.empty():
                    yield queue.get_nowait()
            await enrich_task

            yield ProgressEvent(
                stage=ProgressStage.validate, message="正在检查行程合理性"
            )
            result = validate_trip(trip, check_poi=amap.configured)
            if result.ok:
                trip.warnings = result.warnings
                yield CompleteEvent(trip=trip)
                return
            feedback = result.failures
        except Exception as e:  # noqa: BLE001 —— pipeline 内意外错误统一转 error 事件
            yield ErrorEvent(code="INTERNAL", message=f"生成失败：{e}")
            return

    yield ErrorEvent(
        code="VALIDATION_FAILED",
        message="多次尝试后行程仍未通过校验：" + "；".join(feedback),
    )
