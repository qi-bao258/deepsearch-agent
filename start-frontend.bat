@echo off
chcp 65001 >nul
title DeepSearch Frontend (Vite :5173)
cd /d %~dp0frontend
if not exist "node_modules" (
  echo [INFO] node_modules missing, running pnpm install ...
  call corepack pnpm install
)
echo Starting frontend on http://127.0.0.1:5173 ...
call corepack pnpm dev
pause
