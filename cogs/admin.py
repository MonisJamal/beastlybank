"""
Admin & Settings Cogs:
- /manage: Add, remove, set Cash, CP, and Training Tokens.
- /settings: Toggle economy, purchases, shop, and view status.
- /bank: Server announcements and user financial audits.
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
    parse_amount,
)
from utils.checks import require_beastlyfc, require_banker_or_admin
from utils.embeds import create_beastly_embed, error_embed, success_embed
from cogs.clubs import club_name_autocomplete


class ManageCurrency(commands.GroupCog, name="manage", description="Manage User Cash, CP, and Training Tokens"):
    """Staff commands to adjust player currency balances."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="add",
        description="Add Cash, CP or Training Tokens to a user.",
    )
    @app_commands.describe(
        user="Player to credit",
        currency="Currency to add (Cash, Points/CP, Tokens)",
        amount="Amount to add",
        reason="Reason for credit adjustment",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_add(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Admin Grant",
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
            reason=f"Admin grant by {interaction.user}: {reason}",
            related_user_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        curr_name = CURRENCIES[currency]["name"]
        embed = create_beastly_embed(
            title="🏦 Currency Added",
            description=(
                f"Successfully credited {curr_emoji} **{amount:,} {curr_name}** to {user.mention}!\n\n"
                f"📊 **New Balance:** `{updated[currency]:,}`\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="remove",
        description="Remove Cash, CP or Training Tokens from a user.",
    )
    @app_commands.describe(
        user="Player to debit",
        currency="Currency to remove (Cash, Points/CP, Tokens)",
        amount="Amount to remove",
        reason="Reason for deduction",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_remove(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Admin Deduction",
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
            reason=f"Admin deduction by {interaction.user}: {reason}",
            related_user_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        curr_name = CURRENCIES[currency]["name"]
        embed = create_beastly_embed(
            title="🏦 Currency Removed",
            description=(
                f"Successfully removed {curr_emoji} **{amount:,} {curr_name}** from {user.mention}.\n\n"
                f"📊 **New Balance:** `{updated[currency]:,}`\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="set",
        description="Set a user's Cash, CP or Training Tokens to a specific amount.",
    )
    @app_commands.describe(
        user="Player whose balance to set",
        currency="Currency to modify (Cash, Points/CP, Tokens)",
        amount="Exact new balance",
        reason="Reason for override",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_set(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: Optional[str] = "Admin Override",
    ):
        success, msg, updated = await self.db.admin_set_balance(
            user_id=user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=amount,
            reason=reason or "Admin Override",
            admin_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Error", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        curr_name = CURRENCIES[currency]["name"]
        embed = create_beastly_embed(
            title="🏦 Balance Set",
            description=(
                f"Set {user.mention}'s {curr_emoji} **{curr_name}** balance to **{amount:,}**.\n\n"
                f"📝 **Reason:** *{reason}*\n"
                f"👮 **Authorized by:** {interaction.user.mention}"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="vault",
        description="Manage and operate a club's treasury vault (BeastlyBank Banker command).",
    )
    @app_commands.describe(
        club="Club name or tag to adjust",
        currency="Currency type (Cash, Points/CP, Tokens)",
        action="Adjustment type (add, remove, or set)",
        amount="Amount (e.g. 26e6, 3e7, 500k, 1000)",
        reason="Official memo explaining the vault adjustment",
    )
    @app_commands.autocomplete(club=club_name_autocomplete)
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_vault(
        self,
        interaction: discord.Interaction,
        club: str,
        currency: Literal["cash", "points", "tokens"],
        action: Literal["add", "remove", "set"],
        amount: str,
        reason: Optional[str] = "BeastlyBank Banker Vault Operation",
    ):
        parsed_amount = parse_amount(amount)
        if parsed_amount is None or parsed_amount < 0:
            await interaction.response.send_message(
                embed=error_embed(
                    "Invalid Amount",
                    f"Invalid amount format: `{amount}`. Examples: `26e6`, `3e7`, `500k`, `1000000`, `0`."
                ),
                ephemeral=True,
            )
            return

        success, msg, data = await self.db.update_club_treasury(
            guild_id=interaction.guild_id,
            club_query=club,
            currency=currency,
            action=action,
            amount=parsed_amount,
            admin_id=interaction.user.id,
            reason=reason or "BeastlyBank Banker Vault Operation",
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Vault Operation Failed", msg), ephemeral=True)
            return

        curr_emoji = CURRENCIES[currency]["emoji"]
        curr_name = CURRENCIES[currency]["name"]
        target_club = data["club"]

        embed = create_beastly_embed(
            title="🏦 BeastlyBank Vault Operation Completed",
            description=(
                f"Successfully updated the treasury vault for **[{target_club['tag']}] {target_club['name']}**!\n\n"
                f"• **Operation:** `{action.upper()}`\n"
                f"• **Amount:** {curr_emoji} **{parsed_amount:,} {curr_name}** (`{amount}`)\n"
                f"• **Previous Balance:** {curr_emoji} `{data['previous']:,}`\n"
                f"• **New Vault Balance:** {curr_emoji} **{data['new_balance']:,}**\n"
                f"• **Authorized Banker:** {interaction.user.mention}\n"
                f"• **Official Memo:** *{reason}*"
            ),
            color=COLOR_SUCCESS if action == "add" else COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)


class ServerSettings(commands.GroupCog, name="settings", description="Manage Server Economy & Shop Settings"):
    """Staff controls for server-wide toggles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="economy",
        description="Enable or disable the server economy.",
    )
    @app_commands.describe(enabled="True to enable economy, False to disable")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def settings_economy(self, interaction: discord.Interaction, enabled: bool):
        success, msg = await self.db.update_setting(interaction.guild_id, "economy", enabled)
        await interaction.response.send_message(embed=success_embed("Economy Setting Updated", msg))

    @app_commands.command(
        name="view",
        description="View current server settings.",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def settings_view(self, interaction: discord.Interaction):
        cfg = await self.db.get_settings(interaction.guild_id)

        econ_status = "🟢 Enabled" if cfg.get("economy_enabled", 1) else "🔴 Disabled"

        embed = create_beastly_embed(
            title=f"⚙️ Server Settings • {SERVER_NAME}",
            description="Current financial configurations:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        embed.add_field(name="💰 Server Economy", value=f"**{econ_status}**", inline=True)
        embed.set_footer(text="Use /settings economy <enabled> to toggle the server economy.")
        await interaction.response.send_message(embed=embed)


class BankAdmin(commands.GroupCog, name="bank", description="BeastlyBank Staff & Banker Controls"):
    """Banker and Staff administrative management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

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
    await bot.add_cog(ManageCurrency(bot))
    await bot.add_cog(ServerSettings(bot))
    await bot.add_cog(BankAdmin(bot))
