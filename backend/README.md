# TravelMate 后端

FastAPI + 智谱 GLM + 高德 Web Service。设计文档见 `../docs/superpowers/specs/2026-09-06-travel-assistant-design.md`。

## 本地启动

1. 申请密钥：[智谱 GLM](https://open.bigmodel.cn)（默认模型 glm-5.3-flash）、[高德 Web 服务 Key](https://console.amap.com)（类型选「Web服务」）
2. `cp .env.example .env` 并填入两个 Key
3. `python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"`
4. `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000`

## 测试

`.venv/Scripts/python -m pytest -v`（全部离线，无真实外部调用）

## API

- `GET  /api/health` — 健康检查 + Key 配置状态
- `POST /api/trips/generate` — 请求体 `{destination, days, startDate?, travelers?, budgetLimit?, preferences?}`，SSE 流（progress → complete/error）
- `POST /api/trips/replan` — 请求体 `{trip: <完整行程>, request: "自然语言调整"}`，SSE 流同上

## SSE 冒烟（配置好 Key 后）

```bash
curl -N -X POST http://localhost:8000/api/trips/generate \
  -H "Content-Type: application/json" \
  -d '{"destination":"重庆","days":2,"preferences":"带5岁孩子，不想太赶"}'
```
