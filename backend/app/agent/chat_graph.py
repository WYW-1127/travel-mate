"""对话式改行程的 LangGraph 图运行时（V4）。

图结构（存档见 docs/superpowers/assets/chat-graph.mermaid）：
START → agent_call ⇄ execute_tools（有工具调用时循环，≤MAX_ROUNDS 轮）
      → finalize →（通过或纯问答）END
                →（校验失败且未耗尽重试）agent_call
对外的 chat_turn 签名与 SSE 事件协议与迁移前完全一致。"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import Field, ValidationError

from app.agent.chat_tools import ToolExecutor, build_tools
from app.agent.planner import assign_activity_ids
from app.agent.validator import validate_trip
from app.schemas.chat import ChatRequest
from app.core.config import get_settings
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
DEFAULT_CHECKPOINT_DB = "default"  # 运行时从 settings.checkpoint_db 解析


class _DayEdit(CamelModel):
    index: int
    title: str = ""
    activities: list[Activity] = Field(default_factory=list)


class _ChatOutcome(CamelModel):
    """模型最终输出契约：reply 给用户看；days 只含受影响的天，空数组=纯问答不改行程。"""

    reply: str = ""
    days: list[_DayEdit] = Field(default_factory=list)


class ChatState(TypedDict):
    trip: Trip
    user_message: str
    profile: list[str]
    glm_messages: list[dict]
    attempt: int
    rounds: int
    pending_calls: list[dict] | None  # 本轮待执行的工具调用（dict 形式，可序列化）
    final_content: str
    done: dict | None  # {"trip": Trip} 或 {"error": [code, message]}；非 None 即终态


def _system_prompt(trip: Trip, profile: list[str]) -> str:
    trip_json = json.dumps(trip.model_dump(by_alias=True, exclude={"chat"}), ensure_ascii=False)
    return f"""你是用户的旅行规划助理，通过输出修改后的行程来响应用户需求。

当前行程（以此为准，历史消息可能已过时）：
{trip_json}

