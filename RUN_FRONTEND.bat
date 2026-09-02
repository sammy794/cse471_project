@echo off
setlocal
cd /d "%~dp0frontend"

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found. Install Node.js LTS first.
  pause
  exit /b 1
)

if not exist "node_modules" (
  echo ERROR: Frontend dependencies are missing.
  echo Run SETUP_WINDOWS.bat once first.
  pause
  exit /b 1
)

echo Starting frontend at http://localhost:5173
call npm run dev -- --host 127.0.0.1 --port 5173 --strictPort

if errorlevel 1 (
  echo.
  echo Frontend stopped with an error. Review the message above.
  pause
)
