# 智能旅行助手（TravelMate）设计文档

日期：2026-09-06
状态：已定稿（含用户 6 条调整意见）

## 1. 项目概述

面向真实用户的智能旅行助手 Web 产品，服务**国内游**场景。用户用自然语言描述旅行需求，系统通过智谱 GLM 生成结构化逐日行程，在高德地图上可视化，支持编辑、预算计算、自然语言重规划和导出。

**核心理念**：AI 负责"想去哪里"，地图 API 负责"它在哪里"。LLM 只产出意图和名称，所有地理事实（坐标、POI、路线）一律来自高德。

**成功标准（MVP）**：
- 输入"重庆 3 天 2 晚，带 5 岁孩子，预算 5000"，60 秒内得到可编辑、地图可视、预算清晰的行程
- 自然语言重规划（"不想去长江索道，别太赶"）只影响指定的天，其他天不动
- 可导出可用 PDF

## 2. 范围

### 2.1 MVP 包含
- AI 行程生成（GLM 结构化输出 + 高德 POI 富化）
- 地图可视化（高德 JS API，Marker + 按天路线）
- 行程编辑（增删改活动、拖拽排序、时段与费用调整）
- 预算面板（前端响应式实时汇总）
- 自然语言重规划（手写 pipeline，限定受影响的天）
- 导出（PDF 打印样式 + JSON）
- 免登录，行程存 localStorage（含最近 5 个版本快照，支持撤销重规划）

### 2.2 明确不做（防蔓延）
用户账号/云同步、机票酒店实时比价、跨城多日路线优化、多人协作、小程序、境外游数据优化、语音输入、JSON 导入、图片导出。

## 3. 总体架构

```
                    ┌──────────────┐
                    │   Vue 3 SPA  │
                    │  Pinia /     │
                    │  Tailwind /  │
                    │  AMap JS API │
                    └───────┬──────┘
                            │ REST / SSE (POST + fetch ReadableStream)
                            ▼
               ┌─────────────────────────┐
               │        FastAPI          │
               │      API Layer          │
               └──────────┬──────────────┘
                          ▼
               ┌─────────────────────────┐
               │      Agent Layer        │
               │  Planner / Validator /  │
               │  Replanner              │
               └──────────┬──────────────┘
          ┌───────────────┼────────────────┐
          ▼               ▼                ▼
     GLM Service      Tool Layer       Trip JSON
          │          (POI搜索/地理编码/      │
          ▼           路线/预算)            ▼
      智谱 GLM           │            localStorage
                         ▼
                     高德 Web Service API
```

### 3.1 关键约束
- **GLM API Key 只存在于后端**，通过环境变量注入；前端只持有高德 JS API Key（绑定域名白名单）
- 高德需要两个 Key：**JS API Key**（前端地图，2021-12 后需配套 securityJsCode 安全密钥）、**Web Service Key**（后端 POI 搜索/地理编码/路线）
- LLM 永远不输出经纬度；坐标由后端 POI 富化步骤从高德获取（GCJ-02 坐标系）

### 3.2 演进路线（刻意分阶段，每阶段回答"为什么需要它"）

| 阶段 | 内容 | 动机 |
|---|---|---|
| **V1（本项目 MVP）** | FastAPI + GLM 结构化输出 + 高德 POI 富化 + 确定性校验 + 手写重规划 | 先跑通价值闭环，理解 Agent 的本质是"感知→决策→行动→检查→再决策" |
| V2 | Tool Calling | 把 Tool Layer 暴露给 GLM，让模型自主决定调什么 |
| V3 | Agent Loop（自研） | 显式的循环控制：校验不过带着反馈重试 |
| V4 | LangGraph | 把手写 loop 迁到图运行时，获得检查点/恢复/可视化 |
| V5 | MCP | 把 Tool Layer 封装成 MCP Server，被其他客户端复用 |
| V6 | Memory / 用户偏好档案 | 跨行程记住"带娃出行、不去网红店" |
| V7 | Multi-Agent | 仅当真有必要 |

V1 的 Agent Layer 接口按 V2-V5 的形状设计：Planner/Replanner 是编排函数，Tool Layer 是纯函数（`search_poi` / `geocode` / `calculate_route` / `calculate_budget`），V2 时同一批函数包装成 GLM tool 定义即可，不需要重构。

## 4. 数据模型（Pydantic / TypeScript 双端对齐）

