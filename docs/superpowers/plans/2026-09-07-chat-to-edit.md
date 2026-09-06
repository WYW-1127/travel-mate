# 对话式行程助理（Chat-to-Edit）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent），按用户要求本次会话只执行到 Task 1，完成后停下等用户验收。**

**Goal:** 详情页的「一句话重规划」升级为持续对话：用户随时用自然语言改行程（「第二天太赶」「灵隐寺换成博物馆」），后端 Agent 通过工具调用（GLM tool calling）自主定位新地点，输出改动 + 自然语言回复；对话历史随行程持久化。

**Architecture:** 保持无状态——对话历史存 `Trip.chat`（localStorage），每次请求带全量上下文。新端点 `POST /api/trips/chat`（SSE，复用现有事件协议）；`GLMService` 新增 `chat_with_tools()`（流式 + tools + thinking）；`chat_agent.chat_turn` 驱动「模型 ↔ 工具」循环（≤8 轮，POI 调用 ≤15 次/请求），最终输出 `{reply, days}`，days 按天替换 + 复用确定性校验器 + 带反馈重试 ≤2。生成流程完全不动。

**Tech Stack:** FastAPI + Pydantic v2；httpx 流式；Vue3 + TS + Pinia（复用 `useGenerationStore` 的 SSE 管线）。

**Spec:** 设计在 2026-09-07 会话中经用户批准（对话式改行程 = 终态原型 2），关键决策与 spike 结论收录在本文「设计基线」；V1 设计背景见 `docs/superpowers/specs/2026-09-06-travel-assistant-design.md` §3.2。

## 设计基线（含 Spike 实测结论）

**已批准的决策：**
- 定位完全交给模型：模型自主决定调 `search_poi` / `geocode`、失败换关键词重查；不做代码 enrich 兜底（校验器 30% 熔断 + 反馈重试兜住）。
- 本次只改「对话改行程」链路；生成流程、重规划端点保持不动。
- 工具集：仅 `search_poi` + `geocode`；路线/预算工具不暴露（YAGNI）。
- 过程展示：复用现有 `progress` 消息（前端零改动）；思考过程照旧流式透传。
- 范围外：无跨会话记忆、无天气等新工具、生成页不动。

**Spike 实测（2026-09-07，真实 API）：**
- `tools` + `thinking:{"type":"enabled"}` + `stream:true` 三者兼容（HTTP 200）；delta 中 `reasoning_content`/`content`/`tool_calls` 并存；发起调用时 `finish_reason:"tool_calls"`。
- `delta.tool_calls[].index` 聚合分片；`function.arguments` 为 JSON 字符串片段需拼接。
- 工具结果以 `{"role":"tool","tool_call_id":...,"content":"<JSON 字符串>"}` 回传后，第二轮正常产出最终 `content`。
- `tools` 与 `response_format:{"type":"json_object"}` 可共存（HTTP 200）——最终轮用 JSON 模式强约束输出契约。

## Global Constraints

- 测试必须离线：GLM 用假对象注入（`tests/test_planner.py` 的 FakeGLM 模式），高德用 Fake service / respx；改动后跑全量测试再提交。
- git：中文 conventional commits，每任务完成即 commit + push（走代理 127.0.0.1:7897，已配置）。
- 高德个人 key POI 日配额有限（百次级）：工具循环设硬上限 `MAX_TOOL_CALLS = 15` 次/请求。
- 兼容 glm-5.3-flash「思考无法关闭」：payload 恒带 `thinking:{"type":"enabled","effort":<档位>}`。
- 活动必须带唯一 id（GLM 草稿不输出 id，参考 2026-09-07 联动修复教训）：新 days 落地前过 `assign_activity_ids`。
- 后端五层不变：api / agent / services / tools / schemas。
- 前端：Vue3 + TS + Pinia + Tailwind v4；`npm test` + `npm run build` 过才算完成。

## 文件结构

```
backend/
├── app/
│   ├── services/glm.py          # 修改：+ToolCall/ToolRound dataclass、+chat_with_tools()
│   ├── schemas/trip.py          # 修改：+ChatMessage；Trip +preferences/chat
│   ├── schemas/chat.py          # 新建：ChatRequest
│   ├── agent/chat_tools.py      # 新建：build_tools() + ToolExecutor（配额计数）
│   ├── agent/chat_agent.py      # 新建：chat_turn() 对话循环 + 输出契约 + 应用/校验
│   ├── agent/planner.py         # 修改：draft_to_trip 存 preferences（一行）
│   └── api/trips.py             # 修改：+POST /trips/chat
└── tests/
    ├── test_glm_service.py      # 修改：+chat_with_tools 4 项测试
    ├── test_schemas_trip.py     # 修改：+ChatMessage 持久化测试
    ├── test_planner.py          # 修改：+preferences 传递测试
    ├── test_chat_tools.py       # 新建
    ├── test_chat_agent.py       # 新建
    └── test_api_chat.py         # 新建（含 wiring 源码检查，防 stub 掩盖接线缺陷）

frontend/
├── src/types/trip.ts            # 修改：+ChatMessage/ChatRequest；Trip +preferences/chat
├── src/api/sse.ts               # 修改：postSSE body 类型放宽
├── src/stores/generation.ts     # 修改：run() body 类型放宽
├── src/components/ChatPanel.vue # 新建：聊天面板（消息列表+输入+思考流式+撤销）
├── src/components/ChatPanel.test.ts  # 新建：组件测试（mock postSSE）
├── src/components/ReplanBox.vue # 删除（被 ChatPanel 取代）
└── src/views/TripDetailView.vue # 修改：ReplanBox → ChatPanel
```

