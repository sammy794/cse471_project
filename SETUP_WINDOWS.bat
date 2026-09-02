@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo DisasterNet - First-Time Setup
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
    echo Install Python 3, reopen this folder, and run this file again.
    pause
    exit /b 1
  )
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found.
  echo Install Node.js LTS, reopen this folder, and run this file again.
  pause
  exit /b 1
)

echo.
echo [1/2] Installing Python dependencies...
cd /d "%~dp0backend"
%PYTHON_CMD% -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo [2/2] Installing frontend dependencies...
cd /d "%~dp0frontend"
call npm install
if errorlevel 1 goto :error

echo.
echo Setup completed successfully.
echo You can now run RUN_DISASTERNET.bat
pause
exit /b 0

:error
echo.
echo Setup failed. Check the error shown above.
pause
exit /b 1
