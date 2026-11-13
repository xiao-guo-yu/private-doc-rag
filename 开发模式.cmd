@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  uv sync
  if errorlevel 1 exit /b 1
)
if not exist "frontend\node_modules" (
  pushd frontend
  call npm install
  popd
)

start "Pagewise API" ".venv\Scripts\python.exe" -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8010
start "Pagewise Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:5173"
endlocal
