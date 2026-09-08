# 生成任务持久化（修"刷新丢行程"）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent）。**

**Goal:** 生成中刷新/关闭页面不再丢行程。生成图在后台任务里跑完（与 SSE 连接解耦），事件缓冲在内存任务中；前端提交时记录生成标记（localStorage），页面恢复后凭标记重放事件流拿回完整结果。

**Architecture:** 新增 `services/gen_jobs.py`：`GenJob`（事件缓冲 + 订阅队列 + 状态）与 `GenJobManager`（模块级单例，`start/get/cancel`，容量 30）。`POST /api/trips/generate` 变为"启动任务 + 订阅"：请求体新增可选 `request_id`（前端 UUID，作为 thread_id `gen:{request_id}`），端点返回的 SSE 是对任务事件流的订阅（首次订阅=全量重放+实时，断线重连同一路径）。新增 `POST /api/trips/gen-jobs/{request_id}/replay`（重放）与 `/cancel`（取消并释放配额）。前端：HomeView 提交前写标记；GeneratingView 挂载时若无进行中任务但有新鲜标记（≤15 分钟）则重放重连；完成/失败/取消时清标记。

**Tech Stack:** 既有栈；任务注册表为进程内内存（单 worker，重启即清——标记新鲜窗口兜底）。

**Spec:** 2026-09-07 会话用户确认修复（方向：结果落待领取暂存 + 前端断线重取）。

## Global Constraints

- SSE 事件协议、事件顺序、complete/error 语义不变；重放=按缓冲顺序全量重发（前端 store 先 reset 再收，幂等）。
- 测试离线；中文 conventional commits；每任务 commit + push。
- 用户点「取消，返回」必须真正取消后台任务（释放 GLM/配额），并清理标记。
- 只改生成链路；对话/重规划不接任务化。

---

### Task 1: GenJob 与 GenJobManager

**Files:** Create `backend/app/services/gen_jobs.py`；Modify `backend/app/schemas/generate.py`（+`request_id`）；Test `backend/tests/test_gen_jobs.py`

**Interfaces (Produces):**
- `class GenJob`：`thread_id/status(running|done|error|cancelled)/events`；`publish(ev)`；`subscribe() -> AsyncIterator[StreamEvent]`（先重放缓冲，再实时跟随，遇 complete/error 结束）。
- `class GenJobManager`：`start(req, glm, amap) -> GenJob`（create_task 跑 `generate_trip`，thread=`gen:{request_id or uuid}`，容量 30 淘汰最旧）；`get(request_id) -> GenJob | None`；`cancel(request_id) -> bool`（取消任务并发布 error(CANCELLED)）。
- 模块级单例 `gen_jobs`。
- `GenerateRequest.request_id: str | None = None`。

- [ ] **Step 1 写失败测试** `tests/test_gen_jobs.py`：FakeGLM（复用 chat_with_tools 脚本模式）+ FakeAMap；用例：① start→收齐 progress/thinking/complete 且任务状态 done、行程含 id；② replay 语义——同一 job 二次 subscribe 重放全部事件；③ cancel→后续 subscribe 收到 error(CANCELLED)；④ get 未知 id 返回 None。

- [ ] **Step 2 红 → Step 3 实现 → Step 4 绿**（`pytest tests/test_gen_jobs.py -v`）→ **Step 5** `pytest -q` + commit `feat: 生成任务后台化——GenJob 事件缓冲与订阅（断线可重放）`。

### Task 2: API 端点改造

**Files:** Modify `backend/app/api/trips.py`（generate 走 gen_jobs；新增 replay/cancel）；Test `backend/tests/test_api_trips.py`（stub 目标改 gen_jobs）、`backend/tests/test_gen_jobs.py` 或新 api 级用例

**Interfaces:**
- `POST /api/trips/generate`：SSE = `gen_jobs.start(req, …).subscribe()`。
- `POST /api/trips/gen-jobs/{rid}/replay`：未知 rid → 404 JSON `{"detail":"生成任务不存在或已过期"}`；已知 → 重放 SSE。
- `POST /api/trips/gen-jobs/{rid}/cancel`：200 `{"ok":true}`（未知 rid 也 200 幂等）。
- wiring：`from app.services.gen_jobs import gen_jobs`。

- [ ] Step 1 失败测试（stub gen_jobs：start 返回假 job、replay 流 complete、cancel 200、未知 replay 404、wiring 源码检查）→ Step 2 红 → Step 3 实现 → Step 4 绿 → Step 5 全量 + commit `feat: 生成端点任务化——新增 replay/cancel，刷新页面可领回结果`。

### Task 3: 前端标记与断线重连

**Files:** Create `frontend/src/utils/genMarker.ts`；Modify `frontend/src/views/HomeView.vue`、`frontend/src/views/GeneratingView.vue`、`frontend/src/types/trip.ts`（GenerateRequest + requestId）；Test `frontend/src/utils/genMarker.test.ts`

- [ ] Step 1 genMarker：`saveGenMarker(id)/loadGenMarker()（≤15 分钟有效）/clearGenMarker()` + 测试（红→绿）。
- [ ] Step 2 HomeView：submit 生成 `request_id=crypto.randomUUID()` + `saveGenMarker` + body 带 `request_id`。
- [ ] Step 3 GeneratingView：挂载时 phase=idle 且有新鲜标记 → `generation.run('/api/trips/gen-jobs/{id}/replay', {})` 重放重连；done 落地后与 error、backHome（调 cancel + 清标记）时清标记。
- [ ] Step 4 `npm test && npm run build` → commit `feat: 生成断线重连——刷新/关闭页面后凭标记领回行程`。

### Task 4: 端到端验收

- [ ] 重启后端 → 浏览器生成（深圳 1 天快速档）→ **生成中刷新页面** → 自动重放并落地行程详情页（不丢）。
- [ ] 生成中点「取消，返回」→ 确认后台任务取消（再次 replay 得 CANCELLED error）。
- [ ] 全量回归最后跑一遍，遗留修复一并提交推送。

## 已知问题

- LangGraph 检查点反序列化警告（`LANGGRAPH_STRICT_MSGPACK` 未来将阻止未注册类型）——低优先级，待 langgraph 升级时统一处理。
