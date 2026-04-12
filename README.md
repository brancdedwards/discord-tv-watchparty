# Discord TV & Movie Watch-Party Bot

A Discord bot for you and Morgan to collaboratively pick TV shows and movies to watch together. Search IMDb, view ratings and genres, and get episode-by-episode breakdowns all from Discord!

## Features

- 🔍 **Search IMDb** — Find TV shows and movies with `/add-show` and `/add-movie`
- 📊 **View Metadata** — Get ratings, genres, episode counts, and season-by-season ratings
- 🎬 **One-Click Scraping** — Trigger IMDb scrapes directly from Discord
- 📺 **Separate Channels** — Organize TV shows and movies in different channels
- 🎲 **Random Suggestions** — Get random show ideas with `/random-show`

## Setup

### 1. Prerequisites

- Python 3.10+
- PostgreSQL (same database as review_analyzer)
- Discord bot token (from Discord Developer Portal)
- review_analyzer project (for scraping infrastructure)

### 2. Installation

```bash
# Clone/navigate to the discord-tv-watchparty directory
cd discord-tv-watchparty

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration

```bash
# Copy the example env file
cp .env .env

# Edit .env with your settings:
# - DISCORD_TOKEN: Get from Discord Developer Portal
# - DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD: Same as review_analyzer
# - REVIEW_ANALYZER_PATH: Path to review_analyzer project (default: ../review_analyzer)
```

### 4. Create Discord Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Create a new application
3. Go to **Bot** → **Add Bot**
4. Copy the token to `.env` as `DISCORD_TOKEN`
5. Under **OAUTH2 → URL Generator**:
   - Scopes: `bot`, `applications.commands`
   - Permissions: `Send Messages`, `Embed Links`, `Read Message History`, `Manage Messages`
6. Use the generated URL to invite the bot to your server

### 5. Run the Bot

```bash
python bot.py
```

The bot will sync slash commands with Discord on startup and log successful initialization.

---

## Usage

### TV Shows

**Add a show:**
```
/add-show Breaking Bad
```
The bot returns 5 search results. Click a button to select which show you meant.

**Get show details:**
```
/scrape-show tt0903747
```
or
```
/scrape-show Breaking Bad
```

The bot will:
1. Check if the show is already in the database (instant return if cached)
2. If not, spawn the review_analyzer scraper (5-15 min)
3. Return an embed with: rating, genres, seasons, top-rated seasons

### Movies

Same pattern with `/add-movie` and `/scrape-movie`

### Random Suggestions

```
/random-show
```

Get a random show from the database. Click "Try Another" to get a different one.

---

## Architecture

```
discord-tv-watchparty/          [This bot]
├── bot.py                       Main entry point
├── config.py                    Configuration
├── cogs/                        Discord commands
│   ├── tv_commands.py           /add-show, /scrape-show
│   ├── movie_commands.py        /add-movie, /scrape-movie
│   └── utilities.py             /random-show, /help
├── utils/                       Utilities
│   ├── db_bridge.py             Query review_analyzer DB
│   ├── imdb_scraper_bridge.py   Spawn scraper subprocess
│   └── embed_formatter.py       Format Discord embeds
└── views/                       Button interactions
    └── scrape_buttons.py        Selection and status buttons

                ↓
         review_analyzer/       [Existing project]
         ├── schema.sql         PostgreSQL database
         └── imdb_scraper_project/run_scraper.py  ← Bot calls this
```

## How Scraping Works

1. User requests `/scrape-show Breaking Bad`
2. Bot checks if "Breaking Bad" is in the database
3. If not:
   - Bot spawns: `python review_analyzer/imdb_scraper_project/run_scraper.py tt0903747 --yes`
   - Shows status message while scraping (⏳ In progress...)
   - Polls database every 5 seconds until complete
   - Updates embed with results when done
4. Data is cached, so future requests are instant

**Note:** Scraping takes 5-15 minutes depending on episode count and reviews. This prevents rate limiting.

## Rate Limiting

To prevent IMDb rate limiting abuse:

1. Only authorized users can trigger scrapes (edit `config.py` → `AUTHORIZED_SCRAPERS`)
2. Default: anyone can scrape. To restrict to Brandon & Morgan:

```python
# config.py
AUTHORIZED_SCRAPERS = [123456789, 987654321]  # Their Discord user IDs
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_TOKEN` | Yes | Discord bot token |
| `DB_HOST` | Yes | PostgreSQL host |
| `DB_PORT` | No | PostgreSQL port (default: 5432) |
| `DB_NAME` | No | Database name (default: review_analyzer) |
| `DB_USER` | Yes | Database user |
| `DB_PASSWORD` | Yes | Database password |
| `REVIEW_ANALYZER_PATH` | No | Path to review_analyzer (default: ../review_analyzer) |
| `LOG_LEVEL` | No | Logging level (default: INFO) |

## Troubleshooting

### Bot doesn't respond to commands

1. Check that the bot is online in Discord
2. Verify slash commands synced (check console logs)
3. Make sure bot has "Embed Links" permission

### Scraping fails with "process not found"

1. Verify `REVIEW_ANALYZER_PATH` in `.env` points to review_analyzer
2. Check that review_analyzer's dependencies are installed
3. Test manually: `cd ../review_analyzer && python imdb_scraper_project/run_scraper.py tt0903747`

### Database connection errors

1. Verify `.env` has correct DB credentials
2. Test connection: `psql -h HOST -U USER -d DB_NAME`
3. Make sure review_analyzer database is running

### Scraper times out

1. IMDb might be rate limiting — try again later
2. Show might have huge number of episodes (1000+)
3. Increase timeout in `config.py` → `SCRAPER_TIMEOUT_SECONDS`

## Future Enhancements

- [ ] Watchlist tracking (mark "we watched this")
- [ ] Notification when scrape completes (ping Morgan)
- [ ] Review excerpts (show 2-3 top reviews)
- [ ] Genre-specific randomization
- [ ] Watch progress tracking

## License

For personal use. Respect IMDb's Terms of Service and rate limit requests.

---

Made with ❤️ for Brandon & Morgan 🎬
