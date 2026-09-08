# 外部数据接入（POI 详情 + 天气）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **本项目约定：内联执行（不派 subagent）。**

**Goal:** 给 agent 新增两个真数据工具：`poi_detail`（place/detail：营业时间/评分/人均，修"知识时效"）、`weather`（weatherInfo：目的地未来 3 天预报，免费独立配额）。生成与对话两链路同时可用，SSE/前端零改动。

**Architecture:** amap.py 新增 `poi_detail`/`weather_forecast`/`resolve_admin`（城市归一化升级为 city+adcode，天气接口需要 adcode，坪山→深圳市/440300）；`chat_tools.build_tools` 注册新工具；ToolExecutor 新分支——`poi_detail` 计定位配额，`weather` 不计（独立免费配额）、adcode 由执行器注入；详情字段缺失不编造（剔除空字段回传）。提示词各加一句引导（用不用由模型自主）。

**Tech Stack:** 既有栈，无新依赖。高德 v3 place/detail 与 weather/weatherInfo(extensions=all)。

**Spec:** 2026-09-07 会话用户选定范围（POI 详情 + 天气；周边搜索与点评类不做）。

## Global Constraints

- 测试离线（respx + Fake 注入）；中文 conventional commits；每任务 commit + push。
- 详情/天气失败一律编码为 `{"error": ...}` 回传模型；空字段剔除，绝不诱导编造。
- `weather` 不消耗定位配额；`poi_detail` 计入。

---

### Task 1: amap 服务层

**Files:** Modify `backend/app/services/amap.py`；Test `backend/tests/test_amap_service.py`

**Interfaces (Produces):**
- `async def resolve_admin(name) -> dict`：`{"city": 标准城市名, "adcode": 行政区划码}`，失败回退 `{"city": 原名, "adcode": ""}`；`resolve_city` 改为从它取 city。
- `async def poi_detail(poi_id) -> dict | None`：`{name,type,address,opentime,rating,cost}`（缺失字段为空串），查不到/HTTP 失败 → None。
- `async def weather_forecast(adcode) -> list[dict]`：`[{date,dayweather,nightweather,daytemp,nighttemp}]`；API 错误抛 AMapError。

- [ ] Step 1 写失败测试（respx：place/detail 正常/空、weather 正常/异常、resolve_admin 正常）；Step 2 确认红；Step 3 实现；Step 4 绿；Step 5 `pytest -q` 全量 + commit `feat: amap 新增 POI 详情/天气查询与 resolve_admin（city+adcode）`。

### Task 2: 工具注册与执行

**Files:** Modify `backend/app/agent/chat_tools.py`；Test `backend/tests/test_chat_tools.py`

**Interfaces:**
- `build_tools()` 增 `poi_detail`/`weather` 定义。
- `ToolExecutor`：`_admin()` 缓存（`{"city","adcode"}`，异常回退原名）；`poi_detail` 分支（计配额、剔除空字段）；`weather` 分支（不计配额、无 adcode 报错）。
- FakeAMap（3 个测试文件）的 `resolve_city` stub 替换为 `resolve_admin` stub，并补 `poi_detail`/`weather_forecast` stub。

- [ ] Step 1 失败测试：`test_poi_detail_tool_returns_details`（含空字段剔除）、`test_poi_detail_missing_returns_error`、`test_weather_tool_returns_forecast_without_consuming_quota`、`test_weather_without_adcode_returns_error`；Step 2 红；Step 3 实现；Step 4 绿；Step 5 全量 + commit `feat: agent 新增 poi_detail 与 weather 工具（详情计配额，天气免费）`。

### Task 3: 提示词引导 + 回归 + 端到端

**Files:** Modify `backend/app/agent/generation_graph.py`（规则加一条）、`backend/app/agent/chat_graph.py`（规则 1 扩一句）

- [ ] Step 1 两处提示词更新；Step 2 全量回归；Step 3 重启后端；Step 4 浏览器实测：行程页对话问「深圳未来三天天气」→ 观察调用 weather → 真实预报回复；Step 5 commit `feat: 生成/对话提示词引导使用详情与天气工具` + push。

## 已知问题

（空）
