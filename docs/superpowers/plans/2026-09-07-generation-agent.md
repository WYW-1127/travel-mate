# 生成链路 Agent 化（V1 管线 → LangGraph）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent）。**

**Goal:** 生成新行程从「GLM 出草稿 + 代码并发定位」升级为 agent 自主循环：模型自己决定调 `search_poi`/`geocode` 定位哪些地点、编排完整行程草稿，代码侧只做结构校验、确定性校验与反馈重试。SSE 协议、请求/响应、前端生成页零改动。

**Architecture:** 新建 `app/agent/generation_graph.py`（与 chat_graph 同构的 StateGraph）：`agent_call`（GLM `chat_with_tools`，thinking 走 stream_writer）⇄ `execute_tools`（≤10 轮，进度「正在定位：X」）→ `finalize`（`draft_to_trip` 结构校验+补 id → `validate_trip` → 通过/带反馈重试 ≤3 次尝试 → VALIDATION_FAILED）。工具配额 40 次/次生成（进程缓存对重复关键词去重）。检查点 SqliteSaver，thread=`gen:{uuid}`。

**Tech Stack:** 既有栈（langgraph 已装），无新依赖。

**Spec:** 设计于 2026-09-07 会话经用户批准（只迁生成链路；定位全权交给模型，30% 熔断+反馈重试兜底；重规划不动）。

## Global Constraints

- 对外契约不变：`POST /api/trips/generate` 请求/响应、SSE 事件（progress 的 analyze/plan/enrich/validate 语义、thinking、complete、error 码 GLM_ERROR/VALIDATION_FAILED/INTERNAL）、complete.trip 结构（id 补齐、preferences、warnings、未定位活动保留）。
- 测试离线（FakeGLM 脚本化 `chat_with_tools`）；中文 conventional commits；每任务 commit + push。
- planner.py 保留 replanner 依赖的 `chat_stream_to_queue`/`enrich_activities`/`assign_activity_ids`/`draft_to_trip`，删除被替代的 `generate_trip`。

---

### Task 1: generation_graph 建图迁移

**Files:**
- Create: `backend/app/agent/generation_graph.py`
- Modify: `backend/app/api/trips.py`（import 改 generation_graph）、`backend/app/agent/planner.py`（删 generate_trip 与无用 import）、`backend/app/agent/prompts.py`（删 trip_draft_messages）
- Test: `backend/tests/test_generation_graph.py`（新建，重写生成行为测试）；`backend/tests/test_planner.py`（删 generate_trip 相关用例，保留 draft_to_trip/ids/preferences 用例）；`backend/tests/test_api_trips.py`（stub/wiring 目标改 generation_graph）

**Interfaces:**
- Consumes: `GLMService.chat_with_tools`、`ToolExecutor/build_tools`、`draft_to_trip`、`validate_trip`、事件协议。
- Produces: `async def generate_trip(req, glm=None, amap=None, checkpoint_db=None|"data/checkpoints.db") -> AsyncIterator[StreamEvent]`；`def build_generation_graph(checkpointer=None)`。

- [ ] **Step 1: 写失败测试**——新建 `backend/tests/test_generation_graph.py`：

