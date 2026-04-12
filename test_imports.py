#!/usr/bin/env python3
"""
Test script to verify all imports work correctly.
Run this before starting the bot to catch any import errors.
"""
import sys
from pathlib import Path

print("🔍 Testing imports...")
print()

# Test local imports
print("✓ Testing local utils...")
try:
    from utils.db_bridge import DatabaseBridge
    print("  ✅ db_bridge imported")
except ImportError as e:
    print(f"  ❌ db_bridge import failed: {e}")
    sys.exit(1)

try:
    from utils.imdb_scraper_bridge import ScraperBridge
    print("  ✅ imdb_scraper_bridge imported")
except ImportError as e:
    print(f"  ❌ imdb_scraper_bridge import failed: {e}")
    sys.exit(1)

try:
    from utils.embed_formatter import EmbedFormatter
    print("  ✅ embed_formatter imported")
except ImportError as e:
    print(f"  ❌ embed_formatter import failed: {e}")
    sys.exit(1)

try:
    from views.scrape_buttons import IMDbSelectionView
    print("  ✅ scrape_buttons imported")
except ImportError as e:
    print(f"  ❌ scrape_buttons import failed: {e}")
    sys.exit(1)

print()
print("✓ Testing config...")
try:
    from config import DISCORD_TOKEN, DB_HOST, AUTHORIZED_SCRAPERS
    if DISCORD_TOKEN:
        print("  ✅ DISCORD_TOKEN is set")
    else:
        print("  ⚠️  DISCORD_TOKEN is not set (you need to configure .env)")
    print(f"  ✅ DB_HOST: {DB_HOST}")
except ImportError as e:
    print(f"  ❌ config import failed: {e}")
    sys.exit(1)

print()
print("✓ Testing Discord.py...")
try:
    import discord
    print(f"  ✅ discord.py {discord.__version__}")
except ImportError as e:
    print(f"  ❌ discord.py import failed: {e}")
    sys.exit(1)

print()
print("✓ Testing review_analyzer imports...")
PARENT_DIR = Path(__file__).parent.parent
REVIEW_ANALYZER_PATH = PARENT_DIR / "review_analyzer"
if REVIEW_ANALYZER_PATH.exists():
    sys.path.insert(0, str(REVIEW_ANALYZER_PATH))
    try:
        from imdb_scraper_project.utils.imdb_search import search_imdb_graphql
        print("  ✅ review_analyzer.imdb_search imported")
    except ImportError as e:
        print(f"  ⚠️  review_analyzer.imdb_search not available: {e}")
        print("     This is optional - search will be limited")
else:
    print(f"  ⚠️  review_analyzer not found at {REVIEW_ANALYZER_PATH}")
    print("     Make sure review_analyzer is in the parent directory")

print()
print("=" * 50)
print("✅ All critical imports successful!")
print("=" * 50)
print()
print("Next steps:")
print("1. Make sure .env is configured with DISCORD_TOKEN")
print("2. Run: python bot.py")
