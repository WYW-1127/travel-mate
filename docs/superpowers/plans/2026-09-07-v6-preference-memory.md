# V6 用户偏好记忆（跨行程）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent）。**

**Goal:** 用户说过一次的长期旅行偏好（带娃、不去网红店）被 AI 自动抽取成档案（localStorage，≤20 条），下次生成自动预填、聊天改行程自动注入提示词；档案标签可见可删。

**Architecture:** 后端只提供无状态抽取端点 `POST /api/preferences/extract`（GLM low 档一次性 JSON 调用，过滤一次性需求）；档案存前端 localStorage（Pinia `profile` store）。生成页 submit 时 fire-and-forget 抽取偏好输入；ChatPanel 每轮 complete 后抽取用户消息；`ChatRequest.profile[]` 注入 chat_graph 系统提示词。生成/对话流程本身零改动。

**Tech Stack:** 既有栈，无新依赖。抽取用 `GLMService.chat_json`（普通 JSON 模式，已验证）。

**Spec:** 设计于 2026-09-07 会话经用户批准（决策点：AI 自动抽取+手动管理；档案存前端 localStorage；不做跨设备同步/确认交互）。

## Global Constraints

- 测试离线（FakeGLM/stub 注入）；中文 conventional commits；每任务 commit + push。
- 档案条目：每条 ≤30 字、≤20 条、精确去重；抽取结果 ≤8 条。
- fire-and-forget 抽取必须吞掉异常（`.catch(() => {})`），绝不阻塞生成/对话主流程。

---

### Task 1: 后端抽取端点

**Files:**
- Create: `backend/app/schemas/preferences.py`、`backend/app/agent/preferences.py`、`backend/app/api/preferences.py`
- Modify: `backend/app/main.py`（注册路由）
- Test: `backend/tests/test_preferences.py`、`backend/tests/test_api_preferences.py`

**Interfaces:**
- Produces: `POST /api/preferences/extract`（body `{text}` → `{items: string[]}`）；`async def extract_preferences(text: str, glm=None) -> list[str]`（Task 4 前端不直接用，但 API 层用）。

- [ ] **Step 1: 写失败测试**

`backend/tests/test_preferences.py`：

```python
from app.agent.preferences import extract_preferences
from app.services.glm import GLMService


class FakeGLM(GLMService):
    def __init__(self, result):
        super().__init__(api_key="fake")
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def chat_json(self, system, user, temperature=0.3):
        self.calls.append((system, user))
        return self.result


async def test_extracts_durable_preferences():
    glm = FakeGLM({"items": ["带5岁孩子出行", "不去网红店"]})
    items = await extract_preferences("带5岁孩子，不想太赶，不去网红店", glm=glm)
    assert items == ["带5岁孩子出行", "不去网红店"]
    assert "长期、可复用" in glm.calls[0][0]
    assert "带5岁孩子" in glm.calls[0][1]


async def test_garbage_and_non_string_entries_filtered():
    assert await extract_preferences("x", glm=FakeGLM({"items": "不是列表"})) == []
    assert await extract_preferences("x", glm=FakeGLM({"nope": 1})) == []
    items = await extract_preferences("x", glm=FakeGLM({"items": ["a", 123, "  ", "", "b"]}))
    assert items == ["a", "b"]


async def test_capped_at_eight_and_thirty_chars():
    raw = {"items": [f"偏好{i}" for i in range(12)] + ["x" * 50]}
    items = await extract_preferences("x", glm=FakeGLM(raw))
    assert len(items) == 8
    assert all(len(i) <= 30 for i in items)
```

`backend/tests/test_api_preferences.py`：

