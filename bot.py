import discord
from discord.ext import commands, tasks
import asyncio
import os
import logging
import time
import json
from aiohttp import web
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
        self.start_time = time.time()
        self.health_check_failures = 0
        self.http_server = None
        self.test_channel_id = None  # Will be set on_ready
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

        # Start HTTP health check server
        if not self.http_server:
            self.http_server = web.AppRunner(self._create_health_app())
            await self.http_server.setup()
            site = web.TCPSite(self.http_server, '0.0.0.0', 8080)
            await site.start()
            logger.info("✅ Health check endpoint running on port 8080")

        # Start periodic health monitor
        if not self.periodic_health_check.is_running():
            self.periodic_health_check.start()
            logger.info("✅ Periodic health monitor started")

        try:
            synced = await self.tree.sync()
            logger.info(f"✅ Synced {len(synced)} slash commands with Discord")
        except Exception as e:
            logger.error(f"❌ Failed to sync slash commands: {e}")

    async def on_error(self, event_method, *args, **kwargs):
        """Global error handler."""
        logger.exception(f"❌ Unhandled exception in {event_method}")

    def _create_health_app(self):
        """Create aiohttp app for health checks."""
        app = web.Application()
        app.router.add_get('/health', self._health_endpoint)
        return app

    async def _health_endpoint(self, request):
        """Health check endpoint for Render."""
        try:
            from utils.db_bridge import DatabaseBridge
            db = DatabaseBridge()
            db.get_wishlist()  # Test database connection

            uptime = int(time.time() - self.start_time)
            health_data = {
                "status": "healthy",
                "uptime_seconds": uptime,
                "bot_user": str(self.user),
                "latency_ms": int(self.latency * 1000),
                "database": "connected"
            }
            return web.json_response(health_data)
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return web.json_response(
                {"status": "unhealthy", "error": str(e)},
                status=503
            )

    @tasks.loop(minutes=60)
    async def periodic_health_check(self):
        """Check bot health every 60 minutes and alert if issues found."""
        try:
            logger.info("🏥 Running periodic health check...")

            from utils.db_bridge import DatabaseBridge
            db = DatabaseBridge()

            # Check database
            db.get_wishlist()

            # Check bot latency
            if self.latency > 1.0:
                logger.warning(f"⚠️ High latency detected: {self.latency*1000:.0f}ms")

            logger.info("✅ Health check passed")
            self.health_check_failures = 0

        except Exception as e:
            self.health_check_failures += 1
            logger.error(f"❌ Health check failed ({self.health_check_failures}/5): {e}")

            # Send alert to test channel if configured
            if self.test_channel_id:
                try:
                    channel = self.get_channel(self.test_channel_id)
                    if channel:
                        embed = discord.Embed(
                            title="⚠️ Bot Health Alert",
                            description=f"Health check failed #{self.health_check_failures}/5",
                            color=discord.Color.red()
                        )
                        embed.add_field(name="Error", value=str(e)[:200], inline=False)
                        embed.add_field(name="Action", value="Monitor active", inline=False)
                        await channel.send(embed=embed)
                except Exception as send_err:
                    logger.error(f"Failed to send alert: {send_err}")

            # If max failures reached, send additional alert
            if self.health_check_failures >= 5:
                logger.critical("🚨 Max health check failures reached (5/5)")

    @periodic_health_check.before_loop
    async def before_health_check(self):
        """Wait for bot to be ready before starting periodic checks."""
        await self.wait_until_ready()

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