```jsonc
// Trip
{
  "id": "uuid",                    // 前端生成
  "title": "重庆 3 日亲子游",
  "destination": "重庆",           // 高德城市名，POI 搜索的 city 参数
  "startDate": "2026-10-01",      // 可空
  "travelers": { "adults": 2, "children": 1 },
  "budgetLimit": 5000,             // 用户设定，可空
  "days": [ /* Day[] */ ],
  "version": 3                     // 每次重规划 +1，配合撤销
}

// Day
{
  "title": "解放碑-洪崖洞城市漫游",
  "activities": [ /* Activity[] */ ]
}

// Activity
{
  "id": "uuid",
  "name": "洪崖洞民俗风貌区",
  "type": "attraction",            // attraction|meal|transport|hotel|shopping
  "startTime": "09:30",            // 可空；meal/attraction 尽量有
  "endTime": "12:00",
  "cost": 120,                     // 预估人均费用，可空
  "notes": "记得提前预约",
  "location": {
    "name": "洪崖洞民俗风貌区",     // 高德 POI 富化后的规范名
    "address": "重庆市渝中区嘉陵江滨江路88号",
    "longitude": 106.578,          // GCJ-02，仅来自高德，LLM 不产出
    "latitude": 29.562,
    "amapPoiId": "B00156xxxx",
    "resolved": true               // false = POI 搜索失败，地图上不画点
  }
}
```

**POI 解析失败策略**：`resolved=false` 的活动正常出现在时间线中（带"未定位"标记），不参与地图 Marker 和路线，不阻断整体生成。未解析比例超过 30% 时 Validator 判定失败、触发重试。

## 5. 后端设计（FastAPI）

### 5.1 目录结构（分层，为 V2-V5 预留位置）

```
backend/
├── app/
│   ├── api/                  # API Layer
│   │   ├── trips.py          # generate / replan（SSE 流式）
│   │   └── health.py
│   ├── agent/                # Agent Layer
│   │   ├── planner.py        # 生成 pipeline 编排
│   │   ├── replanner.py      # 重规划 pipeline 编排
│   │   └── validator.py      # 确定性校验
│   ├── services/             # Service Layer
│   │   ├── glm.py            # GLM 客户端（chat、JSON mode、重试）
│   │   └── amap.py           # 高德 Web Service 客户端
│   ├── tools/                # Tool Layer（纯函数）
│   │   ├── search_poi.py
│   │   ├── geocode.py
│   │   ├── route.py
│   │   └── budget.py
│   ├── schemas/              # Schema Layer（Pydantic）
│   │   ├── trip.py / generate.py / replan.py / events.py
│   ├── core/                 # 配置（pydantic-settings）、日志
│   └── main.py
├── tests/
└── pyproject.toml
```

### 5.2 API 契约

**`POST /api/trips/generate`** → SSE 流
```jsonc
// 请求
{ "destination": "重庆", "days": 3, "startDate": "2026-10-01",
  "travelers": {"adults": 2, "children": 1},
  "budgetLimit": 5000, "preferences": "带5岁孩子，不想太赶，喜欢夜景" }

// SSE 事件流（data: 行，每行一个 JSON）
data: {"type":"progress","stage":"analyze","message":"正在分析旅行需求"}
data: {"type":"thinking","content":"用户想去重庆，带孩子的话节奏要放慢……"}
data: {"type":"progress","stage":"plan","message":"正在规划第 1 天"}
data: {"type":"progress","stage":"enrich","message":"正在定位景点（8/12）"}
data: {"type":"complete","trip":{...}}
data: {"type":"error","code":"GLM_INVALID_OUTPUT","message":"..."}
```

`thinking` 事件：GLM 开启思考模式后流式输出的推理过程增量文本（`reasoning_content` delta），前端累积展示为可折叠的「AI 思考过程」面板。thinking 增量不属于结构化结果，校验与错误处理均不依赖它。

**`POST /api/trips/replan`** → SSE 流（同样的事件格式）
```jsonc
// 请求：整个当前行程 + 自然语言修改请求
{ "trip": { /* 当前 Trip 全量 JSON */ },
  "request": "第一天别太赶，而且不想去长江索道" }
```

**`GET /api/health`** → `{"status":"ok"}`

> 为什么用 POST + fetch 流而不是 EventSource：浏览器原生 EventSource 只支持 GET，带不下全量 Trip 请求体。前端用 `fetch()` + `ReadableStream` 手写解析 `data:` 行（几十行代码，不引依赖）。

### 5.3 生成 pipeline（planner.py）

```
1. analyze   组装 Prompt（目的地/天数/人群/预算/偏好）→ GLM 结构化输出行程草稿（只有名称/类型/时段/费用/备注，无坐标）
2. enrich    并发遍历 activities → tools/search_poi(city=destination, keyword=name)
             → 命中：写回规范名/地址/GCJ-02 坐标/amapPoiId，resolved=true
             → 多结果时取第一个（高德已按相关度排序，MVP 不做人工消歧）
             → 未命中：resolved=false（每个活动都推 progress 事件）
3. validate  validator.py 确定性校验（见 5.5）
4. retry     校验失败 → 带具体问题清单重试 GLM（最多 2 次）
5. complete  返回 Trip JSON
```

### 5.4 重规划 pipeline（replanner.py）

