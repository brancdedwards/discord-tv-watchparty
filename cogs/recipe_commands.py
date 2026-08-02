"""
Discord slash commands for recipe capture and extraction.
"""
from __future__ import annotations

import asyncio
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
from utils.youtube_recipe_extractor import extract_youtube_recipe


def _is_youtube_url(url: str) -> bool:
    lowered = url.lower()
    return "youtube.com/" in lowered or "youtu.be/" in lowered


def _format_recipe_extraction_embed(extraction, submitted_by) -> discord.Embed:
    status_labels = {
        "complete_recipe": "Complete recipe",
        "partial_recipe": "Partial recipe",
        "video_only": "Video only",
        "inspiration_only": "Inspiration only",
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
    embed.description = (
        f"**Status:** {status_label}\n"
        f"**Confidence:** {extraction.confidence.title()}\n"
        f"**Source:** {', '.join(extraction.extraction_sources) or 'No extractable source found'}"
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
            value=EmbedFormatter.truncate("\n".join(extraction.warnings[:3])),
            inline=False,
        )

    embed.set_footer(text=f"Submitted by {submitted_by.display_name}")
    return embed


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
        await interaction.response.send_modal(AddRecipeModal(self.cog))


class RecipeCommandsCog(commands.Cog):
    """Cog for recipe commands."""

    recipe = app_commands.Group(
        name="recipe",
        description="Save and inspect recipes for The Living Room"
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.bot.add_view(RecipePanelView(self))

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
            value="YouTube descriptions are inspected automatically. Other links are saved as recipe ideas for review.",
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
        await interaction.response.defer()
        message = await interaction.followup.send(
            embed=self.create_panel_embed(),
            view=RecipePanelView(self),
            wait=True,
        )

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
            if clean_url and _is_youtube_url(clean_url):
                extraction = await asyncio.to_thread(
                    extract_youtube_recipe,
                    clean_url,
                    recipe_title=clean_title,
                )
                embed = _format_recipe_extraction_embed(extraction, interaction.user)
                if clean_notes:
                    embed.add_field(
                        name="Notes",
                        value=EmbedFormatter.truncate(clean_notes),
                        inline=False,
                    )
                embed.add_field(
                    name="Next Step",
                    value="Review the extraction before treating this as a final saved recipe.",
                    inline=False,
                )
                await interaction.followup.send(embed=embed)
                return

            display_title = clean_title or "Recipe idea"
            embed = discord.Embed(
                title=display_title,
                color=discord.Color.blurple(),
                description="Saved as a recipe idea. Extraction is only available for YouTube links right now.",
            )
            if clean_url:
                embed.add_field(name="Source", value=clean_url, inline=False)
            if clean_notes:
                embed.add_field(name="Notes", value=EmbedFormatter.truncate(clean_notes), inline=False)
            embed.add_field(name="Status", value="Needs review", inline=True)
            embed.set_footer(text=f"Submitted by {interaction.user.display_name}")
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
