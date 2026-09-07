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
_last_backup_timestamp: float = time.time()


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

        global _last_backup_mtime, _last_backup_timestamp
        _last_backup_mtime = max(db_path.stat().st_mtime, (Path(str(DATABASE_PATH) + "-wal").stat().st_mtime if Path(str(DATABASE_PATH) + "-wal").exists() else 0))
        _last_backup_timestamp = time.time()
        logger.info("💾 Successfully uploaded database backup to Discord (%s).", reason)

        # Prune older backup messages to keep channel clean (keep newest 5)
        try:
            bot_msgs = []
            async for old_msg in channel.history(limit=25):
                if old_msg.author == bot.user and old_msg.attachments:
                    bot_msgs.append(old_msg)
            if len(bot_msgs) > 5:
                for old in bot_msgs[5:]:
                    try:
                        await old.delete()
                    except Exception:
                        pass
        except Exception as prune_err:
            logger.debug("Old backup prune: %s", prune_err)

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

    @tasks.loop(seconds=60)
    async def auto_backup_loop(self):
        """Check for database modifications every 60s and backup if changed or on 10-min heartbeat."""
        global _last_backup_mtime, _last_backup_timestamp
        db_path = Path(DATABASE_PATH)
        wal_path = Path(str(DATABASE_PATH) + "-wal")
        if not db_path.exists():
            return

        now = time.time()
        mtime_main = db_path.stat().st_mtime
        mtime_wal = wal_path.stat().st_mtime if wal_path.exists() else 0
        wal_size = wal_path.stat().st_size if wal_path.exists() else 0

        current_max_mtime = max(mtime_main, mtime_wal)
        has_new_data = (wal_size > 0) or (current_max_mtime > _last_backup_mtime)
        time_elapsed = now - _last_backup_timestamp
        is_heartbeat = (time_elapsed >= 600)  # 10 minutes heartbeat

        if has_new_data or is_heartbeat:
            reason = "Live Data Change" if has_new_data else "Scheduled 10-Min Heartbeat"
            await upload_database_backup(self.bot, reason=reason)

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

    @commands.command(name="restore", aliases=["dbrestore", "loaddb"])
    async def prefix_restore(self, ctx: commands.Context):
        """bb!restore - Attach a beastlybank.db backup file to restore it directly."""
        from utils.checks import is_banker_or_admin
        if not is_banker_or_admin(ctx.author):
            await ctx.send("❌ Only Server Admins and Bankers can restore the database.")
            return

        att = ctx.message.attachments[0] if ctx.message.attachments else None
        if not att:
            await ctx.send("❌ Please attach the `beastlybank.db` backup file to your message (download it from the backup channel and attach it with `bb!restore`).")
            return

        if not (att.filename.endswith(".db") or att.filename.endswith(".sqlite")):
            await ctx.send("❌ Attached file must be a SQLite database (`.db` or `.sqlite`).")
            return

        try:
            data = await att.read()
            if len(data) < 100:
                await ctx.send("❌ The attached file is empty or invalid.")
                return

            import tempfile, sqlite3
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(data)
                tmp_path = tmp.name

            try:
                test_con = sqlite3.connect(tmp_path)
                cur = test_con.cursor()
                cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
                tables = [t[0] for t in cur.fetchall()]
                test_con.close()
                if "users" not in tables and "clubs" not in tables:
                    await ctx.send("❌ Attached file does not appear to be a valid BeastlyBank database (missing `users`/`clubs` tables).")
                    return
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            # Close current DB connection safely
            if hasattr(self.bot, "db"):
                await self.bot.db.close()

            # Replace local database file
            target = Path(DATABASE_PATH)
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as f:
                f.write(data)

            # Re-initialize DB
            await self.bot.db.init_db()

            # Upload fresh backup confirming restored state
            await upload_database_backup(self.bot, reason=f"Restored from manual file by {ctx.author.display_name}")

            await ctx.send(f"✅ **Database Restored Successfully!** Active ledger loaded with {len(tables)} tables. A new cloud snapshot has been created.")
        except Exception as e:
            logger.error("Restore failed: %s", e)
            await ctx.send(f"❌ Failed to restore database: `{e}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
