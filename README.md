# TravelMate 智能旅行助手

自然语言 → AI 逐日行程（智谱 GLM）→ 高德 POI 定位 → 地图可视化 / 预算 / 编辑 / 重规划 / 导出。

- 设计文档：`docs/superpowers/specs/2026-09-06-travel-assistant-design.md`
- 后端（FastAPI，端口 8000）：见 `backend/README.md`
- 前端（Vue 3，端口 5173）：见 `frontend/README.md`

## 快速开始

```bash
# 1. 后端
cd backend && cp .env.example .env   # 填入 GLM_API_KEY 与 AMAP_WEB_KEY（「Web服务」类型）
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# 2. 前端（新终端）
cd frontend && npm install
npm run dev   # http://localhost:5173
```

架构说明与演进路线（V1→V7）见设计文档。
