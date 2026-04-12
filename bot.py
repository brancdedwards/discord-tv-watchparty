import discord
from discord.ext import commands
import asyncio
import os
import logging
from config import (
    DISCORD_TOKEN,
    BOT_INTENTS,
    COMMAND_PREFIX,
    LOG_LEVEL
)

# ===== Logging Setup =====
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("DiscordBot")

# ===== Bot Class =====
class ReviewBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=BOT_INTENTS,
            help_command=None
        )
        self.active_tasks = set()
        logger.info("ReviewBot initialized")

    async def setup_hook(self):
        """Called before bot connects. Load all cogs."""
        cog_files = [
            "cogs.tv_commands",
            "cogs.movie_commands",
            "cogs.wishlist_commands",
            "cogs.utilities"
        ]

        for cog in cog_files:
            try:
                await self.load_extension(cog)
                logger.info(f"✅ Loaded cog: {cog}")
            except Exception as e:
                logger.error(f"❌ Failed to load {cog}: {e}")

    async def on_ready(self):
        """Called when bot successfully connects to Discord."""
        logger.info(f"✅ Bot logged in as {self.user}")
        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash commands with Discord")
        except Exception as e:
            logger.error(f"❌ Failed to sync slash commands: {e}")

    async def on_error(self, event_method, *args, **kwargs):
        """Global error handler."""
        logger.exception(f"❌ Unhandled exception in {event_method}")

# ===== Main Entry Point =====
async def main():
    """Start the bot."""
    bot = ReviewBot()

    async with bot:
        try:
            await bot.start(DISCORD_TOKEN)
        except Exception as e:
            logger.error(f"❌ Failed to start bot: {e}")
            raise

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot shutdown by user")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
