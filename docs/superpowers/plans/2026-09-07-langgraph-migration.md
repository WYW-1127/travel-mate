# V4 LangGraph 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent）。**

**Goal:** 把 `chat_agent` 手写的「模型↔工具循环 + 校验重试」迁到 LangGraph StateGraph，获得检查点持久化（SqliteSaver）、图可视化（mermaid）；对外 SSE 协议、API、前端零改动。

**Architecture:** 新建 `app/agent/chat_graph.py`（State：trip/glm_messages/attempt/rounds/pending_calls/final_content/done；节点：`agent_call`（调 GLM，stream_writer 发 thinking）→ `execute_tools`（执行工具，发 progress）→ `finalize`（解析+按天替换+校验）；条件边管工具循环 ≤8 轮与校验重试 ≤3 次）。`chat_turn` 变薄壳：建图 + `astream(stream_mode=["custom","values"])` 把 custom 事件映射成现有 SSE 事件，终态取 complete。检查点 `AsyncSqliteSaver`，`thread_id = chat:{trip_id}`。

**Tech Stack:** langgraph 1.2.11 + langgraph-checkpoint-sqlite 3.1.1（spike 已验证：条件边循环、`get_stream_writer` custom 流、AsyncSqliteSaver 落库恢复、`draw_mermaid` 全部可用）。

**Spec:** 设计于 2026-09-07 会话经用户批准（只迁 chat 链路；GLM 用自有 `GLMService` 在节点内直调——方案 A；SqliteSaver——方案 A；不做 interrupt 人工确认）。

## Global Constraints

- 对外行为不变：现有 5 个 chat 行为测试迁移后必须原样通过（仅改导入路径与 monkeypatch 目标）。
- 测试离线；GLM 用 FakeGLM 注入（经 `config["configurable"]` 传入节点）。
- 中文 conventional commits，每任务 commit + push。
- 检查点文件 `backend/data/checkpoints.db` 必须 gitignore。
- State 里只放可序列化对象（Trip/pydantic/dict/list），ToolCall 一律转 dict 存 `pending_calls`。

---

### Task 1: 建图迁移（行为等价，无检查点）

**Files:**
- Create: `backend/app/agent/chat_graph.py`
- Delete: `backend/app/agent/chat_agent.py`
- Modify: `backend/app/api/trips.py`（import 改 chat_graph）、`backend/pyproject.toml`（+langgraph 依赖）
- Test: `backend/tests/test_chat_agent.py` → 改名 `backend/tests/test_chat_graph.py`（导入与 monkeypatch 目标更新，断言不变）；`backend/tests/test_api_chat.py`（wiring 字符串更新）；新增 mermaid/编译测试

**Interfaces:**
- Consumes: 现有 `GLMService.chat_with_tools`、`ToolExecutor/build_tools`、`validate_trip`、`assign_activity_ids`、`ChatRequest`、事件协议。
- Produces:
  - `def build_chat_graph(checkpointer=None)`（langgraph CompiledGraph）
  - `async def chat_turn(req, glm=None, amap=None) -> AsyncIterator[StreamEvent]`（签名与行为同旧版）
  - `def thread_id_of(trip: Trip) -> str`（Task 2 用）
  - `app/api/trips.py` 改为 `from app.agent.chat_graph import chat_turn`。

- [ ] **Step 1: 写失败测试**——把 `tests/test_chat_agent.py` 改名为 `tests/test_chat_graph.py`，只改三处：

```python
from app.agent.chat_graph import chat_turn   # 原 app.agent.chat_agent
```

```python
async def test_rounds_cap_appends_force_finish(monkeypatch):
    import app.agent.chat_graph as mod          # 原 chat_agent
    monkeypatch.setattr(mod, "MAX_ROUNDS", 2)
```

文件末尾追加：

```python
def test_graph_compiles_and_mermaid_contains_nodes():
    from app.agent.chat_graph import build_chat_graph

    graph = build_chat_graph()
    mermaid = graph.get_graph().draw_mermaid()
    assert "agent_call" in mermaid
    assert "execute_tools" in mermaid
    assert "finalize" in mermaid
```

`tests/test_api_chat.py` 的 wiring 断言改为：

```python
    assert "from app.agent.chat_graph import chat_turn" in inspect.getsource(trips_api)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_graph.py tests/test_api_chat.py -q`
Expected: FAIL（chat_graph 模块不存在）

- [ ] **Step 3: 实现**——新建 `app/agent/chat_graph.py`：

