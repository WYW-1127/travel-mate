@echo off
chcp 936 >nul
title TravelMate 一键启动
cd /d "%~dp0"

echo ================================================
echo    TravelMate 智能旅行助手 - 一键启动
echo ================================================

rem ---- 1. 后端环境 ----
if not exist backend\.venv (
  echo [1/4] 首次运行：创建 Python 虚拟环境并安装依赖（约 1-2 分钟）...
  pushd backend
  python -m venv .venv
  if errorlevel 1 goto error
  .venv\Scripts\python -m pip install -e ".[dev]" -q
  if errorlevel 1 goto error
  popd
) else (
  echo [1/4] 后端环境已就绪
)

if not exist backend\.env (
  if exist backend\.env.example (
    copy backend\.env.example backend\.env >nul
    echo.
    echo [!] 已生成 backend\.env，请填入 GLM_API_KEY 和 AMAP_WEB_KEY 后重新运行本脚本！
    echo     申请地址见 backend\README.md
    pause
    exit /b 1
  )
)

rem ---- 2. 前端环境 ----
if not exist frontend\node_modules (
  echo [2/4] 首次运行：安装前端依赖（约 1-3 分钟）...
  pushd frontend
  call npm install
  if errorlevel 1 goto error
  popd
) else (
  echo [2/4] 前端环境已就绪
)

rem ---- 3. 启动服务（已在运行则跳过） ----
set BACKEND_RUNNING=0
set FRONTEND_RUNNING=0
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul && set BACKEND_RUNNING=1
netstat -ano | findstr ":5173" | findstr "LISTENING" >nul && set FRONTEND_RUNNING=1

if "%BACKEND_RUNNING%"=="0" (
  echo [3/4] 启动后端 :8000 ...
  start "TravelMate 后端" cmd /k "cd /d %~dp0backend && .venv\Scripts\python -m uvicorn app.main:app --port 8000"
) else (
  echo [3/4] 后端已在运行，跳过
)

if "%FRONTEND_RUNNING%"=="0" (
  echo [4/4] 启动前端 :5173 ...
  start "TravelMate 前端" cmd /k "cd /d %~dp0frontend && npm run dev"
) else (
  echo [4/4] 前端已在运行，跳过
)

rem ---- 4. 等待后端就绪并打开浏览器 ----
echo 等待后端就绪...
set /a TRIES=0
:waitloop
%SystemRoot%\System32	imeout.exe /t 2 /nobreak >nul
curl -s -o nul http://127.0.0.1:8000/api/health
if errorlevel 1 (
  set /a TRIES+=1
  if %TRIES% lss 15 goto waitloop
  echo [!] 后端未就绪，请查看「TravelMate 后端」窗口中的报错
)
start "" http://localhost:5173/
echo.
echo ================================================
echo   已启动: http://localhost:5173
echo   停止服务: 双击 stop.bat 或关闭两个服务窗口
echo ================================================
%SystemRoot%\System32	imeout.exe /t 10 >nul
exit /b 0

:error
echo [!] 启动失败，请检查上方报错信息
pause
exit /b 1
