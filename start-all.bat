@echo off
chcp 65001 >nul
title DeepSearch Launcher
cd /d %~dp0
echo Starting MySQL (docker) + backend + frontend ...
docker start deepsearch-mysql >nul 2>&1
start "DeepSearch Backend" cmd /k "%~dp0start-backend.bat"
start "DeepSearch Frontend" cmd /k "%~dp0start-frontend.bat"
echo Backend:  http://127.0.0.1:8000
echo Frontend: http://127.0.0.1:5173
echo Close this window when you are done.
pause
