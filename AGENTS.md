# AGENTS.md — TravelMate 智能旅行助手

面向真实用户的智能旅行助手（国内游）：自然语言 → GLM 流式生成逐日行程（含 AI 思考展示）→ 高德 POI 定位 → 地图可视化/编辑/预算/重规划/导出。MVP 已完成。

## 新会话必读

1. **交接文档：`docs/HANDOFF.md`** —— 项目状态、密钥状态、下一步候选、踩坑记录（必读）
2. 设计 spec（需求与架构的权威）：`docs/superpowers/specs/2026-09-06-travel-assistant-design.md`
3. 实施计划：`docs/superpowers/plans/`（backend-part1 / frontend-part2）

## 启动

- 一键：双击根目录 `start.bat`（幂等）；停止 `stop.bat`
- 后端 `backend/`：FastAPI :8000（venv 在 `backend/.venv`，测试 `.venv/Scripts/python -m pytest`）
- 前端 `frontend/`：Vue3+Vite :5173（`npm run dev`，`/api` 代理到 8000）
- 改 `.env` 后必须重启对应服务（Vite/uvicorn 都只在启动时读）

## 约定

- 技术栈：FastAPI + Pydantic v2（后端五层：api/agent/services/tools/schemas）；Vue3 + TS + Pinia + Tailwind v4（前端）
- 密钥只存 `.env`（已 gitignore），绝不入库、尽量不进对话
- 测试必须离线（GLM 用假对象注入、高德用 respx）；改动后跑全量测试再提交
- git：中文 conventional commits，完成即 commit + push；push 走本地代理 127.0.0.1:7897（已配置）
- 交接文档（HANDOFF.md / 待办速览）只在用户明确说「要开新窗口」时更新，平时任务完成只提交代码，别动交接文档
- 工作流：新功能先走 brainstorming → writing-plans（存 `docs/superpowers/plans/`）→ 内联实施（用户嫌 subagent 流程慢）
- Windows + Git Bash 踩坑清单见 `docs/HANDOFF.md` §7（curl 中文、bat 编码、GLM 思考无法关闭等）

## 当前待办速览（截至 2026-09-07）

- ✅ 前端地图 Key 已配置，地图联动已实测通过（含 Activity.id 缺失导致联动失效的修复）
- 候选：JSON 导入、分享、spec §3.2 演进路线 V2（Tool Calling，用户要求逐阶段推进不跳级）