---

### Task 1: GLMService 工具调用能力（chat_with_tools）

**Files:**
- Modify: `backend/app/services/glm.py`
- Test: `backend/tests/test_glm_service.py`

**Interfaces:**
- Consumes: 现有 `GLMService` 的 key/base_url/client/thinking_effort 初始化与流式解析模式。
- Produces:
  - `@dataclass ToolCall: id: str; name: str; arguments: str`（arguments 为原样 JSON 字符串）
  - `@dataclass ToolRound: content: str; tool_calls: list[ToolCall]; reasoning: str`
  - `async def chat_with_tools(self, messages: list[dict], tools: list[dict], on_thinking: Callable[[str], None] | None = None, temperature: float = 0.3) -> ToolRound`
  - 后续任务用 `ToolRound.tool_calls` 驱动循环、`round.content` 做最终 JSON 解析。

- [ ] **Step 1: 写失败测试**（追加到 `backend/tests/test_glm_service.py`）

```python
def _tools_stream_body() -> str:
    # tool_calls 的 arguments 分两个 delta 片段，验证按 index 拼接
    return (
        'data: {"choices":[{"delta":{"role":"assistant","reasoning_content":"需要定位地点"}}]}\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function",'
        '"function":{"name":"search_poi","arguments":"{\\"city\\": "}}]}}]}\n'
        'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"杭州\\"}"}}]}}]}\n'
        'data: {"choices":[{"delta":{"content":""}}]}\n'
        'data: {"choices":[{"finish_reason":"tool_calls"}]}\n'
        "data: [DONE]\n\n"
    )


@respx.mock
async def test_chat_with_tools_assembles_tool_calls_and_thinking():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=_tools_stream_body().encode("utf-8"))
    )
    thoughts: list[str] = []
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    round = await svc.chat_with_tools(
        [{"role": "user", "content": "定位雷峰塔"}],
        tools=[{"type": "function", "function": {"name": "search_poi"}}],
        on_thinking=thoughts.append,
    )
    assert thoughts == ["需要定位地点"]
    assert round.content == ""
    assert round.tool_calls == [
        ToolCall(id="call_1", name="search_poi", arguments='{"city": "杭州"}')
    ]


@respx.mock
async def test_chat_with_tools_returns_content_when_no_tool_calls():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, content=_stream_body().encode("utf-8"))
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    round = await svc.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])
    assert round.tool_calls == []
    assert round.content == '{"title": "重庆一日游"}'


@respx.mock
async def test_chat_with_tools_http_error_raises():
    respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(500, text="boom")
    )
    svc = GLMService(api_key="k", client=httpx.AsyncClient())
    with pytest.raises(GLMError, match="500"):
        await svc.chat_with_tools([{"role": "user", "content": "hi"}], tools=[])


@respx.mock
async def test_chat_with_tools_payload_contains_tools_json_mode_and_thinking():
    captured: list[dict] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content))
        return httpx.Response(200, content=_tools_stream_body().encode("utf-8"))

    respx.post(f"{BASE}/chat/completions").mock(side_effect=capture)
    svc = GLMService(api_key="k", thinking_effort="high", client=httpx.AsyncClient())
    await svc.chat_with_tools(
        [{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "search_poi"}}],
    )
    p = captured[0]
    assert p["tool_choice"] == "auto"
    assert p["response_format"] == {"type": "json_object"}
    assert p["thinking"] == {"type": "enabled", "effort": "high"}
    assert p["stream"] is True
    assert p["tools"][0]["function"]["name"] == "search_poi"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_glm_service.py -k tools -v`
Expected: FAIL（`ImportError: cannot import name 'ToolCall'` 或 AttributeError）

- [ ] **Step 3: 最小实现**（追加到 `backend/app/services/glm.py`）

```python
from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # 原样 JSON 字符串，由调用方解析


@dataclass
class ToolRound:
    """工具模式一轮响应：模型要么发起 tool_calls，要么给出最终 content（两者互斥时以 tool_calls 为准）。"""

    content: str
    tool_calls: list[ToolCall]
    reasoning: str
```