```python
import json

from app.agent.generation_graph import build_generation_graph, generate_trip
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMError, GLMService, ToolCall, ToolRound

REQ = GenerateRequest.model_validate({"destination": "重庆", "days": 1, "preferences": "带娃"})

SEARCH_CALL = ToolCall(id="c1", name="search_poi", arguments='{"city": "重庆", "keyword": "洪崖洞民俗风貌区"}')

GOOD_DRAFT = {
    "title": "重庆一日游",
    "days": [
        {"title": "D1", "activities": [
            {"name": "洪崖洞民俗风貌区", "type": "attraction", "startTime": "09:00", "endTime": "11:00", "cost": 0,
             "location": {"name": "洪崖洞民俗风貌区", "address": "a", "longitude": 106.578, "latitude": 29.562, "resolved": True}},
            {"name": "山城小汤圆", "type": "meal", "startTime": "11:30", "endTime": "12:30", "cost": 30,
             "location": {"name": "山城小汤圆", "resolved": False}},
        ]},
    ],
}


class FakeGLM(GLMService):
    def __init__(self, rounds: list):
        super().__init__(api_key="fake")
        self.rounds = list(rounds)
        self.calls: list[list[dict]] = []

    async def chat_with_tools(self, messages, tools, on_thinking=None, temperature=0.3):
        self.calls.append([dict(m) for m in messages])
        if on_thinking:
            on_thinking("思考片段")
        r = self.rounds.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeAMap(AMapService):
    def __init__(self, key="fake"):
        super().__init__(key=key)

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="a", longitude=106.578, latitude=29.562, poi_id="P")


async def _collect(req=REQ, glm=None, amap=None):
    return [e async for e in generate_trip(req, glm=glm, amap=amap, checkpoint_db=None)]


async def test_tool_round_then_complete():
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.destination == "重庆"
    assert trip.preferences == "带娃"
    assert trip.title == "重庆一日游"
    acts = trip.days[0].activities
    assert all(a.id for a in acts)  # 补齐唯一 id
    assert acts[0].location.resolved is True
    assert acts[1].location.resolved is False  # 未定位保留打标
    assert any(e.type == "thinking" for e in events)
    assert any(e.type == "progress" and "定位" in e.message for e in events)
    assert any(m.get("role") == "tool" for m in glm.calls[1])


async def test_validation_failure_retries_with_feedback():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][0]["endTime"] = "08:00"  # 结束早于开始
    glm = FakeGLM([
        ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2
    assert "问题" in glm.calls[1][-1]["content"]


async def test_exhausted_retries_yields_error():
    bad = json.loads(json.dumps(GOOD_DRAFT))
    bad["days"][0]["activities"][0]["endTime"] = "08:00"
    glm = FakeGLM([ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]) for _ in range(3)])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "error"
    assert events[-1].code == "VALIDATION_FAILED"


async def test_invalid_json_shape_retries():
    glm = FakeGLM([
        ToolRound(content="这不是json", tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM 连接失败")])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "error"
    assert events[-1].code == "GLM_ERROR"


async def test_rounds_cap_appends_force_finish(monkeypatch):
    import app.agent.generation_graph as mod
    monkeypatch.setattr(mod, "MAX_ROUNDS", 2)
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_DRAFT, ensure_ascii=False), tool_calls=[]),
    ])
    events = await _collect(glm=glm, amap=FakeAMap())
    assert events[-1].type == "complete"
    assert any("已达上限" in m.get("content", "") for m in glm.calls[2] if m.get("role") == "user")


def test_graph_compiles_and_mermaid_contains_nodes():
    graph = build_generation_graph()
    mermaid = graph.get_graph().draw_mermaid()
    assert "agent_call" in mermaid and "execute_tools" in mermaid and "finalize" in mermaid
```

`tests/test_planner.py`：删除 `generate_trip` 相关用例（`test_happy_path_progress_then_complete`、`test_thinking_events_streamed_before_complete`、`test_unresolved_poi_kept_with_flag`、`test_validation_failure_triggers_retry_with_feedback`、`test_exhausted_retries_yields_error_event`、`test_glm_error_yields_error_event`、`test_invalid_draft_shape_counts_as_failure_and_retries`、`_collect`/`types` 辅助）与 `generate_trip`/`ErrorEvent` 导入；保留 draft_to_trip/ids/preferences 用例与 FakeGLM/FakeAMap（若仍被引用）。

`tests/test_api_trips.py`：`PLANNER = "app.agent.generation_graph.generate_trip"`，fixture 内模块引用同步改为 `app.agent.generation_graph`；`test_api_trips.py` 若有 wiring 源码断言则改为 `"from app.agent.generation_graph import generate_trip"`。

- [ ] **Step 2: 确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_generation_graph.py -q`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**——新建 `app/agent/generation_graph.py`：

```python
"""生成行程的 LangGraph 图运行时（V1 管线的 agent 化）。

图结构（与 chat_graph 同构）：agent_call ⇄ execute_tools（模型自主定位，≤MAX_ROUNDS 轮）
→ finalize（结构校验+确定性校验，失败带反馈重试 ≤MAX_ATTEMPTS 次尝试）。
对外 generate_trip 签名与 SSE 事件协议与迁移前完全一致。"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from app.agent.chat_tools import ToolExecutor, build_tools
from app.agent.planner import draft_to_trip
from app.agent.validator import validate_trip
from app.schemas.events import (
    CompleteEvent,
    ErrorEvent,
    ProgressEvent,
    ProgressStage,
    StreamEvent,
    ThinkingEvent,
)
from app.schemas.generate import GenerateRequest
from app.schemas.trip import Trip
from app.services.amap import AMapService
from app.services.glm import GLMError, GLMService

MAX_ROUNDS = 10  # 「模型↔工具」循环上限
MAX_ATTEMPTS = 3  # 校验不过的带反馈重试（首次 + 2 次）
MAX_TOOL_CALLS = 40  # 生成定位调用配额（进程缓存对重复关键词去重）
DEFAULT_CHECKPOINT_DB = "data/checkpoints.db"


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
1. 每天 3-6 个活动（含用餐），时段 HH:MM，同一天内不重叠、按时间排序；同一天的活动集中在相邻区域，动线合理。
2. 草稿中的每个地点必须先调工具定位：search_poi 优先，搜不到用 geocode；严禁编造经纬度。
3. type 取值：attraction | meal | transport | hotel | shopping；cost 是人均预估（元），免费填 0。
4. 最终只输出一个 JSON 对象（结构如下，location 用定位返回的规范名/地址/坐标）：
{{"title": "行程标题", "days": [{{"title": "当天主题", "activities": [{{"name": "地点名", "type": "attraction", "startTime": "09:30", "endTime": "12:00", "cost": 0, "notes": "提示可空", "location": {{"name": "…", "address": "…", "longitude": 120.1, "latitude": 30.2, "resolved": true}}}}]}}]}}
5. 定位彻底失败的地点：location 填 {{"name": "地点名", "resolved": false}}，不要虚构坐标。"""


