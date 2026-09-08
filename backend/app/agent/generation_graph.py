"""生成行程的 LangGraph 图运行时（V1 管线的 agent 化）。

图结构（与 chat_graph 同构）：agent_call ⇄ execute_tools（模型自主定位，≤MAX_ROUNDS 轮）
→ finalize（结构校验+确定性校验，失败带反馈重试 ≤MAX_ATTEMPTS 次尝试）。
对外 generate_trip 签名与 SSE 事件协议与迁移前完全一致。"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.chat_tools import ToolExecutor, build_tools
from app.agent.planner import draft_to_trip
from app.agent.validator import validate_trip
from app.core.config import get_settings
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
    ThinkingEvent,
)
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Location
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService

MAX_ROUNDS = 10  # 「模型↔工具」循环上限
MAX_ATTEMPTS = 3  # 校验不过的带反馈重试（首次 + 2 次）
MAX_TOOL_CALLS = 40  # 生成定位调用配额（进程缓存对重复关键词去重）


class GenState(TypedDict):
    req: GenerateRequest
    glm_messages: list[dict]
    attempt: int
    rounds: int
    pending_calls: list[dict] | None
    final_content: str
    done: dict | None  # {"trip": Trip} 或 {"error": [code, message]}


def _system_prompt(req: GenerateRequest) -> str:
    budget = f"{req.budget_limit:.0f} 元" if req.budget_limit else "未定"
    return f"""你是资深国内旅行规划师。为用户规划逐日行程，并通过工具定位其中的地点。

用户需求：
- 目的地：{req.destination}
- 天数：{req.days} 天
- 出发日期：{req.start_date or "未定"}
- 出行人数：成人 {req.travelers.adults}、儿童 {req.travelers.children}
- 总预算：{budget}
- 偏好与要求：{req.preferences or "（无）"}

规则：
1. 每天 3-6 个活动（含用餐），时段 HH:MM，同一天内不重叠、按时间排序；同一天的活动集中在相邻区域，动线合理；notes 每条不超过 20 字，只写关键提示。
2. 动身查询前先想好全部地点，然后在同一轮一次性并行调用 search_poi 定位**所有**地点——严禁分批多次查询，这是硬性要求。
3. 严禁编造或抄写经纬度、地址。最终 JSON 的 location 一律用引用：{{"amapPoiId": "<该地点 search_poi 结果里的 amapPoiId>"}}，系统会自动回填坐标；搜索失败的地点才填 {{"name": "地点名", "resolved": false}}。
4. type 取值：attraction | meal | transport | hotel | shopping；cost 是人均预估（元），免费填 0。
5. 先调用 weather 查看目的地天气：雨天/酷热优先安排室内活动，把户外放在天气好的时段。重点景点可用 poi_detail 核实营业时间与门票（poi_id 来自 search_poi），查不到的信息按常识预估，不要编造。
6. 选点拿不准时（同类候选多个），用 poi_detail 查评分做比较，优先评分高、距离顺路的；需要给某活动补充周边安排（如午餐后附近的咖啡馆）时用 search_around。
6. 最终只输出一个 JSON 对象（结构如下）：
{{"title": "行程标题", "days": [{{"title": "当天主题", "activities": [{{"name": "地点名", "type": "attraction", "startTime": "09:30", "endTime": "12:00", "cost": 0, "notes": "≤20字", "location": {{"amapPoiId": "B0FF000000"}}]}}]}}}}"""


def _retry(state: GenState, problems: list[str]) -> dict:
    return {
        "glm_messages": [
            *state["glm_messages"],
            {
                "role": "user",
                "content": "上一版存在以下问题，必须修复后重新输出完整 JSON：\n"
                + "\n".join(f"- {p}" for p in problems),
            },
        ],
        "attempt": state["attempt"] + 1,
    }


def _tool_label(arguments: str) -> str:
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return ""
    return str(args.get("keyword") or args.get("address") or "")


def _backfill_locations(trip, executor) -> None:
    """最终 JSON 的 location 用 amapPoiId 引用（省模型抄写坐标），这里从工具缓存回填。"""
    if executor is None:
        return
    for day in trip.days:
        for act in day.activities:
            loc = act.location
            if loc is None or loc.resolved or not loc.amap_poi_id:
                continue
            cached = executor.poi_cache.get(loc.amap_poi_id)
            if not cached:
                continue
            act.location = Location.model_validate(cached)


async def agent_call(state: GenState, config) -> dict:
    glm: GLMService = config["configurable"]["glm"]
    writer = get_stream_writer()
    round = await glm.chat_with_tools(
        state["glm_messages"],
        config["configurable"]["tools"],
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


async def execute_tools(state: GenState, config) -> dict:
    executor: ToolExecutor = config["configurable"]["executor"]
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
    elif state["rounds"] >= 2:
        msgs.append({
            "role": "user",
            "content": "以上定位结果已足够参考。若仍有地点未定位，本轮一次性补齐全部查询；否则立即输出最终 JSON，location 用 amapPoiId 引用。",
        })
    return {"glm_messages": msgs, "pending_calls": None}


async def finalize(state: GenState, config) -> dict:
    req: GenerateRequest = config["configurable"]["req"]
    amap: AMapService = config["configurable"]["amap"]
    try:
        draft = json.loads(state["final_content"])
    except json.JSONDecodeError:
        return _retry(state, ["最终输出不是合法 JSON"])

    try:
        trip = draft_to_trip(draft, req)
    except ValidationError as e:
        return _retry(state, [f"行程 JSON 结构不合法：{e.errors()[:3]}"])

    _backfill_locations(trip, config["configurable"].get("executor"))

    result = validate_trip(trip, check_poi=amap.configured)
    if result.ok:
        trip.warnings = result.warnings
        return {"done": {"trip": trip}}
    if state["attempt"] + 1 >= MAX_ATTEMPTS:
        return {
            "done": {
                "error": [
                    "VALIDATION_FAILED",
                    "多次尝试后行程仍未通过校验：" + "；".join(result.failures),
                ]
            }
        }
    return _retry(state, result.failures)


def build_generation_graph(checkpointer=None):
    g = StateGraph(GenState)
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


async def _run(graph, initial: GenState, config: dict) -> AsyncIterator[StreamEvent]:
    final: GenState | None = None
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


async def generate_trip(
    req: GenerateRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
    checkpoint_db: str | None = None,  # None=不落检查点（默认）；显式路径才启用
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService(thinking_effort=req.thinking_effort)
    amap = amap or AMapService()

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在分析旅行需求")
    yield ProgressEvent(stage=ProgressStage.plan, message=f"正在规划 {req.destination} {req.days} 天行程")

    initial: GenState = {
        "req": req,
        "glm_messages": [
            {"role": "system", "content": _system_prompt(req)},
            {"role": "user", "content": f"请为我规划 {req.destination} {req.days} 天行程"},
        ],
        "attempt": 0,
        "rounds": 0,
        "pending_calls": None,
        "final_content": "",
        "done": None,
    }
    config = {
        "configurable": {
            "thread_id": f"gen:{uuid.uuid4().hex}",
            "req": req,
            "glm": glm,
            "amap": amap,
            "tools": build_tools(),
            "executor": ToolExecutor(req.destination, amap, max_calls=MAX_TOOL_CALLS),
        }
    }
    if checkpoint_db == "default":
        checkpoint_db = get_settings().checkpoint_db
    if checkpoint_db:
        Path(checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            async for ev in _run(build_generation_graph(checkpointer=saver), initial, config):
                yield ev
    else:
        async for ev in _run(build_generation_graph(), initial, config):
            yield ev
