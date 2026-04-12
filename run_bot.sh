#!/bin/bash

# Discord TV Watchparty Bot Startup Script

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
echo "🤖 Discord TV Watchparty Bot"
echo "📍 Location: $SCRIPT_DIR"
echo ""

# Check if .env exists
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    echo "❌ Error: .env file not found!"
    echo ""
    echo "Setup steps:"
    echo "1. Copy .env.example to .env:"
    echo "   cp .env.example .env"
    echo ""
    echo "2. Edit .env and fill in:"
    echo "   - DISCORD_TOKEN (from Discord Developer Portal)"
    echo "   - Database credentials (DB_HOST, DB_USER, DB_PASSWORD, etc.)"
    echo ""
    exit 1
fi

# Check if virtual environment exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv .venv
    echo "✅ Virtual environment created"
    echo ""
fi

# Activate virtual environment
echo "🔌 Activating virtual environment..."
source "$SCRIPT_DIR/.venv/bin/activate"

# Install/update dependencies
echo "📚 Checking dependencies..."
pip install -q -r "$SCRIPT_DIR/requirements.txt"
echo "✅ Dependencies installed"
echo ""

# Test imports
echo "🔍 Testing imports..."
python "$SCRIPT_DIR/test_imports.py"
echo ""

# Run the bot
echo "🚀 Starting bot..."
echo ""
python "$SCRIPT_DIR/bot.py"
