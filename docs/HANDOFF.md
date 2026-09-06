# TravelMate 交接文档（HANDOFF）

> 写给下一个会话/新接手的开发者。先读根目录 `AGENTS.md`，再读本文档。

**交接日期**：2026-09-06
**状态**：MVP 全功能完成并推送到 GitHub，无未提交代码，无进行中的半成品。

---

## 1. 一句话概述

智能旅行助手 Web 产品：用户用自然语言描述需求 → 智谱 GLM（glm-5.3-flash）流式生成结构化逐日行程（带实时"AI 思考过程"展示）→ 高德 POI 逐点定位（GCJ-02）→ Vue 3 前端呈现（高德地图可视化 / 时间线编辑 / 预算面板 / 自然语言重规划 / 导出）。免登录，行程存 localStorage。

## 2. 仓库与服务

| 项 | 值 |
|---|---|
| 本地目录 | `C:\Users\wangy\Desktop\项目\智能旅行助手` |
| GitHub | https://github.com/WYW-1127/travel-mate （main 分支，gh CLI 已登录 WYW-1127） |
| 后端 | FastAPI，`backend/`，端口 **8000**，venv 在 `backend/.venv` |
| 前端 | Vue3+Vite，`frontend/`，端口 **5173**，`/api` 代理到 8000 |
| 一键脚本 | 根目录 `start.bat` / `stop.bat`（GBK 编码，双击运行） |
| 网络 | 用户在国内：git/gh 访问 GitHub 走本地代理 `127.0.0.1:7897`（已配置 `http.https://github.com.proxy`）；npm 用 npmmirror（frontend/.npmrc） |

## 3. 关键文档（都在仓库里）

- **设计 spec（权威）**：`docs/superpowers/specs/2026-09-06-travel-assistant-design.md` — 含架构图、数据模型、API 契约（SSE 事件格式）、V1→V7 演进路线
- **后端实施计划**：`docs/superpowers/plans/2026-09-06-backend-part1.md`（12 任务，含全部代码）
- **前端实施计划**：`docs/superpowers/plans/2026-09-06-frontend-part2.md`
- **启动/密钥说明**：`backend/README.md`、`frontend/README.md`、根 `README.md`

## 4. 密钥与环境状态 ⚠️

| 文件 | 状态 |
|---|---|
| `backend/.env` | ✅ 已配置 `GLM_API_KEY`（智谱）+ `AMAP_WEB_KEY`（高德「Web服务」类型，已验证可用）。`.env` 已 gitignore |
| `frontend/.env` | ✅ 已填入 `VITE_AMAP_JS_KEY` + `VITE_AMAP_SECURITY_CODE`（2026-09-07），地图已实测联动正常 |

- 高德控制台：console.amap.com，应用名 `travel-mate`，账号有多个 Key（「Web服务」和「Web端(JS API)」是两种不同类型的 Key，不通用）
- 智谱控制台：open.bigmodel.cn，模型 glm-5.3-flash

## 5. 已实现功能清单

- ✅ 表单 → SSE 流式生成（POST + fetch ReadableStream，事件：progress/thinking/complete/error，错误码 GLM_ERROR / VALIDATION_FAILED / SCOPE_EMPTY / INTERNAL）
- ✅ GLM 思考过程：流式实时展示（生成页 + 重规划框）+ 完成后随行程持久化（`Trip.thinking`，详情页折叠面板可回看，刷新不丢）
- ✅ 思考深度档位：`thinking_effort: "low" | "high"` 逐请求生效（首页/重规划框勾选框）；`.env` 的 `GLM_THINKING_EFFORT` 为默认值
- ✅ 高德 POI 定位：关键词清洗（剥"午餐·X（XX店）"类修饰）→ POI 搜索 → geocode 兜底；限流退避（码 10014/10019/10020/10021/10022/10044，1s/2s 两次）；进程级缓存；并发 3（个人 key QPS=3）
- ✅ 确定性校验器：时段重叠/结束早于开始（fail）、未定位比例 >30%（fail）、相邻距离 >50km（warn）、超预算（warn）；失败带反馈自动重试 ≤2 次
- ✅ 行程详情：逐日 Tab + 时间线行内编辑/增删/HTML5 拖拽排序；地图 Marker 按类型着色 + 按天折线 + 卡片↔Marker 双向联动（2026-09-07 浏览器实测通过）；预算面板实时重算
- ✅ 自然语言重规划：影响范围分析 → 只重生成受影响的天 → version+1 → 快照栈（≤5 版）一键撤销
- ✅ 导出：打印样式 PDF（window.print）+ JSON 下载；我的行程列表（打开/复制/删除）
- ✅ 测试：后端 pytest 66 项、前端 Vitest 15 项，全绿；`npm run build` 通过；`start.bat` 幂等可重复运行