```
1. scope     GLM 分析：当前 Trip + 用户请求 → 受影响的天（结构化输出 affectedDayIndexes）
2. replan    对每个受影响的天：携带"保留的天 + 用户约束（不去XX、别太赶）+ 原天内容"重新生成
3. enrich    同生成的 POI 富化
4. validate  校验受影响的天 + 整体预算
5. complete  返回完整 Trip（仅替换受影响的天，version+1；前端保存旧版本快照供撤销）
```

### 5.5 Validator 确定性规则（validator.py，不经过 LLM）

| 规则 | 级别 | 处理 |
|---|---|---|
| 同一天 activities 时段重叠 | fail | 触发重试 |
| 未解析 POI 比例 > 30% | fail | 触发重试 |
| 相邻活动直线距离 > 50km（市内游不合理） | warn | 附到响应，前端展示 |
| 总费用 > budgetLimit | warn | 附到响应，前端展示 |

### 5.6 GLM 调用

- 模型：`glm-5.3-flash`（环境变量可配），开启 JSON 输出模式；response_format 不满足时降级为 Prompt 强约束 + 提取 JSON
- **流式 + 思考模式**：`stream=true` + `thinking={"type":"enabled"}`，推理过程（`delta.reasoning_content`）以 `thinking` SSE 事件实时透传给前端，最终 JSON 内容（`delta.content`）在流结束后解析
- 超时 120s；Pydantic 校验失败自动重试（含错误反馈，最多 2 次）
- 并发富化用 `asyncio.gather` + 信号量（并发 5），高德限流超限则退避重试

## 6. 前端设计（Vue 3）

- 栈：Vue 3 + Vite + TypeScript + Pinia + Vue Router + Tailwind CSS
- 地图：`@amap/amap-jsapi-loader`，JS Key + securityJsCode 走 `VITE_` 环境变量

### 6.1 页面

1. **首页**：行程表单（目的地、天数、日期、人数、预算、偏好标签 + 自由文本）→ 提交进入生成页
2. **生成页**：SSE 进度展示（阶段 + 消息 + day 计数），完成自动跳转行程详情
3. **行程详情页**（核心）：
   - 左侧：逐日 Tab + 时间线；活动卡片可编辑（名称/时段/费用/备注）、增删、拖拽排序；顶部"调整行程"输入框（自然语言重规划入口）
   - 右侧：高德地图（Marker 按类型着色，按天折线，点击时间线卡片地图定位、点击 Marker 高亮卡片）
   - 底部/侧边：预算面板（分类汇总 + 超预算警告 + 手改费用实时重算）
   - 工具栏：导出 PDF（打印样式 + `window.print()`）、导出 JSON、撤销上次重规划
4. **我的行程**：localStorage 行程列表，打开/复制/删除

### 6.2 状态管理（Pinia）

- `trips` store：行程列表 CRUD + localStorage 持久化 + 版本快照栈（保留最近 5 版，撤销重规划）
- `currentTrip` store：当前行程 + 派生计算（按天路线点、预算汇总）；所有编辑只改 store，地图/预算响应式联动
- `generation` store：SSE 连接状态、进度消息、错误

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| GLM 输出不合法 JSON | Pydantic 校验失败 → 带反馈重试 2 次 → SSE `error` 事件，前端提示可重试 |
| 生成超时（>120s） | SSE error 事件；前端不落任何半截数据 |
| fetch 流中断 | 前端捕获并提示，已生成进度作废 |
| 高德配额/网络失败 | 活动降级 `resolved=false`，功能不中断；全失败时提示纯列表模式 |
| 地图 JS 加载失败 | 降级为纯时间线视图 + 顶部提示 |

## 8. 配置与密钥

```bash
# backend/.env
GLM_API_KEY=xxx
GLM_MODEL=glm-4.6
AMAP_WEB_KEY=xxx          # Web Service：POI 搜索/地理编码/路线

# frontend/.env
VITE_AMAP_JS_KEY=xxx      # JS API：前端地图
VITE_AMAP_SECURITY_CODE=xxx
```

`.env` 加入 `.gitignore`，仓库提供 `.env.example`。

## 9. 测试策略

- **后端 pytest（异步）**：
  - schemas：Trip/Day/Activity 校验、非法输入拒绝
  - validator：每条确定性规则的正反例
  - planner/replanner：mock GLM Service + mock AMap Service，验证 pipeline 编排、重试、失败传播
  - api：httpx AsyncClient 直连 ASGI app，断言 SSE 事件序列格式
- **前端 Vitest**：
  - SSE 流解析器（分块边界、跨 chunk 事件）
  - Pinia store：预算重算、编辑联动、快照撤销
  - 关键组件：BudgetPanel、DayTimeline 编辑操作

## 10. 仓库结构

```
智能旅行助手/
├── frontend/          # Vue 3 SPA
├── backend/           # FastAPI
├── docs/superpowers/specs/
└── README.md
```

前后端独立开发服务器（Vite :5173 / uvicorn :8000），前端 dev proxy `/api` → 后端；部署时同域反代。
