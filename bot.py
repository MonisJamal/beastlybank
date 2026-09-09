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
    "cogs.squad",
    "cogs.shop",
    "cogs.giveaways",
    "cogs.leaderboard",
    "cogs.admin",
    "cogs.sofifa",
    "utils.backup",
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
            intents.members = True

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
        # Cloud persistence: attempt to restore latest database from Discord backup channel
        from utils.backup import restore_database_from_discord
        await restore_database_from_discord(self)

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
                synced_guild = await self.tree.sync(guild=guild_obj)
                logger.info(
                    "⚡ Instantly synced %d commands exclusively to BeastlyFC (Guild ID: %d)",
                    len(synced_guild),
                    BEASTLYFC_GUILD_ID,
                )
            synced_global = await self.tree.sync()
            logger.info("Synced %d commands globally.", len(synced_global))
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
        if not self.intents.message_content:
            logger.warning("⚠️" * 30)
            logger.warning("⚠️ [IMPORTANT] MESSAGE CONTENT INTENT IS DISABLED IN DISCORD DEVELOPER PORTAL!")
            logger.warning("⚠️ 'bb!' prefix commands cannot respond because Discord strips message text.")
            logger.warning("👉 To fix: Open https://discord.com/developers/applications")
            logger.warning("👉 Select your Bot -> Bot tab -> Privileged Gateway Intents -> Enable 'Message Content Intent' -> Save Changes")
            logger.warning("ℹ️ Fallback: Mentioning the bot always works (e.g. '@BeastlyBank balance') or use slash commands.")
            logger.warning("⚠️" * 30)
        else:
            logger.info("✅ MESSAGE CONTENT INTENT: ENABLED ('bb!' prefix commands fully operational).")

        # Pre-cache guild members into memory for instantaneous role lookups
        try:
            for g in self.guilds:
                if not g.chunked and self.intents.members:
                    await g.chunk()
                    logger.info("⚡ Cached %d members for %s", len(g.members), g.name)
        except Exception as e:
            logger.debug("Member pre-cache note: %s", e)

        # Set football economy presence
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name=f"{SERVER_NAME} Finances ⚽ | /balance",
        )
        await self.change_presence(status=discord.Status.online, activity=activity)

    async def on_message(self, message: discord.Message):
        """Process incoming messages and enforce guild locks and bot checks."""
        if message.author.bot:
            return

        # Direct messages check
        if not message.guild:
            if message.content and any(message.content.lower().strip().startswith(p) for p in ("bb!", "bb ", f"<@{self.user.id}>", f"<@!{self.user.id}>")):
                await message.channel.send(embed=error_embed("Access Denied", f"{BOT_NAME} commands can only be used inside the **{SERVER_NAME}** server!"))
            return

        # Enforce BeastlyFC server lock for prefix commands
        if BEASTLYFC_GUILD_ID != 0 and message.guild.id != BEASTLYFC_GUILD_ID:
            if message.content and any(message.content.lower().strip().startswith(p) for p in ("bb!", "bb ", f"<@{self.user.id}>", f"<@!{self.user.id}>")):
                await message.channel.send(embed=error_embed("Server Locked", f"{BOT_NAME} is strictly exclusive to the **{SERVER_NAME}** server!"))
            return

        if message.content:
            low = message.content.lower().strip()
            if low.startswith(("bb!", "bb ", f"<@{self.user.id}>", f"<@!{self.user.id}>")):
                logger.info("Prefix command triggered by %s (%d): %s", message.author, message.author.id, message.content[:80])

        await self.process_commands(message)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        """Global Prefix Command Error Handler."""
        actual_error = getattr(error, "original", error)
        if isinstance(actual_error, commands.CommandNotFound):
            return
        elif isinstance(actual_error, commands.MissingRequiredArgument):
            await ctx.send(embed=error_embed("Missing Argument", f"Missing required parameter: `{actual_error.param.name}`\nUse `bb!help` or `/help` for usage."))
        elif isinstance(actual_error, commands.BadArgument):
            await ctx.send(embed=error_embed("Invalid Parameter", str(actual_error)))
        elif isinstance(actual_error, commands.CommandOnCooldown):
            await ctx.send(embed=error_embed("Cooldown Active", f"Please wait **{actual_error.retry_after:.1f}s** before using this command again."))
        else:
            logger.error("Unhandled Prefix Command Error in %s: %s", ctx.command, actual_error, exc_info=actual_error)
            await ctx.send(embed=error_embed("Command Error", f"An error occurred while running `{ctx.invoked_with}`: {str(actual_error)}"))

    async def close(self):
        logger.info("Shutting down BeastlyBank and closing database connections...")
        await self.db.close()
        await super().close()


bot = BeastlyBankBot()

_web_runner = None
_web_site = None


async def start_web_server(port: int):
    """Instantly bind to $PORT for cloud platforms (Render, Koyeb)."""
    global _web_runner, _web_site
    try:
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/", lambda r: web.Response(text="BeastlyBank is online ⚽"))
        _web_runner = web.AppRunner(app)
        await _web_runner.setup()
        _web_site = web.TCPSite(_web_runner, "0.0.0.0", port)
        await _web_site.start()
        logger.info("⚡ Cloud health server listening on port %d", port)
    except Exception as e:
        logger.warning("Could not start cloud health server: %s", e)


async def render_keepalive_loop():
    """Periodically ping public health endpoint to prevent Render Free Tier from idling to sleep."""
    import os
    import aiohttp
    external_url = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not external_url:
        if os.getenv("RENDER") or os.getenv("PORT"):
            external_url = "https://beastlybank.onrender.com"
        else:
            return

    logger.info("⚡ Render 24/7 keep-alive monitor active for: %s", external_url)
    await asyncio.sleep(60)

    while True:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(external_url) as resp:
                    logger.debug("Render keep-alive ping status: %d", resp.status)
        except Exception as e:
            logger.debug("Render keep-alive ping notice: %s", e)
        # Ping every 10 minutes (600s) to comfortably stay within Render's 15m idle limit
        await asyncio.sleep(600)


async def main_async():
    global bot
    import os
    port_str = os.getenv("PORT")
    if port_str and port_str.isdigit():
        await start_web_server(int(port_str))

    # Launch background keep-alive ping task
    asyncio.create_task(render_keepalive_loop())

    backoff = 5
    while True:
        try:
            if bot.is_closed():
                intents = bot.intents
                bot = BeastlyBankBot(intents=intents)
            await bot.start(DISCORD_TOKEN)
        except discord.errors.PrivilegedIntentsRequired:
            logger.warning("⚠️ Privileged Intents not enabled in Developer Portal. Retrying with fallback intents.")
            intents = discord.Intents.default()
            intents.message_content = True
            intents.members = False
            bot = BeastlyBankBot(intents=intents)
        except discord.errors.LoginFailure as lf:
            logger.critical("❌ Fatal Discord authentication error (invalid token): %s", lf)
            break
        except Exception as e:
            logger.error("⚠️ Discord Gateway connection dropped: %s. Automatically reconnecting in %ds...", e, backoff, exc_info=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)
        else:
            backoff = 5


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