```python
"""对话式改行程的 LangGraph 图运行时（V4）。

图结构（存档见 docs/superpowers/assets/chat-graph.mermaid）：
START → agent_call ⇄ execute_tools（有工具调用时循环，≤MAX_ROUNDS 轮）
      → finalize →（通过或纯问答）END
                →（校验失败且未耗尽重试）agent_call
对外的 chat_turn 签名与 SSE 事件协议与迁移前完全一致。"""

import json
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
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


class ChatState(TypedDict):
    trip: Trip
    user_message: str
    glm_messages: list[dict]
    attempt: int
    rounds: int
    pending_calls: list[dict] | None  # 本轮待执行的工具调用（dict 形式，可序列化）
    final_content: str
    done: dict | None  # {"trip": Trip} 或 {"error": [code, message]}；非 None 即终态


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
) -> AsyncIterator[StreamEvent]:
    glm = glm or GLMService(thinking_effort=req.thinking_effort)
    amap = amap or AMapService()
    trip = req.trip.model_copy(deep=True)

    yield ProgressEvent(stage=ProgressStage.analyze, message="正在理解你的需求")

    initial: ChatState = {
        "trip": trip,
        "user_message": req.message,
        "glm_messages": [
            {"role": "system", "content": _system_prompt(trip)},
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
    async for ev in _run(build_chat_graph(), initial, config):
        yield ev
```

删除 `app/agent/chat_agent.py`；`app/api/trips.py` 的 import 改为：

```python
from app.agent.chat_graph import chat_turn
```

`backend/pyproject.toml` dependencies 增加：

```toml
    "langgraph>=1.2",
    "langgraph-checkpoint-sqlite>=3.1",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_graph.py tests/test_api_chat.py -v`
Expected: 行为测试 5 项 + mermaid 1 项 + API 3 项全部 PASS（行为断言一字未改）

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: V4——对话循环迁移到 LangGraph 图运行时，行为等价（SSE/前端零改动）" && git push
```

---

### Task 2: SqliteSaver 检查点持久化

**Files:**
- Modify: `backend/app/agent/chat_graph.py`（chat_turn 加 checkpoint_db 参数）、`.gitignore`（backend/data/）
- Test: `backend/tests/test_chat_graph.py` 追加持久化测试

**Interfaces:**
- Produces: `async def chat_turn(req, glm=None, amap=None, checkpoint_db: str | None = "data/checkpoints.db")`；`thread_id_of(trip)`。

- [ ] **Step 1: 写失败测试**（追加到 test_chat_graph.py）

```python
async def test_checkpoint_persists_terminal_state(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from app.agent.chat_graph import build_chat_graph, thread_id_of
    from app.schemas.trip import Trip

    db = tmp_path / "ckpt.db"
    glm = FakeGLM([ToolRound(content=json.dumps(GOOD_EDIT, ensure_ascii=False), tool_calls=[])])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap(), checkpoint_db=str(db))]
    assert events[-1].type == "complete"

    thread = thread_id_of(Trip.model_validate(TRIP_DATA))
    async with AsyncSqliteSaver.from_conn_string(str(db)) as saver:
        graph = build_chat_graph(checkpointer=saver)
        snap = await graph.aget_state({"configurable": {"thread_id": thread}})
        assert snap is not None
        assert snap.values["done"]["trip"].version == 2
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_graph.py::test_checkpoint_persists_terminal_state -v`
Expected: FAIL（chat_turn 无 checkpoint_db 参数）

- [ ] **Step 3: 实现**——chat_turn 改为：

```python
async def chat_turn(
    req: ChatRequest,
    glm: GLMService | None = None,
    amap: AMapService | None = None,
    checkpoint_db: str | None = "data/checkpoints.db",
) -> AsyncIterator[StreamEvent]:
```

并把建图/运行段替换为：

```python
    config = {
        "configurable": {
            "thread_id": thread_id_of(trip),
            "glm": glm,
            "amap": amap,
            "tools": build_tools(),
            "executor": ToolExecutor(trip.destination, amap),
        }
    }
    if checkpoint_db:
        async with AsyncSqliteSaver.from_conn_string(checkpoint_db) as saver:
            graph = build_chat_graph(checkpointer=saver)
            async for ev in _run(graph, initial, config):
                yield ev
    else:
        async for ev in _run(build_chat_graph(), initial, config):
            yield ev
```

import 区加：

```python
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
```

`.gitignore` 追加一行：`backend/data/`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_graph.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: 对话图检查点落 SqliteSaver（data/checkpoints.db），服务重启后状态可查" && git push
```

---

### Task 3: 图存档 + 端到端验收

**Files:**
- Create: `docs/superpowers/assets/chat-graph.mermaid`
- Modify: 无代码

- [ ] **Step 1: 导出图存档**

```bash
cd backend && .venv/Scripts/python -c "from app.agent.chat_graph import build_chat_graph; print(build_chat_graph().get_graph().draw_mermaid())" > ../docs/superpowers/assets/chat-graph.mermaid
```

- [ ] **Step 2: 重启后端**（uvicorn 无热重载），`curl http://localhost:8000/api/health` 确认 ok。
- [ ] **Step 3: 浏览器端到端**：在行程页对话「把楼外楼换成外婆家(湖滨店)」→ 预期：思考流式 → 「正在定位」progress → 回复气泡 → 卡片/地图/预算刷新 → version+1 可撤销；再问「人均多少钱？」→ 纯回复不改行程。
- [ ] **Step 4: 确认 `backend/data/checkpoints.db` 已生成且被 git 忽略。**
- [ ] **Step 5: 全量回归 + 提交推送。**

## 已知问题

（空）