```python
    async def chat_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        on_thinking: Callable[[str], None] | None = None,
        temperature: float = 0.3,
    ) -> ToolRound:
        """工具模式流式调用。messages 为完整消息历史（含 system/assistant/tool 角色），由调用方维护。

        reasoning 增量经 on_thinking 回调；tool_calls 分片按 index 聚合（spike 实测协议，
        见 docs/superpowers/plans/2026-09-07-chat-to-edit.md 设计基线）。"""
        if not self._api_key:
            raise GLMError("GLM_API_KEY 未配置（见 backend/.env.example）")
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=180.0)
        payload = {
            "model": self._model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": temperature,
            "response_format": {"type": "json_object"},
            "stream": True,
            "thinking": {"type": "enabled", "effort": self._thinking_effort},
        }
        async with self._client.stream(
            "POST",
            f"{self._base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self._api_key}"},
        ) as resp:
            if resp.status_code != 200:
                body = (await resp.aread()).decode("utf-8", errors="replace")
                raise GLMError(f"GLM HTTP {resp.status_code}: {body[:200]}")

            content_parts: list[str] = []
            reasoning_parts: list[str] = []
            calls: dict[int, dict] = {}
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choice = (chunk.get("choices") or [{}])[0]
                delta = choice.get("delta") or {}
                if delta.get("reasoning_content"):
                    reasoning_parts.append(delta["reasoning_content"])
                    if on_thinking:
                        on_thinking(delta["reasoning_content"])
                if delta.get("content"):
                    content_parts.append(delta["content"])
                for tc in delta.get("tool_calls") or []:
                    idx = tc.get("index", 0)
                    slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.get("id"):
                        slot["id"] = tc["id"]
                    fn = tc.get("function") or {}
                    if fn.get("name"):
                        slot["name"] = fn["name"]
                    if fn.get("arguments"):
                        slot["arguments"] += fn["arguments"]

            tool_calls = [
                ToolCall(id=s["id"], name=s["name"], arguments=s["arguments"])
                for _, s in sorted(calls.items())
            ]
            return ToolRound(
                content="".join(content_parts),
                tool_calls=tool_calls,
                reasoning="".join(reasoning_parts),
            )
```

注意：`from dataclasses import dataclass` 加到文件头部 import 区。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_glm_service.py -v`
Expected: 全部 PASS（旧测试不回归）

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add app/services/glm.py tests/test_glm_service.py
git commit -m "feat: GLMService 工具模式流式调用 chat_with_tools——tools+thinking 兼容（spike 已验证），tool_calls 按 index 聚合"
git push
```

---

### Task 2: Trip 数据模型扩展（ChatMessage / preferences / chat）

**Files:**
- Modify: `backend/app/schemas/trip.py`、`backend/app/agent/planner.py`（draft_to_trip 一行）
- Test: `backend/tests/test_schemas_trip.py`、`backend/tests/test_planner.py`

**Interfaces:**
- Consumes: 现有 `CamelModel`、`Trip`。
- Produces:
  - `class ChatMessage(CamelModel): role: Literal["user","assistant"]; content: str = ""; ts: str = ""`
  - `Trip.preferences: str = ""`（生成时的偏好，对话时注入提示词）
  - `Trip.chat: list[ChatMessage] = []`
  - Task 4 依赖：`trip.chat` 读写、`trip.preferences` 注入。

- [ ] **Step 1: 写失败测试**

`tests/test_schemas_trip.py` 追加：

```python
def test_trip_chat_and_preferences_roundtrip():
    trip = Trip.model_validate(
        {
            "destination": "重庆",
            "preferences": "带娃、不去网红店",
            "chat": [{"role": "user", "content": "别太赶", "ts": "2026-09-07T10:00:00"}],
        }
    )
    assert trip.preferences == "带娃、不去网红店"
    assert trip.chat[0].role == "user"
    dumped = json.loads(trip.model_dump_json(by_alias=True))
    assert dumped["chat"][0]["role"] == "user"
    # 旧行程无新字段可正常解析（向后兼容）
    old = Trip.model_validate({"destination": "重庆"})
    assert old.preferences == "" and old.chat == []
```

`tests/test_planner.py` 追加：

```python
def test_draft_to_trip_keeps_preferences():
    req = GenerateRequest.model_validate(
        {"destination": "重庆", "days": 2, "preferences": "带娃"}
    )
    trip = draft_to_trip(GOOD_DRAFT, req)
    assert trip.preferences == "带娃"
```

（若 test_schemas_trip.py 没有 `import json`，补上。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_schemas_trip.py tests/test_planner.py -v`
Expected: FAIL（Trip 无 preferences/chat 字段）

- [ ] **Step 3: 最小实现**

`app/schemas/trip.py`：头部加 `from typing import Literal`；`Trip` 前加：

```python
class ChatMessage(CamelModel):
    role: Literal["user", "assistant"]
    content: str = ""
    ts: str = ""  # ISO 本地时间，前端展示用
```

`Trip` 增加：

```python
    preferences: str = ""  # 生成时的偏好（带娃、不去网红店），对话式修改时注入提示词
    chat: list[ChatMessage] = Field(default_factory=list)  # 对话历史随行程持久化（≤50 条，超出由写入方裁剪）
