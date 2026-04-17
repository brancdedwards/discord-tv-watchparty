"""
Discord slash commands for wishlist management.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging
import sys
import asyncio
from pathlib import Path

logger = logging.getLogger(__name__)

# Add parent directory to path for imports
SCRIPT_DIR = Path(__file__).parent.parent  # discord-tv-watchparty/
PARENT_DIR = SCRIPT_DIR.parent  # GitHub/Data Science projects/

# Add discord-tv-watchparty to path for local imports
sys.path.insert(0, str(SCRIPT_DIR))

# Import local utilities
from utils.db_bridge import DatabaseBridge
from utils.embed_formatter import EmbedFormatter
from utils.imdb_search import search_imdb_paginated
from views.scrape_buttons import PaginationView
from config import USERS

logger.info("Successfully imported search_imdb_paginated from local utils")


class WishlistCommandsCog(commands.Cog):
    """Cog for wishlist commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()

    def get_user_name(self, user_id: int) -> str:
        """Get username from Discord user ID."""
        return USERS.get(user_id, f"User {user_id}")

    @app_commands.command(
        name="add-to-wishlist",
        description="Search IMDb and add a show or movie to the shared wishlist"
    )
    @app_commands.describe(
        title="Title to search for"
    )
    async def add_to_wishlist(self, interaction: discord.Interaction, title: str):
        """
        Search IMDb for a show/movie, show paginated results with posters, add to wishlist AND scrape queue.
        """
        # Defer immediately to prevent timeout (must happen within 3 seconds)
        try:
            await interaction.response.defer()
        except Exception as e:
            logger.error(f"Failed to defer: {type(e).__name__}: {e}")
            return

        try:
            if not search_imdb_paginated:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        "IMDb search is unavailable. Please ensure review_analyzer is properly configured."
                    ),
                    ephemeral=True
                )
                return

            logger.info(f"{interaction.user.name} searching IMDb to add to wishlist: {title}")

            # Search IMDb with pagination to get 25+ results (both movies and TV shows mixed)
            results = []

            try:
                # Run search with 15-second timeout to prevent hanging
                loop = asyncio.get_event_loop()
                search_results = await asyncio.wait_for(
                    loop.run_in_executor(None, search_imdb_paginated, title, "all", 25),
                    timeout=15.0
                )
                if search_results:
                    results.extend(search_results)
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        "Search timed out. IMDb is responding slowly. Try again in a moment."
                    ),
                    ephemeral=True
                )
                return
            except Exception as e:
                logger.warning(f"IMDb search failed: {e}")

            if not results:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"No results found for '{title}'"),
                    ephemeral=True
                )
                return

            # Debug: log unsorted results
            logger.info("=== BEFORE SORT ===")
            for i, r in enumerate(results[:5]):
                year = r.get("year", "")
                logger.info(f"  {i+1}. {r.get('title')} - Year: {year} (type: {type(year)})")

            # Sort results by year (oldest first), then by rating (highest first)
            def sort_key(result):
                year = result.get("year", "")
                rating = float(result.get("rating", 0)) if result.get("rating") else 0
                try:
                    year_int = int(year) if year else 9999  # Put unknowns at end
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse year: {year}")
                    year_int = 9999
                sort_tuple = (year_int, -rating)
                return sort_tuple

            results.sort(key=sort_key)

            # Debug: log sorted results
            logger.info("=== AFTER SORT ===")
            for i, r in enumerate(results[:5]):
                year = r.get("year", "")
                rating = r.get("rating", "N/A")
                try:
                    year_int = int(year) if year else 9999
                except:
                    year_int = 9999
                logger.info(f"  {i+1}. {r.get('title')} - Year: {year} (int: {year_int}) - Rating: {rating}")

            # Show paginated search results
            await self._show_search_results_paginated(interaction, title, results)

        except Exception as e:
            logger.error(f"Error in add_to_wishlist: {e}")
            try:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                    ephemeral=True
                )
            except:
                pass

    async def _show_search_results_paginated(self, interaction: discord.Interaction, title: str, results: list):
        """Show paginated search results with buttons."""
        page_size = 5
        total_pages = (len(results) + page_size - 1) // page_size
        current_message = None

        async def show_page(page: int):
            nonlocal current_message
            if page < 1 or page > total_pages:
                page = 1

            start = (page - 1) * page_size
            end = start + page_size
            page_results = results[start:end]

            # Create header embed
            header_embed = discord.Embed(
                title=f"🔍 Search Results for '{title}'",
                color=discord.Color.purple(),
                description=f"Page {page}/{total_pages} • Total: {len(results)} results"
            )

            embeds = [header_embed]

            # Create buttons view for this page
            class PageResultsView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=300)

            view = PageResultsView()

            # Create embeds and buttons for each result on this page
            for page_idx, result in enumerate(page_results, 1):
                result_num = start + page_idx
                imdb_id = result.get("imdb_id", "")
                title_text = result.get("title", "Unknown")
                year = result.get("year", "")

                # Normalize content_type
                raw_type = result.get("type", "").lower()
                if "tv" in raw_type or "series" in raw_type:
                    content_type = "tvSeries"
                else:
                    content_type = "movie"

                poster_url = result.get("poster_url", "")
                already_in_wishlist = self.db.wishlist_item_exists(imdb_id)

                # Create embed for this result
                result_embed = discord.Embed(
                    title=f"{result_num}. {title_text}",
                    color=discord.Color.blurple(),
                    description=f"Year: {year if year else 'Unknown'}"
                )

                # Add type and status
                content_emoji = "📺" if content_type == "tvSeries" else "🎬"
                status = "✅ In Wishlist" if already_in_wishlist else "Ready to add"
                rating_str = f"⭐ {result.get('rating')}" if result.get("rating") else "⭐ Not rated"
                result_embed.add_field(
                    name="Info",
                    value=f"{content_emoji} Type: {'TV Series' if content_type == 'tvSeries' else 'Movie'}\n{rating_str}\n{status}",
                    inline=False
                )

                result_embed.add_field(
                    name="IMDb ID",
                    value=f"`{imdb_id}`",
                    inline=False
                )

                # Add poster image
                if poster_url and poster_url.startswith("http"):
                    result_embed.set_image(url=poster_url)

                embeds.append(result_embed)

                # Create button for adding to wishlist
                async def add_button_callback(btn_interaction: discord.Interaction, result_data=result):
                    await btn_interaction.response.defer()
                    imdb_id_sel = result_data.get("imdb_id", "")
                    title_sel = result_data.get("title", "Unknown")

                    raw_type_sel = result_data.get("type", "").lower()
                    content_type_sel = "tvSeries" if ("tv" in raw_type_sel or "series" in raw_type_sel) else "movie"

                    if self.db.wishlist_item_exists(imdb_id_sel):
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Already in Wishlist",
                                f"**{title_sel}** is already in your wishlist!"
                            ),
                            ephemeral=True
                        )
                        return

                    user_name_btn = self.get_user_name(btn_interaction.user.id)
                    rating_val = result_data.get("rating")
                    success = self.db.add_to_wishlist(imdb_id_sel, title_sel, content_type_sel, user_name_btn, rating_val)

                    if success:
                        self.db.add_to_queue(title_sel, content_type_sel, imdb_id_sel)
                        content_emoji_btn = "📺" if content_type_sel == "tvSeries" else "🎬"
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Added to Wishlist & Queue ✅",
                                f"**{title_sel}** {content_emoji_btn}\n\nAdded by {user_name_btn}\nQueued for scraping"
                            )
                        )
                        logger.info(f"Added '{title_sel}' to wishlist & queue by {user_name_btn}")
                    else:
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_error("Failed to add to wishlist"),
                            ephemeral=True
                        )

                # Add button
                content_emoji = "📺" if content_type == "tvSeries" else "🎬"
                year_suffix = f" ({year})" if year else ""
                button_label = f"{result_num}. {content_emoji} {title_text}{year_suffix}"
                if len(button_label) > 80:
                    max_title_len = 80 - len(f"{result_num}. {content_emoji}  ({year})") - 1
                    button_label = f"{result_num}. {content_emoji} {title_text[:max_title_len]}{year_suffix}"

                button = discord.ui.Button(
                    label=button_label,
                    style=discord.ButtonStyle.primary if not already_in_wishlist else discord.ButtonStyle.secondary
                )
                button.callback = add_button_callback
                view.add_item(button)

            # Add pagination buttons
            if total_pages > 1:
                async def prev_callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.defer()
                    await show_page(page - 1)

                async def next_callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.defer()
                    await show_page(page + 1)

                if page > 1:
                    prev_button = discord.ui.Button(label="⬅️ Previous", style=discord.ButtonStyle.secondary)
                    prev_button.callback = prev_callback
                    view.add_item(prev_button)

                if page < total_pages:
                    next_button = discord.ui.Button(label="Next ➡️", style=discord.ButtonStyle.secondary)
                    next_button.callback = next_callback
                    view.add_item(next_button)

            # Send or edit message
            if page == 1:
                current_message = await interaction.followup.send(embeds=embeds, view=view)
            else:
                await interaction.followup.send(embeds=embeds, view=view)

        # Show first page
        await show_page(1)

    async def _show_wishlist_page(self, interaction: discord.Interaction, page: int = 1):
        """
        Internal method to display a wishlist page.
        Called by both the command and pagination buttons.
        """
        try:
            items = self.db.get_wishlist()

            if not items:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error("Wishlist is empty!"),
                    ephemeral=True
                )
                return

            # Paginate
            page_size = 5
            total = len(items)
            total_pages = (total + page_size - 1) // page_size

            if page < 1 or page > total_pages:
                page = 1

            start = (page - 1) * page_size
            end = start + page_size
            page_items = items[start:end]

            # Create embed
            embed = discord.Embed(
                title="💕 Shared Wishlist",
                color=discord.Color.magenta(),
                description=f"Page {page}/{total_pages} • Total: {total} items"
            )

            for i, item in enumerate(page_items, start=start + 1):
                content_emoji = "📺" if item["content_type"] == "tvSeries" else "🎬"
                rating_str = "" if not item.get("rating") else f" • ⭐ {item.get('rating')}"

                embed.add_field(
                    name=f"{i}. {item['title']}",
                    value=f"{content_emoji} Added by **{item['added_by']}**{rating_str}\nID: `{item['imdb_id']}`",
                    inline=False
                )

            embed.set_footer(text="Use /remove-from-wishlist to remove items")

            # Add pagination buttons if needed
            if total_pages > 1:
                async def page_callback(btn_interaction: discord.Interaction, new_offset: int):
                    await btn_interaction.response.defer()
                    new_page = (new_offset // page_size) + 1
                    logger.info(f"Pagination: offset={new_offset}, page_size={page_size}, new_page={new_page}, total_pages={total_pages}")
                    await self._show_wishlist_page(btn_interaction, page=new_page)

                view = PaginationView(page_callback, total, page_size)
                await interaction.followup.send(embed=embed, view=view)
            else:
                await interaction.followup.send(embed=embed)

        except Exception as e:
            logger.error(f"Error in _show_wishlist_page: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )

    @app_commands.command(
        name="wishlist",
        description="View the shared wishlist"
    )
    @app_commands.describe(
        page="Page number (1-based)"
    )
    async def view_wishlist(self, interaction: discord.Interaction, page: int = 1):
        """
        View the shared wishlist with pagination.
        """
        await interaction.response.defer()
        await self._show_wishlist_page(interaction, page=page)

    @app_commands.command(
        name="remove-from-wishlist",
        description="Remove a show or movie from the wishlist"
    )
    @app_commands.describe(
        title="Title to remove from wishlist"
    )
    async def remove_from_wishlist(self, interaction: discord.Interaction, title: str):
        """
        Remove a title from the wishlist.
        """
        await interaction.response.defer()

        try:
            logger.info(f"{interaction.user.name} removing from wishlist: {title}")

            # Search in wishlist
            wishlist = self.db.get_wishlist()
            matches = [item for item in wishlist if title.lower() in item['title'].lower()]

            if not matches:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        f"'{title}' not found in wishlist"
                    ),
                    ephemeral=True
                )
                return

            if len(matches) == 1:
                # Remove directly
                success = self.db.remove_from_wishlist(matches[0]['imdb_id'])
                if success:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_info(
                            "Removed from Wishlist ✅",
                            f"**{matches[0]['title']}** has been removed"
                        )
                    )
                    logger.info(f"Removed '{matches[0]['title']}' from wishlist")
                else:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_error("Failed to remove from wishlist"),
                        ephemeral=True
                    )
                return

            # Multiple matches - show selection
            embed = discord.Embed(
                title=f"Which one to remove?",
                color=discord.Color.red(),
                description="Multiple matches found"
            )

            for i, item in enumerate(matches[:5], 1):
                content_emoji = "📺" if item["content_type"] == "tvSeries" else "🎬"
                embed.add_field(
                    name=f"{i}. {item['title']}",
                    value=f"{content_emoji} Added by {item['added_by']}",
                    inline=False
                )

            class RemovalView(discord.ui.View):
                def __init__(self):
                    super().__init__(timeout=60)

            view = RemovalView()

            for i, item in enumerate(matches[:5], 1):
                async def button_callback(btn_interaction: discord.Interaction, item_data=item):
                    await btn_interaction.response.defer()
                    success = self.db.remove_from_wishlist(item_data['imdb_id'])
                    if success:
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Removed ✅",
                                f"**{item_data['title']}** removed from wishlist"
                            )
                        )
                        logger.info(f"Removed '{item_data['title']}' from wishlist")

                button = discord.ui.Button(
                    label=f"{i}. {item['title'][:20]}...",
                    style=discord.ButtonStyle.danger
                )
                button.callback = button_callback
                view.add_item(button)

            await interaction.followup.send(embed=embed, view=view)

        except Exception as e:
            logger.error(f"Error in remove_from_wishlist: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=True
            )


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(WishlistCommandsCog(bot))
    logger.info("WishlistCommandsCog loaded")
