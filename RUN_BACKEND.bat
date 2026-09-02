@echo off
setlocal
cd /d "%~dp0backend"

echo ========================================
echo DisasterNet Backend

echo ========================================

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
) else (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "PYTHON_CMD=py"
  ) else (
    echo ERROR: Python was not found.
    echo Install Python or add it to PATH, then run SETUP_WINDOWS.bat.
    pause
    exit /b 1
  )
)

%PYTHON_CMD% -c "import fastapi, uvicorn, sqlalchemy, jwt, requests, dotenv" >nul 2>nul
if errorlevel 1 (
  echo ERROR: Backend Python packages are missing.
  echo Run SETUP_WINDOWS.bat once, then try again.
  pause
  exit /b 1
)

echo Starting API at http://127.0.0.1:8000
%PYTHON_CMD% -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

if errorlevel 1 (
  echo.
  echo Backend stopped with an error. Review the message above.
  pause
)