```

`app/agent/planner.py` 的 `draft_to_trip`，`data` 字典加一行：

```python
        "preferences": req.preferences or "",
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_schemas_trip.py tests/test_planner.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: Trip 增加 preferences 与 chat 字段，生成时落偏好供对话使用" && git push
```

---

### Task 3: 工具层——build_tools + ToolExecutor

**Files:**
- Create: `backend/app/agent/chat_tools.py`
- Test: `backend/tests/test_chat_tools.py`

**Interfaces:**
- Consumes: `app.tools.poi.search_poi`（含关键词清洗+geocode 兜底+进程缓存）、`AMapService.geocode`。
- Produces:
  - `def build_tools() -> list[dict]`（search_poi/geocode 的 OpenAI tool 定义）
  - `class ToolExecutor: __init__(self, destination: str, amap: AMapService, max_calls: int = 15)`；`async def execute(self, name: str, arguments: str) -> str`（恒返回 JSON 字符串；错误也用 `{"error": ...}` 表达，喂回模型）
  - 常量 `MAX_TOOL_CALLS = 15`
  - Task 4 依赖这两个名字。

- [ ] **Step 1: 写失败测试**（`backend/tests/test_chat_tools.py` 新建）

```python
import json

from app.agent.chat_tools import MAX_TOOL_CALLS, ToolExecutor, build_tools
from app.services.amap import AMapService, PoiResult


class FakeAMap(AMapService):
    def __init__(self):
        super().__init__(key="fake")
        self.poi_calls = 0

    async def search_poi(self, city, keyword):
        self.poi_calls += 1
        return PoiResult(name=keyword, address="a", longitude=120.1, latitude=30.2, poi_id="P")

    async def geocode(self, address, city=""):
        return (120.1, 30.2)


def test_build_tools_defines_search_poi_and_geocode():
    tools = build_tools()
    names = [t["function"]["name"] for t in tools]
    assert names == ["search_poi", "geocode"]
    for t in tools:
        assert t["type"] == "function"
        assert "parameters" in t["function"]


async def test_search_poi_tool_returns_location_json():
    ex = ToolExecutor("杭州", FakeAMap())
    out = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "雷峰塔"}'))
    assert out["name"] == "雷峰塔"
    assert out["longitude"] == 120.1 and out["resolved"] is True


async def test_geocode_tool_returns_coords():
    ex = ToolExecutor("杭州", FakeAMap())
    out = json.loads(await ex.execute("geocode", '{"address": "西湖区南山路", "city": "杭州"}'))
    assert out == {"longitude": 120.1, "latitude": 30.2}


async def test_unknown_tool_and_bad_args_return_error_json():
    ex = ToolExecutor("杭州", FakeAMap())
    assert "error" in json.loads(await ex.execute("weather", "{}"))
    assert "error" in json.loads(await ex.execute("search_poi", "不是json"))


async def test_quota_cap_blocks_after_max_calls():
    ex = ToolExecutor("杭州", FakeAMap(), max_calls=1)
    first = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "a"}'))
    assert "error" not in first
    second = json.loads(await ex.execute("search_poi", '{"city": "杭州", "keyword": "b"}'))
    assert "上限" in second["error"]
    assert MAX_TOOL_CALLS == 15
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_tools.py -v`
Expected: FAIL（ModuleNotFoundError: app.agent.chat_tools）

- [ ] **Step 3: 最小实现**（`backend/app/agent/chat_tools.py` 新建）

```python
import json

from app.services.amap import AMapError, AMapService
from app.tools.poi import search_poi

MAX_TOOL_CALLS = 15  # 高德个人 key 日配额有限（百次级），单次对话内硬上限


def build_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": "search_poi",
                "description": "在高德地图搜索一个地点（POI），返回规范名称、地址、经纬度。定位地点时优先用它。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名，如 杭州"},
                        "keyword": {"type": "string", "description": "地点名称，尽量用官方规范名"},
                    },
                    "required": ["city", "keyword"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "geocode",
                "description": "把地址或区域名转换为经纬度（地理编码兜底）。search_poi 搜不到时再用。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "address": {"type": "string", "description": "地址或地名"},
                        "city": {"type": "string", "description": "城市名"},
                    },
                    "required": ["address"],
                },
            },
        },
    ]