```python
import pytest

from app.main import app


@pytest.fixture(autouse=True)
def _install():
    async def fake_extract(text, glm=None):
        return ["带5岁孩子出行"]

    import app.api.preferences as prefs_api
    from app.api.preferences import extract_preferences

    prefs_api.extract_preferences = fake_extract
    yield
    prefs_api.extract_preferences = extract_preferences


async def test_extract_returns_items(client):
    resp = await client.post("/api/preferences/extract", json={"text": "带5岁孩子"})
    assert resp.status_code == 200
    assert resp.json() == {"items": ["带5岁孩子出行"]}


async def test_extract_validates_body(client):
    resp = await client.post("/api/preferences/extract", json={"text": ""})
    assert resp.status_code == 422


async def test_wiring_import_present():
    import inspect

    import app.api.preferences as prefs_api

    assert "from app.agent.preferences import extract_preferences" in inspect.getsource(prefs_api)
```

- [ ] **Step 2: 确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_preferences.py tests/test_api_preferences.py -q`
Expected: FAIL（模块不存在 / 404）

- [ ] **Step 3: 实现**

`backend/app/schemas/preferences.py`：

```python
from pydantic import Field

from app.schemas.trip import CamelModel


class ExtractRequest(CamelModel):
    text: str = Field(min_length=1, max_length=500)


class ExtractResult(CamelModel):
    items: list[str] = Field(default_factory=list)
```

`backend/app/agent/preferences.py`：

```python
from app.services.glm import GLMService

_EXTRACT_SYSTEM = """你是旅行偏好分析器。从用户输入中抽取「长期、可复用」的旅行偏好（跨行程有效），如同行人、花费习惯、兴趣喜好、明确忌讳；过滤掉仅对本次旅行有效的一次性需求（如「这次别去太远」「明天想休息」）。
只输出 JSON：{"items": ["短句", ...]}；没有可抽取的就输出 {"items": []}。每条不超过 20 字，最多 8 条。"""


async def extract_preferences(text: str, glm: GLMService | None = None) -> list[str]:
    glm = glm or GLMService(thinking_effort="low")
    data = await glm.chat_json(_EXTRACT_SYSTEM, f"用户输入：{text}")
    items = data.get("items")
    if not isinstance(items, list):
        return []
    cleaned = [i.strip()[:30] for i in items if isinstance(i, str) and i.strip()]
    return cleaned[:8]
```

`backend/app/api/preferences.py`：

```python
from fastapi import APIRouter

from app.agent.preferences import extract_preferences
from app.schemas.preferences import ExtractRequest, ExtractResult

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.post("/extract")
async def extract(req: ExtractRequest) -> ExtractResult:
    return ExtractResult(items=await extract_preferences(req.text))
```

`backend/app/main.py`：import 行加 `preferences`，注册 `app.include_router(preferences.router, prefix="/api")`。

- [ ] **Step 4: 确认通过 + 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: 偏好抽取端点 POST /api/preferences/extract——GLM(low) 过滤一次性需求" && git push
```

---

### Task 2: 对话注入偏好档案

**Files:**
- Modify: `backend/app/schemas/chat.py`（ChatRequest + profile）、`backend/app/agent/chat_graph.py`（State + 提示词）
- Test: `backend/tests/test_chat_graph.py` 追加 1 项

**Interfaces:**
- Produces: `ChatRequest.profile: list[str] = []`；系统提示词新增档案行（profile 非空时）。

- [ ] **Step 1: 写失败测试**（追加到 test_chat_graph.py）

```python
async def test_profile_injected_into_system_prompt():
    glm = FakeGLM([ToolRound(content=json.dumps({"reply": "好", "days": []}), tool_calls=[])])
    req = ChatRequest.model_validate(
        {"trip": TRIP_DATA, "message": "改一下", "profile": ["带5岁孩子出行", "  "]}
    )
    events = [e async for e in chat_turn(req, glm=glm, amap=FakeAMap(), checkpoint_db=None)]
    assert events[-1].type == "complete"
    system = glm.calls[0][0]["content"]
    assert "偏好档案" in system and "带5岁孩子出行" in system
```

