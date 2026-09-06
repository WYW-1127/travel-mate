from collections.abc import AsyncIterator

import asyncio

from pydantic import ValidationError

from app.agent.planner import chat_stream_to_queue, enrich_activities
from app.agent.prompts import day_regen_messages, replan_scope_messages
from app.agent.validator import validate_trip
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
    ThinkingEvent,
)
from app.schemas.replan import ReplanRequest
from app.schemas.trip import Day, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService

MAX_REGEN_ATTEMPTS = 2  # 首次 + 1 次重试


async def replan_trip(
    req: ReplanRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService()
    amap = amap or AMapService()
    trip = req.trip.model_copy(deep=True)

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在理解你的调整需求")
    try:
        queue: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(
            chat_stream_to_queue(
                glm, *replan_scope_messages(trip, req.request), queue
            )
        )
        scope = None
        while scope is None:
            event = await queue.get()
            if isinstance(event, ThinkingEvent):
                yield event
            elif isinstance(event, GLMError):
                raise event
            else:
                scope = event
        await task
    except GLMError as e:
        yield ErrorEvent(code="GLM_ERROR", message=str(e))
        return

    raw = scope.get("affectedDayIndexes", [])
    indexes = sorted(
        {
            i
            for i in raw
            if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(trip.days)
        }
    )
    if not indexes:
        yield ErrorEvent(
            code="SCOPE_EMPTY",
            message="没有识别出需要调整的行程，请描述得更具体一些（如「第一天别太赶」）",
        )
        return

    feedback: list[str] = []
    for attempt in range(1, MAX_REGEN_ATTEMPTS + 1):
        ok = True
        for idx in indexes:
            yield ProgressEvent(
                stage=ProgressStage.plan,
                message=f"正在重新规划第 {idx + 1} 天"
                + (f"（{attempt - 1} 次重试）" if attempt > 1 else ""),
            )
            try:
                system, user = day_regen_messages(trip, idx, req.request, feedback)
                queue = asyncio.Queue()
                task = asyncio.create_task(
                    chat_stream_to_queue(glm, system, user, queue)
                )
                day_draft = None
                while day_draft is None:
                    event = await queue.get()
                    if isinstance(event, ThinkingEvent):
                        yield event
                    elif isinstance(event, GLMError):
                        raise event
                    else:
                        day_draft = event
                await task
                new_day = Day.model_validate(day_draft)
            except (GLMError, ValidationError) as e:
                feedback = [f"第 {idx + 1} 天重新生成失败：{e}"]
                ok = False
                break

            yield ProgressEvent(
                stage=ProgressStage.enrich, message=f"正在定位第 {idx + 1} 天的地点"
            )

            async def put(ev: ProgressEvent) -> None:
                pass  # replan 逐天进度已足够，不再细粒度透传

            await enrich_activities(new_day.activities, trip.destination, amap, put)
            trip.days[idx] = new_day

        if not ok:
            continue

        yield ProgressEvent(stage=ProgressStage.validate, message="正在检查调整后的行程")
        result = validate_trip(trip, check_poi=amap.configured)
        if result.ok:
            trip.version += 1
            trip.warnings = result.warnings
            yield CompleteEvent(trip=trip)
            return
        feedback = result.failures

    yield ErrorEvent(
        code="VALIDATION_FAILED",
        message="重新规划未能通过校验：" + "；".join(feedback),
    )
