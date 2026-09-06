"""
Bank Administration Cog: Staff management, fund adjustments, audits, and official announcements.
"""
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    CURRENCIES,
    BOT_NAME,
    SERVER_NAME,
    COLOR_BEASTLY_GOLD,
    COLOR_PITCH_GREEN,
    COLOR_SUCCESS,
)
from utils.checks import require_beastlyfc, require_banker_or_admin
from utils.embeds import create_beastly_embed, error_embed, success_embed


class BankAdmin(commands.GroupCog, name="bank", description="BeastlyBank Staff & Banker Controls"):
    """Banker and Staff administrative management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="add",
        description="Credit Cash, Points, or Tokens to a player's BeastlyBank account.",
    )
    @app_commands.describe(
        user="Player to credit",
        currency="Currency to add",
        amount="Amount to credit",
        reason="Reason for credit adjustment",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Staff Grant",
    ):
        if amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Amount", "Amount must be greater than 0."),
                ephemeral=True,
            )
            return

        success, msg, updated = await self.db.update_balance(
            user_id=user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            delta=amount,
            tx_type="admin_add",
            reason=f"Staff grant by {interaction.user}: {reason}",
            related_user_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        embed = create_beastly_embed(
            title="🏦 Funds Credited",
            description=(
                f"Successfully credited {curr_emoji} **{amount:,} {CURRENCIES[currency]['name']}** to {user.mention}!\n\n"
                f"📊 **New Balance:** `{updated[currency]:,}`\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="remove",
        description="Debit Cash, Points, or Tokens from a player's BeastlyBank account.",
    )
    @app_commands.describe(
        user="Player to debit",
        currency="Currency to remove",
        amount="Amount to debit",
        reason="Reason for debit adjustment",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Staff Deduction",
    ):
        if amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Amount", "Amount must be greater than 0."),
                ephemeral=True,
            )
            return

        success, msg, updated = await self.db.update_balance(
            user_id=user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            delta=-amount,
            tx_type="admin_remove",
            reason=f"Staff deduction by {interaction.user}: {reason}",
            related_user_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        embed = create_beastly_embed(
            title="🏦 Funds Deducted",
            description=(
                f"Successfully removed {curr_emoji} **{amount:,} {CURRENCIES[currency]['name']}** from {user.mention}.\n\n"
                f"📊 **New Balance:** `{updated[currency]:,}`\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="set",
        description="Directly set a player's BeastlyBank balance to a specific amount.",
    )
    @app_commands.describe(
        user="Player whose balance to modify",
        currency="Currency to set",
        amount="Exact new balance",
        reason="Reason for manual override",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_set(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Manual Audit Override",
    ):
        success, msg, updated = await self.db.admin_set_balance(
            user_id=user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=amount,
            reason=reason or "Manual Override",
            admin_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        embed = create_beastly_embed(
            title="🏦 Balance Overridden",
            description=(
                f"Set {user.mention}'s {curr_emoji} **{CURRENCIES[currency]['name']}** balance to **{amount:,}**.\n\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="audit",
        description="Run a full financial audit log on any BeastlyFC member.",
    )
    @app_commands.describe(user="The player to audit")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_audit(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        account = await self.db.get_or_create_user(user.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, user.id)
        tx_count = await self.db.get_total_transactions_count(user.id, interaction.guild_id)
        recent_txs = await self.db.get_transactions(user.id, interaction.guild_id, limit=5)

        embed = create_beastly_embed(
            title=f"🔍 Financial Audit Report • {user.display_name}",
            description=f"BeastlyBank compliance audit for {user.mention}.\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        embed.add_field(
            name="📊 Account Balances",
            value=(
                f"💵 Cash: `{account['cash']:,}`\n"
                f"⭐ Community Points: `{account['points']:,}`\n"
                f"🎟️ Training Tokens: `{account['tokens']:,}`"
            ),
            inline=True,
        )

        club_name = f"[{club['tag']}] {club['name']}" if club else "Free Agent (None)"
        embed.add_field(
            name="🏟️ Club Association",
            value=f"`{club_name}`",
            inline=True,
        )

        embed.add_field(
            name="📜 Transaction Statistics",
            value=f"Total Logged Transactions: **{tx_count:,}**",
            inline=True,
        )

        if recent_txs:
            lines = []
            for t in recent_txs:
                lines.append(f"• `#{t['id']}` `{t['tx_type']}`: {t['amount']:,} {t['currency']} ({t.get('reason') or 'No memo'})")
            embed.add_field(
                name="🕒 Recent Transactions",
                value="\n".join(lines),
                inline=False,
            )

        embed.set_footer(text=f"Audited by {interaction.user.display_name} • BeastlyBank Security")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="announce",
        description="Broadcast the official BeastlyBank Launch Announcement into a channel.",
    )
    @app_commands.describe(channel="Target channel for announcement (defaults to current channel)")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_announce(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        target_channel = channel or interaction.channel

        embed = create_beastly_embed(
            title="🏦 BEASTLYBANK IS HERE!",
            description=(
                f"We're introducing **{BOT_NAME}**, the official economy and finance system for **{SERVER_NAME}**! 💰⚽\n\n"
                f"**{BOT_NAME}** handles all server financial activities, including:\n\n"
                f"💵 **Cash** — Your main server currency\n"
                f"⭐ **Community Points** — Earned through server activities & match events\n"
                f"🎟️ **Training Tokens** — Used for player drills & club training\n"
                f"💸 **Player-to-Player Payments** — Instant slash payments\n"
                f"🛒 **Shop Purchases** — Unlock exclusive roles & boosts\n"
                f"🏟️ **Club Treasuries** — Dedicated vaults for BeastlyFC squads\n"
                f"🎉 **Giveaways** — Live interactive entry buttons & automated payouts\n"
                f"📜 **Transaction History** — Complete automated double-entry ledger\n"
                f"🏆 **Leaderboards** — Real-time wealth rankings\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **Your Economy**\n"
                f"Every member has their own **BeastlyBank** account automatically created with a starter pack!\n"
                f"Check your balances anytime using:\n\n"
                f"👉 </balance:0>\n\n"
                f"⚠️ **Important Notice**\n"
                f"Do not send money manually or keep track of transactions yourself.\n"
                f"**BeastlyBank** automatically records all supported transactions and manages balances through the secure database.\n\n"
                f"⚽ *Welcome to the next level of BeastlyFC!*"
            ),
            color=COLOR_BEASTLY_GOLD,
        )

        await target_channel.send(embed=embed)
        await interaction.response.send_message(
            f"✅ Announcement sent to {target_channel.mention}!", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BankAdmin(bot))
