"""
Discord slash commands for wishlist management.
"""
import discord
from discord.ext import commands
from discord import app_commands
import logging
import sys
import asyncio
import random
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
from utils.imdb_search import search_imdb
from config import USERS

logger.info("Successfully imported search_imdb from local utils")


CONTENT_TYPE_LABELS = {
    "all": "Movie or TV",
    "movie": "Movie",
    "tvSeries": "TV Show",
}


class SuggestTitleModal(discord.ui.Modal, title="Suggest something to watch"):
    """Modal for entering a movie or show title from the watchparty panel."""

    title_input = discord.ui.TextInput(
        label="Show or movie title",
        placeholder="The Bear, Arrival, Severance...",
        max_length=120
    )

    def __init__(self, cog: "WishlistCommandsCog", content_type: str = "all"):
        super().__init__()
        self.cog = cog
        self.content_type = content_type
        label = CONTENT_TYPE_LABELS.get(content_type, "Movie or TV")
        self.title_input.label = f"{label} title"

    async def on_submit(self, interaction: discord.Interaction):
        title = str(self.title_input.value).strip()
        logger.info(f"Watchparty modal submitted by {interaction.user}: {title}")
        try:
            await interaction.response.send_message(
                f"Searching {CONTENT_TYPE_LABELS.get(self.content_type, 'IMDb')} for **{title}**...",
                ephemeral=True
            )
            await self.cog.search_and_show_results(
                interaction,
                title,
                content_type=self.content_type,
                ephemeral=True
            )
        except Exception:
            logger.exception("Unhandled error in SuggestTitleModal.on_submit")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Something went wrong while searching. Brandon can check the bot logs.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Something went wrong while searching. Brandon can check the bot logs.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "Discord UI error in SuggestTitleModal",
            exc_info=(type(error), error, error.__traceback__)
        )


class RemoveTitleModal(discord.ui.Modal, title="Remove from wishlist"):
    """Modal for entering a wishlist title to remove."""

    title_input = discord.ui.TextInput(
        label="Title to remove",
        placeholder="Type part of the title",
        max_length=120
    )

    def __init__(self, cog: "WishlistCommandsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        title = str(self.title_input.value).strip()
        logger.info(f"Remove modal submitted by {interaction.user}: {title}")
        try:
            await interaction.response.send_message(
                f"Looking for **{title}** on the shared list...",
                ephemeral=True
            )
            await self.cog.remove_wishlist_by_title(interaction, title, ephemeral=True)
        except Exception:
            logger.exception("Unhandled error in RemoveTitleModal.on_submit")
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Something went wrong while removing that idea. Brandon can check the bot logs.",
                    ephemeral=True
                )
            else:
                await interaction.followup.send(
                    "Something went wrong while removing that idea. Brandon can check the bot logs.",
                    ephemeral=True
                )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "Discord UI error in RemoveTitleModal",
            exc_info=(type(error), error, error.__traceback__)
        )


class WatchpartyPanelView(discord.ui.View):
    """Persistent button panel for non-technical watchparty use."""

    def __init__(self, cog: "WishlistCommandsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Suggest Movie",
        style=discord.ButtonStyle.primary,
        custom_id="watchparty_panel:suggest_movie"
    )
    async def suggest_movie_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestTitleModal(self.cog, content_type="movie"))

    @discord.ui.button(
        label="Suggest TV",
        style=discord.ButtonStyle.primary,
        custom_id="watchparty_panel:suggest_tv"
    )
    async def suggest_tv_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestTitleModal(self.cog, content_type="tvSeries"))

    @discord.ui.button(
        label="Suggest Anything",
        style=discord.ButtonStyle.secondary,
        custom_id="watchparty_panel:suggest_anything"
    )
    async def suggest_anything_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestTitleModal(self.cog, content_type="all"))

    @discord.ui.button(
        label="See Wishlist",
        style=discord.ButtonStyle.secondary,
        custom_id="watchparty_panel:wishlist"
    )
    async def wishlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog._show_wishlist_page(interaction, page=1, ephemeral=True)

    @discord.ui.button(
        label="Pick Tonight",
        style=discord.ButtonStyle.secondary,
        custom_id="watchparty_panel:random"
    )
    async def random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.show_pick_tonight_options(interaction, ephemeral=True)

    @discord.ui.button(
        label="Remove Idea",
        style=discord.ButtonStyle.danger,
        custom_id="watchparty_panel:remove"
    )
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RemoveTitleModal(self.cog))