- [ ] **Step 2: 确认失败**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_chat_graph.py::test_profile_injected_into_system_prompt -v`
Expected: FAIL（ChatRequest 无 profile 字段）

- [ ] **Step 3: 实现**

`schemas/chat.py` 的 ChatRequest 加：

```python
    profile: list[str] = Field(default_factory=list)  # 用户长期偏好档案（前端 localStorage）
```

`chat_graph.py`：`_system_prompt(trip, profile)`，规则第 4 条改为：

```python
4. 用户长期偏好档案（跨行程有效，优先级最高）：{"；".join(profile) if profile else "（无）"}。同时尊重本次行程的偏好：{trip.preferences or "（无记录）"}。
```

`ChatState` 加 `profile: list[str]`；`chat_turn` 里清洗后放入 initial state：

```python
    profile = [p.strip()[:30] for p in (req.profile or []) if p.strip()][:20]
```

（`_system_prompt(trip, profile)` 与 initial `"profile": profile` 同步更新。）

- [ ] **Step 4: 确认通过 + 全量回归 + 提交**

```bash
cd backend && .venv/Scripts/python -m pytest -q
git add -A && git commit -m "feat: 对话系统提示词注入用户长期偏好档案（ChatRequest.profile）" && git push
```

---

### Task 3: 前端 profile store + API helper

**Files:**
- Create: `frontend/src/stores/profile.ts`、`frontend/src/api/client.ts`、`frontend/src/api/preferences.ts`
- Test: `frontend/src/stores/stores.test.ts` 追加

**Interfaces:**
- Produces: `useProfileStore`（`items` / `addAll(items)` / `remove(i)`）；`postJson<T>(url, body)`；`extractPreferences(text): Promise<string[]>`（失败抛错，调用方吞）。

- [ ] **Step 1: 写失败测试**（追加到 stores.test.ts，beforeEach 已有 localStorage.clear）

```ts
describe('profile store', () => {
  it('addAll 去重/截断 30 字/上限 20 条并持久化', () => {
    const profile = useProfileStore()
    profile.addAll(['带娃', '带娃', '  不去网红店  ', ''])
    expect(profile.items).toEqual(['带娃', '不去网红店'])
    for (let i = 0; i < 25; i++) profile.addAll([`偏好${i}`])
    expect(profile.items.length).toBe(20)
    expect(JSON.parse(localStorage.getItem('travelmate.profile')!)).toHaveLength(20)
  })

  it('remove 删除单条', () => {
    const profile = useProfileStore()
    profile.addAll(['a', 'b'])
    profile.remove(0)
    expect(profile.items).toEqual(['b'])
    expect(JSON.parse(localStorage.getItem('travelmate.profile')!)).toEqual(['b'])
  })
})
```

（`x.trim().slice(0,30)` 后为空的丢弃——`''` 与 `'  '` 不入库，断言已覆盖。测试文件顶部补 `import { useProfileStore } from '@/stores/profile'`。）

- [ ] **Step 2: 确认失败 → Step 3: 实现**

`frontend/src/api/client.ts`：

```ts
export async function postJson<T>(url: string, body: unknown): Promise<T> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return (await resp.json()) as T
}
```

`frontend/src/stores/profile.ts`：

```ts
import { defineStore } from 'pinia'

const KEY = 'travelmate.profile'
const MAX_ITEMS = 20

function load(): string[] {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : []
  } catch {
    return []
  }
}

/** 用户长期偏好档案（跨行程），localStorage 持久化。 */
export const useProfileStore = defineStore('profile', {
  state: () => ({ items: load() }),
  actions: {
    persist() {
      localStorage.setItem(KEY, JSON.stringify(this.items))
    },
    /** 并入新偏好：trim/截断 30 字/精确去重，总量上限 20 条 */
    addAll(items: string[]) {
      for (const raw of items) {
        const text = String(raw ?? '').trim().slice(0, 30)
        if (text && !this.items.includes(text)) this.items.push(text)
      }
      this.items = this.items.slice(0, MAX_ITEMS)
      this.persist()
    },
    remove(index: number) {
      this.items.splice(index, 1)
      this.persist()
    },
  },
})
```

`frontend/src/api/preferences.ts`：

```ts
import { postJson } from '@/api/client'

