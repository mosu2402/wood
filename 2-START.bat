@echo off
title Luxe Laminate - Running (do not close this window)
cd /d "%~dp0"
echo Stopping any old Luxe Laminate still running on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /PID %%a >nul 2>&1
echo Running from: %CD%
echo Updating database...
python -m alembic upgrade head
if errorlevel 1 (
  echo.
  echo Database update failed. Run 1-INSTALL.bat first, then try again.
  pause
  exit /b 1
)
python -m scripts.first_run
echo.
echo ============================================================
echo   Luxe Laminate is running:  http://localhost:8000
echo   Version 2026-10-23  (shown at the bottom-left of the menu)
echo   Keep this window open while you work. Close it to stop.
echo ============================================================
echo.
start "" cmd /c "timeout /t 3 >nul & start http://localhost:8000"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
pause
