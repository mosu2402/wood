@echo off
title Luxe Laminate - Install
cd /d "%~dp0"
echo Installing the libraries Luxe Laminate needs. This takes a few minutes...
echo.
python -m pip install fastapi "uvicorn[standard]" sqlalchemy alembic pyjwt bcrypt python-multipart openpyxl reportlab python-dotenv pydantic
if errorlevel 1 (
  echo.
  echo Install failed. Is Python installed with "Add python.exe to PATH" ticked?
  pause
  exit /b 1
)
echo.
echo Done. Now double-click 2-START.bat
pause
