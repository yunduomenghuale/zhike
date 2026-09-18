@echo off
chcp 65001 >nul 2>&1
title 网络学习小伴侣 - 服务器守护进程

echo ========================================
echo   网络学习小伴侣 - 服务器守护进程
echo   端口: 8081 (后端API) + 3000 (前端HTTP)
echo   守护进程将自动重启崩溃的服务器
echo ========================================
echo.

cd /d "%~dp0"

echo [1/2] 停止旧的Node.js进程...
taskkill /f /im node.exe >nul 2>&1
timeout /t 1 /nobreak >nul

echo [2/2] 启动守护进程(前台运行)...
echo.
echo   访问地址: http://127.0.0.1:3000
echo   API地址: http://127.0.0.1:8081
echo.
echo   服务器崩溃时会自动重启
echo   按 Ctrl+C 停止服务器
echo ========================================
echo.

node keepalive.js

echo.
echo 服务器已停止。
pause
