"""
Discord slash commands for TV show suggestions and scraping.
"""
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
SCRIPT_DIR = Path(__file__).parent.parent  # discord-tv-watchparty/
PARENT_DIR = SCRIPT_DIR.parent  # GitHub/Data Science projects/

# Add discord-tv-watchparty to path for local imports
sys.path.insert(0, str(SCRIPT_DIR))

# Add review_analyzer to path for its imports
REVIEW_ANALYZER_PATH = PARENT_DIR / "review_analyzer"
if REVIEW_ANALYZER_PATH.exists():
    sys.path.insert(0, str(REVIEW_ANALYZER_PATH))
    logger.info(f"Added review_analyzer to path: {REVIEW_ANALYZER_PATH}")
else:
    logger.warning(f"review_analyzer not found at {REVIEW_ANALYZER_PATH}")

# Import local utilities
from utils.db_bridge import DatabaseBridge
from utils.imdb_scraper_bridge import ScraperBridge
from utils.embed_formatter import EmbedFormatter
from views.scrape_buttons import PaginationView
from config import SCRAPER_POLL_INTERVAL, MAX_SCRAPE_POLLS, AUTHORIZED_SCRAPERS, USERS

# Get Brandon's user ID for permission checks
BRANDON_ID = None
for user_id, name in USERS.items():
    if name == "Brandon":
        BRANDON_ID = user_id
        break

async def brandon_only(interaction: discord.Interaction) -> bool:
    """Check if user is Brandon."""
    if interaction.user.id != BRANDON_ID:
        await interaction.response.send_message(
            embed=EmbedFormatter.format_error(
                "❌ Only Brandon can scrape shows. Use `/wishlist` to suggest shows instead!"
            ),
            ephemeral=True
        )
        return False
    return True

# Import IMDb search from review_analyzer (optional)
search_imdb_graphql = None
try:
    from imdb_scraper_project.utils.imdb_search import search_imdb_graphql
    logger.info("Successfully imported imdb_search from review_analyzer")
except ImportError as e:
    logger.warning(f"Failed to import imdb_search from review_analyzer: {e}")


