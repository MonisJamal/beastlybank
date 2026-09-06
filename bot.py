"""
BeastlyBank Discord Bot - Main Entrypoint.
Built exclusively for the BeastlyFC Discord Server.
"""
import asyncio
import logging
import sys
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    DISCORD_TOKEN,
    BEASTLYFC_GUILD_ID,
    DATABASE_PATH,
    BOT_NAME,
    SERVER_NAME,
)
from database.db import DatabaseManager
from utils.checks import NotBankerError, NotInBeastlyFCError
from utils.embeds import error_embed
from utils.views import GiveawayView

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("BeastlyBank")

COGS = [
    "cogs.economy",
    "cogs.clubs",
    "cogs.giveaways",
    "cogs.leaderboard",
    "cogs.admin",
]


class BeastlyCommandTree(app_commands.CommandTree):
    """Custom CommandTree with BeastlyFC guild-locking and error handling."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Enforce that BeastlyBank only operates within the BeastlyFC Guild."""
        if not interaction.guild:
            await interaction.response.send_message(
                embed=error_embed("Access Denied", f"{BOT_NAME} commands can only be used inside the **{SERVER_NAME}** server!"),
                ephemeral=True,
            )
            return False

        if BEASTLYFC_GUILD_ID != 0 and interaction.guild.id != BEASTLYFC_GUILD_ID:
            await interaction.response.send_message(
                embed=error_embed(
                    "Server Locked",
                    f"{BOT_NAME} is strictly exclusive to the **{SERVER_NAME}** server!\n"
                    f"Commands cannot be used in this guild.",
                ),
                ephemeral=True,
            )
            return False

        return True

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        """Global Slash Command Error Handler."""
        actual_error = getattr(error, "original", error)

        async def safe_reply(embed: discord.Embed):
            try:
                if interaction.response.is_done():
                    try:
                        await interaction.followup.send(embed=embed, ephemeral=True)
                    except Exception:
                        await interaction.followup.send(embed=embed)
                else:
                    await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception as e:
                logger.error("Failed to send slash error response: %s", e)

        if isinstance(actual_error, NotInBeastlyFCError):
            await safe_reply(error_embed("Server Lock Violation", str(actual_error)))
        elif isinstance(actual_error, NotBankerError):
            await safe_reply(error_embed("Staff Authorization Required", str(actual_error)))
        elif isinstance(actual_error, app_commands.CommandOnCooldown):
            await safe_reply(error_embed("Cooldown Active", f"Please wait **{actual_error.retry_after:.1f} seconds** before using this again."))
        else:
            logger.error("Unhandled Slash Command Error: %s", actual_error, exc_info=actual_error)
            msg = f"An unexpected error occurred: {str(actual_error)}"
            await safe_reply(error_embed("System Error", msg))


class BeastlyBankBot(commands.Bot):
    def __init__(self, intents=None):
        if intents is None:
            intents = discord.Intents.default()
            intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned_or("bb!", "BB!", "bb ", "BB "),
            intents=intents,
            help_command=None,
            tree_cls=BeastlyCommandTree,
            case_insensitive=True,
        )
        self.db = DatabaseManager(DATABASE_PATH)

    async def setup_hook(self) -> None:
        """Initialize database, persistent views, and load cogs."""
        logger.info("Initializing BeastlyBank database...")
        await self.db.init_db()

        # Register persistent views
        self.add_view(GiveawayView(self.db))

        # Load extension cogs
        for cog in COGS:
            try:
                await self.load_extension(cog)
                logger.info("Loaded extension: %s", cog)
            except Exception as e:
                logger.error("Failed to load extension %s: %s", cog, e, exc_info=True)

        # Sync Slash Commands
        try:
            if BEASTLYFC_GUILD_ID != 0:
                guild_obj = discord.Object(id=BEASTLYFC_GUILD_ID)
                self.tree.copy_global_to(guild=guild_obj)
                synced = await self.tree.sync(guild=guild_obj)
                logger.info(
                    "⚡ Instantly synced %d commands exclusively to BeastlyFC (Guild ID: %d)",
                    len(synced),
                    BEASTLYFC_GUILD_ID,
                )
            else:
                synced = await self.tree.sync()
                logger.info("Synced %d commands globally (No BEASTLYFC_GUILD_ID set).", len(synced))
        except Exception as e:
            logger.warning("Slash command tree sync postponed: %s", e)

    async def on_ready(self):
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info("🏦 %s is online and guarding %s finances!", BOT_NAME, SERVER_NAME)
        logger.info("Logged in as: %s (ID: %d)", self.user.name, self.user.id)
        if BEASTLYFC_GUILD_ID != 0:
            logger.info("🔒 SERVER LOCK: ACTIVE (Locked to Guild: %d)", BEASTLYFC_GUILD_ID)
        else:
            logger.warning("⚠️ SERVER LOCK: INACTIVE (Set BEASTLYFC_GUILD_ID in .env)")
        logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # Set football economy presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{SERVER_NAME} Finances ⚽ | /balance",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Global Prefix Command Error Handler."""
        if isinstance(error, commands.CommandNotFound):
            return
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed("Missing Argument", f"Missing required parameter: `{error.param.name}`\nUse `bb!help` or `/help` for usage."))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=error_embed("Invalid Parameter", str(error)))
        elif isinstance(error, commands.CommandOnCooldown):
            await ctx.send(embed=error_embed("Cooldown Active", f"Please wait **{error.retry_after:.1f}s** before using this command again."))
        else:
            logger.error("Unhandled Prefix Command Error in %s: %s", ctx.command, error, exc_info=error)
            await ctx.send(embed=error_embed("Command Error", f"An error occurred while running `{ctx.invoked_with}`: {str(error)}"))

    async def close(self):
        logger.info("Shutting down BeastlyBank and closing database connections...")
        await self.db.close()
        await super().close()


bot = BeastlyBankBot()


async def start_web_server(port: int):
    """Instantly bind to $PORT for cloud platforms (Render, Koyeb)."""
    try:
        import os
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/", lambda r: web.Response(text="BeastlyBank is online ⚽"))
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("⚡ Cloud health server listening on port %d", port)
    except Exception as e:
        logger.warning("Could not start cloud health server: %s", e)


async def main_async():
    global bot
    import os
    port_str = os.getenv("PORT")
    if port_str and port_str.isdigit():
        await start_web_server(int(port_str))

    try:
        await bot.start(DISCORD_TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        logger.warning("Message Content Intent not enabled in Developer Portal. Starting with default intents.")
        intents = discord.Intents.default()
        intents.message_content = False
        bot = BeastlyBankBot(intents=intents)
        await bot.start(DISCORD_TOKEN)


def main():
    if not DISCORD_TOKEN or DISCORD_TOKEN == "your_bot_token_here":
        print("\n" + "=" * 60)
        print("❌ ERROR: DISCORD_TOKEN is not set in environment or .env!")
        print("Please configure DISCORD_TOKEN.")
        print("=" * 60 + "\n")
        sys.exit(1)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("BeastlyBank stopped.")


if __name__ == "__main__":
    main()

