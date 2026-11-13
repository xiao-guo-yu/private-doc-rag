@echo off
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [Pagewise] Installing backend dependencies...
  uv sync
  if errorlevel 1 (
    goto :error
  )
)

echo [Pagewise] Starting local service and opening the browser...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-app.ps1"
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo [Pagewise] Startup failed. See data\server.err.log.
pause
exit /b 1
