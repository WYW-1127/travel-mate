import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable

from app.schemas.events import ProgressEvent, ProgressStage, ThinkingEvent
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Activity, ActivityType, Location, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService
from app.tools.poi import search_poi

CONCURRENCY = 3  # 高德个人 key QPS=3


async def chat_stream_to_queue(
    glm: GLMService,
    system: str,
    user: str,
    queue: asyncio.Queue,
) -> None:
    """GLM 流式调用协程（调用方 create_task 后轮询 queue）：
    thinking 增量以 ThinkingEvent 入队；结束时入队最终 dict（成功）或 GLMError（失败）。"""
    try:
        result = await glm.chat_json_stream(
            system,
            user,
            on_thinking=lambda s: queue.put_nowait(ThinkingEvent(content=s)),
        )
        await queue.put(result)
    except GLMError as e:
        await queue.put(e)
    except Exception as e:  # noqa: BLE001 —— httpx 网络错误等按 GLM 失败处理
        await queue.put(GLMError(f"GLM 连接失败：{e}"))


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


def assign_activity_ids(activities: list[Activity]) -> None:
    """GLM 草稿不输出活动 id，前端卡片 key 与地图联动依赖它，空 id 就地补齐。"""
    for act in activities:
        if not act.id:
            act.id = uuid.uuid4().hex


def draft_to_trip(draft: dict, req: GenerateRequest) -> Trip:
    data = {
        **draft,
        "destination": req.destination,
        "startDate": req.start_date,
        "travelers": req.travelers.model_dump(by_alias=True),
        "budgetLimit": req.budget_limit,
        "preferences": req.preferences or "",
        "version": 1,
    }
    trip = Trip.model_validate(data)
    for day in trip.days:
        assign_activity_ids(day.activities)
    return trip
