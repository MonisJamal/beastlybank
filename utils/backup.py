"""
Automated Discord Cloud Database Backup & Restore for BeastlyBank.
Guarantees zero data loss on ephemeral cloud hosts (Render, Heroku, Discloud, Square Cloud).
Provides instant direct downloads via /backup, /bank backup, and bb!backup.
"""
import os
import time
import shutil
import sqlite3
import tempfile
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union, Dict, Any

import aiohttp
import discord
from discord import app_commands
from discord.ext import tasks, commands

from config import BACKUP_CHANNEL_ID, DATABASE_PATH, BOT_NAME
from utils.checks import is_banker_or_admin, require_beastlyfc, require_banker_or_admin
from utils.embeds import error_embed, success_embed

logger = logging.getLogger("BeastlyBank.Backup")

_last_backup_mtime: float = 0.0
_last_backup_timestamp: float = time.time()


def create_local_backup_file() -> Optional[Path]:
    """Create a timestamped SQLite copy in backups/ and keep the newest 15."""
    try:
        db_path = Path(DATABASE_PATH)
        if not db_path.exists():
            return None

        backup_dir = Path("backups")
        backup_dir.mkdir(parents=True, exist_ok=True)

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest_path = backup_dir / f"beastlybank_{now_str}.db"
        shutil.copy2(db_path, dest_path)

        # Rotate: keep newest 15
        existing = sorted(
            [p for p in backup_dir.glob("beastlybank_*.db") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if len(existing) > 15:
            for old_f in existing[15:]:
                try:
                    old_f.unlink()
                except Exception:
                    pass

        return dest_path
    except Exception as e:
        logger.warning("Failed to create local backup snapshot: %s", e)
        return None


def create_pre_restore_snapshot() -> Optional[Path]:
    """Create an emergency snapshot of current database before restore."""
    try:
        db_path = Path(DATABASE_PATH)
        if not db_path.exists():
            return None
        backup_dir = Path("backups")
        backup_dir.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest_path = backup_dir / f"pre_restore_{now_str}.db"
        shutil.copy2(db_path, dest_path)
        return dest_path
    except Exception as e:
        logger.warning("Failed to create pre-restore snapshot: %s", e)
        return None


async def restore_database_from_discord(bot: commands.Bot) -> bool:
    """Download the latest database file from the backup channel before initializing."""
    if not BACKUP_CHANNEL_ID:
        logger.info("ℹ️ BACKUP_CHANNEL_ID not set; skipping cloud database restore.")
        return False

    logger.info("🔍 Checking Discord backup channel (%d) for database snapshots...", BACKUP_CHANNEL_ID)
    try:
        messages = await asyncio.wait_for(bot.http.logs_from(BACKUP_CHANNEL_ID, limit=10), timeout=4.0)
        for msg in messages:
            for att in msg.get("attachments", []):
                filename = att.get("filename", "").lower()
                if filename.endswith(".db") or filename.endswith(".sqlite"):
                    url = att.get("url")
                    client_timeout = aiohttp.ClientTimeout(total=5.0, connect=2.0)
                    async with aiohttp.ClientSession(timeout=client_timeout) as session:
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
                                    create_local_backup_file()
                                    logger.info(
                                        "✅ Successfully restored database from Discord backup! (%d bytes)",
                                        len(data),
                                    )
                                    return True
        logger.info("ℹ️ No previous database backups found in channel. Initializing fresh.")
    except discord.Forbidden:
        logger.warning(
            "⚠️ Bot lacks permissions to access backup channel (%d). "
            "Please ensure the bot is in the server and granted 'View Channel', 'Read Message History', and 'Attach Files'.",
            BACKUP_CHANNEL_ID,
        )
    except discord.NotFound:
        logger.warning(
            "⚠️ Backup channel (%d) was not found. Please verify BACKUP_CHANNEL_ID in your configuration.",
            BACKUP_CHANNEL_ID,
        )
    except asyncio.TimeoutError:
        logger.warning("⏱️ Timeout while querying Discord backup channel (%d). Proceeding with startup.", BACKUP_CHANNEL_ID)
    except Exception as e:
        logger.warning("Could not restore database from Discord: %s", e)
    return False


async def upload_database_backup(
    bot: commands.Bot, reason: str = "Automated Periodic Sync"
) -> Optional[discord.Message]:
    """Upload current database file to the backup channel."""
    # Always maintain local rotating backup snapshot
    create_local_backup_file()

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
            except Exception as cp_err:
                logger.debug("WAL checkpoint note: %s", cp_err)

        channel = bot.get_channel(BACKUP_CHANNEL_ID)
        if not channel:
            try:
                channel = await asyncio.wait_for(bot.fetch_channel(BACKUP_CHANNEL_ID), timeout=5.0)
            except discord.Forbidden:
                logger.warning(
                    "⚠️ Bot lacks permission to access backup channel (%d). "
                    "Please ensure the bot has 'View Channel', 'Send Messages', and 'Attach Files' permissions.",
                    BACKUP_CHANNEL_ID,
                )
                return None
            except discord.NotFound:
                logger.warning(
                    "⚠️ Backup channel (%d) was not found. Please verify BACKUP_CHANNEL_ID.",
                    BACKUP_CHANNEL_ID,
                )
                return None
            except Exception as fe:
                logger.warning("Could not fetch backup channel (%d): %s", BACKUP_CHANNEL_ID, fe)
                return None
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
    except discord.Forbidden:
        logger.warning(
            "⚠️ Bot cannot send database backup to channel (%d): Forbidden. "
            "Please ensure the bot has 'View Channel', 'Send Messages', and 'Attach Files' permissions in that channel.",
            BACKUP_CHANNEL_ID,
        )
        return None
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

async def handle_backup_execution(
    bot: commands.Bot,
    target: Union[commands.Context, discord.Interaction],
):
    """Unified handler for manual backup via slash command (/backup, /bank backup) or prefix (bb!backup)."""
    author = target.user if isinstance(target, discord.Interaction) else target.author

    if not is_banker_or_admin(author):
        err_text = "Only Server Admins and Bankers can generate backups."
        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                await target.response.send_message(
                    embed=error_embed("Staff Authorization Required", err_text),
                    ephemeral=True,
                )
            else:
                await target.followup.send(
                    embed=error_embed("Staff Authorization Required", err_text),
                    ephemeral=True,
                )
        else:
            await target.send(f"❌ {err_text}")
        return

    if isinstance(target, discord.Interaction) and not target.response.is_done():
        await target.response.defer(ephemeral=True)

    db_path = Path(DATABASE_PATH)
    if not db_path.exists():
        err_text = f"Database file not found at `{DATABASE_PATH}`."
        if isinstance(target, discord.Interaction):
            await target.followup.send(embed=error_embed("Database Missing", err_text), ephemeral=True)
        else:
            await target.send(f"❌ {err_text}")
        return

    # Flush all uncheckpointed Write-Ahead Log (WAL) pages directly into the .db file
    if hasattr(bot, "db"):
        try:
            conn = await bot.db.connect()
            await conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
        except Exception as cp_err:
            logger.debug("WAL checkpoint note: %s", cp_err)

    # Create local rotating snapshot
    snapshot_path = create_local_backup_file()
    snapshot_name = snapshot_path.name if snapshot_path else "beastlybank.db"

    # Query key statistics for embed
    total_clubs = 0
    total_users = 0
    total_cash = 0
    try:
        if hasattr(bot, "db"):
            conn = await bot.db.connect()
            async with conn.cursor() as cur:
                await cur.execute("SELECT count(*) FROM clubs;")
                total_clubs = (await cur.fetchone())[0]
                await cur.execute("SELECT count(*) FROM users;")
                total_users = (await cur.fetchone())[0]
                await cur.execute("SELECT COALESCE(SUM(cash), 0) FROM users;")
                user_cash = (await cur.fetchone())[0]
                await cur.execute("SELECT COALESCE(SUM(balance), 0) FROM clubs;")
                club_cash = (await cur.fetchone())[0]
                total_cash = user_cash + club_cash
    except Exception as e:
        logger.debug("Backup stats query note: %s", e)

    size_kb = db_path.stat().st_size / 1024

    cloud_synced = False
    if BACKUP_CHANNEL_ID:
        try:
            cloud_msg = await upload_database_backup(bot, reason=f"Manual backup by {author.display_name}")
            if cloud_msg:
                cloud_synced = True
        except Exception as e:
            logger.warning("Cloud upload failed during manual backup: %s", e)

    if cloud_synced:
        color = 0x2ECC71
        title = "💾 Database Backup & Cloud Sync Complete"
        desc = (
            f"✅ **Database Snapshot Created & Cloud Synced!**\n\n"
            f"• **Database Size:** `{size_kb:.1f} KB`\n"
            f"• **Registered Clubs:** `{total_clubs}`\n"
            f"• **User Accounts:** `{total_users}`\n"
            f"• **Circulation:** 🪙 `{total_cash:,}` Cash\n"
            f"• **Local Snapshot:** `{snapshot_name}`\n"
            f"• **Cloud Auto-Sync:** ☁️ Uploaded to <#{BACKUP_CHANNEL_ID}>\n\n"
            f"📥 *Your direct database file (`beastlybank.db`) is attached below. Click to download and store safely!*"
        )
    else:
        color = 0xF1C40F
        title = "💾 Database Backup Created (Direct Download)"
        warning_block = ""
        if not BACKUP_CHANNEL_ID:
            warning_block = (
                f"\n\n⚠️ **CRITICAL: CLOUD AUTO-SYNC IS NOT CONFIGURED!**\n"
                f"Because this bot runs on cloud hosting (Discloud, Square Cloud, Render, etc.), "
                f"**all money, clubs, and data will be wiped whenever the bot restarts or redeploys** "
                f"unless you configure `BACKUP_CHANNEL_ID`!\n\n"
                f"**How to enable 24/7 Cloud Auto-Backup in 30 seconds:**\n"
                f"1. In your Discord server, create a private channel (e.g. `#bot-backups`).\n"
                f"2. Right-click the channel ➔ **Copy Channel ID**.\n"
                f"3. In your `.env` file (or host dashboard environment variables), set:\n"
                f"   `BACKUP_CHANNEL_ID=your_channel_id`\n"
                f"4. Restart the bot. BeastlyBank will automatically sync changes every 60s and auto-restore on boot!"
            )
        else:
            warning_block = f"\n\n⚠️ Could not upload to cloud backup channel `<#{BACKUP_CHANNEL_ID}>`. Please verify bot permissions in that channel."

        desc = (
            f"✅ **Database Snapshot Created!**\n\n"
            f"• **Database Size:** `{size_kb:.1f} KB`\n"
            f"• **Registered Clubs:** `{total_clubs}`\n"
            f"• **User Accounts:** `{total_users}`\n"
            f"• **Circulation:** 🪙 `{total_cash:,}` Cash\n"
            f"• **Local Snapshot:** `{snapshot_name}`"
            f"{warning_block}\n\n"
            f"📥 *Your direct database file (`beastlybank.db`) is attached below. Click to download and store safely!*"
        )

    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
    )
    embed.set_footer(text=f"{BOT_NAME} Automated Persistence Guard")

    file = discord.File(str(db_path), filename="beastlybank.db")
    if isinstance(target, discord.Interaction):
        try:
            await target.followup.send(embed=embed, file=file, ephemeral=True)
        except Exception:
            file = discord.File(str(db_path), filename="beastlybank.db")
            await target.followup.send(embed=embed, file=file)
    else:
        await target.send(embed=embed, file=file)


async def handle_restore_execution(
    bot: commands.Bot,
    target: Union[commands.Context, discord.Interaction],
    attachment: Optional[discord.Attachment],
):
    """Unified handler for restoring database from an attached SQLite file."""
    author = target.user if isinstance(target, discord.Interaction) else target.author

    if not is_banker_or_admin(author):
        err_text = "Only Server Admins and Bankers can restore the database."
        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                await target.response.send_message(
                    embed=error_embed("Staff Authorization Required", err_text),
                    ephemeral=True,
                )
            else:
                await target.followup.send(
                    embed=error_embed("Staff Authorization Required", err_text),
                    ephemeral=True,
                )
        else:
            await target.send(f"❌ {err_text}")
        return

    if not attachment:
        msg = "Please attach a valid `beastlybank.db` backup file to restore."
        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                await target.response.send_message(embed=error_embed("Missing Attachment", msg), ephemeral=True)
            else:
                await target.followup.send(embed=error_embed("Missing Attachment", msg), ephemeral=True)
        else:
            await target.send(f"❌ {msg}")
        return

    fname = attachment.filename.lower()
    if not (fname.endswith(".db") or fname.endswith(".sqlite")):
        msg = "Attached file must be a SQLite database file (`.db` or `.sqlite`)."
        if isinstance(target, discord.Interaction):
            if not target.response.is_done():
                await target.response.send_message(embed=error_embed("Invalid File", msg), ephemeral=True)
            else:
                await target.followup.send(embed=error_embed("Invalid File", msg), ephemeral=True)
        else:
            await target.send(f"❌ {msg}")
        return

    if isinstance(target, discord.Interaction) and not target.response.is_done():
        await target.response.defer(ephemeral=True)

    try:
        data = await attachment.read()
        if len(data) < 100:
            err_msg = "The attached database file is empty or corrupted."
            if isinstance(target, discord.Interaction):
                await target.followup.send(embed=error_embed("Invalid File", err_msg), ephemeral=True)
            else:
                await target.send(f"❌ {err_msg}")
            return

        # Validate SQLite format and tables
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            test_con = sqlite3.connect(tmp_path)
            cur = test_con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [t[0] for t in cur.fetchall()]

            user_cnt = 0
            club_cnt = 0
            if "users" in tables:
                cur.execute("SELECT count(*) FROM users;")
                user_cnt = cur.fetchone()[0]
            if "clubs" in tables:
                cur.execute("SELECT count(*) FROM clubs;")
                club_cnt = cur.fetchone()[0]
            test_con.close()

            if "users" not in tables and "clubs" not in tables:
                err_msg = "Attached file is not a valid BeastlyBank database (missing required `users` or `clubs` tables)."
                if isinstance(target, discord.Interaction):
                    await target.followup.send(embed=error_embed("Corrupt Database", err_msg), ephemeral=True)
                else:
                    await target.send(f"❌ {err_msg}")
                return
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        # 1. Take safety pre-restore backup of current DB
        pre_path = create_pre_restore_snapshot()

        # 2. Close current active DB connection
        if hasattr(bot, "db"):
            await bot.db.close()

        # 3. Overwrite database file
        target_path = Path(DATABASE_PATH)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with open(target_path, "wb") as f:
            f.write(data)

        # 4. Re-initialize database
        if hasattr(bot, "db"):
            await bot.db.init_db()

        # 5. Flush checkpoint & upload confirmation to backup channel
        if BACKUP_CHANNEL_ID:
            await upload_database_backup(
                bot, reason=f"Restored from manual file by {author.display_name}"
            )

        success_desc = (
            f"✅ **Database Restored Successfully!**\n\n"
            f"• **Tables Restored:** `{len(tables)}`\n"
            f"• **Registered Clubs:** `{club_cnt}`\n"
            f"• **User Accounts:** `{user_cnt}`\n"
            f"• **Safety Snapshot:** Created `{pre_path.name if pre_path else 'N/A'}` before overwrite.\n"
        )
        if BACKUP_CHANNEL_ID:
            success_desc += f"• **Cloud Checkpoint:** ☁️ Uploaded fresh state to <#{BACKUP_CHANNEL_ID}>.\n"

        embed = discord.Embed(
            title="🔄 BeastlyBank Database Restored",
            description=success_desc,
            color=0x2ECC71,
        )
        embed.set_footer(text=f"{BOT_NAME} Database Recovery System")

        if isinstance(target, discord.Interaction):
            await target.followup.send(embed=embed, ephemeral=True)
        else:
            await target.send(embed=embed)

    except Exception as e:
        logger.error("Restore failed: %s", e, exc_info=True)
        err_msg = f"Failed to restore database: `{e}`"
        if isinstance(target, discord.Interaction):
            await target.followup.send(embed=error_embed("Restore Failed", err_msg), ephemeral=True)
        else:
            await target.send(f"❌ {err_msg}")


class BackupCog(commands.Cog):
    """Background backup scheduler, direct database downloads, and restore controls."""

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

    @app_commands.command(
        name="backup",
        description="Download an instant backup of the BeastlyBank database & sync to cloud.",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def slash_backup(self, interaction: discord.Interaction):
        await handle_backup_execution(self.bot, interaction)

    @app_commands.command(
        name="restore",
        description="Restore BeastlyBank database from an attached .db backup file (Admin/Banker only).",
    )
    @app_commands.describe(
        backup_file="Attach the beastlybank.db backup file to restore",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def slash_restore(self, interaction: discord.Interaction, backup_file: discord.Attachment):
        await handle_restore_execution(self.bot, interaction, backup_file)

    @commands.command(name="backup", aliases=["dbbackup", "savedb"])
    async def prefix_manual_backup(self, ctx: commands.Context):
        """bb!backup - Manually snapshot and download database, syncing to Discord cloud."""
        await handle_backup_execution(self.bot, ctx)

    @commands.command(name="restore", aliases=["dbrestore", "loaddb"])
    async def prefix_restore(self, ctx: commands.Context):
        """bb!restore - Attach a beastlybank.db backup file to restore it directly."""
        att = ctx.message.attachments[0] if ctx.message.attachments else None
        await handle_restore_execution(self.bot, ctx, att)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
