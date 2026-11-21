@echo off
chcp 65001 >nul
title DeepSearch Backend (FastAPI :8000)
cd /d %~dp0
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] venv not found. Run: uv sync --python 3.12
  pause
  exit /b 1
)
echo Starting backend on http://127.0.0.1:8000 ...
.venv\Scripts\python.exe -m uvicorn app.api.server:app --host 127.0.0.1 --port 8000 --reload
pause