def _retry(state: GenState, problems: list[str]) -> dict:
    return {
        "glm_messages": [
            *state["glm_messages"],
            {"role": "user", "content": "上一版存在以下问题，必须修复后重新输出完整 JSON：\n"
             + "\n".join(f"- {p}" for p in problems)},
        ],
        "attempt": state["attempt"] + 1,
    }


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


def _tool_label(arguments: str) -> str:
    try:
        args = json.loads(arguments)
    except json.JSONDecodeError:
        return ""
    return str(args.get("keyword") or args.get("address") or "")


async def execute_tools(state: GenState, config) -> dict:
    executor: ToolExecutor = config["configurable"]["executor"]
    writer = get_stream_writer()
    msgs = list(state["glm_messages"])
    for call in state["pending_calls"] or []:
        label = _tool_label(call["arguments"])
        if label and writer:
            writer({"kind": "progress", "message": f"正在定位：{label}"})
        result = await executor.execute(call["name"], call["arguments"])
        msgs.append({"role": "tool", "tool_call_id": call["id"], "content": result})
    if state["rounds"] >= MAX_ROUNDS:
        msgs.append({"role": "user", "content": "工具调用已达上限，立即基于已有信息输出最终 JSON。"})
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

    result = validate_trip(trip, check_poi=amap.configured)
    if result.ok:
        trip.warnings = result.warnings
        return {"done": {"trip": trip}}
    if state["attempt"] + 1 >= MAX_ATTEMPTS:
        return {"done": {"error": ["VALIDATION_FAILED", "多次尝试后行程仍未通过校验：" + "；".join(result.failures)]}}
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
    checkpoint_db: str | None = DEFAULT_CHECKPOINT_DB,
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
    if checkpoint_db:
        from pathlib import Path

        Path(checkpoint_db).parent.mkdir(parents=True, exist_ok=True)
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            async for ev in _run(build_generation_graph(checkpointer=saver), initial, config):
                yield ev
    else:
        async for ev in _run(build_generation_graph(), initial, config):
            yield ev
```

（`Trip` 若未用到则不导入；`from pathlib import Path` 提到文件头部。）

`app/api/trips.py`：`from app.agent.planner import generate_trip` → `from app.agent.generation_graph import generate_trip`。

`app/agent/planner.py`：删除 `generate_trip`、`MAX_ATTEMPTS`、`from app.agent.prompts import trip_draft_messages`、`from app.schemas.events import …`/`from app.services.glm import …`/`from app.tools.poi import search_poi` 中不再使用的导入（保留 `chat_stream_to_queue`/`enrich_activities`/`draft_to_trip`/`assign_activity_ids` 所需项）。`app/agent/prompts.py`：删除 `trip_draft_messages`。

- [ ] **Step 4: 确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_generation_graph.py tests/test_planner.py tests/test_api_trips.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: 生成链路 agent 化——LangGraph 图上模型自主定位编排行程，SSE/前端零改动" && git push
```

---

### Task 2: 图存档 + 端到端验收

- [ ] 导出 mermaid 存档：`docs/superpowers/assets/generation-graph.mermaid`。
- [ ] 重启后端（uvicorn 无热重载），health 检查。
- [ ] 浏览器实测：首页填「北京 1 天、带 5 岁孩子，不去网红店」生成 → 观察思考流式 + 「正在定位：…」进度 → 行程页验证卡片/地图/预算/档案注入；全量回归最终跑一遍，遗留修复一并提交推送。

## 已知问题

（空）