class LegacyWatchpartyPanelView(discord.ui.View):
    """Compatibility view for pinned panels posted before filters were added."""

    def __init__(self, cog: "WishlistCommandsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Suggest Something",
        style=discord.ButtonStyle.primary,
        custom_id="watchparty_panel:suggest"
    )
    async def legacy_suggest_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestTitleModal(self.cog, content_type="all"))


class SearchAgainView(discord.ui.View):
    """Short-lived helper for trying another search with the same filter."""

    def __init__(self, cog: "WishlistCommandsCog", content_type: str = "all"):
        super().__init__(timeout=300)
        self.cog = cog
        self.content_type = content_type

    @discord.ui.button(label="Search Again", style=discord.ButtonStyle.secondary, row=1)
    async def search_again_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SuggestTitleModal(self.cog, content_type=self.content_type))


class WishlistPageView(discord.ui.View):
    """Actions shown under the shared wishlist."""

    def __init__(
        self,
        cog: "WishlistCommandsCog",
        page: int,
        total_pages: int,
        ephemeral: bool = False
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.page = page
        self.total_pages = total_pages
        self.ephemeral = ephemeral

        if page > 1:
            back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=0)
            back_button.callback = self._back
            self.add_item(back_button)

        if page < total_pages:
            more_button = discord.ui.Button(label="More Ideas", style=discord.ButtonStyle.secondary, row=0)
            more_button.callback = self._more
            self.add_item(more_button)

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog._show_wishlist_page(interaction, page=self.page - 1, ephemeral=self.ephemeral)

    async def _more(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog._show_wishlist_page(interaction, page=self.page + 1, ephemeral=self.ephemeral)

    @discord.ui.button(label="Pick Tonight", style=discord.ButtonStyle.primary, row=1)
    async def pick_random_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_tonight_options(interaction, ephemeral=self.ephemeral)

    @discord.ui.button(label="Remove Idea", style=discord.ButtonStyle.danger, row=1)
    async def remove_idea_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RemoveTitleModal(self.cog))


