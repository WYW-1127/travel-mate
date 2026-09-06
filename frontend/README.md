# TravelMate 前端

Vue 3 + Vite + TypeScript + Pinia + Tailwind CSS v4 + 高德 JS API。

## 启动

1. `npm install`（已配置 npmmirror 镜像）
2. 地图（可选）：`cp .env.example .env` 并填入高德「Web端(JS API)」Key 与安全密钥；不填则地图降级为提示，时间线功能不受影响
3. `npm run dev` → http://localhost:5173 （`/api` 已代理到本地 8000 后端，需先启动 backend）
4. 测试：`npm test`；构建：`npm run build`

## 页面

- `/` 规划表单 → `/generating` SSE 进度 → `/trips/:id` 行程详情（时间线编辑/地图/预算/重规划/导出）→ `/trips` 我的行程