class ToolExecutor:
    """执行模型发起的工具调用，结果以 JSON 字符串回传给模型。

    失败不抛异常——一切错误都编码为 {"error": ...} 让模型自行决策（换关键词/换工具/放弃）。
    进程内计数保护高德配额（POI 底层另有进程级缓存，重复关键词不重复计数扣量由缓存挡掉）。"""

    def __init__(self, destination: str, amap: AMapService, max_calls: int = MAX_TOOL_CALLS):
        self.destination = destination
        self.amap = amap
        self.remaining = max_calls

    async def execute(self, name: str, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
            if not isinstance(args, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            return json.dumps({"error": "工具参数不是合法 JSON 对象"}, ensure_ascii=False)

        if name == "search_poi":
            if self.remaining <= 0:
                return json.dumps({"error": "定位次数已达上限，请基于已有信息完成回答"}, ensure_ascii=False)
            self.remaining -= 1
            loc = await search_poi(self.destination, str(args.get("keyword", "")), self.amap)
            if loc is None:
                return json.dumps({"error": "未找到该地点，可尝试更换关键词或改用 geocode"}, ensure_ascii=False)
            return loc.model_dump_json(by_alias=True)

        if name == "geocode":
            if self.remaining <= 0:
                return json.dumps({"error": "定位次数已达上限，请基于已有信息完成回答"}, ensure_ascii=False)
            self.remaining -= 1
            try:
                coords = await self.amap.geocode(str(args.get("address", "")), str(args.get("city", "")))
            except AMapError:
                return json.dumps({"error": "地理编码服务暂时不可用"}, ensure_ascii=False)
            if coords is None:
                return json.dumps({"error": "未能解析该地址"}, ensure_ascii=False)
            return json.dumps({"longitude": coords[0], "latitude": coords[1]}, ensure_ascii=False)

        return json.dumps({"error": f"未知工具 {name}"}, ensure_ascii=False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_tools.py -v`
Expected: PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: 对话工具层——search_poi/geocode 工具定义与执行器，错误编码回传模型，配额硬上限 15 次/请求" && git push
```

---

### Task 4: chat_agent——对话循环 + 输出契约 + 应用校验

**Files:**
- Create: `backend/app/schemas/chat.py`、`backend/app/agent/chat_agent.py`
- Test: `backend/tests/test_chat_agent.py`

**Interfaces:**
- Consumes: Task 1 `chat_with_tools/ToolRound`、Task 2 `ChatMessage/preferences`、Task 3 `build_tools/ToolExecutor`、planner 的 `assign_activity_ids`、validator 的 `validate_trip`、events 的既有事件。
- Produces:
  - `class ChatRequest(CamelModel): trip: Trip; message: str (1..500); thinking_effort: Literal["low","high"] | None`
  - `async def chat_turn(req: ChatRequest, glm=None, amap=None) -> AsyncIterator[StreamEvent]`
  - 事件协议：复用 progress（工具定位进度）/thinking/complete/error；**complete 事件的 trip 已包含追加后的 chat（user+assistant 两条）与替换后的 days（version+1）**——前端零协议改动。
  - Task 5 依赖 `chat_turn` 与 `ChatRequest`。

- [ ] **Step 1: 写失败测试**（`backend/tests/test_chat_agent.py` 新建）

```python
import json

from app.agent.chat_agent import chat_turn
from app.schemas.chat import ChatRequest
from app.services.amap import AMapService, PoiResult
from app.services.glm import GLMError, GLMService, ToolCall, ToolRound

TRIP_DATA = {
    "id": "t1",
    "title": "杭州一日游",
    "destination": "杭州",
    "version": 1,
    "preferences": "带娃",
    "days": [
        {
            "title": "D1",
            "activities": [
                {"id": "a1", "name": "西湖风景名胜区", "type": "attraction",
                 "startTime": "09:00", "endTime": "11:00", "cost": 0,
                 "location": {"name": "西湖风景名胜区", "resolved": True, "longitude": 120.14, "latitude": 30.24}},
            ],
        },
        {
            "title": "D2",
            "activities": [
                {"id": "a2", "name": "灵隐飞来峰景区", "type": "attraction",
                 "startTime": "09:30", "endTime": "11:30", "cost": 75,
                 "location": {"name": "灵隐飞来峰景区", "resolved": True, "longitude": 120.097, "latitude": 30.241}},
            ],
        },
    ],
}

SEARCH_CALL = ToolCall(id="call_1", name="search_poi", arguments='{"city": "杭州", "keyword": "中国茶叶博物馆"}')

GOOD_EDIT = {
    "reply": "已把第 2 天的灵隐飞来峰换成中国茶叶博物馆，时间不变",
    "days": [
        {
            "index": 1,
            "title": "茶文化",
            "activities": [
                {"name": "中国茶叶博物馆", "type": "attraction", "startTime": "09:30", "endTime": "11:30", "cost": 0,
                 "location": {"name": "中国茶叶博物馆", "resolved": True, "longitude": 120.09, "latitude": 30.22}},
            ],
        }
    ],
}


class FakeGLM(GLMService):
    """按脚本依次返回 ToolRound；记录每轮完整 messages 供断言。"""

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
    def __init__(self):
        super().__init__(key="fake")

    async def search_poi(self, city, keyword):
        return PoiResult(name=keyword, address="a", longitude=120.09, latitude=30.22, poi_id="P")


def _req(message: str = "把第 2 天的灵隐寺换成中国茶叶博物馆") -> ChatRequest:
    return ChatRequest.model_validate({"trip": TRIP_DATA, "message": message})


async def test_tool_call_round_edits_day_and_appends_chat():
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps(GOOD_EDIT, ensure_ascii=False), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]

    complete = events[-1]
    assert complete.type == "complete"
    trip = complete.trip
    assert trip.version == 2
    assert trip.days[1].activities[0].name == "中国茶叶博物馆"
    assert trip.days[1].activities[0].id  # 新活动补了唯一 id
    assert trip.days[0].activities[0].name == "西湖风景名胜区"  # 未提的天原样
    assert [m.role for m in trip.chat] == ["user", "assistant"]
    assert trip.chat[0].content == "把第 2 天的灵隐寺换成中国茶叶博物馆"
    assert any(e.type == "progress" and "定位" in e.message for e in events)
    # 工具结果以 role=tool 回传进了下一轮
    assert any(m.get("role") == "tool" for m in glm.calls[1])
    # thinking 流式透传
    assert any(e.type == "thinking" for e in events)


async def test_pure_chat_keeps_trip_untouched():
    glm = FakeGLM([
        ToolRound(content=json.dumps({"reply": "人均约 375 元", "days": []}), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req("人均要花多少钱"), glm=glm, amap=FakeAMap())]
    trip = events[-1].trip
    assert trip.version == 1
    assert trip.days[1].activities[0].name == "灵隐飞来峰景区"
    assert trip.chat[-1].content == "人均约 375 元"


async def test_invalid_days_shape_retries_with_feedback():
    bad = {"reply": "改好了", "days": [{"index": 1, "title": "x", "activities": [
        {"name": "a", "startTime": "10:00", "endTime": "09:00"}]}]}
    glm = FakeGLM([
        ToolRound(content=json.dumps(bad, ensure_ascii=False), tool_calls=[]),
        ToolRound(content=json.dumps(GOOD_EDIT, ensure_ascii=False), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"
    assert len(glm.calls) == 2
    last_user = glm.calls[1][-1]
    assert last_user["role"] == "user" and "问题" in last_user["content"]


async def test_rounds_cap_appends_force_finish(monkeypatch):
    import app.agent.chat_agent as mod
    monkeypatch.setattr(mod, "MAX_ROUNDS", 2)
    glm = FakeGLM([
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content="", tool_calls=[SEARCH_CALL]),
        ToolRound(content=json.dumps({"reply": "好", "days": []}), tool_calls=[]),
    ])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "complete"
    assert any("已达上限" in m.get("content", "") for m in glm.calls[2] if m.get("role") == "user")


async def test_glm_error_yields_error_event():
    glm = FakeGLM([GLMError("GLM 连接失败")])
    events = [e async for e in chat_turn(_req(), glm=glm, amap=FakeAMap())]
    assert events[-1].type == "error"
    assert events[-1].code == "GLM_ERROR"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_agent.py -v`
Expected: FAIL（ModuleNotFoundError: app.schemas.chat / app.agent.chat_agent）

- [ ] **Step 3: 最小实现**

`backend/app/schemas/chat.py`：

```python
from typing import Literal

from pydantic import Field

from app.schemas.trip import CamelModel, Trip


class ChatRequest(CamelModel):
    trip: Trip
    message: str = Field(min_length=1, max_length=500)
    thinking_effort: Literal["low", "high"] | None = None
```

`backend/app/agent/chat_agent.py`：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_agent.py -v`
Expected: 5 项 PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: chat_agent 对话循环——模型自主调定位工具，按天编辑+确定性校验+反馈重试，纯问答不改行程" && git push
```

---

### Task 5: API 端点 POST /api/trips/chat

**Files:**
- Modify: `backend/app/api/trips.py`
- Test: `backend/tests/test_api_chat.py`（新建，模式照抄 `test_api_replan.py`，含 wiring 源码检查——防 stub 掩盖接线缺陷的既定兜底）

**Interfaces:**
- Consumes: Task 4 `chat_turn` / `ChatRequest`；现有 `_sse`/`SSE_HEADERS`/`get_amap`。
- Produces: `POST /api/trips/chat`（SSE），Task 6 前端调用。

- [ ] **Step 1: 写失败测试**（`backend/tests/test_api_chat.py` 新建）

```python
import pytest

from app.main import app
from app.schemas.events import CompleteEvent


@pytest.fixture(autouse=True)
def _install():
    async def fake_chat(req, glm=None, amap=None):
        yield CompleteEvent(trip=req.trip.model_copy(update={"version": 2}))

    import app.agent.chat_agent as chat_mod
    import app.api.trips as trips_api

    trips_api.chat_turn = fake_chat
    yield
    trips_api.chat_turn = chat_mod.chat_turn


async def test_chat_streams_complete(client):
    resp = await client.post(
        "/api/trips/chat",
        json={
            "trip": {"destination": "重庆", "days": [], "version": 1, "chat": []},
            "message": "别太赶",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert '"type":"complete"' in resp.text
    assert '"version":2' in resp.text


async def test_chat_validates_body(client):
    resp = await client.post("/api/trips/chat", json={"trip": {"destination": "重庆"}, "message": ""})
    assert resp.status_code == 422


async def test_chat_wiring_import_present():
    """防回归：trips 模块必须真实 import chat_turn（源码级检查）。"""
    import inspect

    import app.api.trips as trips_api

    assert "from app.agent.chat_agent import chat_turn" in inspect.getsource(trips_api)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api_chat.py -v`
Expected: FAIL（trips_api 无 chat_turn 属性 / 404）

- [ ] **Step 3: 最小实现**（`app/api/trips.py`）

import 区加：

```python
from app.agent.chat_agent import chat_turn
from app.schemas.chat import ChatRequest
```

文件尾部加：

```python
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api_chat.py -v`
Expected: 3 项 PASS

- [ ] **Step 5: 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: POST /api/trips/chat 对话端点（SSE，复用事件协议）" && git push
```

---

### Task 6: 前端——ChatPanel 替换 ReplanBox

**Files:**
- Modify: `frontend/src/types/trip.ts`、`frontend/src/api/sse.ts`（body 类型）、`frontend/src/stores/generation.ts`（body 类型）、`frontend/src/views/TripDetailView.vue`
- Create: `frontend/src/components/ChatPanel.vue`、`frontend/src/components/ChatPanel.test.ts`
- Delete: `frontend/src/components/ReplanBox.vue`

**Interfaces:**
- Consumes: `POST /api/trips/chat`（complete 事件的 trip 已含追加后的 chat）；`useGenerationStore.run`；`trips.saveSnapshot/undo`；`ThinkingPanel`。
- Produces: 详情页聊天面板；`Trip.chat`/`Trip.preferences` 类型；body 类型放宽为 `GenerateRequest | ReplanRequest | ChatRequest`。

- [ ] **Step 1: 类型与 store 放宽**（`src/types/trip.ts` 追加）

```ts
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  ts?: string
}
```

`Trip` 接口追加字段：

```ts
  /** 生成时的偏好（带娃、不去网红店），对话修改时服务端注入提示词 */
  preferences?: string
  /** 与 AI 的对话历史，随行程持久化 */
  chat?: ChatMessage[]
```

追加请求类型：

```ts
export interface ChatRequest {
  trip: Trip
  message: string
  thinking_effort?: 'low' | 'high'
}
```

`src/api/sse.ts` 与 `src/stores/generation.ts` 中 `GenerateRequest | ReplanRequest` 全部放宽为 `GenerateRequest | ReplanRequest | ChatRequest`（改 import 与两处签名）。

- [ ] **Step 2: 写组件测试**（`src/components/ChatPanel.test.ts` 新建）

```ts
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { StreamEvent } from '@/types/trip'

const postSSE = vi.fn()
vi.mock('@/api/sse', () => ({ postSSE: (...args: unknown[]) => postSSE(...args) }))

import ChatPanel from './ChatPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useTripsStore } from '@/stores/trips'

function makeTrip() {
  return {
    id: 't1',
    destination: '杭州',
    version: 1,
    preferences: '带娃',
    days: [{ title: 'D1', activities: [{ id: 'a1', name: '西湖', type: 'attraction', cost: 0 }] }],
    chat: [{ role: 'assistant', content: '行程已生成，随时告诉我要改什么', ts: '2026-09-07T10:00:00' }],
  }
}

function sseMock(events: StreamEvent[]) {
  postSSE.mockImplementation((_url: string, _body: unknown, onEvent: (e: StreamEvent) => void) => {
    for (const e of events) onEvent(e)
    return { stop: vi.fn(), done: Promise.resolve() }
  })
}

beforeEach(() => {
  localStorage.clear()
  setActivePinia(createPinia())
  postSSE.mockReset()
})

describe('ChatPanel', () => {
  it('渲染已有对话历史', () => {
    const store = useCurrentTripStore()
    store.set(makeTrip() as never)
    const wrapper = mount(ChatPanel)
    expect(wrapper.text()).toContain('行程已生成，随时告诉我要改什么')
  })

  it('发送后 complete 事件落地：version 变化才存快照，trip 整体替换', async () => {
    const current = useCurrentTripStore()
    const trips = useTripsStore()
    const trip = trips.upsert(makeTrip() as never)
    current.set(trip)

    const next = { ...trip, version: 2, chat: [...(trip.chat ?? []), { role: 'user', content: '别太赶' }, { role: 'assistant', content: '已放慢节奏' }] }
    sseMock([{ type: 'complete', trip: next as never }])

    const wrapper = mount(ChatPanel)
    await wrapper.find('input[type="text"], textarea').setValue('第二天别太赶')
    await wrapper.find('form').trigger('submit')
    await vi.waitFor(() => expect(current.trip!.version).toBe(2))
    expect(current.trip!.chat).toHaveLength(3)
    expect(trips.snapshotCount('t1')).toBe(1)
  })
})
```

（挂载需要 `global.plugins: [pinia]` 时改用 `mount(ChatPanel, { global: { plugins: [createPinia()] } })`，以能跑通为准；如 jsdom 缺 DOM API 按报错补 stub。）

- [ ] **Step 3: 跑测试确认失败**

Run: `cd frontend && npm test`
Expected: FAIL（ChatPanel.vue 不存在）

- [ ] **Step 4: 实现 ChatPanel.vue**

```vue
<script setup lang="ts">
import { ref } from 'vue'

import ThinkingPanel from '@/components/ThinkingPanel.vue'
import { useCurrentTripStore } from '@/stores/currentTrip'
import { useGenerationStore } from '@/stores/generation'
import { useTripsStore } from '@/stores/trips'

const store = useCurrentTripStore()
const generation = useGenerationStore()
const trips = useTripsStore()

const draft = ref('')
const thinking = ref(true)

async function send() {
  if (!draft.value.trim() || !store.trip || generation.phase === 'running') return
  const current = store.trip
  const done = generation.run(
    '/api/trips/chat',
    { trip: current, message: draft.value.trim(), thinking_effort: thinking.value ? 'high' : 'low' },
  )
  await done
  if (generation.phase === 'done' && generation.result) {
    if (generation.result.version !== current.version) trips.saveSnapshot(current)
    store.replaceTrip(generation.result)
    trips.upsert(generation.result)
    draft.value = ''
  }
}

function undo() {
  if (!store.trip) return
  const restored = trips.undo(store.trip)
  if (restored) store.replaceTrip(restored)
}

function fmt(ts?: string) {
  return ts ? ts.slice(5, 16).replace('T', ' ') : ''
}
</script>

<template>
  <div class="no-print flex flex-col rounded-xl border border-teal-200 bg-teal-50/50 p-3">
    <h3 class="mb-2 text-sm font-bold text-slate-700">和 AI 规划师聊两句</h3>

    <!-- 对话历史 -->
    <div class="mb-2 max-h-60 space-y-2 overflow-y-auto pr-1">
      <div
        v-for="(m, i) in store.trip?.chat ?? []"
        :key="i"
        class="max-w-[85%] rounded-xl px-3 py-1.5 text-sm whitespace-pre-wrap"
        :class="m.role === 'user' ? 'ml-auto bg-teal-600 text-white' : 'bg-white text-slate-700'"
        :title="fmt(m.ts)"
      >
        {{ m.content }}
      </div>
    </div>

    <!-- 运行中的进度与思考 -->
    <p v-if="generation.phase === 'running'" class="h-4 text-xs text-teal-700">
      {{ generation.messages.at(-1) ?? '…' }}
    </p>
    <div v-if="generation.phase === 'running'" class="mb-2">
      <ThinkingPanel :text="generation.thinking" running />
    </div>
    <p v-else-if="generation.phase === 'error'" class="text-xs text-red-600">
      {{ generation.error?.message }}
    </p>

    <!-- 输入区 -->
    <form class="flex gap-2" @submit.prevent="send">
      <input
        v-model="draft"
        type="text"
        :disabled="generation.phase === 'running'"
        placeholder="如：第二天别太赶 / 把灵隐寺换成博物馆 / 要花多少钱？"
        class="flex-1 rounded-lg border border-teal-300 bg-white px-3 py-2 text-sm focus:border-teal-500 focus:outline-none disabled:opacity-50"
      />
      <button
        type="submit"
        :disabled="generation.phase === 'running' || !draft.trim()"
        class="rounded-lg bg-teal-600 px-4 py-2 text-sm font-medium text-white hover:bg-teal-700 disabled:opacity-50"
      >
        {{ generation.phase === 'running' ? '…' : '发送' }}
      </button>
      <button
        v-if="store.trip && trips.snapshotCount(store.trip.id!) > 0"
        type="button"
        class="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
        title="恢复到上次改动前"
        @click="undo"
      >
        撤销
      </button>
    </form>
    <label class="mt-2 flex w-fit cursor-pointer items-center gap-1.5 text-xs text-slate-500">
      <input v-model="thinking" type="checkbox" class="h-3.5 w-3.5 accent-teal-600" />
      深度思考（取消=快速档）
    </label>
  </div>
</template>
```

`TripDetailView.vue`：`import ReplanBox` → `import ChatPanel from '@/components/ChatPanel.vue'`，模板 `<ReplanBox />` → `<ChatPanel />`；删除 `src/components/ReplanBox.vue`。

- [ ] **Step 5: 跑测试与构建确认通过**

Run: `cd frontend && npm test && npm run build`
Expected: 全部 PASS，vue-tsc 无类型错误

- [ ] **Step 6: 提交**

```bash
git add -A && git commit -m "feat: 详情页对话式改行程——ChatPanel 替换一次性重规划框，对话历史随行程持久化" && git push
```

---

### Task 7: 端到端真机验收

**Files:** 无代码（验收 + 可能的小修）

**Interfaces:** Consumes 全部前序任务。

- [ ] **Step 1: 重启后端**（uvicorn 不带 --reload，改代码后必须重启）：杀掉旧 uvicorn 进程后 `cd backend && .venv/Scripts/python -m uvicorn app.main:app --port 8000`；`curl http://localhost:8000/api/health` 确认 ok。
- [ ] **Step 2: 浏览器实测改行程**：打开 `http://localhost:5173/trips/<已有行程id>`，在聊天面板输入「把第二天的雷峰塔换成中国茶叶博物馆」→ 预期：思考流式出现 → 「正在定位：中国茶叶博物馆」progress → 助理气泡回复 → 第 2 天卡片更新、地图 Marker/预算联动刷新、version+1、可撤销。
- [ ] **Step 3: 纯问答实测**：输入「这个行程人均大概要花多少钱？」→ 预期：只有回复，行程无变化、version 不变、不产生快照。
- [ ] **Step 4: 观察配额消耗**（本次实测预计 ≤5 次 POI 调用）；若模型行为异常（如编坐标、乱改天），把案例记回本计划「已知问题」再修。
- [ ] **Step 5: 全量测试最后跑一遍，提交遗留修复并 push。**

## 已知问题

（空——实施中发现的记在这里）