class RandomPickView(discord.ui.View):
    """Actions shown under a random watchparty pick."""

    def __init__(
        self,
        cog: "WishlistCommandsCog",
        content_type: str = "all",
        genre: str = None,
        ephemeral: bool = False
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.content_type = content_type
        self.genre = genre
        self.ephemeral = ephemeral

    @discord.ui.button(label="Try Another", style=discord.ButtonStyle.secondary)
    async def try_another_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.pick_tonight(
            interaction,
            content_type=self.content_type,
            genre=self.genre,
            ephemeral=self.ephemeral
        )

    @discord.ui.button(label="See Wishlist", style=discord.ButtonStyle.secondary)
    async def see_wishlist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog._show_wishlist_page(interaction, page=1, ephemeral=self.ephemeral)

    @discord.ui.button(label="Change Filters", style=discord.ButtonStyle.secondary)
    async def change_filters_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_tonight_options(interaction, ephemeral=self.ephemeral)


class PickTonightTypeView(discord.ui.View):
    """First step in the Pick Tonight workflow."""

    def __init__(self, cog: "WishlistCommandsCog", ephemeral: bool = False):
        super().__init__(timeout=300)
        self.cog = cog
        self.ephemeral = ephemeral

    @discord.ui.button(label="Movies", style=discord.ButtonStyle.primary)
    async def movies_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_genre_options(interaction, content_type="movie", ephemeral=self.ephemeral)

    @discord.ui.button(label="TV Shows", style=discord.ButtonStyle.primary)
    async def tv_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_genre_options(interaction, content_type="tvSeries", ephemeral=self.ephemeral)

    @discord.ui.button(label="Anything", style=discord.ButtonStyle.secondary)
    async def anything_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_genre_options(interaction, content_type="all", ephemeral=self.ephemeral)


class PickTonightGenreView(discord.ui.View):
    """Second step in the Pick Tonight workflow."""

    def __init__(
        self,
        cog: "WishlistCommandsCog",
        content_type: str,
        genres: list,
        ephemeral: bool = False
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.content_type = content_type
        self.ephemeral = ephemeral

        surprise_button = discord.ui.Button(label="Surprise Me", style=discord.ButtonStyle.primary, row=0)
        surprise_button.callback = self._surprise
        self.add_item(surprise_button)

        for index, genre in enumerate(genres[:4]):
            button = discord.ui.Button(label=genre[:80], style=discord.ButtonStyle.secondary, row=0)
            button.callback = self._genre_callback(genre)
            self.add_item(button)

        back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
        back_button.callback = self._back
        self.add_item(back_button)

    async def _surprise(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.pick_tonight(
            interaction,
            content_type=self.content_type,
            genre=None,
            ephemeral=self.ephemeral
        )

    def _genre_callback(self, genre: str):
        async def callback(interaction: discord.Interaction):
            await interaction.response.defer(ephemeral=self.ephemeral)
            await self.cog.pick_tonight(
                interaction,
                content_type=self.content_type,
                genre=genre,
                ephemeral=self.ephemeral
            )

        return callback

    async def _back(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=self.ephemeral)
        await self.cog.show_pick_tonight_options(interaction, ephemeral=self.ephemeral)


class WishlistCommandsCog(commands.Cog):
    """Cog for wishlist commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()
        self.bot.add_view(WatchpartyPanelView(self))
        self.bot.add_view(LegacyWatchpartyPanelView(self))

    def get_user_name(self, user_id: int) -> str:
        """Get username from Discord user ID."""
        return USERS.get(user_id, f"User {user_id}")

    @staticmethod
    def create_panel_embed() -> discord.Embed:
        """Create the pinned watchparty control panel embed."""
        embed = discord.Embed(
            title="The Living Room",
            description="Suggest something, browse the shared list, or let the bot pick an idea.",
            color=discord.Color.gold()
        )
        embed.add_field(
            name="Shared Ideas",
            value="Everything you add lands on the same list for both of you.",
            inline=False
        )
        embed.set_footer(text="Pin this message so it is easy to find.")
        return embed

    @app_commands.command(
        name="watchparty-panel",
        description="Post the button panel for the shared watchparty wishlist"
    )
    @app_commands.describe(pin="Try to pin the panel after posting it")
    async def watchparty_panel(self, interaction: discord.Interaction, pin: bool = True):
        """
        Post a persistent button panel that can be pinned in the channel.
        """
        await interaction.response.defer()
        message = await interaction.followup.send(
            embed=self.create_panel_embed(),
            view=WatchpartyPanelView(self),
            wait=True
        )

        if pin:
            try:
                await message.pin(reason="Watchparty panel")
            except discord.Forbidden:
                await interaction.followup.send(
                    "I posted the panel, but I do not have permission to pin it.",
                    ephemeral=True
                )
            except discord.HTTPException as e:
                logger.warning(f"Failed to pin watchparty panel: {e}")

    async def search_and_show_results(
        self,
        interaction: discord.Interaction,
        title: str,
        content_type: str = "all",
        ephemeral: bool = False
    ):
        """Search IMDb and show selectable wishlist results."""
        if not title:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Type a title to search for."),
                ephemeral=ephemeral
            )
            return

        if not search_imdb:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(
                    "Search is unavailable right now. Brandon can check the bot logs."
                ),
                ephemeral=ephemeral
            )
            return

        logger.info(f"{interaction.user.name} searching IMDb to add to wishlist: {title}")

        try:
            loop = asyncio.get_event_loop()
            results = await asyncio.wait_for(
                loop.run_in_executor(None, search_imdb, title, content_type),
                timeout=15.0
            )
        except asyncio.TimeoutError:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(
                    "Search timed out. IMDb is responding slowly. Try again in a moment."
                ),
                ephemeral=ephemeral
            )
            return
        except Exception as e:
            logger.warning(f"IMDb search failed: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_info(
                    "Search Did Not Finish",
                    f"I could not search for **{title}** right now. Try again in a minute."
                ),
                ephemeral=ephemeral
            )
            return

        if not results:
            await interaction.followup.send(
                embed=EmbedFormatter.format_info(
                    "No Matches Found",
                    f"I did not find any {CONTENT_TYPE_LABELS.get(content_type, 'title').lower()} matches for **{title}**.\n\n"
                    "Try again in a minute or try a more specific title."
                ),
                view=SearchAgainView(self, content_type),
                ephemeral=ephemeral
            )
            return

        results.sort(key=lambda result: self._search_result_sort_key(result, title))
        await self._show_search_results_paginated(
            interaction,
            title,
            results,
            content_type=content_type,
            ephemeral=ephemeral
        )

    @app_commands.command(
        name="add-to-wishlist",
        description="Search IMDb and add a show or movie to the shared wishlist"
    )
    @app_commands.describe(
        title="Title to search for",
        kind="What kind of title to search for"
    )
    @app_commands.choices(kind=[
        app_commands.Choice(name="Movies", value="movie"),
        app_commands.Choice(name="TV Shows", value="tvSeries"),
        app_commands.Choice(name="Both", value="all"),
    ])
    async def add_to_wishlist(
        self,
        interaction: discord.Interaction,
        title: str,
        kind: app_commands.Choice[str] = None
    ):
        """
        Search for a show/movie, show results with posters, and add one to the shared list.
        """
        # Defer immediately to prevent timeout (must happen within 3 seconds)
        try:
            await interaction.response.defer()
        except Exception as e:
            logger.error(f"Failed to defer: {type(e).__name__}: {e}")
            return

        try:
            content_type = kind.value if kind else "all"
            await self.search_and_show_results(
                interaction,
                title,
                content_type=content_type,
                ephemeral=False
            )

        except Exception as e:
            logger.error(f"Error in add_to_wishlist: {e}")
            try:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                    ephemeral=True
                )
            except:
                pass

    async def _show_search_results_paginated(
        self,
        interaction: discord.Interaction,
        title: str,
        results: list,
        content_type: str = "all",
        ephemeral: bool = False
    ):
        """Show paginated search results with buttons."""
        page_size = 3
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
                title=f"Search Results for '{title}'",
                color=discord.Color.purple(),
                description=f"{CONTENT_TYPE_LABELS.get(content_type, 'Movie or TV')} • Page {page}/{total_pages} • Total: {len(results)}"
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

                result_content_type = self._normalize_result_content_type(result)
                poster_url = result.get("poster_url", "")
                already_in_wishlist = self.db.wishlist_item_exists(imdb_id)

                # Create embed for this result
                type_label = self._result_type_label(result_content_type)
                result_embed = discord.Embed(
                    title=f"{result_num}. {type_label} · {title_text}",
                    color=discord.Color.blurple(),
                    description=self._format_search_result_description(
                        result,
                        result_content_type,
                        already_in_wishlist
                    )
                )

                # Add poster image
                if poster_url and poster_url.startswith("http"):
                    result_embed.set_image(url=poster_url)

                embeds.append(result_embed)

                # Create button for adding to wishlist
                async def add_button_callback(btn_interaction: discord.Interaction, result_data=result):
                    await btn_interaction.response.defer(ephemeral=ephemeral)
                    imdb_id_sel = result_data.get("imdb_id", "")
                    title_sel = result_data.get("title", "Unknown")

                    content_type_sel = self._normalize_result_content_type(result_data)

                    if self.db.wishlist_item_exists(imdb_id_sel):
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Already on the List",
                                f"**{title_sel}** is already on the shared list."
                            ),
                            ephemeral=ephemeral
                        )
                        return

                    user_name_btn = self.get_user_name(btn_interaction.user.id)
                    rating_val = result_data.get("rating")
                    success = self.db.add_to_wishlist(imdb_id_sel, title_sel, content_type_sel, user_name_btn, rating_val)

                    if success:
                        self.db.add_to_queue(
                            title=title_sel,
                            content_type=content_type_sel,
                            imdb_id=imdb_id_sel,
                            year=self._parse_year(result_data.get("year")),
                            poster_url=result_data.get("poster_url"),
                            rating=rating_val
                        )
                        content_label = "TV series" if content_type_sel == "tvSeries" else "movie"
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Added to Shared List",
                                f"**{title_sel}** is on the shared list.\n\nAdded by {user_name_btn} • {content_label}"
                            ),
                            ephemeral=ephemeral
                        )
                        if ephemeral and btn_interaction.channel:
                            try:
                                await btn_interaction.channel.send(
                                    embed=EmbedFormatter.format_info(
                                        "New Watchparty Idea",
                                        f"**{title_sel}** was added by {user_name_btn}."
                                    )
                                )
                            except discord.HTTPException as e:
                                logger.warning(f"Could not announce wishlist add: {e}")
                        logger.info(f"Added '{title_sel}' to wishlist & queue by {user_name_btn}")
                    else:
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_error("I could not save that idea. Try again in a moment."),
                            ephemeral=ephemeral
                        )

                # Add button
                button_label = self._format_result_button_label(
                    result_num,
                    result_content_type,
                    title_text,
                    year,
                    already_in_wishlist
                )
                button = discord.ui.Button(
                    label=button_label,
                    style=discord.ButtonStyle.primary if not already_in_wishlist else discord.ButtonStyle.secondary,
                    disabled=already_in_wishlist,
                    row=0
                )
                if not already_in_wishlist:
                    button.callback = add_button_callback
                view.add_item(button)

            # Add pagination buttons
            async def search_again_callback(btn_interaction: discord.Interaction):
                await btn_interaction.response.send_modal(SuggestTitleModal(self, content_type=content_type))

            if total_pages > 1:
                async def prev_callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.defer(ephemeral=ephemeral)
                    await show_page(page - 1)

                async def next_callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.defer(ephemeral=ephemeral)
                    await show_page(page + 1)

                if page > 1:
                    prev_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
                    prev_button.callback = prev_callback
                    view.add_item(prev_button)

                if page < total_pages:
                    next_button = discord.ui.Button(label="More Results", style=discord.ButtonStyle.secondary, row=1)
                    next_button.callback = next_callback
                    view.add_item(next_button)

            search_again_button = discord.ui.Button(label="Search Again", style=discord.ButtonStyle.secondary, row=1)
            search_again_button.callback = search_again_callback
            view.add_item(search_again_button)

            # Send or edit message
            if page == 1:
                current_message = await interaction.followup.send(embeds=embeds, view=view, ephemeral=ephemeral)
            else:
                await interaction.followup.send(embeds=embeds, view=view, ephemeral=ephemeral)

        # Show first page
        await show_page(1)

    @staticmethod
    def _normalize_result_content_type(result: dict) -> str:
        raw_type = str(result.get("type") or result.get("content_type") or "").lower()
        if "tv" in raw_type or "series" in raw_type:
            return "tvSeries"
        return "movie"

    @staticmethod
    def _result_type_label(content_type: str) -> str:
        return "TV Show" if content_type == "tvSeries" else "Movie"

    @staticmethod
    def _truncate_text(value: str, max_length: int = 140) -> str:
        if not value:
            return ""
        value = " ".join(str(value).split())
        if len(value) <= max_length:
            return value
        return value[:max_length - 3].rstrip() + "..."

    def _format_search_result_description(
        self,
        result: dict,
        result_content_type: str,
        already_in_wishlist: bool
    ) -> str:
        year = result.get("year_range") or result.get("year") or "Year unknown"
        rating = result.get("rating")
        rating_label = f"Rating {rating}" if rating else "Rating unavailable"
        status = "Already on the shared list" if already_in_wishlist else "Ready to add"

        lines = [
            f"{self._result_type_label(result_content_type)} • {year} • {rating_label} • {status}"
        ]

        genres = [genre for genre in result.get("genres", []) if genre]
        if genres:
            lines.append("Genres: " + ", ".join(genres[:3]))

        summary = self._truncate_text(result.get("summary") or result.get("type_description"), 140)
        if summary:
            lines.append(summary)

        return "\n".join(lines)

    def _format_result_button_label(
        self,
        result_num: int,
        result_content_type: str,
        title: str,
        year,
        already_in_wishlist: bool
    ) -> str:
        type_label = self._result_type_label(result_content_type)
        year_suffix = f" ({year})" if year else ""
        status_suffix = " - added" if already_in_wishlist else ""
        prefix = f"{result_num}. {type_label} · "
        max_title_len = 80 - len(prefix) - len(year_suffix) - len(status_suffix)
        safe_title = title if len(title) <= max_title_len else title[:max_title_len - 3].rstrip() + "..."
        return f"{prefix}{safe_title}{year_suffix}{status_suffix}"

    def _format_wishlist_item_line(self, item: dict) -> str:
        content_label = self._result_type_label(item.get("content_type"))
        rating_str = "" if not item.get("rating") else f" • Rating {item.get('rating')}"
        added_by = item.get("added_by") or "Someone"
        added_at = item.get("added_at")

        if added_at:
            try:
                added_str = f" • Added {added_at.strftime('%b %-d')}"
            except ValueError:
                added_str = f" • Added {added_at.strftime('%b %d')}"
        else:
            added_str = ""

        return f"{content_label} • Added by **{added_by}**{rating_str}{added_str}"

    def _format_random_wishlist_pick_embed(self, item: dict) -> discord.Embed:
        content_label = self._result_type_label(item.get("content_type"))
        rating_str = "" if not item.get("rating") else f"\nRating: {item.get('rating')}"
        added_by = item.get("added_by") or "Someone"
        genre_str = ""
        if item.get("genres"):
            genre_str = "\nGenres: " + ", ".join(item["genres"][:3])

        embed = discord.Embed(
            title=item.get("title", "Random Pick"),
            color=discord.Color.gold(),
            description=f"This is the pick from the shared list.\n\n{content_label} • Added by {added_by}{rating_str}{genre_str}"
        )
        embed.set_footer(text="Not feeling it? Try another.")
        return embed

    def _wishlist_item_matches_content_type(self, item: dict, content_type: str) -> bool:
        if content_type == "all":
            return True
        return self._normalize_result_content_type(item) == content_type

    def _get_wishlist_candidates(self, content_type: str = "all", genre: str = None) -> list:
        items = [
            item for item in self.db.get_wishlist()
            if self._wishlist_item_matches_content_type(item, content_type)
        ]

        if not genre:
            return items

        matches = []
        for item in items:
            genres = self.db.get_genres(item["imdb_id"])
            if any(existing.lower() == genre.lower() for existing in genres):
                item = dict(item)
                item["genres"] = genres
                matches.append(item)

        return matches

    def _get_genre_counts(self, items: list) -> dict:
        genre_counts = {}
        for item in items:
            for genre in self.db.get_genres(item["imdb_id"]):
                genre_counts[genre] = genre_counts.get(genre, 0) + 1
        return genre_counts

    def _format_pick_scope(self, content_type: str, genre: str = None) -> str:
        label = CONTENT_TYPE_LABELS.get(content_type, "Movie or TV")
        if genre:
            return f"{label} • {genre}"
        return label

    @staticmethod
    def _normalize_title_for_sort(title: str) -> str:
        normalized = "".join(ch.lower() for ch in title if ch.isalnum() or ch.isspace()).strip()
        if normalized.startswith("the "):
            normalized = normalized[4:]
        return " ".join(normalized.split())

    def _search_result_sort_key(self, result: dict, query: str):
        result_title = self._normalize_title_for_sort(result.get("title", ""))
        query_title = self._normalize_title_for_sort(query)
        rating = float(result.get("rating", 0)) if result.get("rating") else 0
        source_rank = result.get("source_rank")
        if source_rank is None:
            source_rank = 9999
        year = self._parse_year(result.get("year")) or 0

        if result_title == query_title:
            match_rank = 0
        elif result_title.startswith(query_title):
            match_rank = 1
        elif query_title in result_title:
            match_rank = 2
        else:
            match_rank = 3

        return (match_rank, source_rank, -rating, -year, result_title)

    @staticmethod
    def _parse_year(year_value):
        """Return an int year when IMDb search gives us a clean year."""
        try:
            return int(year_value) if year_value else None
        except (TypeError, ValueError):
            return None

    async def _show_wishlist_page(
        self,
        interaction: discord.Interaction,
        page: int = 1,
        ephemeral: bool = False
    ):
        """
        Internal method to display a wishlist page.
        Called by both the command and pagination buttons.
        """
        try:
            items = self.db.get_wishlist()

            if not items:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_info("No Ideas Yet", "The shared list is empty."),
                    ephemeral=ephemeral
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
                title="Shared Watch Ideas",
                color=discord.Color.magenta(),
                description=f"Page {page}/{total_pages} • {total} idea(s)"
            )

            for i, item in enumerate(page_items, start=start + 1):
                embed.add_field(
                    name=f"{i}. {item['title']}",
                    value=self._format_wishlist_item_line(item),
                    inline=False
                )

            embed.set_footer(text="Pick from this list, add more ideas, or remove one by title.")

            view = WishlistPageView(self, page=page, total_pages=total_pages, ephemeral=ephemeral)
            await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)

        except Exception as e:
            logger.error(f"Error in _show_wishlist_page: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=ephemeral
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

    async def show_pick_tonight_options(
        self,
        interaction: discord.Interaction,
        ephemeral: bool = False
    ):
        """Start the Pick Tonight workflow."""
        items = self.db.get_wishlist()
        if not items:
            await interaction.followup.send(
                embed=EmbedFormatter.format_info(
                    "No Ideas Yet",
                    "The shared list is empty. Add a movie or show first, then I can pick one."
                ),
                ephemeral=ephemeral
            )
            return

        movies = sum(1 for item in items if self._wishlist_item_matches_content_type(item, "movie"))
        tv_shows = sum(1 for item in items if self._wishlist_item_matches_content_type(item, "tvSeries"))

        embed = discord.Embed(
            title="Pick Tonight",
            color=discord.Color.gold(),
            description="What kind of idea should I pick from the shared list?"
        )
        embed.add_field(name="Movies", value=str(movies), inline=True)
        embed.add_field(name="TV Shows", value=str(tv_shows), inline=True)
        embed.add_field(name="Anything", value=str(len(items)), inline=True)

        await interaction.followup.send(
            embed=embed,
            view=PickTonightTypeView(self, ephemeral=ephemeral),
            ephemeral=ephemeral
        )

    async def show_pick_genre_options(
        self,
        interaction: discord.Interaction,
        content_type: str = "all",
        ephemeral: bool = False
    ):
        """Show genre choices for the selected Pick Tonight type."""
        candidates = self._get_wishlist_candidates(content_type=content_type)
        if not candidates:
            await interaction.followup.send(
                embed=EmbedFormatter.format_info(
                    "No Matching Ideas",
                    f"There are no {CONTENT_TYPE_LABELS.get(content_type, 'matching').lower()} ideas on the shared list yet."
                ),
                view=PickTonightTypeView(self, ephemeral=ephemeral),
                ephemeral=ephemeral
            )
            return

        genre_counts = self._get_genre_counts(candidates)
        top_genres = [
            genre
            for genre, _ in sorted(genre_counts.items(), key=lambda item: (-item[1], item[0]))[:4]
        ]

        embed = discord.Embed(
            title="Pick Tonight",
            color=discord.Color.gold(),
            description=f"{self._format_pick_scope(content_type)} • {len(candidates)} idea(s)"
        )

        if top_genres:
            genre_lines = [
                f"{genre} ({genre_counts[genre]})"
                for genre in top_genres
            ]
            embed.add_field(name="Genre Options", value="\n".join(genre_lines), inline=False)
        else:
            embed.add_field(
                name="Genre Options",
                value="No scraped genre data yet. I can still surprise-pick from this set.",
                inline=False
            )

        await interaction.followup.send(
            embed=embed,
            view=PickTonightGenreView(
                self,
                content_type=content_type,
                genres=top_genres,
                ephemeral=ephemeral
            ),
            ephemeral=ephemeral
        )

    async def pick_tonight(
        self,
        interaction: discord.Interaction,
        content_type: str = "all",
        genre: str = None,
        ephemeral: bool = False
    ):
        """Pick a title from the shared wishlist using optional type and genre filters."""
        try:
            candidates = self._get_wishlist_candidates(content_type=content_type, genre=genre)
            if not candidates:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_info(
                        "No Matching Ideas",
                        f"I could not find anything for **{self._format_pick_scope(content_type, genre)}** on the shared list."
                    ),
                    view=PickTonightTypeView(self, ephemeral=ephemeral),
                    ephemeral=ephemeral
                )
                return

            selected_item = random.choice(candidates)
            if "genres" not in selected_item:
                genres = self.db.get_genres(selected_item["imdb_id"])
                if genres:
                    selected_item = dict(selected_item)
                    selected_item["genres"] = genres

            embed = self._format_random_wishlist_pick_embed(selected_item)
            embed.description = (
                f"{embed.description}\n\n"
                f"Filter: {self._format_pick_scope(content_type, genre)}"
            )

            await interaction.followup.send(
                embed=embed,
                view=RandomPickView(
                    self,
                    content_type=content_type,
                    genre=genre,
                    ephemeral=ephemeral
                ),
                ephemeral=ephemeral
            )

        except Exception as e:
            logger.error(f"Error picking tonight: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=ephemeral
            )

    async def show_random_suggestion(
        self,
        interaction: discord.Interaction,
        ephemeral: bool = False
    ):
        """Compatibility wrapper for older random-pick callbacks."""
        await self.pick_tonight(interaction, content_type="all", genre=None, ephemeral=ephemeral)

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

        await self.remove_wishlist_by_title(interaction, title, ephemeral=False)

    async def remove_wishlist_by_title(
        self,
        interaction: discord.Interaction,
        title: str,
        ephemeral: bool = False
    ):
        """Remove an item from the wishlist, asking with buttons when there are multiple matches."""
        if not title:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Type part of the title to remove from the shared list."),
                ephemeral=ephemeral
            )
            return

        try:
            logger.info(f"{interaction.user.name} removing from wishlist: {title}")

            # Search in wishlist
            wishlist = self.db.get_wishlist()
            matches = [item for item in wishlist if title.lower() in item['title'].lower()]

            if not matches:
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        f"I could not find **{title}** on the shared list."
                    ),
                    ephemeral=ephemeral
                )
                return

            if len(matches) == 1:
                # Remove directly
                success = self.db.remove_from_wishlist(matches[0]['imdb_id'])
                if success:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_info(
                            "Removed from Shared List",
                            f"**{matches[0]['title']}** has been removed"
                        ),
                        ephemeral=ephemeral
                    )
                    logger.info(f"Removed '{matches[0]['title']}' from wishlist")
                else:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_error("I could not remove that idea. Try again in a moment."),
                        ephemeral=ephemeral
                    )
                return

            # Multiple matches - show selection
            embed = discord.Embed(
                title=f"Which one would you like to remove?",
                color=discord.Color.red(),
                description="Multiple matches found"
            )

            for i, item in enumerate(matches[:5], 1):
                content_emoji = "TV" if item["content_type"] == "tvSeries" else "Movie"
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
                    await btn_interaction.response.defer(ephemeral=ephemeral)
                    success = self.db.remove_from_wishlist(item_data['imdb_id'])
                    if success:
                        await btn_interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Removed",
                                f"**{item_data['title']}** removed from wishlist"
                            ),
                            ephemeral=ephemeral
                        )
                        logger.info(f"Removed '{item_data['title']}' from wishlist")

                button = discord.ui.Button(
                    label=f"{i}. {item['title'][:20]}...",
                    style=discord.ButtonStyle.danger
                )
                button.callback = button_callback
                view.add_item(button)

            await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)

        except Exception as e:
            logger.error(f"Error in remove_from_wishlist: {e}")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Error: {str(e)[:100]}"),
                ephemeral=ephemeral
            )


async def setup(bot: commands.Bot):
    """Load the cog."""
    await bot.add_cog(WishlistCommandsCog(bot))
    logger.info("WishlistCommandsCog loaded")
