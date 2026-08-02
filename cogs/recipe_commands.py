"""
Discord slash commands for recipe capture and extraction.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import sys
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

from utils.embed_formatter import EmbedFormatter
from utils.db_bridge import DatabaseBridge
from utils.youtube_recipe_extractor import extract_youtube_recipe


def _is_youtube_url(url: str) -> bool:
    lowered = url.lower()
    return "youtube.com/" in lowered or "youtu.be/" in lowered


def _format_source_labels(sources: list[str]) -> str:
    labels = {
        "youtube_api_description": "YouTube description",
        "youtube_oembed": "YouTube video metadata",
        "watch_page_description": "YouTube watch page",
        "caption_transcript": "captions/transcript",
        "youtube_api_comments": "YouTube comments",
    }
    return ", ".join(labels.get(source, source.replace("_", " ")) for source in sources)


def _recipe_next_step(extraction) -> str:
    if extraction.recipe_status == "complete_recipe":
        return "I found ingredients and steps. Give it a quick review before treating it as final."
    if extraction.recipe_status == "partial_recipe":
        if extraction.ingredients and not extraction.instructions:
            return "I found ingredients, but no written steps. Add notes if you want this to become a full recipe."
        if extraction.instructions and not extraction.ingredients:
            return "I found possible steps, but no ingredient list. Add notes if you want this to become a full recipe."
        return "I found some recipe text, but it may need notes or missing steps filled in."
    if extraction.recipe_status == "video_only":
        return "I found the video, but not ingredients or steps. Add notes if you want this to become a searchable recipe."
    if extraction.recipe_status == "inspiration_only":
        return "I saved this as an idea. Add a recipe name, ingredients, or notes when you have them."
    return "Review this before saving it as a recipe."


def _clean_video_description(description: str) -> str:
    lines = []
    for line in description.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        if stripped.startswith(("http://", "https://", "www.")):
            continue
        if any(marker in lowered for marker in ["follow me", "instagram:", "tik tok:", "twitter:", "facebook:", "subreddit:"]):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def _format_captured_time(captured_at: str | None) -> str:
    if not captured_at:
        return "Captured just now"
    try:
        captured = datetime.fromisoformat(captured_at)
        return f"Captured {discord.utils.format_dt(captured, style='f')}"
    except ValueError:
        return "Captured just now"


def _snapshot_text(extraction) -> str:
    description = _clean_video_description(extraction.description)
    if not description:
        return ""
    return EmbedFormatter.truncate(description, 700)


def _format_recipe_extraction_embed(extraction, submitted_by) -> discord.Embed:
    status_labels = {
        "complete_recipe": "Complete recipe",
        "partial_recipe": "Partial recipe",
        "video_only": "Video/recipe idea",
        "inspiration_only": "Idea saved",
        "not_recipe": "Not a recipe",
    }
    status_label = status_labels.get(extraction.recipe_status, extraction.recipe_status)

    color = {
        "complete_recipe": discord.Color.green(),
        "partial_recipe": discord.Color.gold(),
        "video_only": discord.Color.blurple(),
        "inspiration_only": discord.Color.light_grey(),
        "not_recipe": discord.Color.red(),
    }.get(extraction.recipe_status, discord.Color.blurple())

    title = extraction.recipe_title or extraction.title or "Recipe idea"
    embed = discord.Embed(title=title, url=extraction.url, color=color)
    try:
        embed.timestamp = datetime.fromisoformat(extraction.captured_at)
    except (TypeError, ValueError):
        embed.timestamp = discord.utils.utcnow()
    source_text = _format_source_labels(extraction.extraction_sources) or "No extractable source found"
    embed.description = (
        f"**Status:** {status_label}\n"
        f"**Confidence:** {extraction.confidence.title()}\n"
        f"**Source:** {source_text}\n"
        f"**Snapshot:** {_format_captured_time(extraction.captured_at)}"
    )

    if extraction.title and extraction.title != title:
        embed.add_field(
            name="YouTube Title",
            value=EmbedFormatter.truncate(extraction.title, 256),
            inline=False,
        )

    if extraction.channel:
        embed.add_field(name="Channel", value=extraction.channel, inline=True)

    if extraction.tags:
        embed.add_field(name="Tags", value=", ".join(extraction.tags[:8]), inline=True)

    if extraction.recipe_status == "partial_recipe":
        missing_parts = []
        if not extraction.ingredients:
            missing_parts.append("ingredients")
        if not extraction.instructions:
            missing_parts.append("steps")
        if missing_parts:
            embed.add_field(
                name="Recipe Text",
                value=f"Found partial recipe text. Missing: {', '.join(missing_parts)}.",
                inline=False,
            )

    if extraction.recipe_status == "video_only" and not extraction.ingredients and not extraction.instructions:
        snapshot = _snapshot_text(extraction)
        if snapshot:
            embed.add_field(
                name="Source Snapshot",
                value=snapshot,
                inline=False,
            )
        if extraction.title and "#shorts" in extraction.title.lower():
            embed.add_field(
                name="Shorts Note",
                value="YouTube Shorts often do not include full recipe text, so this is saved as a video idea.",
                inline=False,
            )

    if extraction.recipe_status in {"partial_recipe", "inspiration_only"} and not extraction.ingredients:
        snapshot = _snapshot_text(extraction)
        if snapshot:
            embed.add_field(
                name="Source Snapshot",
                value=snapshot,
                inline=False,
            )

    if extraction.source_links:
        links = "\n".join(extraction.source_links[:3])
        if len(extraction.source_links) > 3:
            links += f"\n...and {len(extraction.source_links) - 3} more"
        embed.add_field(
            name="Links Found",
            value=EmbedFormatter.truncate(links, 700),
            inline=False,
        )

    if extraction.ingredients:
        ingredients = "\n".join(f"- {ingredient}" for ingredient in extraction.ingredients[:12])
        if len(extraction.ingredients) > 12:
            ingredients += f"\n...and {len(extraction.ingredients) - 12} more"
        embed.add_field(
            name="Ingredients Found",
            value=EmbedFormatter.truncate(ingredients),
            inline=False,
        )

    if extraction.instructions:
        steps = "\n".join(f"{index}. {step}" for index, step in enumerate(extraction.instructions[:6], 1))
        if len(extraction.instructions) > 6:
            steps += f"\n...and {len(extraction.instructions) - 6} more"
        embed.add_field(
            name="Steps Found",
            value=EmbedFormatter.truncate(steps),
            inline=False,
        )

    if extraction.warnings:
        embed.add_field(
            name="Warnings",
            value=EmbedFormatter.truncate("\n".join(extraction.warnings[:2])),
            inline=False,
        )

    embed.add_field(
        name="Next Step",
        value=_recipe_next_step(extraction),
        inline=False,
    )
    embed.set_footer(text=f"Submitted by {submitted_by.display_name}")
    return embed


def _recipe_status_label(status: str) -> str:
    labels = {
        "complete_recipe": "Complete recipe",
        "partial_recipe": "Partial recipe",
        "video_only": "Video idea",
        "inspiration_only": "Idea saved",
        "idea_saved": "Idea saved",
        "needs_review": "Needs review",
    }
    return labels.get(status, status.replace("_", " ").title())


def _recipe_color(status: str) -> discord.Color:
    return {
        "complete_recipe": discord.Color.green(),
        "partial_recipe": discord.Color.gold(),
        "video_only": discord.Color.blurple(),
        "inspiration_only": discord.Color.light_grey(),
        "idea_saved": discord.Color.light_grey(),
        "needs_review": discord.Color.gold(),
    }.get(status, discord.Color.blurple())


def _recipe_from_extraction(extraction, added_by: str, notes: str | None = None) -> dict:
    return {
        "title": extraction.recipe_title or extraction.title or "Recipe idea",
        "source_url": extraction.url,
        "source_type": "youtube",
        "source_video_id": extraction.video_id,
        "source_title": extraction.title,
        "channel": extraction.channel,
        "status": extraction.recipe_status,
        "confidence": extraction.confidence,
        "added_by": added_by,
        "notes": notes,
        "source_description": extraction.description,
        "source_links": extraction.source_links,
        "ingredients": extraction.ingredients,
        "instructions": extraction.instructions,
        "tags": extraction.tags,
        "extraction_sources": extraction.extraction_sources,
        "warnings": extraction.warnings,
        "captured_at": extraction.captured_at,
    }


def _manual_recipe_payload(
    title: str,
    added_by: str,
    url: str | None = None,
    notes: str | None = None,
) -> dict:
    return {
        "title": title,
        "source_url": url,
        "source_type": "link" if url else "manual",
        "status": "idea_saved",
        "confidence": "low",
        "added_by": added_by,
        "notes": notes,
        "source_links": [url] if url else [],
    }


def _format_saved_recipe_embed(recipe: dict) -> discord.Embed:
    embed = discord.Embed(
        title=recipe["title"],
        url=recipe.get("source_url"),
        color=_recipe_color(recipe.get("status")),
        description=(
            f"**ID:** `{recipe['recipe_id']}`\n"
            f"**Status:** {_recipe_status_label(recipe.get('status'))}\n"
            f"**Confidence:** {(recipe.get('confidence') or 'low').title()}"
        ),
    )
    if recipe.get("added_at"):
        embed.timestamp = recipe["added_at"]
    if recipe.get("channel"):
        embed.add_field(name="Channel", value=recipe["channel"], inline=True)
    if recipe.get("tags"):
        embed.add_field(name="Tags", value=", ".join(recipe["tags"][:8]), inline=True)
    if recipe.get("notes"):
        embed.add_field(name="Notes", value=EmbedFormatter.truncate(recipe["notes"]), inline=False)
    if recipe.get("status") == "partial_recipe":
        missing = []
        if not recipe.get("ingredients"):
            missing.append("ingredients")
        if not recipe.get("instructions"):
            missing.append("steps")
        if missing:
            embed.add_field(name="Recipe Text", value=f"Missing: {', '.join(missing)}.", inline=False)
    if recipe.get("ingredients"):
        ingredients = "\n".join(f"- {item}" for item in recipe["ingredients"][:12])
        if len(recipe["ingredients"]) > 12:
            ingredients += f"\n...and {len(recipe['ingredients']) - 12} more"
        embed.add_field(name="Ingredients", value=EmbedFormatter.truncate(ingredients), inline=False)
    if recipe.get("instructions"):
        steps = "\n".join(f"{idx}. {step}" for idx, step in enumerate(recipe["instructions"][:6], 1))
        if len(recipe["instructions"]) > 6:
            steps += f"\n...and {len(recipe['instructions']) - 6} more"
        embed.add_field(name="Steps", value=EmbedFormatter.truncate(steps), inline=False)
    if recipe.get("source_links"):
        links = "\n".join(recipe["source_links"][:3])
        if len(recipe["source_links"]) > 3:
            links += f"\n...and {len(recipe['source_links']) - 3} more"
        embed.add_field(name="Links", value=EmbedFormatter.truncate(links, 700), inline=False)
    embed.set_footer(text=f"Added by {recipe.get('added_by') or 'Unknown'}")
    return embed


def _format_recipe_list_embed(recipes: list, total: int, page: int, query: str | None = None) -> discord.Embed:
    title = "Saved Recipes" if not query else f"Recipe Search: {query}"
    embed = discord.Embed(
        title=title,
        color=discord.Color.green(),
        description=f"Page {page} • {total} saved recipe{'s' if total != 1 else ''}",
    )
    if not recipes:
        embed.description = "No recipes found yet."
        return embed

    for recipe in recipes:
        bits = [
            f"`#{recipe['recipe_id']}`",
            _recipe_status_label(recipe.get("status")),
        ]
        if recipe.get("ingredients"):
            bits.append(f"{len(recipe['ingredients'])} ingredients")
        if recipe.get("tags"):
            bits.append(", ".join(recipe["tags"][:3]))
        embed.add_field(
            name=recipe["title"][:256],
            value=" • ".join(bits),
            inline=False,
        )
    return embed


class RecipeListView(discord.ui.View):
    """Interactive recipe list with detail selection and pagination."""

    def __init__(
        self,
        cog: "RecipeCommandsCog",
        recipes: list,
        page: int,
        total_pages: int,
        query: str | None = None,
        ephemeral: bool = False,
    ):
        super().__init__(timeout=300)
        self.cog = cog
        self.recipes = recipes
        self.page = page
        self.total_pages = total_pages
        self.query = query
        self.ephemeral = ephemeral

        if recipes:
            select = discord.ui.Select(
                placeholder="Open recipe details",
                min_values=1,
                max_values=1,
                options=[
                    discord.SelectOption(
                        label=recipe["title"][:100],
                        value=str(recipe["recipe_id"]),
                        description=f"#{recipe['recipe_id']} • {_recipe_status_label(recipe.get('status'))}"[:100],
                    )
                    for recipe in recipes[:25]
                ],
            )
            select.callback = self._select_recipe
            self.add_item(select)

        if page > 1:
            back_button = discord.ui.Button(label="Back", style=discord.ButtonStyle.secondary, row=1)
            back_button.callback = self._back
            self.add_item(back_button)

        if page < total_pages:
            next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.secondary, row=1)
            next_button.callback = self._next
            self.add_item(next_button)

    async def _select_recipe(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=self.ephemeral, thinking=True)
        except discord.NotFound:
            logger.warning("Recipe detail selection expired before it could be deferred")
            return

        recipe_id = int(interaction.data["values"][0])
        recipe = await asyncio.to_thread(self.cog.db.get_recipe, recipe_id)
        if not recipe:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"No saved recipe found for ID `{recipe_id}`."),
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            embed=_format_saved_recipe_embed(recipe),
            ephemeral=self.ephemeral,
        )

    async def _back(self, interaction: discord.Interaction):
        await self._change_page(interaction, self.page - 1)

    async def _next(self, interaction: discord.Interaction):
        await self._change_page(interaction, self.page + 1)

    async def _change_page(self, interaction: discord.Interaction, page: int):
        try:
            await interaction.response.defer()
        except discord.NotFound:
            logger.warning("Recipe pagination interaction expired before it could be deferred")
            return

        await self.cog.update_recipe_list_message(
            interaction,
            page=page,
            query=self.query,
            ephemeral=self.ephemeral,
        )


class AddRecipeModal(discord.ui.Modal, title="Add a recipe"):
    """Modal opened by the pinned recipe panel."""

    url_input = discord.ui.TextInput(
        label="Recipe link",
        placeholder="YouTube, TikTok, Facebook, or recipe page link",
        required=False,
        max_length=500,
    )
    title_input = discord.ui.TextInput(
        label="Recipe name",
        placeholder="Optional, e.g. Marry Me Chicken",
        required=False,
        max_length=120,
    )
    notes_input = discord.ui.TextInput(
        label="Notes",
        placeholder="Optional ingredients, comments, or what looked good",
        required=False,
        max_length=1000,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: "RecipeCommandsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        await self.cog.handle_recipe_submission(
            interaction,
            title=str(self.title_input.value).strip() or None,
            url=str(self.url_input.value).strip() or None,
            notes=str(self.notes_input.value).strip() or None,
        )

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "Discord UI error in AddRecipeModal",
            exc_info=(type(error), error, error.__traceback__),
        )


class RemoveRecipeModal(discord.ui.Modal, title="Remove a recipe"):
    """Modal for removing a saved recipe by ID."""

    recipe_id_input = discord.ui.TextInput(
        label="Recipe ID",
        placeholder="Use /recipe list or See Recipes to find the ID",
        required=True,
        max_length=12,
    )

    def __init__(self, cog: "RecipeCommandsCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        raw_recipe_id = str(self.recipe_id_input.value).strip().lstrip("#")
        if not raw_recipe_id.isdigit():
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe ID must be a number, like `12` or `#12`."),
                ephemeral=True,
            )
            return
        await self.cog.remove_recipe_by_id(interaction, int(raw_recipe_id), ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "Discord UI error in RemoveRecipeModal",
            exc_info=(type(error), error, error.__traceback__),
        )


class RecipePanelView(discord.ui.View):
    """Persistent recipe channel button panel."""

    def __init__(self, cog: "RecipeCommandsCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Add Recipe",
        style=discord.ButtonStyle.primary,
        custom_id="recipe_panel:add_recipe",
    )
    async def add_recipe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(AddRecipeModal(self.cog))
        except discord.NotFound:
            logger.warning("Recipe panel interaction expired before modal could be opened")

    @discord.ui.button(
        label="See Recipes",
        style=discord.ButtonStyle.secondary,
        custom_id="recipe_panel:list_recipes",
    )
    async def list_recipes_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.NotFound:
            logger.warning("Recipe list interaction expired before it could be deferred")
            return
        await self.cog.show_recipe_list(interaction, page=1, ephemeral=True)

    @discord.ui.button(
        label="Remove Recipe",
        style=discord.ButtonStyle.danger,
        custom_id="recipe_panel:remove_recipe",
    )
    async def remove_recipe_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.send_modal(RemoveRecipeModal(self.cog))
        except discord.NotFound:
            logger.warning("Recipe remove interaction expired before modal could be opened")


class RecipeCommandsCog(commands.Cog):
    """Cog for recipe commands."""

    recipe = app_commands.Group(
        name="recipe",
        description="Save and inspect recipes for The Living Room"
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = DatabaseBridge()
        self._recipes_schema_ready = False
        self.bot.add_view(RecipePanelView(self))

    async def ensure_recipes_ready(self) -> bool:
        """Ensure recipe persistence exists without blocking interaction ACKs."""
        if self._recipes_schema_ready:
            return True
        ready = await asyncio.to_thread(self.db.ensure_recipes_schema)
        self._recipes_schema_ready = ready
        if not ready:
            logger.warning("Recipe schema was not created; recipe persistence may fail")
        return ready

    @staticmethod
    def create_panel_embed() -> discord.Embed:
        """Create the pinned recipe control panel embed."""
        embed = discord.Embed(
            title="Kitchen Counter",
            description="Drop in recipe links, videos, or notes. A clean recipe name is helpful, but optional.",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="How It Saves",
            value="YouTube descriptions are inspected automatically. Saved recipes can be viewed, edited, or removed later.",
            inline=False,
        )
        embed.set_footer(text="Pin this message in #recipes so it is easy to find.")
        return embed

    @app_commands.command(
        name="recipe-panel",
        description="Post the button panel for adding recipes"
    )
    @app_commands.describe(pin="Try to pin the panel after posting it")
    async def recipe_panel(self, interaction: discord.Interaction, pin: bool = True):
        """Post a persistent button panel for the recipe channel."""
        try:
            await interaction.response.send_message(
                embed=self.create_panel_embed(),
                view=RecipePanelView(self),
            )
            message = await interaction.original_response()
        except discord.NotFound:
            logger.warning("Recipe panel interaction expired before response")
            return

        if pin:
            try:
                await message.pin(reason="Recipe panel")
            except discord.Forbidden:
                await interaction.followup.send(
                    "I posted the recipe panel, but I do not have permission to pin it.",
                    ephemeral=True,
                )
            except discord.HTTPException as exc:
                logger.warning(f"Failed to pin recipe panel: {exc}")

    @recipe.command(
        name="add",
        description="Add a recipe idea with an optional title and source link"
    )
    @app_commands.describe(
        url="Optional YouTube, TikTok, Facebook, or recipe link",
        title="Optional clean recipe name, e.g. Marry Me Chicken",
        notes="Optional notes, ingredients, or context"
    )
    async def add_recipe(
        self,
        interaction: discord.Interaction,
        url: str | None = None,
        title: str | None = None,
        notes: str | None = None,
    ):
        await interaction.response.defer(thinking=True)
        await self.handle_recipe_submission(interaction, title=title, url=url, notes=notes)

    async def show_recipe_list(
        self,
        interaction: discord.Interaction,
        page: int = 1,
        query: str | None = None,
        ephemeral: bool = False,
    ):
        if not await self.ensure_recipes_ready():
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                ephemeral=True,
            )
            return
        page = max(page, 1)
        limit = 10
        offset = (page - 1) * limit
        total, recipes = await asyncio.to_thread(self.db.get_recipes, limit, offset, query)
        total_pages = max(1, (total + limit - 1) // limit)
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * limit
            total, recipes = await asyncio.to_thread(self.db.get_recipes, limit, offset, query)
        embed = _format_recipe_list_embed(recipes, total, page, query=query)
        view = RecipeListView(
            self,
            recipes,
            page=page,
            total_pages=total_pages,
            query=query,
            ephemeral=ephemeral,
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=ephemeral)

    async def update_recipe_list_message(
        self,
        interaction: discord.Interaction,
        page: int = 1,
        query: str | None = None,
        ephemeral: bool = False,
    ):
        """Update an existing recipe list message after a pagination interaction."""
        if not await self.ensure_recipes_ready():
            await interaction.edit_original_response(
                embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                view=None,
            )
            return

        page = max(page, 1)
        limit = 10
        offset = (page - 1) * limit
        total, recipes = await asyncio.to_thread(self.db.get_recipes, limit, offset, query)
        total_pages = max(1, (total + limit - 1) // limit)
        if page > total_pages:
            page = total_pages
            offset = (page - 1) * limit
            total, recipes = await asyncio.to_thread(self.db.get_recipes, limit, offset, query)

        embed = _format_recipe_list_embed(recipes, total, page, query=query)
        view = RecipeListView(
            self,
            recipes,
            page=page,
            total_pages=total_pages,
            query=query,
            ephemeral=ephemeral,
        )
        await interaction.edit_original_response(embed=embed, view=view)

    @recipe.command(
        name="list",
        description="View saved recipes"
    )
    @app_commands.describe(
        page="Page number",
        query="Optional title/notes search"
    )
    async def list_recipes(
        self,
        interaction: discord.Interaction,
        page: int = 1,
        query: str | None = None,
    ):
        await interaction.response.defer(thinking=True)
        await self.show_recipe_list(interaction, page=page, query=query)

    @recipe.command(
        name="view",
        description="View one saved recipe by ID"
    )
    @app_commands.describe(recipe_id="Recipe ID from /recipe list")
    async def view_recipe(self, interaction: discord.Interaction, recipe_id: int):
        await interaction.response.defer(thinking=True)
        if not await self.ensure_recipes_ready():
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                ephemeral=True,
            )
            return
        recipe = await asyncio.to_thread(self.db.get_recipe, recipe_id)
        if not recipe:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"No saved recipe found for ID `{recipe_id}`."),
                ephemeral=True,
            )
            return
        await interaction.followup.send(embed=_format_saved_recipe_embed(recipe))

    @recipe.command(
        name="edit",
        description="Edit a saved recipe's title, notes, or status"
    )
    @app_commands.describe(
        recipe_id="Recipe ID from /recipe list",
        title="Optional new title",
        notes="Optional replacement notes",
        status="Optional status"
    )
    @app_commands.choices(status=[
        app_commands.Choice(name="Complete recipe", value="complete_recipe"),
        app_commands.Choice(name="Partial recipe", value="partial_recipe"),
        app_commands.Choice(name="Video idea", value="video_only"),
        app_commands.Choice(name="Idea saved", value="idea_saved"),
        app_commands.Choice(name="Needs review", value="needs_review"),
    ])
    async def edit_recipe(
        self,
        interaction: discord.Interaction,
        recipe_id: int,
        title: str | None = None,
        notes: str | None = None,
        status: app_commands.Choice[str] | None = None,
    ):
        await interaction.response.defer(thinking=True)
        if not await self.ensure_recipes_ready():
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                ephemeral=True,
            )
            return
        clean_title = title.strip() if title else None
        clean_notes = notes.strip() if notes is not None else None
        status_value = status.value if status else None

        if not clean_title and notes is None and not status_value:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Provide a title, notes, or status to update."),
                ephemeral=True,
            )
            return

        updated = await asyncio.to_thread(
            self.db.update_recipe,
            recipe_id,
            title=clean_title,
            notes=clean_notes,
            status=status_value,
        )
        if not updated:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"No saved recipe found for ID `{recipe_id}`."),
                ephemeral=True,
            )
            return

        recipe = await asyncio.to_thread(self.db.get_recipe, recipe_id)
        embed = _format_saved_recipe_embed(recipe)
        embed.add_field(name="Updated", value="Recipe changes saved.", inline=False)
        await interaction.followup.send(embed=embed)

    @recipe.command(
        name="remove",
        description="Remove a saved recipe by ID"
    )
    @app_commands.describe(recipe_id="Recipe ID from /recipe list")
    async def remove_recipe(self, interaction: discord.Interaction, recipe_id: int):
        await interaction.response.defer(thinking=True)
        await self.remove_recipe_by_id(interaction, recipe_id)

    async def remove_recipe_by_id(
        self,
        interaction: discord.Interaction,
        recipe_id: int,
        ephemeral: bool = False,
    ):
        """Remove a recipe after the interaction has already been acknowledged."""
        if not await self.ensure_recipes_ready():
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                ephemeral=True,
            )
            return
        removed = await asyncio.to_thread(self.db.remove_recipe, recipe_id)
        if not removed:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"No saved recipe found for ID `{recipe_id}`."),
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            embed=EmbedFormatter.format_info("Recipe Removed", f"Removed recipe `#{recipe_id}`."),
            ephemeral=ephemeral,
        )

    async def handle_recipe_submission(
        self,
        interaction: discord.Interaction,
        title: str | None = None,
        url: str | None = None,
        notes: str | None = None,
    ):
        """Process a recipe submission from either slash commands or modal input."""
        clean_title = title.strip() if title else None
        clean_url = url.strip() if url else None
        clean_notes = notes.strip() if notes else None

        if clean_title and len(clean_title) < 2:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Recipe title must be at least 2 characters."),
                ephemeral=True,
            )
            return

        if not clean_title and not clean_url and not clean_notes:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error("Add a recipe name, link, or note so I have something to save."),
                ephemeral=True,
            )
            return

        try:
            if not await self.ensure_recipes_ready():
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error("Recipe storage is unavailable right now."),
                    ephemeral=True,
                )
                return

            if clean_url and _is_youtube_url(clean_url):
                extraction = await asyncio.to_thread(
                    extract_youtube_recipe,
                    clean_url,
                    recipe_title=clean_title,
                )
                payload = _recipe_from_extraction(
                    extraction,
                    added_by=interaction.user.display_name,
                    notes=clean_notes,
                )
                add_result = await asyncio.to_thread(self.db.add_recipe, payload)
                if not add_result.get("success"):
                    duplicate_id = add_result.get("duplicate_id")
                    if duplicate_id:
                        await interaction.followup.send(
                            embed=EmbedFormatter.format_info(
                                "Already Saved",
                                f"That source link is already saved as recipe `#{duplicate_id}`."
                            ),
                            ephemeral=True,
                        )
                        return
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_error(
                            f"Could not save recipe: {add_result.get('error', 'unknown error')[:120]}"
                        ),
                        ephemeral=True,
                    )
                    return

                saved_recipe = await asyncio.to_thread(self.db.get_recipe, add_result["recipe_id"])
                embed = _format_saved_recipe_embed(saved_recipe)
                embed.add_field(
                    name="Saved",
                    value=f"Use `/recipe view {saved_recipe['recipe_id']}` to open it later.",
                    inline=False,
                )
                await interaction.followup.send(embed=embed)
                return

            display_title = clean_title or "Recipe idea"
            payload = _manual_recipe_payload(
                display_title,
                added_by=interaction.user.display_name,
                url=clean_url,
                notes=clean_notes,
            )
            add_result = await asyncio.to_thread(self.db.add_recipe, payload)
            if not add_result.get("success"):
                duplicate_id = add_result.get("duplicate_id")
                if duplicate_id:
                    await interaction.followup.send(
                        embed=EmbedFormatter.format_info(
                            "Already Saved",
                            f"That source link is already saved as recipe `#{duplicate_id}`."
                        ),
                        ephemeral=True,
                    )
                    return
                await interaction.followup.send(
                    embed=EmbedFormatter.format_error(
                        f"Could not save recipe: {add_result.get('error', 'unknown error')[:120]}"
                    ),
                    ephemeral=True,
                )
                return

            saved_recipe = await asyncio.to_thread(self.db.get_recipe, add_result["recipe_id"])
            embed = _format_saved_recipe_embed(saved_recipe)
            embed.add_field(
                name="Saved",
                value=f"Use `/recipe view {saved_recipe['recipe_id']}` to open it later.",
                inline=False,
            )
            await interaction.followup.send(embed=embed)

        except ValueError as exc:
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(str(exc)),
                ephemeral=True,
            )
        except Exception as exc:
            logger.exception("Error adding recipe")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"Recipe extraction failed: {str(exc)[:100]}"),
                ephemeral=True,
            )

    @recipe.command(
        name="inspect-youtube",
        description="Preview what the bot can extract from a YouTube recipe video"
    )
    @app_commands.describe(
        url="YouTube URL to inspect",
        title="Optional clean recipe title to use instead of the video title"
    )
    async def inspect_youtube(
        self,
        interaction: discord.Interaction,
        url: str,
        title: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            extraction = await asyncio.to_thread(
                extract_youtube_recipe,
                url,
                recipe_title=title.strip() if title else None,
            )
            embed = _format_recipe_extraction_embed(extraction, interaction.user)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            logger.exception("Error inspecting YouTube recipe")
            await interaction.followup.send(
                embed=EmbedFormatter.format_error(f"YouTube inspection failed: {str(exc)[:100]}"),
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    """Load the recipe commands cog."""
    await bot.add_cog(RecipeCommandsCog(bot))
