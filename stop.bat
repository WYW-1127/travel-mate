@echo off
chcp 936 >nul
title TravelMate 停止服务
echo 正在停止 TravelMate 服务...
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /F /PID %%p >nul 2>&1
echo 已停止。
%SystemRoot%\System32	imeout.exe /t 3 >nul