class TVCommandsCog(commands.Cog):
    """Cog for TV show commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()

    def is_authorized_scraper(self, user_id: int) -> bool:
        """Check if user is authorized to trigger scrapes."""
        if not AUTHORIZED_SCRAPERS:
            return True  # No restrictions
        return user_id in AUTHORIZED_SCRAPERS

    @app_commands.command(
        name="list-shows",
        description="Browse all TV shows in the database"
    )
    @app_commands.describe(
        sort="Sort by: title, rating, or recent",
        page="Page number (1-based)"
    )
    async def list_shows(
        self,
        interaction: discord.Interaction,
        sort: str = "title",
        page: int = 1
    ):
        """
        List all TV shows in paginated format.
        """
        await interaction.response.defer()

        try:
            # Get paginated results
            page_size = 10
            offset = (page - 1) * page_size
            total, shows = self.db.get_all_titles(
                content_type="tvSeries",
                limit=page_size,
                offset=offset,
                sort_by=sort
            )

            if not shows:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error("No TV shows found in database"),
                    ephemeral=True
                )
                return

            # Create embed
            total_pages = (total + page_size - 1) // page_size
            embed = discord.Embed(
                title="📺 TV Shows in Database",
                color=discord.Color.blue(),
                description=f"Page {page}/{total_pages} • Sorted by {sort} • Total: {total} shows"
            )

            # Add shows to embed
            for i, show in enumerate(shows, 1):
                title = show.get("title", "Unknown")
                rating = show.get("rating", "N/A")
                seasons = show.get("seasons") or "?"
                rating_str = f"⭐ {rating}" if rating != "N/A" else "⭐ Not rated"

                embed.add_field(
                    name=f"{(offset + i)}. {title}",
                    value=f"{rating_str} • {seasons} seasons",
                    inline=False
                )

            embed.set_footer(text=f"Use /scrape-show to add shows to your queue")

            # Create pagination view
            async def page_callback(interaction: discord.Interaction, new_offset: int):
                await interaction.response.defer()
                new_page = (new_offset // page_size) + 1
                new_offset_calc = (new_page - 1) * page_size

                total_titles, shows_data = self.db.get_all_titles(
                    content_type="tvSeries",
                    limit=page_size,
                    offset=new_offset_calc,
                    sort_by=sort
                )

                # Create new embed
                total_pages = (total_titles + page_size - 1) // page_size
                new_embed = discord.Embed(
                    title="📺 TV Shows in Database",
                    color=discord.Color.blue(),
                    description=f"Page {new_page}/{total_pages} • Sorted by {sort} • Total: {total_titles} shows"
                )

                for i, show in enumerate(shows_data, 1):
                    title = show.get("title", "Unknown")
                    rating = show.get("rating", "N/A")
                    seasons = show.get("seasons") or "?"
                    rating_str = f"⭐ {rating}" if rating != "N/A" else "⭐ Not rated"
                    new_embed.add_field(
                        name=f"{(new_offset_calc + i)}. {title}",
                        value=f"{rating_str} • {seasons} seasons",
                        inline=False
                    )

                new_embed.set_footer(text=f"Use /scrape-show to add shows to your queue")

                new_view = PaginationView(page_callback, total_titles, page_size)
                await interaction.followup.send(embed=new_embed, view=new_view)

            view = PaginationView(page_callback, total, page_size)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in list_shows: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="add-show",
        description="Add a TV show to the watchlist queue"
    )
    @app_commands.describe(title="TV show title")
    async def add_show(self, interaction: discord.Interaction, title: str):
        """
        Add a TV show to the scrape queue.
        """
        await interaction.response.defer()

        try:
            logger.info(f"Adding show to queue: {title}")

            # Add to queue
            result = self.db.add_to_queue(title, content_type="tv_series")

            if result.get("success"):
                embed = EmbedFormatter.format_info(
                    "Added to Queue",
                    f"✅ **{title}** added to watchlist!\n\n"
                    f"Use `/pending-shows` to see your queue\n"
                    f"or `/scrape-show {title}` to scrape it now!"
                )
                await interaction.followup.send(embed=embed)
                logger.info(f"Successfully added {title} to queue")
            else:
                error_msg = result.get("error", "Unknown error")
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"Failed to add show: {error_msg}"),
                    ephemeral=True
                )

        except Exception as e:
            logger.error(f"Error in add_show: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="pending-shows",
        description="View shows in your watchlist queue"
    )
    async def pending_shows(self, interaction: discord.Interaction):
        """
        List pending shows in the scrape queue.
        """
        await interaction.response.defer()

        try:
            pending = self.db.get_pending_queue(limit=10)

            if not pending:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_info(
                        "Queue Empty",
                        "No pending shows. Use `/add-show` to add one!"
                    )
                )
                return

            embed = discord.Embed(
                title=f"📺 Watchlist Queue ({len(pending)})",
                color=discord.Color.blue()
            )

            for i, item in enumerate(pending, 1):
                title = item.get("title", "Unknown")
                added = item.get("added_at", "")
                embed.add_field(
                    name=f"{i}. {title}",
                    value=f"Added: {str(added)[:10]}\n"
                          f"Status: {item.get('status')}\n"
                          f"Use: `/scrape-show {title}`",
                    inline=False
                )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in pending_shows: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="scrape-show",
        description="Scrape a TV show from the queue"
    )
    @app_commands.check(brandon_only)
    @app_commands.describe(
        title="TV show title (from queue)",
        force="Force scrape even if already in database"
    )
    async def scrape_show(
        self,
        interaction: discord.Interaction,
        title: str,
        force: bool = False
    ):
        """
        Scrape a TV show from the queue.
        """
        await interaction.response.defer()

        # Check authorization
        if not self.is_authorized_scraper(interaction.user.id):
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(
                    "You are not authorized to trigger scrapes."
                ),
                ephemeral=True
            )
            return

        try:
            logger.info(f"Scrape requested for: {title} by {interaction.user}")

            # Find in queue
            pending = self.db.get_pending_queue(limit=100)
            queue_item = next((item for item in pending if item.get("title").lower() == title.lower()), None)

            if not queue_item:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"'{title}' not found in queue. Use `/add-show` first!"),
                    ephemeral=True
                )
                return

            queue_id = queue_item.get("queue_id")
            imdb_id = queue_item.get("imdb_id")

            # If we already have the IMDb ID, check if it's already in the database
            if imdb_id and not force:
                if self.db.title_exists(imdb_id):
                    series_data = self.db.get_series_by_imdb_id(imdb_id)
                    if series_data:
                        genres = self.db.get_genres(imdb_id)
                        seasons_data = self.db.get_episode_ratings_by_season(imdb_id)
                        embed = EmbedFormatter.format_series_summary(series_data, seasons_data, genres)
                        self.db.update_queue_item(queue_id, status="completed")
                        await interaction.followup.send(embed=embed)
                        logger.info(f"Show {imdb_id} already in database, marked complete")
                        return

            # Need to search and scrape
            if not imdb_id:
                # Try to find it
                logger.info(f"Searching for {title}")
                if search_imdb_graphql:
                    try:
                        results, _, _ = search_imdb_graphql(title, content_type="tvSeries", num_results=1)
                        if results:
                            imdb_id = results[0].get("imdb_id")
                            logger.info(f"Found IMDb ID: {imdb_id}")
                            self.db.update_queue_item(queue_id, imdb_id=imdb_id)
                        else:
                            await interaction.followup.send(
                                embed=EmbedFormatter.format_error(f"Could not find '{title}' on IMDb"),
                                ephemeral=True
                            )
                            return
                    except Exception as e:
                        logger.warning(f"Search failed: {e}")
                        await interaction.followup.send(
                            embed=EmbedFormatter.format_error(f"Could not search for '{title}': {e}"),
                            ephemeral=True
                        )
                        return
                else:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_error("IMDb search unavailable"),
                        ephemeral=True
                    )
                    return

            # Check if already in database
            if self.db.title_exists(imdb_id) and not force:
                series_data = self.db.get_series_by_imdb_id(imdb_id)
                if series_data:
                    genres = self.db.get_genres(imdb_id)
                    seasons_data = self.db.get_episode_ratings_by_season(imdb_id)
                    embed = EmbedFormatter.format_series_summary(series_data, seasons_data, genres)
                    self.db.update_queue_item(queue_id, status="completed")
                    await interaction.followup.send(embed=embed)
                    logger.info(f"Show {imdb_id} already in database, marked complete")
                    return

            # Send status and start scraping
            logger.info(f"Starting scrape for {imdb_id}")
            status_embed = EmbedFormatter.format_scraping_status(title, "starting")
            status_message = await interaction.followup.send(embed=status_embed)

            # Mark as in progress
            self.db.update_queue_item(queue_id, status="in_progress")

            # Spawn scraper
            scrape_result = await ScraperBridge.scrape_show(imdb_id, "tvseries")

            if not scrape_result.get("success"):
                error_msg = scrape_result.get("error", "Unknown error")
                error_embed = EmbedFormatter.format_error(f"Failed to start scrape: {error_msg}")
                await status_message.edit(embed=error_embed)
                self.db.update_queue_item(queue_id, status="failed", error_message=error_msg)
                logger.error(f"Failed to spawn scraper: {error_msg}")
                return

            process = scrape_result.get("process")

            # Update status
            progress_embed = EmbedFormatter.format_scraping_status(
                title,
                "in_progress",
                "This may take 5-15 minutes..."
            )
            await status_message.edit(embed=progress_embed)

            # Poll until complete
            poll_count = 0
            while poll_count < MAX_SCRAPE_POLLS:
                poll_count += 1
                returncode = process.poll()
                if returncode is not None:
                    logger.info(f"Scraper finished with return code {returncode}")

                    if returncode == 0:
                        await asyncio.sleep(1)
                        series_data = self.db.get_series_by_imdb_id(imdb_id)
                        if series_data:
                            genres = self.db.get_genres(imdb_id)
                            seasons_data = self.db.get_episode_ratings_by_season(imdb_id)
                            final_embed = EmbedFormatter.format_series_summary(
                                series_data,
                                seasons_data,
                                genres
                            )
                            await status_message.edit(embed=final_embed)
                            self.db.update_queue_item(queue_id, status="completed")
                            # Update wishlist rating if in wishlist
                            if series_data.get("rating"):
                                self.db.update_wishlist_rating(imdb_id, series_data["rating"])
                        else:
                            error_embed = EmbedFormatter.format_error("Scrape completed but data not found")
                            await status_message.edit(embed=error_embed)
                            self.db.update_queue_item(queue_id, status="failed", error_message="Data not found after scrape")
                    else:
                        error_embed = EmbedFormatter.format_error(f"Scraper failed with return code {returncode}")
                        await status_message.edit(embed=error_embed)
                        self.db.update_queue_item(queue_id, status="failed", error_message=f"Return code {returncode}")

                    return

                await asyncio.sleep(SCRAPER_POLL_INTERVAL)

            # Timeout
            logger.warning(f"Scraper timed out for {imdb_id}")
            timeout_embed = EmbedFormatter.format_error("Scrape timed out after 15 minutes")
            await status_message.edit(embed=timeout_embed)
            self.db.update_queue_item(queue_id, status="failed", error_message="Timeout after 15 minutes")

            if process.returncode is None:
                process.kill()

        except Exception as e:
            logger.error(f"Error in scrape_show: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Unexpected error: {str(e)[:100]}"),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(TVCommandsCog(bot))
    logger.info("TVCommandsCog loaded")
