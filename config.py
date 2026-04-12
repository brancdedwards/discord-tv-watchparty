import os
from dotenv import load_dotenv
import discord

load_dotenv()

# ===== Discord Bot Config =====
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN not set in .env file")

COMMAND_PREFIX = "!"
# Use default intents - we only need slash commands, not privileged intents
BOT_INTENTS = discord.Intents.default()

# ===== Database Config =====
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_NAME = os.getenv("DB_NAME", "review_analyzer")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ===== Review Analyzer Path =====
REVIEW_ANALYZER_PATH = os.getenv(
    "REVIEW_ANALYZER_PATH",
    "../review_analyzer"
)

# ===== Scraper Config =====
SCRAPER_TIMEOUT_SECONDS = 900  # 15 minutes
SCRAPER_POLL_INTERVAL = 5  # Check every 5 seconds
MAX_SCRAPE_POLLS = SCRAPER_TIMEOUT_SECONDS // SCRAPER_POLL_INTERVAL

# ===== Permissions =====
# Discord user IDs who can trigger scrapes (prevent rate limiting)
AUTHORIZED_SCRAPERS = []  # Empty = anyone can scrape. Add Discord user IDs to restrict.
# Example: AUTHORIZED_SCRAPERS = [123456789, 987654321]

# ===== User Mapping =====
# Map Discord user IDs to names for wishlist tracking
USERS = {
    881336025325142017: "Morgan",
    455189485710475265: "Brandon"
}

# ===== Logging =====
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
