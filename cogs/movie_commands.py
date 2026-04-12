"""
Discord slash commands for movie suggestions and scraping.
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
from views.scrape_buttons import IMDbSelectionView, PaginationView
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
                "❌ Only Brandon can scrape movies. Use `/wishlist` to suggest movies instead!"
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


class MovieCommandsCog(commands.Cog):
    """Cog for movie commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()

    def is_authorized_scraper(self, user_id: int) -> bool:
        """Check if user is authorized to trigger scrapes."""
        if not AUTHORIZED_SCRAPERS:
            return True  # No restrictions
        return user_id in AUTHORIZED_SCRAPERS

    @app_commands.command(
        name="add-movie",
        description="Add a movie to the watchlist"
    )
    @app_commands.describe(title="Movie title to search for")
    async def add_movie(self, interaction: discord.Interaction, title: str):
        """
        Search for a movie and add it to watchlist.
        """
        await interaction.response.defer()

        if not search_imdb_graphql:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(
                    "IMDb search is unavailable. Please ensure review_analyzer is properly configured."
                ),
                ephemeral=True
            )
            return

        try:
            logger.info(f"Searching for movie: {title}")

            # Search IMDb for movies
            results, _, _ = search_imdb_graphql(
                title,
                content_type="movie",
                num_results=5
            )

            if not results:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"No movies found matching '{title}'"),
                    ephemeral=True
                )
                return

            # Format search results
            embed = EmbedFormatter.format_imdb_search_results(results)

            # Create selection view
            async def selection_callback(interaction: discord.Interaction, selected: dict):
                imdb_id = selected.get("imdb_id")
                movie_title = selected.get("title")

                # Respond to selection
                confirm_embed = EmbedFormatter.format_info(
                    "Movie Added",
                    f"✅ **{movie_title}** added to suggestions!\n\n"
                    f"Use `/scrape-movie` with this ID to fetch details:\n`{imdb_id}`"
                )
                await interaction.followup.send(embed=confirm_embed)
                logger.info(f"User selected: {movie_title} ({imdb_id})")

            view = IMDbSelectionView(results, selection_callback)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in add_movie: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="scrape-movie",
        description="Scrape and get details for a movie"
    )
    @app_commands.check(brandon_only)
    @app_commands.describe(
        movie_id="IMDb ID (tt...) or movie title",
        skip_if_exists="Skip if already scraped (default: False)"
    )
    async def scrape_movie(
        self,
        interaction: discord.Interaction,
        movie_id: str,
        skip_if_exists: bool = False
    ):
        """
        Scrape a movie and return metadata.
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
            logger.info(f"Movie scrape requested for: {movie_id} by {interaction.user}")

            # Determine IMDb ID
            imdb_id = movie_id if movie_id.startswith("tt") else movie_id
            movie_title = movie_id if not movie_id.startswith("tt") else None

            # Check if movie is already in database
            exists = self.db.series_exists(imdb_id)

            if exists and skip_if_exists:
                logger.info(f"Movie {imdb_id} already scraped, skipping")
                series_data = self.db.get_series_by_imdb_id(imdb_id)
                if series_data:
                    genres = self.db.get_genres(imdb_id)
                    embed = EmbedFormatter.format_series_summary(series_data, {}, genres)
                    await interaction.followup.send(embed=embed)
                    return

            if exists:
                # Movie is already scraped, return cached data
                logger.info(f"Movie {imdb_id} already in database, returning cached data")
                series_data = self.db.get_series_by_imdb_id(imdb_id)
                if series_data:
                    genres = self.db.get_genres(imdb_id)
                    embed = EmbedFormatter.format_series_summary(series_data, {}, genres)
                    await interaction.followup.send(embed=embed)
                    return

            # Not in database, need to scrape
            logger.info(f"Starting scrape for movie {imdb_id}")

            # Send initial status
            status_embed = EmbedFormatter.format_scraping_status(
                movie_title or imdb_id,
                "starting"
            )
            status_message = await interaction.followup.send(embed=status_embed)

            # Spawn scraper
            scrape_result = await ScraperBridge.scrape_show(imdb_id, "movie")

            if not scrape_result.get("success"):
                error_msg = scrape_result.get("error", "Unknown error")
                error_embed = EmbedFormatter.format_error(f"Failed to start scrape: {error_msg}")
                await status_message.edit(embed=error_embed)
                logger.error(f"Failed to spawn scraper: {error_msg}")
                return

            process = scrape_result.get("process")

            # Update status to in_progress
            progress_embed = EmbedFormatter.format_scraping_status(
                movie_title or imdb_id,
                "in_progress",
                "Fetching movie details and reviews... This may take 5-10 minutes."
            )
            await status_message.edit(embed=progress_embed)

            # Poll until complete
            poll_count = 0
            while poll_count < MAX_SCRAPE_POLLS:
                poll_count += 1

                # Check if process finished
                returncode = process.poll()
                if returncode is not None:
                    # Process finished
                    logger.info(f"Movie scraper finished with return code {returncode}")

                    if returncode == 0:
                        # Success - fetch and display data
                        await asyncio.sleep(1)  # Give DB time to sync

                        series_data = self.db.get_series_by_imdb_id(imdb_id)
                        if series_data:
                            genres = self.db.get_genres(imdb_id)
                            final_embed = EmbedFormatter.format_series_summary(
                                series_data,
                                {},  # No seasons for movies
                                genres
                            )
                            await status_message.edit(embed=final_embed)
                        else:
                            error_embed = EmbedFormatter.format_error(
                                "Scrape completed but data not found in database"
                            )
                            await status_message.edit(embed=error_embed)
                    else:
                        # Scraper failed
                        error_embed = EmbedFormatter.format_error(
                            f"Scraper failed with return code {returncode}"
                        )
                        await status_message.edit(embed=error_embed)

                    return

                # Still running, wait before next poll
                await asyncio.sleep(SCRAPER_POLL_INTERVAL)

            # Timeout
            logger.warning(f"Movie scraper timed out for {imdb_id}")
            timeout_embed = EmbedFormatter.format_error(
                "Scrape timed out after 15 minutes. Please try again later."
            )
            await status_message.edit(embed=timeout_embed)

            # Kill process if still running
            if process.returncode is None:
                process.kill()

        except Exception as e:
            logger.error(f"Error in scrape_movie: {e}")
            error_embed = EmbedFormatter.format_error(f"Unexpected error: {str(e)[:100]}")
            await interaction.followup.send(embed=error_embed, ephemeral=True)

    @app_commands.command(
        name="list-movies",
        description="Browse all movies in the database"
    )
    @app_commands.describe(
        sort="Sort by: title, rating, or recent",
        page="Page number (1-based)"
    )
    async def list_movies(
        self,
        interaction: discord.Interaction,
        sort: str = "title",
        page: int = 1
    ):
        """
        List all movies in paginated format.
        """
        await interaction.response.defer()

        try:
            # Get paginated results
            page_size = 10
            offset = (page - 1) * page_size
            total, movies = self.db.get_all_titles(
                content_type="movie",
                limit=page_size,
                offset=offset,
                sort_by=sort
            )

            if not movies:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error("No movies found in database"),
                    ephemeral=True
                )
                return

            # Create embed
            total_pages = (total + page_size - 1) // page_size
            embed = discord.Embed(
                title="🎬 Movies in Database",
                color=discord.Color.gold(),
                description=f"Page {page}/{total_pages} • Sorted by {sort} • Total: {total} movies"
            )

            # Add movies to embed
            for i, movie in enumerate(movies, 1):
                title = movie.get("title", "Unknown")
                rating = movie.get("rating", "N/A")
                rating_str = f"⭐ {rating}" if rating != "N/A" else "⭐ Not rated"

                embed.add_field(
                    name=f"{(offset + i)}. {title}",
                    value=f"{rating_str}",
                    inline=False
                )

            embed.set_footer(text=f"Use /scrape-movie to get full details")

            # Create pagination view
            async def page_callback(interaction: discord.Interaction, new_offset: int):
                await interaction.response.defer()
                new_page = (new_offset // page_size) + 1
                new_offset_calc = (new_page - 1) * page_size

                total_titles, movies_data = self.db.get_all_titles(
                    content_type="movie",
                    limit=page_size,
                    offset=new_offset_calc,
                    sort_by=sort
                )

                # Create new embed
                total_pages = (total_titles + page_size - 1) // page_size
                new_embed = discord.Embed(
                    title="🎬 Movies in Database",
                    color=discord.Color.gold(),
                    description=f"Page {new_page}/{total_pages} • Sorted by {sort} • Total: {total_titles} movies"
                )

                for i, movie in enumerate(movies_data, 1):
                    title = movie.get("title", "Unknown")
                    rating = movie.get("rating", "N/A")
                    rating_str = f"⭐ {rating}" if rating != "N/A" else "⭐ Not rated"
                    new_embed.add_field(
                        name=f"{(new_offset_calc + i)}. {title}",
                        value=f"{rating_str}",
                        inline=False
                    )

                new_embed.set_footer(text=f"Use /scrape-movie to get full details")

                new_view = PaginationView(page_callback, total_titles, page_size)
                await interaction.followup.send(embed=new_embed, view=new_view)

            view = PaginationView(page_callback, total, page_size)
            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in list_movies: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(MovieCommandsCog(bot))
    logger.info("MovieCommandsCog loaded")
