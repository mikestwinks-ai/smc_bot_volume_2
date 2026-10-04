@echo off
title SMC Trading Bot

:: ─────────────────────────────────────────────
:: Resolve the directory this .bat file lives in
:: Place this file inside the smc_bot\ folder
:: ─────────────────────────────────────────────
cd /d "%~dp0"

:: ─────────────────────────────────────────────
:: Check Python is available
:: ─────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Make sure Python 3.11+ is installed and on PATH.
    pause
    exit /b 1
)

:: ─────────────────────────────────────────────
:: Activate virtual environment if it exists
:: ─────────────────────────────────────────────
if exist "venv\Scripts\activate.bat" (
    echo [INFO] Activating virtual environment...
    call venv\Scripts\activate.bat
) else (
    echo [WARN] No venv found. Creating one now...
    python -m venv venv
    call venv\Scripts\activate.bat
    echo [INFO] Installing dependencies...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed.
        pause
        exit /b 1
    )
)

:: ─────────────────────────────────────────────
:: Check .env exists
:: ─────────────────────────────────────────────
if not exist ".env" (
    echo [ERROR] .env file not found. Copy .env and fill in your MT5 credentials.
    pause
    exit /b 1
)

:: ─────────────────────────────────────────────
:: Create logs folder if missing
:: ─────────────────────────────────────────────
if not exist "logs" mkdir logs

:: ─────────────────────────────────────────────
:: Launch the bot
:: ─────────────────────────────────────────────
echo.
echo ============================================================
echo   SMC Trading Bot — Starting
echo   Time: %date% %time%
echo ============================================================
echo.

:restart
python main.py

:: ─────────────────────────────────────────────
:: Auto-restart on non-zero exit (e.g. crash)
:: Ctrl+C exits cleanly with code 0 — no restart
:: ─────────────────────────────────────────────
if errorlevel 1 (
    echo.
    echo [WARN] Bot exited with an error. Restarting in 15 seconds...
    echo        Press Ctrl+C now to cancel restart.
    timeout /t 15
    goto restart
)

echo.
echo [INFO] Bot stopped cleanly.
pause
