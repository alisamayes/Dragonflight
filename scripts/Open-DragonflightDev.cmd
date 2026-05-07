@echo off
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\activate.bat" (
    echo No virtualenv yet. Run setup once:
    echo   powershell -ExecutionPolicy Bypass -File "%~dp0Setup-DragonflightDev.ps1"
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"
title Dragonflight dev — Python venv
echo Dragonflight venv active.
echo.
cmd /k