/** 抽取长期偏好；网络/GLM 失败会抛错，调用方 fire-and-forget 时自行吞掉 */
export async function extractPreferences(text: string): Promise<string[]> {
  const r = await postJson<{ items: string[] }>('/api/preferences/extract', { text })
  return Array.isArray(r.items) ? r.items.filter((x): x is string => typeof x === 'string') : []
}
```

- [ ] **Step 4: 确认通过 + 提交**

```bash
cd frontend && npm test
git add -A && git commit -m "feat: 偏好档案 store（localStorage 去重持久化）与抽取 API helper" && git push
```

---

### Task 4: 生成页与对话接线

**Files:**
- Modify: `frontend/src/types/trip.ts`（ChatRequest + profile）、`frontend/src/views/HomeView.vue`、`frontend/src/components/ChatPanel.vue`
- Test: `npm test`（现有断言不破坏）+ `npm run build`

**Interfaces:**
- Consumes: `useProfileStore` / `extractPreferences`（Task 3）、`ChatRequest.profile`（Task 2）。

- [ ] **Step 1: types**——ChatRequest 加 `profile?: string[]`。

- [ ] **Step 2: HomeView**——script 增：

```ts
import { onMounted } from 'vue'
import { extractPreferences } from '@/api/preferences'
import { useProfileStore } from '@/stores/profile'

const profile = useProfileStore()

onMounted(() => {
  if (!form.preferences && profile.items.length) {
    form.preferences = profile.items.join('；')
  }
})
```

`submit()` 里、`generation.run(...)` 之前加（fire-and-forget）：

```ts
  if (form.preferences.trim()) {
    extractPreferences(form.preferences.trim())
      .then((items) => profile.addAll(items))
      .catch(() => {})
  }
```

模板：偏好 textarea 下方加档案标签（可删）：

```html
      <div v-if="profile.items.length" class="flex flex-wrap items-center gap-1.5">
        <span class="text-xs text-slate-400">记住的偏好：</span>
        <span
          v-for="(p, i) in profile.items"
          :key="p"
          class="flex items-center gap-1 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
        >
          {{ p }}
          <button type="button" class="text-slate-400 hover:text-red-500" @click="profile.remove(i)">×</button>
        </span>
      </div>
```

- [ ] **Step 3: ChatPanel**——script 增 `const profile = useProfileStore()`；send 的 body 加 `profile: profile.items`；`send()` 末尾（await done 之后、无条件）加：

```ts
  extractPreferences(draft.value.trim() || ' ')
    .then((items) => profile.addAll(items))
    .catch(() => {})
```

注意：`draft.value` 此时可能已被清空——在 `await done` 之前先把 `const message = draft.value.trim()` 存下来供抽取用（body 也复用该变量）。

- [ ] **Step 4: 确认通过 + 提交**

```bash
cd frontend && npm test && npm run build
git add -A && git commit -m "feat: 生成页偏好记忆预填与标签管理，对话注入档案并静默抽取" && git push
```

---

### Task 5: 端到端验收

- [ ] 重启后端（uvicorn 无热重载），health 检查。
- [ ] 浏览器实测三步：① 首页偏好框留「带 5 岁孩子，不去网红店」生成行程 → 提交后档案出现标签；② 回首页新建行程 → 偏好框已预填；③ 行程页聊天说「以后都不要网红店」→ 回复遵循 → 再开新行程页确认档案生长。
- [ ] `backend && pytest -q` + `frontend && npm test` 最终全绿，遗留修复一并提交推送。

## 已知问题

（空）
