# TravelMate 前端 MVP 实施计划（Part 2 / 共 2 部分）

> 执行方式：内联（controller 直接实施）。本计划给出文件结构、任务顺序、接口契约与验收标准；组件实现细节在实施时按 spec §6 落地。

**Goal:** Vue 3 SPA 把后端 API 变成可用产品——表单生成、SSE 进度、行程详情（时间线编辑 + 高德地图联动 + 预算面板）、自然语言重规划、导出、本地多行程管理。

**Architecture:** Vite SPA，`/api` 代理到 FastAPI:8000。SSE 用 fetch+ReadableStream 手写解析（POST 场景）。全部状态在 Pinia：`trips`（localStorage 持久化 + ≤5 版快照栈）、`currentTrip`（派生：按天路线点/预算汇总）、`generation`（连接与进度）。高德 JS API 懒加载进详情页，Key/安全密钥走 `VITE_` 环境变量，加载失败降级纯时间线。

**Tech Stack:** Vue 3 + Vite + TypeScript、Pinia、Vue Router、Tailwind CSS v4、@amap/amap-jsapi-loader、Vitest（registry 用 npmmirror）。

**Spec:** `docs/superpowers/specs/2026-09-06-travel-assistant-design.md` §4/§5.2/§6

## Global Constraints

- 类型与后端 schema 逐字对齐（camelCase wire 格式：`startDate`/`budgetLimit`/`startTime`/`amapPoiId`/`resolved`）
- SSE 事件：`data: {json}\n\n`，`type: progress|complete|error`；错误码 `GLM_ERROR|VALIDATION_FAILED|SCOPE_EMPTY|INTERNAL`
- 坐标只消费不生产；`resolved=false` 的活动不上地图
- Key 不入库：`.env` gitignore，只提交 `.env.example`
- 编辑只改 store，地图/预算响应式联动；导出 PDF 用打印样式 + `window.print()`

## 文件结构（frontend/）

```
src/
├── api/sse.ts              # postSSE(url, body, onEvent, signal)
├── types/trip.ts           # Trip/Day/Activity/Location/Travelers/GenerateRequest/事件类型
├── stores/
│   ├── trips.ts            # 列表 CRUD + localStorage + 快照栈(≤5) + undo
│   ├── currentTrip.ts      # 当前 Trip + getters: budgetTotal/budgetByType/dayRoutePoints
│   └── generation.ts       # phase(idle|running|done|error) + events[] + error + run()
├── views/
│   ├── HomeView.vue        # 行程表单
│   ├── GeneratingView.vue  # SSE 进度页
│   ├── TripDetailView.vue  # 详情（时间线+地图+预算+重规划+导出）
│   └── MyTripsView.vue     # 行程列表
├── components/
│   ├── DayTimeline.vue     # 逐日活动列表（编辑/增删/拖拽排序）
│   ├── ActivityCard.vue    # 单活动卡片（行内编辑）
│   ├── ReplanBox.vue       # 自然语言重规划输入 + 进度
│   ├── AMapView.vue        # 高德地图封装
│   └── BudgetPanel.vue     # 预算汇总
├── router/index.ts
├── App.vue                 # 导航壳 + 路由出口
└── main.ts
```

## 任务与验收

| 任务 | 内容 | 验收 |
|---|---|---|
| F1 脚手架 | Vite vue-ts + Tailwind v4 + Pinia + Router + `.npmrc`(npmmirror) + vite proxy `/api`→8000 + types + `.env.example` | `npm run dev` 启动无错；`npm run build` 通过 |
| F2 SSE 客户端 | `postSSE`：fetch 流读取、跨 chunk 缓冲、`\n\n` 分帧、AbortController；Vitest 覆盖分块边界/多事件一帧/服务端断流 | vitest 全绿 |
| F3 stores | trips(localStorage CRUD+快照undo)、currentTrip(预算派生)、generation(run→事件流)；Vitest 覆盖预算计算/快照撤销/持久化 | vitest 全绿 |
| F4 生成流程 | HomeView 表单（校验目的地/天数）→ generation.run → GeneratingView 阶段进度 → complete 落库跳详情 | 手测：真实生成→落库→跳转 |
| F5 时间线 | DayTabs + 活动卡片行内编辑/增删/HTML5 拖拽排序 + ReplanBox（SSE 进度+替换+可撤销） | 手测编辑与重规划 |
| F6 地图 | AMapView：loader 初始化(securityCode)、按类型着色 Marker、按天折线、卡片↔Marker 双向高亮、无 Key/加载失败降级提示 | 手测联动；无 Key 降级可见 |
| F7 预算+导出 | BudgetPanel 分类汇总+超预算警告+实时重算；导出打印样式 `window.print()`；JSON Blob 下载 | 手测导出 |
| F8 收尾 | MyTripsView 列表/打开/复制/删除 + App 导航 + README + 构建验证 + 端到端手测（生成→编辑→重规划→导出→撤销） | `npm run build` 通过；全流程手测通过 |

## 已知风险

- 高德 JS API 需要 Key+安全密钥；未配置时地图区显示引导提示（不阻断时间线）
- Windows curl 中文编码问题已踩过——前端 fetch 无此问题
- 拖拽用原生 HTML5 DnD，不引库（YAGNI）
