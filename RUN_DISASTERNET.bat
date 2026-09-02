@echo off
setlocal
cd /d "%~dp0"

if not exist "%~dp0frontend\node_modules" (
  echo Frontend dependencies are not installed.
  echo Run SETUP_WINDOWS.bat once first.
  pause
  exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found. Install Node.js LTS first.
  pause
  exit /b 1
)

echo Checking for older DisasterNet servers...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo.
  echo ERROR: Port 8000 is already in use by an older backend.
  echo Close the old DisasterNet Backend terminal with CTRL+C, then run this file again.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -State Listen -LocalPort 5173 -ErrorAction SilentlyContinue) { exit 1 } else { exit 0 }"
if errorlevel 1 (
  echo.
  echo ERROR: Port 5173 is already in use by an older frontend.
  echo Close the old DisasterNet Frontend terminal with CTRL+C, then run this file again.
  pause
  exit /b 1
)

echo Starting DisasterNet backend...
start "DisasterNet Backend" cmd /k ""%~dp0RUN_BACKEND.bat""

echo Waiting for backend at http://127.0.0.1:8000 ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ready=$false; for($i=0;$i -lt 25;$i++){ try { $r=Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/' -TimeoutSec 1; if($r.StatusCode -eq 200){$ready=$true; break} } catch {}; Start-Sleep -Seconds 1 }; if($ready){exit 0}else{exit 1}"

if errorlevel 1 (
  echo.
  echo ERROR: The backend did not start successfully.
  echo Check the 'DisasterNet Backend' terminal for the exact error.
  echo If packages are missing, run SETUP_WINDOWS.bat once.
  pause
  exit /b 1
)

echo Backend is online.
echo Starting frontend...
start "DisasterNet Frontend" cmd /k ""%~dp0RUN_FRONTEND.bat""

echo.
echo DisasterNet is starting successfully.
echo Open: http://localhost:5173
echo API:  http://127.0.0.1:8000/docs
exit /b 0
