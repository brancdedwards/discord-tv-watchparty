# Discord TV & Movie Watch-Party Bot

A Discord bot for you and Morgan to collaboratively pick TV shows and movies to watch together. Search IMDb, view ratings and genres, and get episode-by-episode breakdowns all from Discord!

## Features

- 🧭 **Pinned Watchparty Panel** — Post one button menu with `/watchparty-panel`, then pin it
- 🔍 **Search IMDb** — Search from a button modal and add with one click, including ratings and genres
- 📊 **View Metadata** — Get ratings, genres, episode counts, and season-by-season ratings
- 🛠️ **Admin Maintenance** — Keep detailed metadata refreshed without exposing the technical flow
- 📺 **Separate Channels** — Organize TV shows and movies in different channels
- 🎲 **Pick Tonight** — Pick from the shared list by Movie, TV, Anything, and available genres

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

### Easiest Flow for Morgan

Run this once in the Discord channel. The bot will try to pin the message automatically if it has permission:

```
/watchparty-panel
```

The pinned panel gives everyone six buttons:

- **Suggest Movie** — opens a text box and searches movie results only.
- **Suggest TV** — opens a text box and searches TV results only.
- **Suggest Anything** — searches both movies and TV shows.
- **See Wishlist** — shows the shared list without needing to type a command.
- **Pick Tonight** — choose Movie, TV, or Anything, then pick a genre or let the bot surprise you.
- **Remove Idea** — opens a text box to remove an item by title.

This keeps Morgan out of IMDb IDs, queue language, and scraper commands.

Search results show the content type, release year, IMDb rating when available, genres when available, and a poster. If IMDb search cannot provide a rating, the bot says "Rating unavailable" rather than implying the title itself is unrated.

### Fallback Commands

These still work if you prefer typing:

```
/add-to-wishlist Breaking Bad
/wishlist
/random-show
```

### Brandon/Admin Scraping

Maintenance commands are still available for Brandon/admin use:

```
/scrape-show Breaking Bad
/scrape-movie tt0133093
```

The bot will:
1. Check if the title is already in the database
2. If not, spawn the review_analyzer scraper
3. Return an embed with rating, genres, seasons, and top-rated seasons when available

### Random Suggestions

```
/random-show
```

Get a random detailed show from the scraped database. From the watchparty panel, **Pick Tonight** chooses from the shared wishlist instead.

### Pick Tonight

The panel's **Pick Tonight** button walks through:

1. Movie, TV Show, or Anything
2. Genre or Surprise Me
3. A random pick from the matching shared wishlist ideas

Genre buttons appear when matching wishlist items already have scraped genre metadata. If no genres are available yet, **Surprise Me** still picks from the selected Movie/TV/Anything set.

### Health Check

```
/health
```

Admin-only. Checks the database, critical imports, bot uptime, and whether IMDb GraphQL search is returning ratings. This helps catch IMDb endpoint/query changes before Morgan sees broken search results.

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

1. Someone suggests a title from the watchparty panel
2. The selected IMDb result is added to the shared wishlist and scrape queue
3. Brandon can process the queue with scraper commands
4. Data is cached, so future requests are instant

Manual scraper flow:

1. Brandon requests `/scrape-show Breaking Bad`
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

### Search works but ratings disappear

1. Run `/health` and check the **IMDb Search** line.
2. If it says "Search fallback only", IMDb changed or blocked the GraphQL path.
3. Check logs for `GraphQL search ... returned errors`.
4. The current rich search path lives in `utils/imdb_search.py` and uses a direct `FindPageSearch` POST to `https://api.graphql.imdb.com/`.
5. The autocomplete fallback may still return titles, posters, years, and cast summaries, but it does not include ratings.

### Render deployment

1. Commit local changes.
2. Push to the branch Render deploys from.
3. Restart or redeploy the Render service so the running bot process loads the new code.
4. Watch startup logs for command sync and run `/health` after deploy.

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
