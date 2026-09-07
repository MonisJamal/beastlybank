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
        club="Club role mention to adjust",
        currency="Currency type (Cash, Points/CP, Tokens)",
        action="Adjustment type (add, remove, or set)",
        amount="Amount (e.g. 26e6, 3e7, 500k, 1000)",
        reason="Official memo explaining the vault adjustment",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_vault(
        self,
        interaction: discord.Interaction,
        club: discord.Role,
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
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"

        embed = create_beastly_embed(
            title="🏦 BeastlyBank Vault Operation Completed",
            description=(
                f"Successfully updated the treasury vault for {role_label}!\n\n"
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

    @app_commands.command(
        name="manager",
        description="Add or remove a Club Manager for any club (BeastlyBank Banker command).",
    )
    @app_commands.describe(
        action="Appoint or remove manager role (add or remove)",
        club="Target club Discord role",
        user="Squad member to promote or demote",
        reason="Official memo explaining the appointment or demotion",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def manage_manager(
        self,
        interaction: discord.Interaction,
        action: Literal["add", "remove"],
        club: discord.Role,
        user: discord.Member,
        reason: Optional[str] = "BeastlyBank Staff Operation",
    ):
        is_manager = (action == "add")
        success, msg, target_club = await self.db.admin_set_club_manager(
            guild_id=interaction.guild_id,
            club_query=club,
            target_user_id=user.id,
            is_manager=is_manager,
            admin_id=interaction.user.id,
            reason=reason or "BeastlyBank Staff Operation",
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Manager Operation Failed", msg), ephemeral=True)
            return

        role_label = f"<@&{target_club['role_id']}>" if target_club and target_club.get("role_id") else f"**[{target_club.get('tag', 'FC')}] {target_club.get('name', 'Club')}**"
        action_title = "Manager Appointed" if is_manager else "Manager Removed"

        embed = create_beastly_embed(
            title=f"👔 Club Manager Update • {action_title}",
            description=(
                f"Successfully updated club management roster for {role_label}!\n\n"
                f"• **Target Member:** {user.mention} (`{user.display_name}`)\n"
                f"• **New Club Status:** {'⭐ **Club Manager**' if is_manager else '⚽ **Squad Member**'}\n"
                f"• **Authorized Banker:** {interaction.user.mention}\n"
                f"• **Official Memo:** *{reason}*\n"
                f"• **Data Integrity:** 🛡️ Zero data loss (player balances, cards, and treasury 100% intact)."
            ),
            color=COLOR_SUCCESS if is_manager else COLOR_BEASTLY_GOLD,
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
        name="purchases",
        description="Enable or disable shop purchases.",
    )
    @app_commands.describe(enabled="True to enable purchases, False to disable")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def settings_purchases(self, interaction: discord.Interaction, enabled: bool):
        success, msg = await self.db.update_setting(interaction.guild_id, "purchases", enabled)
        await interaction.response.send_message(embed=success_embed("Purchases Setting Updated", msg))

    @app_commands.command(
        name="shop",
        description="Enable or disable the shop.",
    )
    @app_commands.describe(enabled="True to enable shop, False to disable")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def settings_shop(self, interaction: discord.Interaction, enabled: bool):
        success, msg = await self.db.update_setting(interaction.guild_id, "shop", enabled)
        await interaction.response.send_message(embed=success_embed("Shop Setting Updated", msg))

    @app_commands.command(
        name="view",
        description="View current server settings.",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def settings_view(self, interaction: discord.Interaction):
        cfg = await self.db.get_settings(interaction.guild_id)

        econ_status = "🟢 Enabled" if cfg.get("economy_enabled", 1) else "🔴 Disabled"
        purchases_status = "🟢 Enabled" if cfg.get("purchases_enabled", 1) else "🔴 Disabled"
        shop_status = "🟢 Enabled" if cfg.get("shop_enabled", 1) else "🔴 Disabled"

        embed = create_beastly_embed(
            title=f"⚙️ Server Settings • {SERVER_NAME}",
            description="Current financial and store configurations:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        embed.add_field(name="💰 Server Economy", value=f"**{econ_status}**", inline=True)
        embed.add_field(name="🛒 Server Shop", value=f"**{shop_status}**", inline=True)
        embed.add_field(name="🛍️ Item Purchases", value=f"**{purchases_status}**", inline=True)

        embed.set_footer(text="Use /settings <economy|shop|purchases> to toggle settings.")
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
        name="manager",
        description="Add or remove a Club Manager for any club (BeastlyBank Banker command).",
    )
    @app_commands.describe(
        action="Appoint or remove manager role (add or remove)",
        club="Target club Discord role",
        user="Squad member to promote or demote",
        reason="Official memo explaining the appointment or demotion",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_manager(
        self,
        interaction: discord.Interaction,
        action: Literal["add", "remove"],
        club: discord.Role,
        user: discord.Member,
        reason: Optional[str] = "BeastlyBank Staff Operation",
    ):
        is_manager = (action == "add")
        success, msg, target_club = await self.db.admin_set_club_manager(
            guild_id=interaction.guild_id,
            club_query=club,
            target_user_id=user.id,
            is_manager=is_manager,
            admin_id=interaction.user.id,
            reason=reason or "BeastlyBank Staff Operation",
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Manager Operation Failed", msg), ephemeral=True)
            return

        role_label = f"<@&{target_club['role_id']}>" if target_club and target_club.get("role_id") else f"**[{target_club.get('tag', 'FC')}] {target_club.get('name', 'Club')}**"
        action_title = "Manager Appointed" if is_manager else "Manager Removed"

        embed = create_beastly_embed(
            title=f"👔 Club Manager Update • {action_title}",
            description=(
                f"Successfully updated club management roster for {role_label}!\n\n"
                f"• **Target Member:** {user.mention} (`{user.display_name}`)\n"
                f"• **New Club Status:** {'⭐ **Club Manager**' if is_manager else '⚽ **Squad Member**'}\n"
                f"• **Authorized Banker:** {interaction.user.mention}\n"
                f"• **Official Memo:** *{reason}*\n"
                f"• **Data Integrity:** 🛡️ Zero data loss (player balances, cards, and treasury 100% intact)."
            ),
            color=COLOR_SUCCESS if is_manager else COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="backup",
        description="Save and backup the BeastlyBank database to the cloud backup channel.",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def bank_backup(self, interaction: discord.Interaction):
        from utils.backup import upload_database_backup
        from config import BACKUP_CHANNEL_ID
        if not BACKUP_CHANNEL_ID:
            await interaction.response.send_message(
                embed=error_embed("Backup Not Configured", "Set `BACKUP_CHANNEL_ID` in your environment variables."),
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        msg = await upload_database_backup(self.bot, reason=f"Manual backup by {interaction.user.display_name}")
        if msg:
            await interaction.followup.send(
                embed=success_embed("Database Backup Saved", f"Successfully saved and uploaded latest snapshot to <#{BACKUP_CHANNEL_ID}>!"),
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                embed=error_embed("Backup Failed", "Could not upload snapshot. Please check bot permissions in the backup channel."),
                ephemeral=True
            )


class BankerPrefixCommands(commands.Cog):
    """Prefix commands for BeastlyBank Bankers and Admins."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @commands.command(name="vault")
    @require_banker_or_admin()
    async def prefix_vault(self, ctx: commands.Context, *args):
        """
        bb!vault <@club_role> <cash|points|tokens> <add|remove|set> <amount> [reason]
        e.g. bb!vault @RealMadrid cash add 10m Bonus
        """
        if len(args) < 4 and not (ctx.message.role_mentions and len(args) >= 3):
            embed = error_embed(
                "Invalid Command Usage",
                "**Usage:** `bb!vault <@club_role> <currency> <add|remove|set> <amount> [reason]`\n"
                "**Example:** `bb!vault @RealMadrid cash add 10m Bonus`"
            )
            await ctx.send(embed=embed)
            return

        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None

        # Filter args
        cur_args = list(args)
        if target_role:
            cur_args = [a for a in cur_args if not (a.startswith("<@&") and a.endswith(">"))]

        # Extract currency
        valid_currencies = ("cash", "points", "tokens", "token", "point")
        curr_key = None
        curr_idx = -1
        for i, a in enumerate(cur_args):
            low = a.lower().strip()
            if low in valid_currencies:
                curr_key = "points" if "point" in low else ("tokens" if "token" in low else "cash")
                curr_idx = i
                break

        if not curr_key:
            await ctx.send(embed=error_embed("Invalid Currency", "Currency must be `cash`, `points`, or `tokens`."))
            return

        cur_args.pop(curr_idx)

        # Extract action
        valid_actions = ("add", "remove", "set")
        action = None
        action_idx = -1
        for i, a in enumerate(cur_args):
            low = a.lower().strip()
            if low in valid_actions:
                action = low
                action_idx = i
                break

        if not action:
            await ctx.send(embed=error_embed("Invalid Action", "Action must be `add`, `remove`, or `set`."))
            return

        cur_args.pop(action_idx)

        # Extract amount
        amount_idx = -1
        parsed_amount = None
        amount_raw = ""
        for i, a in enumerate(cur_args):
            val = parse_amount(a)
            if val is not None and val >= 0:
                parsed_amount = val
                amount_raw = a
                amount_idx = i
                break

        if parsed_amount is None:
            await ctx.send(embed=error_embed("Invalid Amount", "Please specify a valid amount (e.g. `26e6`, `3e7`, `500k`, `1000`)."))
            return

        cur_args.pop(amount_idx)

        # Remaining is club (if no role mention) and reason
        if target_role:
            club_target = target_role
            reason = " ".join(cur_args).strip() or "BeastlyBank Banker Vault Operation"
        else:
            if not cur_args:
                await ctx.send(embed=error_embed("Missing Club", "Please mention a club role (e.g. `bb!vault @ClubRole cash add 10m`)."))
                return
            club_target = cur_args[0]
            reason = " ".join(cur_args[1:]).strip() or "BeastlyBank Banker Vault Operation"

        success, msg, data = await self.db.update_club_treasury(
            guild_id=ctx.guild.id,
            club_query=club_target,
            currency=curr_key,
            action=action,
            amount=parsed_amount,
            admin_id=ctx.author.id,
            reason=reason,
        )

        if not success:
            await ctx.send(embed=error_embed("Vault Operation Failed", msg))
            return

        curr_emoji = CURRENCIES[curr_key]["emoji"]
        curr_name = CURRENCIES[curr_key]["name"]
        target_club = data["club"]
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"

        embed = create_beastly_embed(
            title="🏦 BeastlyBank Vault Operation Completed",
            description=(
                f"Successfully updated the treasury vault for {role_label}!\n\n"
                f"• **Operation:** `{action.upper()}`\n"
                f"• **Amount:** {curr_emoji} **{parsed_amount:,} {curr_name}** (`{amount_raw}`)\n"
                f"• **Previous Balance:** {curr_emoji} `{data['previous']:,}`\n"
                f"• **New Vault Balance:** {curr_emoji} **{data['new_balance']:,}**\n"
                f"• **Authorized Banker:** {ctx.author.mention}\n"
                f"• **Official Memo:** *{reason}*"
            ),
            color=COLOR_SUCCESS if action == "add" else COLOR_BEASTLY_GOLD,
        )
        await ctx.send(embed=embed)

    @commands.command(name="manager", aliases=["clubmanager", "setmanager"])
    @require_banker_or_admin()
    async def prefix_manager(self, ctx: commands.Context, *args):
        """
        bb!manager <add|remove> <@club_role> <@user> [reason]
        e.g. bb!manager add @RealMadrid @User Official Appointment
        """
        await self._handle_manager_prefix(ctx, args)

    @commands.command(name="addmanager", aliases=["adminaddmanager"])
    @require_banker_or_admin()
    async def prefix_addmanager(self, ctx: commands.Context, *args):
        """
        bb!addmanager <@club_role> <@user> [reason]
        """
        await self._handle_manager_prefix(ctx, ("add",) + args)

    @commands.command(name="removemanager", aliases=["adminremovemanager"])
    @require_banker_or_admin()
    async def prefix_removemanager(self, ctx: commands.Context, *args):
        """
        bb!removemanager <@club_role> <@user> [reason]
        """
        await self._handle_manager_prefix(ctx, ("remove",) + args)

    async def _handle_manager_prefix(self, ctx: commands.Context, args):
        if len(args) < 2 and not (ctx.message.role_mentions and ctx.message.mentions):
            embed = error_embed(
                "Invalid Command Usage",
                "**Usage:** `bb!manager <add|remove> <@club_role> <@user> [reason]`\n"
                "**Example:** `bb!manager add @RealMadrid @Member Official Appointment`\n"
                "*(Or use `bb!addmanager @ClubRole @User` / `bb!removemanager @ClubRole @User`)*",
            )
            await ctx.send(embed=embed)
            return

        cur_args = list(args)

        # Detect action
        action = None
        for i, a in enumerate(cur_args):
            low = a.lower().strip()
            if low in ("add", "promote", "assign", "set", "+"):
                action = "add"
                cur_args.pop(i)
                break
            elif low in ("remove", "demote", "delete", "rm", "-"):
                action = "remove"
                cur_args.pop(i)
                break

        if not action:
            action = "add"

        # Target role
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        # Target user
        target_user = ctx.message.mentions[0] if ctx.message.mentions else None

        # Filter out mentions from args to get reason
        filtered_args = []
        for a in cur_args:
            if a.startswith("<@&") and a.endswith(">"):
                continue
            if (a.startswith("<@!") or a.startswith("<@")) and a.endswith(">"):
                continue
            filtered_args.append(a)

        reason = " ".join(filtered_args).strip() or "BeastlyBank Banker Club Operation"

        if not target_role:
            await ctx.send(embed=error_embed("Missing Club Role", "Please mention the club's Discord role (e.g. `@RealMadrid`)."))
            return

        if not target_user:
            await ctx.send(embed=error_embed("Missing User", "Please mention the member to add or remove as manager (e.g. `@User`)."))
            return

        is_manager = (action == "add")
        success, msg, target_club = await self.db.admin_set_club_manager(
            guild_id=ctx.guild.id,
            club_query=target_role,
            target_user_id=target_user.id,
            is_manager=is_manager,
            admin_id=ctx.author.id,
            reason=reason,
        )

        if not success:
            await ctx.send(embed=error_embed("Operation Failed", msg))
            return

        role_label = f"<@&{target_club['role_id']}>" if target_club and target_club.get("role_id") else f"**[{target_club.get('tag', 'FC')}] {target_club.get('name', 'Club')}**"
        action_title = "Manager Appointed" if is_manager else "Manager Removed"

        embed = create_beastly_embed(
            title=f"👔 Club Manager Update • {action_title}",
            description=(
                f"Successfully updated club management roster for {role_label}!\n\n"
                f"• **Target Member:** {target_user.mention} (`{target_user.display_name}`)\n"
                f"• **New Club Status:** {'⭐ **Club Manager**' if is_manager else '⚽ **Squad Member**'}\n"
                f"• **Authorized Banker:** {ctx.author.mention}\n"
                f"• **Official Memo:** *{reason}*\n"
                f"• **Data Integrity:** 🛡️ Zero data loss (player balances, cards, and treasury 100% intact)."
            ),
            color=COLOR_SUCCESS if is_manager else COLOR_BEASTLY_GOLD,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ManageCurrency(bot))
    await bot.add_cog(ServerSettings(bot))
    await bot.add_cog(BankAdmin(bot))
    await bot.add_cog(BankerPrefixCommands(bot))
