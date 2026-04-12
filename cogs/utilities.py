"""
Utility commands for the bot.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging
import random
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Add discord-tv-watchparty to path for local imports
SCRIPT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.db_bridge import DatabaseBridge
from utils.embed_formatter import EmbedFormatter


class UtilitiesCog(commands.Cog):
    """Utility commands for the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()

    @app_commands.command(
        name="random-show",
        description="Get a random show suggestion"
    )
    @app_commands.describe(genre="Optional: Filter by genre")
    async def random_show(self, interaction: discord.Interaction, genre: str = None):
        """
        Get a random show suggestion from the database.
        """
        await interaction.response.defer()

        try:
            # Get random title from database
            results = self.db.get_random_title(limit=1)

            if not results:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        f"No shows found{f' in genre {genre}' if genre else ''}"
                    )
                )
                return

            imdb_id = results[0]["imdb_id"]

            # Get full data
            series_data = self.db.get_series_by_imdb_id(imdb_id)
            genres = self.db.get_genres(imdb_id)
            seasons_data = self.db.get_episode_ratings_by_season(imdb_id)

            embed = EmbedFormatter.format_series_summary(series_data, seasons_data, genres)
            embed.description = "🎲 Random show suggestion for your watchparty!"

            view = RandomShowView(self)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in random_show: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="help",
        description="Show available commands and how to use them"
    )
    async def help_command(self, interaction: discord.Interaction):
        """
        Show help information.
        """
        embed = discord.Embed(
            title="🎬 TV & Movie Watchparty Bot",
            description="Commands to help Brandon and Morgan pick shows to watch together!",
            color=discord.Color.gold()
        )

        embed.add_field(
            name="💕 Wishlist (Shared Ideas)",
            value="**/add-to-wishlist** - Add a show/movie to your shared wishlist\n"
                  "**/wishlist** - View the shared wishlist (shows who suggested what)\n"
                  "**/remove-from-wishlist** - Remove from wishlist",
            inline=False
        )

        embed.add_field(
            name="🔍 Search & Browse",
            value="**/search** - Search the database for shows/movies\n"
                  "**/list-shows** - Browse all TV shows (paginated)\n"
                  "**/list-movies** - Browse all movies (paginated)",
            inline=False
        )

        embed.add_field(
            name="📺 TV Shows",
            value="**/add-show** - Add TV show to scrape queue\n"
                  "**/pending-shows** - View shows waiting to be scraped\n"
                  "**/scrape-show** - Fetch full details from IMDb",
            inline=False
        )

        embed.add_field(
            name="🎬 Movies",
            value="**/add-movie** - Add movie to scrape queue\n"
                  "**/pending-movies** - View movies waiting to be scraped\n"
                  "**/scrape-movie** - Fetch full details from IMDb",
            inline=False
        )

        embed.add_field(
            name="🎲 Fun",
            value="**/random-show** - Get a random show suggestion\n"
                  "**/help** - Show this help message",
            inline=False
        )

        embed.add_field(
            name="🔧 Admin (Brandon Only)",
            value="**/health** - Check bot status (database, imports, uptime)\n"
                  "**/scrape-show** - Scrape TV show details from IMDb\n"
                  "**/scrape-movie** - Scrape movie details from IMDb\n"
                  "_Note: Morgan can only suggest via wishlist_",
            inline=False
        )

        embed.add_field(
            name="💡 How It Works",
            value="**Option 1: Wishlist Mode**\n"
                  "1. `/search breaking bad` to find shows in database\n"
                  "2. `/add-to-wishlist` to add to shared wishlist\n"
                  "3. `/wishlist` to see all suggestions\n"
                  "4. Decide together what to watch!\n\n"
                  "**Option 2: Scrape Mode**\n"
                  "1. `/add-show` to queue a show for scraping\n"
                  "2. `/scrape-show` to fetch full IMDb details\n"
                  "3. Review rating, genres, season ratings\n"
                  "4. Then add to wishlist if interested!",
            inline=False
        )

        embed.set_footer(text="Made with ❤️ for Brandon & Morgan")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="search",
        description="Search for a show or movie in the database"
    )
    @app_commands.describe(query="Title to search for")
    async def search(self, interaction: discord.Interaction, query: str):
        """
        Search database for shows or movies.
        """
        await interaction.response.defer()

        try:
            if not query or len(query) < 2:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error("Search query must be at least 2 characters"),
                    ephemeral=True
                )
                return

            logger.info(f"Searching for: {query}")

            # Search in titles table
            conn = self.db.get_connection()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT
                        title_id,
                        title_name,
                        title_type,
                        imdb_rating,
                        num_seasons
                    FROM titles
                    WHERE LOWER(title_name) LIKE LOWER(%s)
                    LIMIT 10
                """, (f"%{query}%",))
                rows = cur.fetchall()
            if conn:
                conn.close()

            if not rows:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"No results found for '{query}'"),
                    ephemeral=True
                )
                return

            # Create embed with results
            embed = discord.Embed(
                title=f"🔍 Search Results for '{query}'",
                color=discord.Color.purple(),
                description=f"Found {len(rows)} result(s)"
            )

            for i, row in enumerate(rows, 1):
                imdb_id = row[0]
                title = row[1]
                content_type = "📺 TV" if row[2] == "tvSeries" else "🎬 Movie"
                rating = f"⭐ {row[3]}" if row[3] else "⭐ Not rated"
                seasons = f" • {row[4]} seasons" if row[4] and row[2] == "tvSeries" else ""

                embed.add_field(
                    name=f"{i}. {title}",
                    value=f"{content_type} {rating}{seasons}\nIMDb: `{imdb_id}`",
                    inline=False
                )

            embed.set_footer(text="Use /scrape-show or /scrape-movie with the IMDb ID to get full details")
            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in search: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="health",
        description="Check bot health status (database, imports, uptime)"
    )
    async def health_check(self, interaction: discord.Interaction):
        """
        Check bot health status.
        """
        await interaction.response.defer(ephemeral=True)

        try:
            import time
            from datetime import datetime, timedelta

            health_status = {
                "database": False,
                "imports": False,
                "bot_uptime": "Unknown",
                "timestamp": datetime.now().isoformat()
            }

            # Check database connection
            try:
                self.db.get_wishlist()
                health_status["database"] = True
            except Exception as e:
                logger.warning(f"Database health check failed: {e}")

            # Check critical imports
            try:
                from cogs.wishlist_commands import search_imdb_paginated
                health_status["imports"] = search_imdb_paginated is not None
            except:
                health_status["imports"] = False

            # Get bot uptime (approximate)
            try:
                uptime_seconds = int(time.time() - self.bot.start_time)
                hours = uptime_seconds // 3600
                minutes = (uptime_seconds % 3600) // 60
                health_status["bot_uptime"] = f"{hours}h {minutes}m"
            except:
                pass

            # Build response embed
            db_status = "✅ Connected" if health_status["database"] else "❌ Failed"
            imports_status = "✅ Available" if health_status["imports"] else "⚠️ Missing (IMDb search unavailable)"

            embed = discord.Embed(
                title="🏥 Bot Health Check",
                color=discord.Color.green() if health_status["database"] else discord.Color.red(),
                timestamp=datetime.fromisoformat(health_status["timestamp"])
            )

            embed.add_field(name="Database", value=db_status, inline=False)
            embed.add_field(name="Critical Imports", value=imports_status, inline=False)
            embed.add_field(name="Uptime", value=health_status["bot_uptime"], inline=False)
            embed.add_field(name="Status",
                          value="🟢 Healthy" if health_status["database"] else "🔴 Unhealthy",
                          inline=False)

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in health_check: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Health check error: {str(e)[:100]}"),
                ephemeral=True
            )


class RandomShowView(discord.ui.View):
    """View for random show with 'try another' button."""

    def __init__(self, cog, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.cog = cog

    @discord.ui.button(label="🎲 Try Another", style=discord.ButtonStyle.secondary)
    async def try_another(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Get another random suggestion."""
        await interaction.response.defer()
        # Call the random_show command again
        await self.cog.random_show(interaction, genre=None)


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(UtilitiesCog(bot))
    logger.info("UtilitiesCog loaded")
