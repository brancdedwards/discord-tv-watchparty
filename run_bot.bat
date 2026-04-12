@echo off
REM Discord TV Watchparty Bot Startup Script (Windows)

setlocal enabledelayedexpansion

echo.
echo 🤖 Discord TV Watchparty Bot
echo 📍 Location: %CD%
echo.

REM Check if .env exists
if not exist ".env" (
    echo ❌ Error: .env file not found!
    echo.
    echo Setup steps:
    echo 1. Copy .env.example to .env
    echo 2. Edit .env and fill in:
    echo    - DISCORD_TOKEN (from Discord Developer Portal)
    echo    - Database credentials
    echo.
    pause
    exit /b 1
)

REM Check if virtual environment exists
if not exist ".venv" (
    echo 📦 Creating virtual environment...
    python -m venv .venv
    echo ✅ Virtual environment created
    echo.
)

REM Activate virtual environment
echo 🔌 Activating virtual environment...
call .venv\Scripts\activate.bat

REM Install/update dependencies
echo 📚 Checking dependencies...
pip install -q -r requirements.txt
echo ✅ Dependencies installed
echo.

REM Test imports
echo 🔍 Testing imports...
python test_imports.py
if errorlevel 1 (
    echo.
    echo ❌ Import test failed!
    pause
    exit /b 1
)
echo.

REM Run the bot
echo 🚀 Starting bot...
echo.
python bot.py
