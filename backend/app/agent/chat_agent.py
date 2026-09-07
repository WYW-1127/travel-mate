import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime

from pydantic import Field, ValidationError

from app.agent.chat_tools import ToolExecutor, build_tools
from app.agent.planner import assign_activity_ids
from app.agent.validator import validate_trip
from app.schemas.chat import ChatRequest
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
    ThinkingEvent,
)
from app.schemas.trip import Activity, CamelModel, ChatMessage, Day, Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService, ToolRound

MAX_ROUNDS = 8  # 单轮对话内「模型↔工具」循环上限
MAX_ATTEMPTS = 3  # 最终输出校验不过的带反馈重试（首次 + 2 次）
HISTORY_LIMIT = 20  # 发给模型的对话历史上限
CHAT_LIMIT = 50  # 行程内保存的对话上限


class _DayEdit(CamelModel):
    index: int
    title: str = ""
    activities: list[Activity] = Field(default_factory=list)


class _ChatOutcome(CamelModel):
    """模型最终输出契约：reply 给用户看；days 只含受影响的天，空数组=纯问答不改行程。"""

    reply: str = ""
    days: list[_DayEdit] = Field(default_factory=list)


def _system_prompt(trip: Trip) -> str:
    trip_json = json.dumps(trip.model_dump(by_alias=True, exclude={"chat"}), ensure_ascii=False)
    return f"""你是用户的旅行规划助理，通过输出修改后的行程来响应用户需求。

当前行程（以此为准，历史消息可能已过时）：
{trip_json}

规则：
1. 涉及新地点时先调工具定位：search_poi 优先，搜不到用 geocode；严禁编造经纬度。
2. 用户只是提问、不需要改行程时，days 返回 []，只在 reply 里回答。
3. 需要修改时，days 里只放受影响的天：{{"index": 天序号从0开始, "title": 当天主题, "activities": [活动结构与你看到的行程一致，含 name/type/startTime/endTime/cost/notes/location]}}；未提到的天不要输出。
4. 安排要尊重用户偏好：{trip.preferences or "（无记录）"}。
5. 最终只输出一个 JSON 对象：{{"reply": "给用户的回复，说清楚改了什么、为什么", "days": [...]}}"""


def _history_messages(trip: Trip) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in trip.chat[-HISTORY_LIMIT:]]


def _tool_label(arguments: str) -> str:
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return ""
    return str(args.get("keyword") or args.get("address") or "")


async def _stream_to_queue(
    glm: GLMService, messages: list[dict], tools: list[dict], queue: asyncio.Queue
) -> None:
    try:
        round = await glm.chat_with_tools(
            messages, tools, on_thinking=lambda s: queue.put_nowait(ThinkingEvent(content=s))
        )
        await queue.put(round)
    except GLMError as e:
        await queue.put(e)


def _apply_days(trip: Trip, outcome: _ChatOutcome) -> Trip | None:
    """把模型给出的按天编辑落到行程副本；index 越界返回 None（反馈重试）。"""
    candidate = trip.model_copy(deep=True)
    for edit in outcome.days:
        if not 0 <= edit.index < len(candidate.days):
            return None
        candidate.days[edit.index] = Day(title=edit.title, activities=edit.activities)
    for day in candidate.days:
        assign_activity_ids(day.activities)  # GLM 不输出 id，只补空 id（联动/key 依赖）
    return candidate


def _with_chat(trip: Trip, user_message: str, reply: str) -> Trip:
    now = datetime.now().isoformat(timespec="seconds")
    trip.chat = [
        *trip.chat,
        ChatMessage(role="user", content=user_message, ts=now),
        ChatMessage(role="assistant", content=reply, ts=now),
    ][-CHAT_LIMIT:]
    return trip


async def chat_turn(
    req: ChatRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService(thinking_effort=req.thinking_effort)
    amap = amap or AMapService()
    trip = req.trip.model_copy(deep=True)
    tools = build_tools()
    executor = ToolExecutor(trip.destination, amap)

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在理解你的需求")

    messages: list[dict] = [
        {"role": "system", "content": _system_prompt(trip)},
        *_history_messages(trip),
        {"role": "user", "content": req.message},
    ]

    feedback: list[str] = []
    for _attempt in range(1, MAX_ATTEMPTS + 1):
        round: ToolRound | None = None
        rounds = 0
        while round is None:  # 「模型↔工具」循环
            rounds += 1
            if rounds > MAX_ROUNDS:
                messages.append({"role": "user", "content": "工具调用已达上限，立即基于已有信息输出最终 JSON。"})
            queue: asyncio.Queue = asyncio.Queue()
            task = asyncio.create_task(_stream_to_queue(glm, messages, tools, queue))
            item = None
            try:
                while item is None:
                    event = await queue.get()
                    if isinstance(event, ThinkingEvent):
                        yield event
                    elif isinstance(event, GLMError):
                        raise event
                    else:
                        item = event
                await task
            except GLMError as e:
                yield ErrorEvent(code="GLM_ERROR", message=str(e))
                return
            round = item

            if round.tool_calls:
                messages.append({
                    "role": "assistant",
                    "content": round.content or None,
                    "tool_calls": [
                        {"id": c.id, "type": "function",
                         "function": {"name": c.name, "arguments": c.arguments}}
                        for c in round.tool_calls
                    ],
                })
                for c in round.tool_calls:
                    label = _tool_label(c.arguments)
                    if label:
                        yield ProgressEvent(stage=ProgressStage.enrich, message=f"正在定位：{label}")
                    result = await executor.execute(c.name, c.arguments)
                    messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
                round = None  # 继续循环

        try:
            outcome = _ChatOutcome.model_validate_json(round.content)
        except ValidationError:
            feedback = ["最终输出不是合法 JSON 或结构不符（需要 reply + days）"]
            messages.append({"role": "user", "content": f"上一轮输出无效：{feedback[0]}。请重新输出。"})
            continue

        if not outcome.days:
            yield CompleteEvent(trip=_with_chat(trip, req.message, outcome.reply))
            return

        candidate = _apply_days(trip, outcome)
        if candidate is None:
            feedback = ["days 里出现了不存在的天序号"]
            messages.append({"role": "user", "content": f"上一轮输出无效：{feedback[0]}。请修正后重新输出。"})
            continue

        result = validate_trip(candidate, check_poi=amap.configured)
        if result.ok:
            candidate.warnings = result.warnings
            candidate.version += 1
            yield CompleteEvent(trip=_with_chat(candidate, req.message, outcome.reply))
            return
        feedback = result.failures
        messages.append({
            "role": "user",
            "content": "修改后的行程存在以下问题，必须修复后重新输出完整 JSON：" + "；".join(feedback),
        })

    yield ErrorEvent(
        code="VALIDATION_FAILED",
        message="多次尝试后仍未通过校验：" + "；".join(feedback),
    )
