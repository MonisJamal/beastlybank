"""
Giveaways Cog: Automated giveaways, interactive entry buttons, timer task, and prize disbursements.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import json
import re
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import CURRENCIES, COLOR_BEASTLY_GOLD, COLOR_SUCCESS, COLOR_ERROR
from utils.checks import require_beastlyfc, require_banker_or_admin
from utils.embeds import create_beastly_embed, error_embed, success_embed
from utils.views import GiveawayView


def parse_duration(time_str: str) -> Optional[timedelta]:
    """Parse time strings like 30s, 15m, 2h, 3d."""
    pattern = r"(\d+)\s*([smhd])"
    match = re.match(pattern, time_str.strip().lower())
    if not match:
        return None
    val, unit = match.groups()
    val = int(val)
    if unit == "s":
        return timedelta(seconds=val)
    elif unit == "m":
        return timedelta(minutes=val)
    elif unit == "h":
        return timedelta(hours=val)
    elif unit == "d":
        return timedelta(days=val)
    return None


class Giveaways(commands.GroupCog, name="giveaway", description="Host and manage BeastlyBank giveaways"):
    """BeastlyFC server giveaways with direct bank prize integration."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @tasks.loop(seconds=15.0)
    async def check_giveaways(self):
        """Background task checking for expired active giveaways."""
        try:
            active_gws = await self.db.get_active_giveaways()
            now = datetime.now(timezone.utc)

            for gw in active_gws:
                end_time = datetime.fromisoformat(gw["end_time"])
                if now >= end_time:
                    await self._conclude_giveaway(gw["message_id"], gw["channel_id"])
        except Exception as e:
            # Avoid crashing loop
            pass

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    async def _conclude_giveaway(self, message_id: int, channel_id: int):
        """Pick winners, disburse bank prizes, and post announcement."""
        success, msg, winners, gw = await self.db.end_giveaway(message_id)
        if not success:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            return

        # Fetch original message if possible to update embed
        try:
            message = await channel.fetch_message(message_id)
        except Exception:
            message = None

        prize_str = gw["prize_name"]
        if gw.get("prize_currency") and gw.get("prize_amount", 0) > 0:
            emoji = CURRENCIES.get(gw["prize_currency"], {}).get("emoji", "💰")
            prize_str = f"{emoji} {gw['prize_amount']:,} {gw['prize_name']}"

        if not winners:
            end_embed = create_beastly_embed(
                title="🎉 Giveaway Concluded",
                description=f"**Prize:** {prize_str}\n\n*No valid entries were received. No winners selected.*",
                color=COLOR_ERROR,
            )
            if message:
                await message.edit(embed=end_embed, view=None)
            await channel.send(f"📢 **Giveaway Ended:** No participants joined for **{prize_str}**.")
            return

        winner_mentions = ", ".join(f"<@{w}>" for w in winners)
        end_embed = create_beastly_embed(
            title="🏆 BeastlyBank Giveaway Concluded!",
            description=(
                f"**Prize:** {prize_str}\n"
                f"**Winner(s):** {winner_mentions}\n"
                f"**Total Entries:** `{len(json.loads(gw.get('entries', '[]')))}`\n\n"
                f"🏦 *If this prize included currency, funds have been automatically disbursed into the winners' BeastlyBank accounts!*"
            ),
            color=COLOR_SUCCESS,
        )

        if message:
            await message.edit(embed=end_embed, view=None)

        await channel.send(
            f"🎉 Congratulations {winner_mentions}! You won **{prize_str}** in the BeastlyBank giveaway!"
        )

    @app_commands.command(
        name="start",
        description="Host a BeastlyBank giveaway with interactive button entry and optional bank prizes.",
    )
    @app_commands.describe(
        duration="Duration of the giveaway (e.g. 10m, 2h, 1d)",
        prize="Name or description of the prize (e.g. VIP Club Pass, 5,000 Cash)",
        winners="Number of winners to draw (default: 1)",
        currency="Currency to automatically award winners (optional)",
        currency_amount="Amount of currency each winner receives (optional)",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def giveaway_start(
        self,
        interaction: discord.Interaction,
        duration: str,
        prize: str,
        winners: int = 1,
        currency: Optional[Literal["cash", "points", "tokens"]] = None,
        currency_amount: Optional[int] = None,
    ):
        delta = parse_duration(duration)
        if not delta:
            await interaction.response.send_message(
                embed=error_embed("Invalid Duration", "Use formats like `30s`, `15m`, `2h`, or `1d`."),
                ephemeral=True,
            )
            return

        if winners < 1:
            await interaction.response.send_message(
                embed=error_embed("Invalid Winners", "There must be at least 1 winner."),
                ephemeral=True,
            )
            return

        now = datetime.now(timezone.utc)
        end_time = now + delta
        end_timestamp = int(end_time.timestamp())

        prize_display = prize
        if currency and currency_amount and currency_amount > 0:
            emoji = CURRENCIES.get(currency, {}).get("emoji", "💰")
            prize_display = f"{emoji} {currency_amount:,} {CURRENCIES[currency]['name']} - {prize}"

        embed = create_beastly_embed(
            title="🎉 BEASTLYBANK OFFICIAL GIVEAWAY 🎉",
            description=(
                f"**Prize:** **{prize_display}**\n"
                f"**Hosted by:** {interaction.user.mention}\n"
                f"**Winners:** `{winners}`\n"
                f"**Ends:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n\n"
                f"Click the green button below to enter!"
            ),
            color=COLOR_BEASTLY_GOLD,
        )

        view = GiveawayView(self.db)
        await interaction.response.send_message("Creating giveaway...", ephemeral=True)
        gw_msg = await interaction.channel.send(embed=embed, view=view)

        await self.db.create_giveaway(
            message_id=gw_msg.id,
            channel_id=interaction.channel_id,
            guild_id=interaction.guild_id,
            host_id=interaction.user.id,
            prize_name=prize,
            prize_currency=currency,
            prize_amount=currency_amount or 0,
            winner_count=winners,
            end_time=end_time.isoformat(),
        )

        await interaction.edit_original_response(content="✅ Giveaway is live!")

    @app_commands.command(
        name="end",
        description="Immediately conclude an active giveaway.",
    )
    @app_commands.describe(message_id="Discord message ID of the giveaway")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def giveaway_end(self, interaction: discord.Interaction, message_id: str):
        if not message_id.isdigit():
            await interaction.response.send_message("Invalid Message ID.", ephemeral=True)
            return

        msg_int = int(message_id)
        await interaction.response.defer(ephemeral=True)
        await self._conclude_giveaway(msg_int, interaction.channel_id)
        await interaction.followup.send("✅ Giveaway processed.", ephemeral=True)

    @app_commands.command(
        name="reroll",
        description="Reroll winners for a concluded giveaway.",
    )
    @app_commands.describe(message_id="Discord message ID of the concluded giveaway")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def giveaway_reroll(self, interaction: discord.Interaction, message_id: str):
        if not message_id.isdigit():
            await interaction.response.send_message("Invalid Message ID.", ephemeral=True)
            return

        conn = await self.db.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM giveaways WHERE message_id = ?;", (int(message_id),)
            )
            gw = await cur.fetchone()

        if not gw:
            await interaction.response.send_message("Giveaway record not found.", ephemeral=True)
            return

        entries = json.loads(gw["entries"])
        if not entries:
            await interaction.response.send_message("No entries to reroll.", ephemeral=True)
            return

        import random
        winner = random.choice(entries)
        await interaction.response.send_message(
            f"🎲 **Reroll Winner:** Congratulations <@{winner}>! You are the new winner for **{gw['prize_name']}**!"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