## 6. 下一步候选（用户未明确排序）

1. JSON 导入（导出的对称功能，未做）
2. 图片导出、行程分享
3. spec §3.2 演进路线：V2 Tool Calling → V3 Agent Loop → V4 LangGraph → V5 MCP → V6 Memory → V7 Multi-Agent（用户明确要求逐阶段学，不要跳级）
4. 账号系统 + 云同步（spec §2.2 明确 MVP 不做，做之前需重读 spec）
5. 注意：高德个人 key POI 搜索日配额有限（百次级），大量端到端测试会烧穿，当天配额耗尽会再次出现"未定位"比例升高

> 2026-09-07 已完成：地图 Key 配置 + 浏览器实测地图联动；修复联动失效 bug（GLM 草稿不输出活动 id，导致 id 全为空串——后端生成/重规划后补齐唯一 id，前端 `:key` 空串回退；旧 localStorage 行程的 id 仍是空的，联动对这些老数据无效，重新生成即可）。

## 7. 踩坑记录（新会话必读，都是真实踩过的）

**环境（Windows + Git Bash）：**
- curl 发中文 JSON 必须写 UTF-8 文件后 `--data-binary @file`，命令行内联中文会被 GBK 搞成 400
- `.bat` 文件必须 GBK + CRLF；bash heredoc 传含反斜杠的 Python 代码会丢一层转义（踩过两次），写复杂文件优先用 Write 工具
- Git Bash 的 `/tmp` 与 Windows Python 的路径映射不一致——跨工具传文件用项目内相对路径
- Git Bash 下 `timeout` 是 GNU coreutils；bat 里延时用 `ping -n N 127.0.0.1`

**GLM（智谱）：**
- glm-5.3-flash **始终思考无法关闭**，`thinking.type=disabled` 返回 1210 错误；只能 `{"type":"enabled","effort":"low"|"high"}`
- OpenAI 兼容端点 `https://open.bigmodel.cn/api/paas/v4`；思考内容在 `delta.reasoning_content`
- GLM 草稿 JSON **不输出活动 id**（提示词没要求）——凡是从草稿 model_validate 出来的 Activity 都要后端补齐 id（planner.assign_activity_ids），否则前端联动/排序 key 全断

**高德：**
- infocode 10009 = Key 平台类型不匹配（Web服务 vs JS API 是两种 Key）；10014 = QPS 超限；v3 place/text 对假地名也会模糊返回，判断搜索失败要看 pois 空
- JS API 需要配对 securityJsCode

**前端（Vue3/Pinia/TS）：**
- Vite env 只在 dev server 启动时读取
- Pinia options 式 getter 用箭头函数时 `this` 不绑定 store（要用方法简写才能引用其他 getter）；`structuredClone` 不能克隆 reactive Proxy（用 JSON 往返）
- TS6：`paths` 不需要 `baseUrl`（已弃用）；`erasableSyntaxOnly` 禁止构造器参数属性
- IAB 浏览器 fullPage 截图有平铺伪影，验证页面状态以 DOM snapshot + 视口截图为准

**流程教训：**
- 测试 stub 会掩盖接线缺陷（replan 端点漏 import 全绿通过）→ 已有 wiring 源码检查测试兜底，新端点照做
- 用户嫌 subagent 双评审流程慢 → 当前约定：内联执行（写码+测试一起推进），关键节点一次终审
- git 提交信息用中文 conventional commits；每个功能点完成即 commit + push

## 8. 测试与验证命令

```bash
# 后端（cwd: backend/）
.venv/Scripts/python -m pytest -v          # 66 项，全离线
.venv/Scripts/python -m uvicorn app.main:app --port 8000

# 前端（cwd: frontend/）
npm test        # 15 项
npm run build   # vue-tsc + vite
npm run dev     # :5173

# SSE 冒烟（注意中文要用 UTF-8 文件传参）
curl -N -X POST http://localhost:8000/api/trips/generate -H "Content-Type: application/json" --data-binary @req.json
```
