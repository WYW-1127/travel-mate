# 智能旅行助手（TravelMate）实施计划

日期：2026-09-06
依据：[设计文档](../specs/2026-09-06-travel-assistant-design.md)（已确认）

## 总则

- 按 Milestone 推进，每个 Milestone 结束时：测试通过 → git commit（必要时 push）
- 环境：Python 3.11（pip + venv）、Node 22（npm）、Windows / Git Bash
- API Key 缺失不得阻塞开发：所有外部调用（GLM/高德）在测试中以 mock 替代；`.env.example` 提供模板；Key 由用户事后填入
- 分支策略：直接在 main 上开发（单人项目），每个 Milestone 一个 commit

## M1 后端地基
- `backend/pyproject.toml`（fastapi、uvicorn、httpx、pydantic、pydantic-settings；dev: pytest、pytest-asyncio、respx）
- `app/core/config.py`：pydantic-settings 读取 `.env`（GLM_API_KEY/GLM_MODEL/AMAP_WEB_KEY）
- `app/main.py`：FastAPI 实例 + CORS（放行 Vite dev 端口）+ 路由注册
- `app/api/health.py`：`GET /api/health`
- 依赖安装 `pip install -e ".[dev]"`，跑通第一个测试
- ✅ 验收：pytest 通过；`uvicorn` 可启动，health 返回 ok

## M2 Schema 层（schemas/）
- `trip.py`：Location（resolved 标记）、Activity（type 枚举/时段/费用）、Day、Trip（version）
- `generate.py`：GenerateRequest（destination/days/startDate/travelers/budgetLimit/preferences）
- `replan.py`：ReplanRequest（trip 全量 + request 文本）
- `events.py`：SSE 事件模型（progress: stage+message / complete: trip / error: code+message）
- 测试：合法 Trip 通过；缺字段/错类型/坐标越界被拒
- ✅ 验收：schema 测试全绿

## M3 Service + Tool 层（services/、tools/）
- `services/glm.py`：httpx 调 GLM chat completions（OpenAI 兼容端点），JSON 输出模式 + 降级提取（剥 markdown 代码栅栏）；超时 120s；`chat_json()` 返回 dict
- `services/amap.py`：POI 文本搜索（place/text，citylimit）、地理编码、驾车路线；status!=1 抛错；结果截取字段
- `tools/`：`search_poi(city, keyword)`、`geocode(addr)`、`route_time(lng1,lat1,lng2,lat2)`、`haversine_km()` + `budget.py` 汇总
- 测试：respx mock 高德 HTTP（成功/失败/空结果）；GLM JSON 提取（纯净 JSON / 带栅栏 / 非法）
- ✅ 验收：service/tool 测试全绿，外部零真实调用

## M4 Agent 层（agent/）
- `validator.py`：时段重叠（fail）、未解析比例>30%（fail）、相邻距离>50km（warn）、超预算（warn）→ 返回 `ValidationResult(fail_reasons, warnings)`
- `planner.py`：analyze（GLM 草稿）→ enrich（asyncio.gather + 信号量5，逐活动 progress 事件）→ validate → 失败带反馈重试（≤2 次）；async generator 或 emit 回调产出进度
- `replanner.py`：GLM 分析 affectedDayIndexes → 逐天重生成（携带保留天+用户约束）→ enrich → validate → 合成新 Trip（version+1）
- Prompt 模板集中管理（`agent/prompts.py`），明确要求模型**不输出坐标**
- 测试：monkeypatch GLMService/AMapService，验证编排顺序、重试触发、富化降级（resolved=false）、重规划只替换受影响天
- ✅ 验收：agent 测试全绿

## M5 API 层（api/trips.py）
- `POST /api/trips/generate`：StreamingResponse(text/event-stream)，包装 planner 的进度为 `data: {...}\n\n`；错误→error 事件而非 500
- `POST /api/trips/replan`：同上
- Key 未配置时返回明确 error 事件（提示填 .env）
- 测试：httpx AsyncClient + ASGI，断言事件序列（progress…→complete）与 content-type
- ✅ 验收：api 测试全绿；curl 手测可见流式输出

## M6 前端地基（frontend/）
- `npm create vite`（vue-ts）+ Pinia + Vue Router + Tailwind CSS v4
- 目录：`src/{api,stores,views,components,types,utils}`
- `types/trip.ts` 与后端 schema 对齐
- vite.config：`/api` proxy → `http://localhost:8000`
- ✅ 验收：dev server 启动，路由骨架可导航

## M7 前端核心数据层 + 生成流程
- `api/sse.ts`：fetch + ReadableStream 解析（跨 chunk 缓冲、`\n\n` 分帧）；AbortController 支持取消
- `stores/generation.ts`：连接状态/进度/错误
- `stores/trips.ts`：localStorage 持久化 CRUD + 快照栈（≤5 版）
- `stores/currentTrip.ts`：当前行程 + 派生（按天路线点、预算汇总）
- `views/HomeView.vue`：行程表单（校验：目的地/天数必填）→ 提交跳生成页
- `views/GeneratingView.vue`：进度阶段可视化，complete→落库跳详情
- 测试：SSE 解析器（分块边界）、trips store（持久化/快照撤销）、预算计算
- ✅ 验收：vitest 全绿；mock 后端下完整走通表单→生成→详情

## M8 行程详情页（核心交互）
- 左栏 DayTabs + DayTimeline：活动卡片编辑（名称/时段/费用/备注/类型）、增删、拖拽排序；"调整行程"输入框触发 replan（SSE 进度 + 完成替换 + 快照可撤销）
- 右栏 AMapView：`@amap/amap-jsapi-loader`；Marker 按类型配色、按天折线；卡片↔Marker 双向联动；resolved=false 不上图；地图加载失败降级提示
- BudgetPanel：分类汇总、超预算警告、手改实时重算（computed）
- 导出：打印样式 + `window.print()`；JSON Blob 下载
- 测试：BudgetPanel 渲染与联动、时间线编辑操作
- ✅ 验收：详情页全功能可用（高德 Key 未配时地图区显示引导提示，其余不阻断）

## M9 收尾
- `views/MyTripsView.vue`：列表/打开/复制/删除
- 根 README（项目介绍/架构图/本地启动步骤/Key 申请指引）
- `.gitignore`（.env、node_modules、dist、__pycache__ 等）+ 两端 `.env.example`
- 全量测试回归；启动两端做端到端手测（无 Key 路径 + 有 Key 路径说明）
- ✅ 验收：克隆即跑；push GitHub

## 风险与对策
| 风险 | 对策 |
|---|---|
| GLM JSON 模式不稳 | 已有降级提取 + 重试（M3/M4） |
| 高德 Key 未申请 | 前后端均有无 Key 降级路径，不阻塞演示 |
| 高德 POI 搜不到 LLM 给的名字 | resolved=false 降级 + Validator 比例熔断重试 |
| SSE 在代理/开发环境下缓冲 | X-Accel-Buffering: no 头 + 本地直连开发 |
