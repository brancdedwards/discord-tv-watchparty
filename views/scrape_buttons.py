"""
Discord button views for interactive scraping workflow.
"""
import discord
from discord.ui import View, Button
import logging

logger = logging.getLogger(__name__)


class IMDbSelectionView(View):
    """
    View with buttons for selecting from IMDb search results.
    Users click to select which show to scrape.
    """

    def __init__(self, results: list, callback, timeout: int = 300):
        """
        Initialize selection view.

        Args:
            results: List of search result dicts
            callback: Async callback function(interaction, selected_result)
            timeout: How long buttons are active (seconds)
        """
        super().__init__(timeout=timeout)
        self.results = results
        self.callback = callback
        self.selected = None

        # Create a button for each result (max 5)
        for i, result in enumerate(results[:5]):
            title = result.get("title", "Unknown")
            year = result.get("year", "")
            year_str = f" ({year})" if year else ""
            label = f"{i+1}. {title}{year_str}"[:80]  # Discord button label limit

            button = Button(
                label=label,
                style=discord.ButtonStyle.primary,
                custom_id=f"select_{i}"
            )
            button.callback = self._create_callback(i)
            self.add_item(button)

    async def _create_callback(self, index: int):
        """Create callback for a specific button."""
        async def button_callback(interaction: discord.Interaction):
            await interaction.response.defer()
            self.selected = self.results[index]
            await self.callback(interaction, self.selected)
            self.stop()

        return button_callback


class ScrapeStatusView(View):
    """
    View with buttons for scrape status (cancel, refresh).
    Shows during active scraping.
    """

    def __init__(self, process=None, timeout: int = 900):  # 15 mins
        """
        Initialize status view.

        Args:
            process: The asyncio Process object (for kill)
            timeout: How long buttons are active
        """
        super().__init__(timeout=timeout)
        self.process = process
        self.cancelled = False

    @discord.ui.button(label="Cancel Scrape", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: Button):
        """Cancel the scrape."""
        if self.process and self.process.returncode is None:
            self.process.kill()
            self.cancelled = True
            logger.info(f"Scrape cancelled by {interaction.user}")

        await interaction.response.defer()
        await interaction.followup.send(
            "❌ Scrape cancelled.",
            ephemeral=True
        )
        self.stop()


class RandomizeView(View):
    """
    Simple view with a "Try Another" button for random genre suggestions.
    """

    def __init__(self, callback, timeout: int = 300):
        """
        Initialize randomize view.

        Args:
            callback: Async callback function(interaction)
            timeout: How long buttons are active
        """
        super().__init__(timeout=timeout)
        self.callback = callback

    @discord.ui.button(label="🎲 Try Another", style=discord.ButtonStyle.secondary)
    async def randomize_button(self, interaction: discord.Interaction, button: Button):
        """Get another random suggestion."""
        await interaction.response.defer()
        await self.callback(interaction)


class PaginationView(View):
    """
    View for paginated list navigation.
    """

    def __init__(self, callback, total: int, page_size: int = 10, current_offset: int = 0, timeout: int = 300):
        """
        Initialize pagination view.

        Args:
            callback: Async callback function(interaction, offset)
            total: Total number of items
            page_size: Items per page
            current_offset: Current page offset (for multi-page navigation)
            timeout: How long buttons are active
        """
        super().__init__(timeout=timeout)
        self.callback = callback
        self.total = total
        self.page_size = page_size
        self.current_offset = current_offset
        self.max_page = (total + page_size - 1) // page_size

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.primary)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        """Go to previous page."""
        if self.current_offset > 0:
            self.current_offset -= self.page_size
            await self.callback(interaction, self.current_offset)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        """Go to next page."""
        if self.current_offset + self.page_size < self.total:
            self.current_offset += self.page_size
            await self.callback(interaction, self.current_offset)
