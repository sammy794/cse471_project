@echo off
setlocal
cd /d "%~dp0"

echo ========================================
echo DisasterNet - Google Maps API Key Setup
echo ========================================
echo.
echo In Google Cloud, enable:
echo   - Maps JavaScript API
echo   - Places API (New)
echo   - Routes API
echo   - Distance Matrix API (Legacy)
echo.
set /p "MAPS_KEY=Paste your Google Maps Platform API key: "

if "%MAPS_KEY%"=="" (
  echo ERROR: No API key entered.
  pause
  exit /b 1
)

> "%~dp0frontend\.env.local" echo VITE_GOOGLE_MAPS_API_KEY=%MAPS_KEY%

echo.
echo Google Maps API key saved to frontend\.env.local
 echo Restart RUN_DISASTERNET.bat if the app is already running.
pause