规则：
1. 涉及新地点时先调工具定位：search_poi 优先，搜不到用 geocode；严禁编造经纬度。
2. 用户只是提问、不需要改行程时，days 返回 []，只在 reply 里回答。
3. 需要修改时，days 里只放受影响的天：{{"index": 天序号从0开始, "title": 当天主题, "activities": [活动结构与你看到的行程一致，含 name/type/startTime/endTime/cost/notes/location]}}；未提到的天不要输出。
4. 用户长期偏好档案（跨行程有效，优先级最高）：{"；".join(profile) if profile else "（无）"}。同时尊重本次行程的偏好：{trip.preferences or "（无记录）"}。
5. 最终只输出一个 JSON 对象：{{"reply": "给用户的回复，说清楚改了什么、为什么", "days": [...]}}"""


def _history_messages(trip: Trip) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in trip.chat[-HISTORY_LIMIT:]]


def _tool_label(arguments: str) -> str:
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return ""
    return str(args.get("keyword") or args.get("address") or "")


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


def _retry(state: ChatState, message: str) -> dict:
    """finalize 失败：反馈写回消息流，attempt+1 走重试边。"""
    return {
        "glm_messages": [*state["glm_messages"], {"role": "user", "content": message}],
        "attempt": state["attempt"] + 1,
    }


async def agent_call(state: ChatState, config) -> dict:
    """调 GLM 一轮：thinking 经 stream_writer 透传；有工具调用则转 execute_tools。"""
    cfg = config["configurable"]
    glm: GLMService = cfg["glm"]
    writer = get_stream_writer()
    round = await glm.chat_with_tools(
        state["glm_messages"],
        cfg["tools"],
        on_thinking=lambda s: writer({"kind": "thinking", "content": s}) if writer else None,
    )
    update: dict = {"rounds": state["rounds"] + 1, "pending_calls": None}
    if round.tool_calls:
        update["glm_messages"] = [
            *state["glm_messages"],
            {
                "role": "assistant",
                "content": round.content or None,
                "tool_calls": [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.name, "arguments": c.arguments}}
                    for c in round.tool_calls
                ],
            },
        ]
        update["pending_calls"] = [
            {"id": c.id, "name": c.name, "arguments": c.arguments} for c in round.tool_calls
        ]
        return update
    update["final_content"] = round.content
    return update


async def execute_tools(state: ChatState, config) -> dict:
    cfg = config["configurable"]
    executor: ToolExecutor = cfg["executor"]
    writer = get_stream_writer()
    calls = state["pending_calls"] or []

    async def one(call: dict):
        label = _tool_label(call["arguments"])
        if label and writer:
            writer({"kind": "progress", "message": f"正在定位：{label}"})
        # 个人 key QPS=3：并发执行但限 3 路
        async with asyncio.Semaphore(3):
            return call["id"], await executor.execute(call["name"], call["arguments"])

    results = await asyncio.gather(*(one(c) for c in calls))
    msgs = list(state["glm_messages"])
    msgs.extend({"role": "tool", "tool_call_id": cid, "content": result} for cid, result in results)
    if state["rounds"] >= MAX_ROUNDS:
        msgs.append({"role": "user", "content": "工具调用已达上限，立即基于已有信息输出最终 JSON。"})
    return {"glm_messages": msgs, "pending_calls": None}


async def finalize(state: ChatState, config) -> dict:
    amap: AMapService = config["configurable"]["amap"]
    try:
        outcome = _ChatOutcome.model_validate_json(state["final_content"])
    except ValidationError:
        return _retry(state, "上一轮输出无效：最终输出不是合法 JSON 或结构不符（需要 reply + days）。请重新输出。")

    if not outcome.days:
        return {"done": {"trip": _with_chat(state["trip"], state["user_message"], outcome.reply)}}

    candidate = _apply_days(state["trip"], outcome)
    if candidate is None:
        return _retry(state, "上一轮输出无效：days 里出现了不存在的天序号。请修正后重新输出。")

    result = validate_trip(candidate, check_poi=amap.configured)
    if result.ok:
        candidate.warnings = result.warnings
        candidate.version += 1
        return {"done": {"trip": _with_chat(candidate, state["user_message"], outcome.reply)}}
    if state["attempt"] + 1 >= MAX_ATTEMPTS:
        return {
            "done": {
                "error": [
                    "VALIDATION_FAILED",
                    "多次尝试后仍未通过校验：" + "；".join(result.failures),
                ]
            }
        }
    return _retry(
        state,
        "修改后的行程存在以下问题，必须修复后重新输出完整 JSON：" + "；".join(result.failures),
    )


def build_chat_graph(checkpointer=None):
    g = StateGraph(ChatState)
    g.add_node("agent_call", agent_call)
    g.add_node("execute_tools", execute_tools)
    g.add_node("finalize", finalize)
    g.add_edge(START, "agent_call")
    g.add_conditional_edges(
        "agent_call",
        lambda s: "execute_tools" if s.get("pending_calls") else "finalize",
        ["execute_tools", "finalize"],
    )
    g.add_edge("execute_tools", "agent_call")
    g.add_conditional_edges(
        "finalize",
        lambda s: END if s.get("done") else "agent_call",
        ["agent_call", END],
    )
    return g.compile(checkpointer=checkpointer)


async def _run(graph, initial: ChatState, config: dict) -> AsyncIterator[StreamEvent]:
    final: ChatState | None = None
    try:
        async for mode, chunk in graph.astream(initial, config, stream_mode=["custom", "values"]):
            if mode == "custom" and chunk:
                kind = chunk.get("kind")
                if kind == "thinking":
                    yield ThinkingEvent(content=chunk["content"])
                elif kind == "progress":
                    yield ProgressEvent(stage=ProgressStage.enrich, message=chunk["message"])
            elif mode == "values":
                final = chunk
    except GLMError as e:
        yield ErrorEvent(code="GLM_ERROR", message=str(e))
        return
    done = (final or {}).get("done") or {}
    if "trip" in done:
        yield CompleteEvent(trip=done["trip"])
    else:
        code, message = done.get("error", ("INTERNAL", "未知错误"))
        yield ErrorEvent(code=code, message=message)


def thread_id_of(trip: Trip) -> str:
    return f"chat:{trip.id or uuid.uuid4().hex}"


async def chat_turn(
    req: ChatRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
    checkpoint_db: str | None = DEFAULT_CHECKPOINT_DB,
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService(thinking_effort=req.thinking_effort)
    amap = amap or AMapService()
    trip = req.trip.model_copy(deep=True)
    profile = [p.strip()[:30] for p in (req.profile or []) if p.strip()][:20]

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在理解你的需求")

    initial: ChatState = {
        "trip": trip,
        "user_message": req.message,
        "profile": profile,
        "glm_messages": [
            {"role": "system", "content": _system_prompt(trip, profile)},
            *_history_messages(trip),
            {"role": "user", "content": req.message},
        ],
        "attempt": 0,
        "rounds": 0,
        "pending_calls": None,
        "final_content": "",
        "done": None,
    }
    config = {
        "configurable": {
            "thread_id": thread_id_of(trip),
            "glm": glm,
            "amap": amap,
            "tools": build_tools(),
            "executor": ToolExecutor(trip.destination, amap),
        }
    }
    if checkpoint_db == "default":
        checkpoint_db = get_settings().checkpoint_db
    if checkpoint_db:
        Path(checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            graph = build_chat_graph(checkpointer=saver)
            async for ev in _run(graph, initial, config):
                yield ev
    else:
        async for ev in _run(build_chat_graph(), initial, config):
            yield ev
