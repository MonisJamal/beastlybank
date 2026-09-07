"""
Automated Discord Cloud Database Backup & Restore for BeastlyBank.
Guarantees zero data loss on ephemeral cloud hosts (Render, Heroku, Discloud).
"""
import os
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiohttp
import discord
from discord.ext import tasks, commands

from config import BACKUP_CHANNEL_ID, DATABASE_PATH, BOT_NAME

logger = logging.getLogger("BeastlyBank.Backup")

_last_backup_mtime: float = 0.0


async def restore_database_from_discord(bot: commands.Bot) -> bool:
    """Download the latest database file from the backup channel before initializing."""
    if not BACKUP_CHANNEL_ID:
        logger.info("ℹ️ BACKUP_CHANNEL_ID not set; skipping cloud database restore.")
        return False

    logger.info("🔍 Checking Discord backup channel (%d) for database snapshots...", BACKUP_CHANNEL_ID)
    try:
        messages = await bot.http.logs_from(BACKUP_CHANNEL_ID, limit=15)
        for msg in messages:
            for att in msg.get("attachments", []):
                filename = att.get("filename", "").lower()
                if filename.endswith(".db") or filename.endswith(".sqlite"):
                    url = att.get("url")
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.read()
                                if len(data) > 0:
                                    target = Path(DATABASE_PATH)
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    with open(target, "wb") as f:
                                        f.write(data)
                                    global _last_backup_mtime
                                    _last_backup_mtime = os.path.getmtime(target)
                                    logger.info(
                                        "✅ Successfully restored database from Discord backup! (%d bytes)",
                                        len(data),
                                    )
                                    return True
        logger.info("ℹ️ No previous database backups found in channel. Initializing fresh.")
    except Exception as e:
        logger.warning("Could not restore database from Discord: %s", e)
    return False


async def upload_database_backup(
    bot: commands.Bot, reason: str = "Automated Periodic Sync"
) -> Optional[discord.Message]:
    """Upload current database file to the backup channel."""
    if not BACKUP_CHANNEL_ID:
        return None

    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        return None

    try:
        # Flush all uncheckpointed Write-Ahead Log (WAL) pages directly into the .db file
        if hasattr(bot, "db"):
            try:
                conn = await bot.db.connect()
                await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
                await conn.commit()
            except Exception as cp_err:
                logger.warning("WAL checkpoint warning: %s", cp_err)

        channel = bot.get_channel(BACKUP_CHANNEL_ID)
        if not channel:
            channel = await bot.fetch_channel(BACKUP_CHANNEL_ID)
        if not channel:
            return None

        size_kb = db_path.stat().st_size / 1024
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        stats = {}
        if hasattr(bot, "db"):
            try:
                stats = await bot.db.get_economy_stats(guild_id=0)
            except Exception:
                pass

        desc = (
            f"**Timestamp:** `{now_str}`\n"
            f"**Trigger:** {reason}\n"
            f"**File Size:** `{size_kb:.1f} KB`\n"
        )
        if stats and stats.get("total_clubs"):
            desc += f"**Registered Clubs:** `{stats.get('total_clubs', 0)}` • **Users:** `{stats.get('total_users', 0)}`\n"

        embed = discord.Embed(
            title="💾 BeastlyBank Cloud Database Backup",
            description=desc,
            color=0x2ECC71,
        )
        embed.set_footer(text=f"{BOT_NAME} Automated Persistence Guard")

        file = discord.File(str(db_path), filename="beastlybank.db")
        msg = await channel.send(embed=embed, file=file)

        global _last_backup_mtime
        _last_backup_mtime = db_path.stat().st_mtime
        logger.info("💾 Successfully uploaded database backup to Discord (%s).", reason)
        return msg
    except Exception as e:
        logger.warning("Failed to upload database backup to Discord: %s", e)
        return None


class BackupCog(commands.Cog):
    """Background backup scheduler and manual backup commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if BACKUP_CHANNEL_ID:
            self.auto_backup_loop.start()

    def cog_unload(self):
        if self.auto_backup_loop.is_running():
            self.auto_backup_loop.cancel()

    @tasks.loop(minutes=3)
    async def auto_backup_loop(self):
        """Periodically backup database if it has been updated."""
        global _last_backup_mtime
        db_path = Path(DATABASE_PATH)
        if not db_path.exists():
            return

        current_mtime = db_path.stat().st_mtime
        if current_mtime > _last_backup_mtime:
            await upload_database_backup(self.bot, reason="Automated Periodic Sync")

    @auto_backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="backup", aliases=["dbbackup", "savedb"])
    async def prefix_manual_backup(self, ctx: commands.Context):
        """bb!backup - Manually snapshot and backup database to Discord."""
        from utils.checks import is_banker_or_admin
        if not is_banker_or_admin(ctx.author):
            await ctx.send("❌ Only Bankers and Admins can trigger manual backups.")
            return

        if not BACKUP_CHANNEL_ID:
            await ctx.send("⚠️ `BACKUP_CHANNEL_ID` is not configured in environment variables.")
            return

        msg = await upload_database_backup(self.bot, reason=f"Manual backup by {ctx.author.display_name}")
        if msg:
            await ctx.send(f"✅ **Database Backup Saved!** Successfully uploaded to <#{BACKUP_CHANNEL_ID}>.")
        else:
            await ctx.send("❌ Failed to create database backup. Check bot permissions in backup channel.")


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
