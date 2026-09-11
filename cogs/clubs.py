"""
Club Treasuries Cog: Club vaults, formations, deposits, withdrawals, and leaderboards.
"""
import logging
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger("BeastlyBank.Clubs")

from config import CURRENCIES, COLOR_BEASTLY_GOLD, COLOR_PITCH_GREEN, COLOR_SUCCESS, parse_amount
from utils.checks import require_beastlyfc, is_banker_or_admin
from utils.embeds import (
    club_info_embed,
    club_payroll_embed,
    club_roster_embed,
    create_beastly_embed,
    error_embed,
    resolve_user_names,
    safe_defer,
    send_msg,
    success_embed,
)
from utils.views import PaginationView



async def club_name_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete club names and tags for transfer commands."""
    try:
        db = interaction.client.db  # type: ignore
        clubs = await db.get_club_leaderboard(interaction.guild_id, limit=25)
        choices = []
        cur_low = current.lower()
        for c in clubs:
            display_name = f"[{c['tag']}] {c['name']}"
            if not current or cur_low in display_name.lower():
                choices.append(app_commands.Choice(name=display_name[:100], value=c["name"]))
        return choices[:25]
    except Exception:
        return []


async def execute_transfer(
    db,
    ctx_or_interaction: discord.Interaction | commands.Context,
    player: str,
    from_club: discord.Role | str,
    to_club: discord.Role | str,
    amount: str,
):
    """Shared execution logic for /transfer, /club transfer, and bb!transfer."""
    guild_id = ctx_or_interaction.guild_id if hasattr(ctx_or_interaction, "guild_id") and ctx_or_interaction.guild_id else ctx_or_interaction.guild.id
    caller = ctx_or_interaction.user if hasattr(ctx_or_interaction, "user") else ctx_or_interaction.author

    parsed_fee = parse_amount(amount)
    if parsed_fee is None or parsed_fee < 0:
        await send_msg(
            ctx_or_interaction,
            embed=error_embed(
                "Invalid Transfer Fee",
                (
                    f"Invalid transfer amount: `{amount}`.\n\n"
                    f"**Supported Formats:**\n"
                    f"• Scientific notation: `26e6` (26,000,000), `3e7` (30,000,000)\n"
                    f"• Suffix multipliers: `26m`, `500k`, `1b`\n"
                    f"• Exact numbers: `26000000`, `26,000,000`, or `0` for free transfer."
                ),
            ),
            ephemeral=True,
        )
        return

    clean_player = player.strip()
    if not clean_player:
        await send_msg(
            ctx_or_interaction,
            embed=error_embed("Invalid Player Name", "Player name cannot be empty."),
            ephemeral=True,
        )
        return

    if isinstance(ctx_or_interaction, discord.Interaction):
        if not ctx_or_interaction.response.is_done():
            await ctx_or_interaction.response.defer()

    try:
        success, msg, data = await db.transfer_player(
            guild_id=guild_id,
            player_name=clean_player,
            from_club_query=from_club,
            to_club_query=to_club,
            amount=parsed_fee,
            payer_id=caller.id,
            recipient_id=None,
        )
    except Exception as e:
        logger.error("Error executing player transfer: %s", e, exc_info=True)
        await send_msg(
            ctx_or_interaction,
            embed=error_embed("Transfer Error", f"An unexpected error occurred during transfer: {str(e)}"),
            ephemeral=True,
        )
        return

    if not success:
        await send_msg(
            ctx_or_interaction,
            embed=error_embed("Transfer Failed", msg),
            ephemeral=True,
        )
        return

    f_club = data["from_club"]
    t_club = data["to_club"]
    player_name = data["player_name"]

    from_label = from_club.mention if hasattr(from_club, "mention") else (f"<@&{f_club['role_id']}>" if f_club.get("role_id") else f"**[{f_club['tag']}] {f_club['name']}**")
    to_label = to_club.mention if hasattr(to_club, "mention") else (f"<@&{t_club['role_id']}>" if t_club.get("role_id") else f"**[{t_club['tag']}] {t_club['name']}**")

    embed = create_beastly_embed(
        title="🚨 OFFICIAL TRANSFER CONFIRMED • HERE WE GO! 🚨",
        description=(
            f"Official agreement finalized! **{player_name}** has completed the transfer from {from_label} to {to_label}!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(
        name="🏃 Player",
        value=f"**{player_name}**",
        inline=True,
    )
    embed.add_field(
        name="💰 Transfer Fee",
        value=f"💵 **{parsed_fee:,} Cash** (`{amount}`)",
        inline=True,
    )
    embed.add_field(
        name="💳 Fee Paid To",
        value=f"{from_label} Treasury",
        inline=True,
    )
    embed.add_field(
        name="📤 Departing Club",
        value=from_label,
        inline=True,
    )
    embed.add_field(
        name="📥 Destination Club",
        value=to_label,
        inline=True,
    )
    embed.add_field(
        name="📋 Authorized By",
        value=caller.mention,
        inline=True,
    )

    embed.set_footer(text="BeastlyFC Official Transfer Market • BeastlyBank")
    await send_msg(ctx_or_interaction, embed=embed)


async def resolve_owner_names(
    bot: Any,
    guild: Optional[discord.Guild],
    clubs: List[Dict[str, Any]],
    max_fetch: int = 15,
    use_cache: bool = True,
) -> Dict[int, str]:
    """Map owner_id -> display username using cached and bounded parallel resolution."""
    owner_ids = [c.get("owner_id") for c in clubs if c.get("owner_id")]
    owner_map = await resolve_user_names(bot, guild, owner_ids, max_fetch=max_fetch, use_cache=use_cache)
    owner_map[0] = "Vacant"
    return owner_map


class Clubs(commands.GroupCog, name="club", description="Manage BeastlyFC Club Treasuries and Squads"):
    """BeastlyFC Club Finance and Treasury Management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="create",
        description="Register a new BeastlyFC football club with its own official BeastlyBank Treasury (100% Free!).",
    )
    @app_commands.describe(
        name="Full name of your club (e.g. Red Dragons FC)",
        tag="Short abbreviation tag (up to 5 letters, e.g. RDF)",
        role="Mandatory Discord role representing your club",
    )
    @require_beastlyfc()
    async def club_create(
        self,
        interaction: discord.Interaction,
        name: str,
        tag: str,
        role: discord.Role,
    ):
        if not role:
            await interaction.response.send_message(
                embed=error_embed("Club Role Required", "A Discord club role is mandatory to register a club!"),
                ephemeral=True,
            )
            return

        success, msg, club = await self.db.create_club(
            guild_id=interaction.guild_id,
            name=name,
            tag=tag,
            owner_id=interaction.user.id,
            role_id=role.id,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Club Registration Failed", msg),
                ephemeral=True,
            )
            return

        role_info = f"\n• 🏷️ **Club Role:** {role.mention}"
        embed = create_beastly_embed(
            title="🏟️ Club Registered Successfully!",
            description=(
                f"Congratulations {interaction.user.mention}! **[{club['tag']}] {club['name']}** is now officially affiliated with BeastlyFC!{role_info}\n\n"
                f"🏦 **Club Treasury Vault Activated:**\n"
                f"• 💵 **Cash:** `0`\n"
                f"• ⭐ **Points:** `0`\n"
                f"• 🎟️ **Tokens:** `0`\n\n"
                f"Use `/club deposit` to fund your treasury or `/club info` to view your squad!"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="info",
        description="Inspect a club's treasury balance, squad roster, and official details.",
    )
    @app_commands.describe(club="Club role mention to lookup (defaults to your own club)")
    @require_beastlyfc()
    async def club_info(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            target_text = f"for role {club.mention}" if club else "for your account"
            await interaction.response.send_message(
                embed=error_embed("Club Not Found", f"Could not find an active club {target_text}."),
                ephemeral=True,
            )
            return

        members = await self.db.get_club_members(target_club["id"])
        owner_map = await resolve_owner_names(self.bot, interaction.guild, [target_club])
        owner_name = owner_map.get(target_club.get("owner_id", 0), "Vacant")
        member_ids = [m["user_id"] for m in members[:12] if m.get("user_id")]
        member_names = await resolve_user_names(self.bot, interaction.guild, member_ids)
        embed = club_info_embed(target_club, members, owner_name=owner_name, member_names=member_names)
        await send_msg(interaction, embed=embed)

    @app_commands.command(
        name="payroll",
        description="Inspect a club's matchday wage bill, starting/bench payroll, and treasury runway.",
    )
    @app_commands.describe(club="Club role mention to lookup (defaults to your own club)")
    @require_beastlyfc()
    async def club_payroll(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        await safe_defer(interaction)
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            target_text = f"for role {club.mention}" if club else "for your account"
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", f"Could not find an active club {target_text}."),
                ephemeral=True,
            )
            return

        success, msg, payroll = await self.db.get_club_payroll(interaction.guild_id, target_club["id"])
        if not success:
            await send_msg(interaction, embed=error_embed("Payroll Error", msg), ephemeral=True)
            return

        embed = club_payroll_embed(payroll)
        await send_msg(interaction, embed=embed)

    @app_commands.command(
        name="roster",
        description="Inspect a club's full squad roster with pagination and member usernames.",
    )
    @app_commands.describe(
        club="Club role mention to lookup (defaults to your own club)",
        page="Page number to view (default: 1)",
    )
    @require_beastlyfc()
    async def club_roster(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
        page: Optional[int] = 1,
    ):
        await safe_defer(interaction)
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            target_text = f"for role {club.mention}" if club else "for your account"
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", f"Could not find an active club {target_text}."),
                ephemeral=True,
            )
            return

        members = await self.db.get_club_members(target_club["id"])
        if not members:
            embed = error_embed("Empty Squad", f"No members registered in **[{target_club['tag']}] {target_club['name']}**.")
            await send_msg(interaction, embed=embed)
            return

        per_page = 10
        total_pages = max(1, (len(members) + per_page - 1) // per_page)
        target_page = max(1, min(page or 1, total_pages))

        start_idx = (target_page - 1) * per_page
        page_members = members[start_idx : start_idx + per_page]
        page_uids = [m["user_id"] for m in page_members if m.get("user_id")]
        member_names = await resolve_user_names(self.bot, interaction.guild, page_uids)

        async def make_roster_page(p: int) -> discord.Embed:
            p = max(1, min(p, total_pages))
            s_idx = (p - 1) * per_page
            p_members = members[s_idx : s_idx + per_page]
            p_uids = [m["user_id"] for m in p_members if m.get("user_id")]
            missing = [uid for uid in p_uids if uid not in member_names]
            if missing:
                fresh = await resolve_user_names(self.bot, interaction.guild, missing)
                member_names.update(fresh)
            return club_roster_embed(target_club, members, member_names, page=p, total_pages=total_pages)

        initial_embed = await make_roster_page(target_page)
        if total_pages <= 1:
            await send_msg(interaction, embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_roster_page,
                total_pages=total_pages,
                author_id=interaction.user.id,
                current_page=target_page,
            )
            await send_msg(interaction, embed=initial_embed, view=view)

    @app_commands.command(
        name="deposit",
        description="Deposit personal Cash, Points, or Tokens into a club's treasury vault.",
    )
    @app_commands.describe(
        currency="Currency type to deposit into the treasury",
        amount="Amount to deposit (e.g. 5000, 26e6, 1m)",
        club="Target club role mention (Bankers can deposit into any club; defaults to your club)",
    )
    @require_beastlyfc()
    async def club_deposit(
        self,
        interaction: discord.Interaction,
        currency: Literal["cash", "points", "tokens"],
        amount: str,
        club: Optional[discord.Role] = None,
    ):
        parsed_amount = parse_amount(amount)
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Amount", f"Deposit amount must be greater than 0: `{amount}`"),
                ephemeral=True,
            )
            return

        is_banker = is_banker_or_admin(interaction.user)

        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
            if not target_club:
                await interaction.response.send_message(
                    embed=error_embed("Club Not Found", f"No club found for role {club.mention}."),
                    ephemeral=True,
                )
                return
            if not is_banker:
                user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
                if not user_club or user_club["id"] != target_club["id"]:
                    await interaction.response.send_message(
                        embed=error_embed("Permission Denied", "You must be a BeastlyBank Banker to deposit directly into another club's vault."),
                        ephemeral=True,
                    )
                    return
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
            if not target_club:
                await interaction.response.send_message(
                    embed=error_embed("No Club Affiliation", "You must be a member of a club to deposit funds (or specify a club role if you are a BeastlyBank Banker)!"),
                    ephemeral=True,
                )
                return

        success, msg = await self.db.club_deposit(
            club_id=target_club["id"],
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=parsed_amount,
            is_banker=is_banker,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Deposit Failed", msg),
                ephemeral=True,
            )
            return

        curr_emoji = CURRENCIES.get(currency, {}).get("emoji", "💰")
        banker_note = " *(Authorized by BeastlyBank Banker)*" if is_banker else ""
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"
        embed = create_beastly_embed(
            title="📥 Club Treasury Deposit",
            description=(
                f"{interaction.user.mention} contributed {curr_emoji} **{parsed_amount:,}** into {role_label} Treasury!{banker_note}\n\n"
                f"🏦 *Recorded in BeastlyBank automated club ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="withdraw",
        description="Withdraw funds from a club treasury into your personal account (Owner, Captain, or Banker).",
    )
    @app_commands.describe(
        currency="Currency type to withdraw",
        amount="Amount to withdraw (e.g. 5000, 26e6, 1m)",
        reason="Official memo explaining the treasury withdrawal",
        club="Target club role mention (Bankers can withdraw from any club; defaults to your club)",
    )
    @require_beastlyfc()
    async def club_withdraw(
        self,
        interaction: discord.Interaction,
        currency: Literal["cash", "points", "tokens"],
        amount: str,
        reason: str,
        club: Optional[discord.Role] = None,
    ):
        parsed_amount = parse_amount(amount)
        if parsed_amount is None or parsed_amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Amount", f"Withdrawal amount must be greater than 0: `{amount}`"),
                ephemeral=True,
            )
            return

        is_banker = is_banker_or_admin(interaction.user)

        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
            if not target_club:
                await interaction.response.send_message(
                    embed=error_embed("Club Not Found", f"No club found for role {club.mention}."),
                    ephemeral=True,
                )
                return
            if not is_banker:
                user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
                if not user_club or user_club["id"] != target_club["id"]:
                    await interaction.response.send_message(
                        embed=error_embed("Permission Denied", "You must be a BeastlyBank Banker to withdraw from another club's vault."),
                        ephemeral=True,
                    )
                    return
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
            if not target_club:
                await interaction.response.send_message(
                    embed=error_embed("No Club Affiliation", "You must be in a club to withdraw funds (or specify a club role if you are a BeastlyBank Banker)!"),
                    ephemeral=True,
                )
                return

        success, msg = await self.db.club_withdraw(
            club_id=target_club["id"],
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=parsed_amount,
            reason=reason,
            is_banker=is_banker,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Withdrawal Denied", msg),
                ephemeral=True,
            )
            return

        curr_emoji = CURRENCIES.get(currency, {}).get("emoji", "💰")
        banker_note = " *(Authorized by BeastlyBank Banker)*" if is_banker else ""
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"
        embed = create_beastly_embed(
            title="📤 Club Treasury Withdrawal",
            description=(
                f"{interaction.user.mention} withdrew {curr_emoji} **{parsed_amount:,}** from "
                f"{role_label} Treasury.{banker_note}\n\n"
                f"📝 **Reason:** *{reason}*\n"
                f"🏦 *Funds credited to personal account.*"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="list",
        description="View the wealthiest BeastlyFC Club Treasuries leaderboard (with multi-page navigation).",
    )
    @app_commands.describe(
        page="Page number of clubs to view (10 clubs per page)",
    )
    @require_beastlyfc()
    async def club_list(self, interaction: discord.Interaction, page: Optional[int] = 1):
        await safe_defer(interaction)
        clubs = await self.db.get_club_leaderboard(interaction.guild_id, limit=200)

        if not clubs:
            embed = create_beastly_embed(
                title="🏟️ BeastlyFC Club Treasuries Leaderboard",
                description=(
                    "Ranking of all registered clubs by total treasury assets:\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "*No clubs have registered with BeastlyBank yet. Be the first with `/club create`!*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            await send_msg(interaction, embed=embed)
            return

        per_page = 10
        total_pages = max(1, (len(clubs) + per_page - 1) // per_page)
        target_page = max(1, min(page or 1, total_pages))

        start_idx = (target_page - 1) * per_page
        page_clubs = clubs[start_idx : start_idx + per_page]
        owner_map = await resolve_owner_names(self.bot, interaction.guild, page_clubs)

        async def make_page_embed(p: int) -> discord.Embed:
            p = max(1, min(p, total_pages))
            s_idx = (p - 1) * per_page
            p_clubs = clubs[s_idx : s_idx + per_page]

            missing = [c for c in p_clubs if c.get("owner_id", 0) not in owner_map]
            if missing:
                fresh = await resolve_owner_names(self.bot, interaction.guild, missing)
                owner_map.update(fresh)

            embed = create_beastly_embed(
                title="🏟️ BeastlyFC Club Treasuries Leaderboard",
                description=(
                    f"Ranking of all registered clubs by total treasury assets:\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"*Showing clubs {s_idx + 1}–{s_idx + len(p_clubs)} of {len(clubs)} registered clubs*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )

            medals = ["🥇", "🥈", "🥉"]
            for idx, c in enumerate(p_clubs, start=s_idx + 1):
                rank_str = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                owner_name = owner_map.get(c.get("owner_id", 0), "Vacant")
                embed.add_field(
                    name=f"{rank_str} [{c['tag']}] {c['name']} (Owner: {owner_name})",
                    value=(
                        f"👥 Squad: **{c.get('member_count', 1)}** | "
                        f"💵 Cash: `{c['treasury_cash']:,}` | "
                        f"⭐ Points: `{c['treasury_points']:,}` | "
                        f"🎟️ Tokens: `{c['treasury_tokens']:,}`"
                    ),
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyFC Bank")
            return embed

        initial_embed = await make_page_embed(target_page)

        if total_pages <= 1:
            await send_msg(interaction, embed=initial_embed)
            return

        view = PaginationView(
            embed_generator=make_page_embed,
            total_pages=total_pages,
            author_id=interaction.user.id,
            current_page=target_page,
        )
        await send_msg(interaction, embed=initial_embed, view=view)

    @app_commands.command(
        name="addmanager",
        description="Promote a squad member to Club Manager (Owner only, or Bankers/Admins).",
    )
    @app_commands.describe(
        user="The squad member to promote to Manager",
        club="Optional club role (required for Bankers/Admins managing other clubs)",
    )
    @require_beastlyfc()
    async def club_addmanager(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        club: Optional[discord.Role] = None,
    ):
        is_banker = is_banker_or_admin(interaction.user)
        if club:
            if is_banker:
                success, msg, _ = await self.db.admin_set_club_manager(
                    guild_id=interaction.guild_id,
                    club_query=club,
                    target_user_id=user.id,
                    is_manager=True,
                    admin_id=interaction.user.id,
                    reason=f"Staff promotion by {interaction.user}",
                )
                if not success:
                    await interaction.response.send_message(embed=error_embed("Action Failed", msg), ephemeral=True)
                    return
                embed = success_embed("Manager Promoted", msg)
                await interaction.response.send_message(embed=embed)
                return
            else:
                user_club = await self.db.get_or_create_club_from_role(interaction.guild_id, club, default_owner_id=interaction.user.id)
        else:
            user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not user_club:
            target_msg = f"for role {club.mention}" if club else "You are not in a club! Bankers can specify `club: @role`."
            await interaction.response.send_message(
                embed=error_embed("No Club", target_msg), ephemeral=True
            )
            return

        if is_banker:
            success, msg, _ = await self.db.admin_set_club_manager(
                guild_id=interaction.guild_id,
                club_query=user_club["id"],
                target_user_id=user.id,
                is_manager=True,
                admin_id=interaction.user.id,
                reason=f"Staff promotion by {interaction.user}",
            )
        else:
            success, msg = await self.db.set_club_manager(
                club_id=user_club["id"],
                owner_id=interaction.user.id,
                target_user_id=user.id,
                is_manager=True,
            )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Action Failed", msg), ephemeral=True
            )
            return

        embed = success_embed("Manager Promoted", msg)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="removemanager",
        description="Demote a Club Manager back to normal squad member (Owner only, or Bankers/Admins).",
    )
    @app_commands.describe(
        user="The manager to demote",
        club="Optional club role (required for Bankers/Admins managing other clubs)",
    )
    @require_beastlyfc()
    async def club_removemanager(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        club: Optional[discord.Role] = None,
    ):
        is_banker = is_banker_or_admin(interaction.user)
        if club:
            if is_banker:
                success, msg, _ = await self.db.admin_set_club_manager(
                    guild_id=interaction.guild_id,
                    club_query=club,
                    target_user_id=user.id,
                    is_manager=False,
                    admin_id=interaction.user.id,
                    reason=f"Staff demotion by {interaction.user}",
                )
                if not success:
                    await interaction.response.send_message(embed=error_embed("Action Failed", msg), ephemeral=True)
                    return
                embed = success_embed("Manager Demoted", msg)
                await interaction.response.send_message(embed=embed)
                return
            else:
                user_club = await self.db.get_or_create_club_from_role(interaction.guild_id, club, default_owner_id=interaction.user.id)
        else:
            user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not user_club:
            target_msg = f"for role {club.mention}" if club else "You are not in a club! Bankers can specify `club: @role`."
            await interaction.response.send_message(
                embed=error_embed("No Club", target_msg), ephemeral=True
            )
            return

        if is_banker:
            success, msg, _ = await self.db.admin_set_club_manager(
                guild_id=interaction.guild_id,
                club_query=user_club["id"],
                target_user_id=user.id,
                is_manager=False,
                admin_id=interaction.user.id,
                reason=f"Staff demotion by {interaction.user}",
            )
        else:
            success, msg = await self.db.set_club_manager(
                club_id=user_club["id"],
                owner_id=interaction.user.id,
                target_user_id=user.id,
                is_manager=False,
            )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Action Failed", msg), ephemeral=True
            )
            return

        embed = success_embed("Manager Demoted", msg)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="history",
        description="View recent transactions and activity for your club treasury.",
    )
    @app_commands.describe(club="Target club role mention (defaults to your own club)")
    @require_beastlyfc()
    async def club_history(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        if club:
            user_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not user_club:
            target_str = f"for role {club.mention}" if club else "for your account"
            await interaction.response.send_message(
                embed=error_embed("No Club Found", f"No club found {target_str}!"), ephemeral=True
            )
            return

        txs = await self.db.get_club_transactions(user_club["id"], interaction.guild_id, limit=8)

        role_str = f" • <@&{user_club['role_id']}>" if user_club.get("role_id") else ""
        embed = create_beastly_embed(
            title=f"📜 Club Treasury History • [{user_club['tag']}] {user_club['name']}{role_str}",
            description=f"Recent deposits, withdrawals, and club activity:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not txs:
            embed.description += "\n*No recorded transactions found for this club.*"
        else:
            for t in txs:
                curr_info = CURRENCIES.get(t["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                tx_type = t["tx_type"].replace("_", " ").title()
                reason = t.get("reason") or "No memo"
                time_str = t.get("created_at", "")[:16]
                embed.add_field(
                    name=f"#{t['id']} | {tx_type} — {emoji} {t['amount']:,}",
                    value=f"📝 *{reason}* • `{time_str}`",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="transfer",
        description="Transfer a player between clubs with official transfer fee disbursement.",
    )
    @app_commands.describe(
        player="The BeastlyFC player being transferred (custom written name, e.g. Erling Haaland)",
        from_club="Selling club Discord role mention",
        to_club="Destination/Buying club Discord role mention",
        amount="Transfer fee in Cash (e.g. 26e6 for 26M, 3e7 for 30M, 500k, 0)",
    )
    @require_beastlyfc()
    async def club_transfer(
        self,
        interaction: discord.Interaction,
        player: str,
        from_club: discord.Role,
        to_club: discord.Role,
        amount: str,
    ):
        await execute_transfer(self.db, interaction, player, from_club, to_club, amount)

    @app_commands.command(
        name="setbranding",
        description="Customize your club's matchday lineup card colors, slogans, and chant.",
    )
    @app_commands.describe(
        club="Club role to update (defaults to your own club)",
        kit_primary="Primary kit hex color (e.g. #DA291C)",
        kit_secondary="Secondary kit/accent hex color (e.g. #FFFFFF)",
        slogan_1="Tactical motto line 1 (e.g. LEAD. ADAPT. WIN.)",
        slogan_2="Tactical motto line 2 (e.g. UNITED IS THE WAY.)",
        chant="Club chant/motto at the bottom (e.g. GLORY GLORY MAN UNITED.)",
        logo_url="Direct image URL for club crest",
    )
    @require_beastlyfc()
    async def slash_club_setbranding(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
        kit_primary: Optional[str] = None,
        kit_secondary: Optional[str] = None,
        slogan_1: Optional[str] = None,
        slogan_2: Optional[str] = None,
        chant: Optional[str] = None,
        logo_url: Optional[str] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."),
                ephemeral=True,
            )
            return

        is_owner = target_club.get("owner_id") == interaction.user.id
        can_admin = await is_banker_or_admin(interaction)
        if not is_owner and not can_admin:
            await send_msg(
                interaction,
                embed=error_embed("Permission Denied", "Only the club owner or server administrators can edit club branding."),
                ephemeral=True,
            )
            return

        success, msg, updated = await self.db.set_club_branding(
            guild_id=interaction.guild_id,
            club_query=target_club["id"],
            kit_primary=kit_primary,
            kit_secondary=kit_secondary,
            logo_url=logo_url,
            slogan_1=slogan_1,
            slogan_2=slogan_2,
            chant=chant,
        )

        if not success:
            await send_msg(interaction, embed=error_embed("Branding Update Failed", msg), ephemeral=True)
            return

        embed = success_embed(
            "Club Branding Updated!",
            (
                f"Successfully customized matchday branding for **[{updated['tag']}] {updated['name']}**:\n\n"
                f"• **Primary Kit Color:** `{updated.get('kit_primary') or 'Default'}`\n"
                f"• **Secondary Kit Color:** `{updated.get('kit_secondary') or 'Default'}`\n"
                f"• **Tactical Motto 1:** `{updated.get('slogan_1') or 'Default'}`\n"
                f"• **Tactical Motto 2:** `{updated.get('slogan_2') or 'Default'}`\n"
                f"• **Footer Chant:** `{updated.get('chant') or 'Default'}`\n\n"
                f"Run `/lineupcard` to preview your club's new matchday card!"
            ),
        )
        await send_msg(interaction, embed=embed)


class TransferMarket(commands.Cog):
    """Top-level transfer commands for BeastlyFC transfer market (/transfer and bb!transfer)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="transfer",
        description="Transfer a player between clubs with official transfer fee disbursement.",
    )
    @app_commands.describe(
        player="The BeastlyFC player being transferred (custom written name, e.g. Erling Haaland)",
        from_club="Selling club Discord role mention",
        to_club="Destination/Buying club Discord role mention",
        amount="Transfer fee in Cash (e.g. 26e6 for 26M, 3e7 for 30M, 500k, 0)",
    )
    @require_beastlyfc()
    async def transfer(
        self,
        interaction: discord.Interaction,
        player: str,
        from_club: discord.Role,
        to_club: discord.Role,
        amount: str,
    ):
        await execute_transfer(self.db, interaction, player, from_club, to_club, amount)

    @commands.command(name="transfer")
    async def prefix_transfer(self, ctx: commands.Context, *args):
        """
        Transfer a player between clubs using bb! prefix:
        bb!transfer <player> <@from_role> <@to_role> <amount>
        e.g. bb!transfer Erling Haaland @RealStars @BlueHawks 26e6
        """
        if not args or len(args) < 3:
            embed = error_embed(
                "Invalid Command Usage",
                "**Usage:** `bb!transfer <player> <@from_club_role> <@to_club_role> <amount>`\n"
                "**Example:** `bb!transfer Erling Haaland @RealStars @BlueHawks 26e6`"
            )
            await ctx.send(embed=embed)
            return

        import re
        role_matches = list(re.finditer(r"<@&(\d+)>", ctx.message.content))
        if len(role_matches) >= 2:
            m1 = role_matches[0]
            m2 = role_matches[1]
            r1_id = int(m1.group(1))
            r2_id = int(m2.group(1))
            from_role = ctx.guild.get_role(r1_id) if ctx.guild else None
            if not from_role:
                from_role = f"<@&{r1_id}>"
            to_role = ctx.guild.get_role(r2_id) if ctx.guild else None
            if not to_role:
                to_role = f"<@&{r2_id}>"

            before_m1 = ctx.message.content[:m1.start()]
            player_name = re.sub(r"^(?:<@!?\d+>\s*|bb!\s*|BB!\s*|bb\s+|BB\s+)transfer\s+", "", before_m1, flags=re.IGNORECASE).strip()
            after_m2 = ctx.message.content[m2.end():].strip()
            amount_str = after_m2.split()[0] if after_m2 else args[-1]
        elif len(args) >= 4:
            player_name = " ".join(args[:-3])
            from_role = args[-3]
            to_role = args[-2]
            amount_str = args[-1]
        elif len(ctx.message.role_mentions) >= 2:
            from_role = ctx.message.role_mentions[0]
            to_role = ctx.message.role_mentions[1]
            amount_str = args[-1]
            player_words = [a for a in args[:-1] if not a.startswith("<@&")]
            player_name = " ".join(player_words).strip()
        else:
            embed = error_embed(
                "Missing Information",
                "Please specify the player, selling club, buying club, and amount:\n"
                "`bb!transfer <player> <@from_club_role> <@to_club_role> <amount>`\n"
                "**Example:** `bb!transfer Erling Haaland @RealStars @BlueHawks 26e6`"
            )
            await ctx.send(embed=embed)
            return

        await execute_transfer(self.db, ctx, player_name, from_role, to_role, amount_str)


class ClubHistoryTop(commands.Cog):
    """Top-level /clubhistory command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="clubhistory",
        description="View recent transactions and ledger history for your club treasury.",
    )
    @app_commands.describe(club="Club role mention (defaults to your own club)")
    @require_beastlyfc()
    async def clubhistory_top(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            target_str = f"for role {club.mention}" if club else "for your account"
            await interaction.response.send_message(
                embed=error_embed("Club Not Found", f"No club found {target_str}."),
                ephemeral=True,
            )
            return

        txs = await self.db.get_club_transactions(target_club["id"], interaction.guild_id, limit=8)

        role_str = f" • <@&{target_club['role_id']}>" if target_club.get("role_id") else ""
        embed = create_beastly_embed(
            title=f"📜 Club Treasury History • [{target_club['tag']}] {target_club['name']}{role_str}",
            description=f"Official treasury activity for **[{target_club['tag']}] {target_club['name']}**:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not txs:
            embed.description += "\n*No recorded transactions found for this club.*"
        else:
            for t in txs:
                curr_info = CURRENCIES.get(t["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                tx_type = t["tx_type"].replace("_", " ").title()
                reason = t.get("reason") or "No memo"
                time_str = t.get("created_at", "")[:16]
                embed.add_field(
                    name=f"#{t['id']} | {tx_type} — {emoji} {t['amount']:,}",
                    value=f"📝 *{reason}* • `{time_str}`",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)

    @commands.command(name="clubhistory", aliases=["chistory", "ch"])
    async def prefix_clubhistory(self, ctx: commands.Context, *, club_query: Optional[str] = None):
        """bb!clubhistory [@role_or_club_name]"""
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        if target_role:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, target_role, default_owner_id=ctx.author.id)
        elif club_query:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, club_query.strip(), default_owner_id=ctx.author.id)
        else:
            club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not club:
            target_str = f"matching '{club_query}'" if club_query else "for your account"
            await ctx.send(embed=error_embed("Club Not Found", f"No club found {target_str}."))
            return

        txs = await self.db.get_club_transactions(club["id"], ctx.guild.id, limit=8)

        role_str = f" • <@&{club['role_id']}>" if club.get("role_id") else ""
        embed = create_beastly_embed(
            title=f"📜 Club Treasury History • [{club['tag']}] {club['name']}{role_str}",
            description=f"Official treasury activity for **[{club['tag']}] {club['name']}**:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not txs:
            embed.description += "\n*No recorded transactions found for this club.*"
        else:
            for t in txs:
                curr_info = CURRENCIES.get(t["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                tx_type = t["tx_type"].replace("_", " ").title()
                reason = t.get("reason") or "No memo"
                time_str = t.get("created_at", "")[:16]
                embed.add_field(
                    name=f"#{t['id']} | {tx_type} — {emoji} {t['amount']:,}",
                    value=f"📝 *{reason}* • `{time_str}`",
                    inline=False,
                )

        await ctx.send(embed=embed)


class ClubPrefixCommands(commands.Cog):
    """Prefix commands for BeastlyFC Clubs (bb!club ...)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @commands.group(name="club", invoke_without_command=True)
    async def prefix_club(self, ctx: commands.Context, *, club_query: Optional[str] = None):
        """bb!club [@role_or_club_name]"""
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        if target_role:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, target_role, default_owner_id=ctx.author.id)
        elif club_query:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, club_query.strip(), default_owner_id=ctx.author.id)
        else:
            club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not club:
            target_text = f"matching '{club_query}'" if club_query else "for your account"
            await ctx.send(embed=error_embed("Club Not Found", f"Could not find an active club {target_text}."))
            return

        members = await self.db.get_club_members(club["id"])
        owner_map = await resolve_owner_names(self.bot, ctx.guild, [club])
        owner_name = owner_map.get(club.get("owner_id", 0), "Vacant")
        member_ids = [m["user_id"] for m in members[:12] if m.get("user_id")]
        member_names = await resolve_user_names(self.bot, ctx.guild, member_ids)
        embed = club_info_embed(club, members, owner_name=owner_name, member_names=member_names)
        await send_msg(ctx, embed=embed)

    @prefix_club.command(name="info")
    async def prefix_club_info(self, ctx: commands.Context, *, club_query: Optional[str] = None):
        """bb!club info [@role_or_club_name]"""
        await self.prefix_club(ctx, club_query=club_query)

    @prefix_club.command(name="payroll")
    async def prefix_club_payroll(self, ctx: commands.Context, *, club_query: Optional[str] = None):
        """View a club's matchday payroll and wage bill. Usage: bb!club payroll [@role/tag]"""
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        q = target_role if target_role else club_query

        if q:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, q, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "Could not find an active club for you or the specified role/tag."))
            return

        success, msg, payroll = await self.db.get_club_payroll(ctx.guild.id, target_club["id"])
        if not success:
            await ctx.send(embed=error_embed("Payroll Error", msg))
            return

        embed = club_payroll_embed(payroll)
        await send_msg(ctx, embed=embed)

    @commands.command(name="payroll")
    async def prefix_standalone_payroll(self, ctx: commands.Context, *, club_query: Optional[str] = None):
        """Inspect matchday wage bill and treasury runway. Usage: bb!payroll [@role/tag]"""
        await self.prefix_club_payroll(ctx, club_query=club_query)

    @prefix_club.command(name="create")
    async def prefix_club_create(self, ctx: commands.Context, *args):
        """
        Register a new BeastlyFC football club with mandatory Discord role.
        Usage: bb!club create <name> <tag> <@role>
        Example: bb!club create Real Madrid RMA @RealMadrid
        """
        role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        role_id = role.id if role else None

        clean_args = []
        for a in args:
            if role and a == role.mention:
                continue
            if a.startswith("<@&") and a.endswith(">"):
                r_id = a.strip("<@&>")
                if r_id.isdigit():
                    role_id = int(r_id)
                    continue
            clean_args.append(a)

        if not role_id:
            await ctx.send(
                embed=error_embed(
                    "Club Role Required",
                    "A Discord club role is mandatory to register a club!\n\n"
                    "**Usage:** `bb!club create <name> <tag> <@role>`\n"
                    "**Example:** `bb!club create Real Madrid RMA @RealMadrid`",
                )
            )
            return

        if len(clean_args) < 2:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "Please specify both the club name and tag.\n\n"
                    "**Usage:** `bb!club create <name> <tag> <@role>`\n"
                    "**Example:** `bb!club create Real Madrid RMA @RealMadrid`",
                )
            )
            return

        tag = clean_args[-1].strip().upper()
        name = " ".join(clean_args[:-1]).strip()

        success, msg, club = await self.db.create_club(
            guild_id=ctx.guild.id,
            name=name,
            tag=tag,
            owner_id=ctx.author.id,
            role_id=role_id,
        )
        if not success:
            await ctx.send(embed=error_embed("Club Registration Failed", msg))
            return

        role_info = f"\n• 🏷️ **Club Role:** <@&{role_id}>"
        embed = create_beastly_embed(
            title="🏟️ Club Registered Successfully!",
            description=(
                f"Congratulations {ctx.author.mention}! **[{club['tag']}] {club['name']}** is now officially affiliated with BeastlyFC!{role_info}\n\n"
                f"🏦 **Club Treasury Vault Activated:**\n"
                f"• 💵 **Cash:** `0`\n"
                f"• ⭐ **Points:** `0`\n"
                f"• 🎟️ **Tokens:** `0`\n\n"
                f"Use `bb!club deposit` to fund your treasury or `bb!club info` to view your squad!"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @prefix_club.command(name="deposit")
    async def prefix_club_deposit(self, ctx: commands.Context, *args):
        """bb!club deposit <cash|points|tokens> <amount> [@role/club_name]"""
        if not args:
            await ctx.send(embed=error_embed("Invalid Command Usage", "**Usage:** `bb!club deposit <currency> <amount> [@role/club_name]`"))
            return

        curr_key = None
        curr_idx = -1
        for i, a in enumerate(args):
            low = a.lower().strip()
            if low in ("cash", "points", "tokens", "token", "point"):
                curr_key = "points" if "point" in low else ("tokens" if "token" in low else "cash")
                curr_idx = i
                break

        if curr_key is None:
            await ctx.send(embed=error_embed("Invalid Currency", "Currency must be `cash`, `points`, or `tokens`."))
            return

        remaining_args = [a for i, a in enumerate(args) if i != curr_idx]
        if not remaining_args:
            await ctx.send(embed=error_embed("Missing Amount", "Please specify an amount to deposit (e.g. `5000`, `26e6`, `1m`)."))
            return

        amount_idx = -1
        parsed_amount = None
        for i, a in enumerate(remaining_args):
            val = parse_amount(a)
            if val is not None and val > 0:
                parsed_amount = val
                amount_idx = i
                break

        if parsed_amount is None:
            await ctx.send(embed=error_embed("Invalid Amount", "Please specify a valid positive amount (e.g. `5000`, `26e6`, `1m`)."))
            return

        club_args = [a for i, a in enumerate(remaining_args) if i != amount_idx]
        is_banker = is_banker_or_admin(ctx.author)

        target_club = None
        if ctx.message.role_mentions:
            target_club = await self.db.get_or_create_club_from_role(ctx.guild.id, ctx.message.role_mentions[0], default_owner_id=ctx.author.id)
        elif club_args:
            club_query = " ".join(club_args)
            target_club = await self.db.get_or_create_club_from_role(ctx.guild.id, club_query, default_owner_id=ctx.author.id)
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            if ctx.message.role_mentions or club_args:
                await ctx.send(embed=error_embed("Club Not Found", "Could not find or register the specified club."))
            else:
                await ctx.send(embed=error_embed("No Club Affiliation", "You must be a member of a club to deposit funds (or mention a club role if you are a BeastlyBank Banker)!"))
            return

        if (ctx.message.role_mentions or club_args) and not is_banker:
            user_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
            if not user_club or user_club["id"] != target_club["id"]:
                await ctx.send(embed=error_embed("Permission Denied", "You must be a BeastlyBank Banker to deposit directly into another club's vault."))
                return

        success, msg = await self.db.club_deposit(
            club_id=target_club["id"],
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            currency=curr_key,
            amount=parsed_amount,
            is_banker=is_banker,
        )

        if not success:
            await ctx.send(embed=error_embed("Deposit Failed", msg))
            return

        curr_emoji = CURRENCIES.get(curr_key, {}).get("emoji", "💰")
        banker_note = " *(Authorized by BeastlyBank Banker)*" if is_banker else ""
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"
        embed = create_beastly_embed(
            title="📥 Club Treasury Deposit",
            description=(
                f"{ctx.author.mention} contributed {curr_emoji} **{parsed_amount:,}** into {role_label} Treasury!{banker_note}\n\n"
                f"🏦 *Recorded in BeastlyBank automated club ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @prefix_club.command(name="withdraw")
    async def prefix_club_withdraw(self, ctx: commands.Context, *args):
        """bb!club withdraw <cash|points|tokens> <amount> [reason] [@club_role]"""
        if not args:
            await ctx.send(embed=error_embed("Invalid Command Usage", "**Usage:** `bb!club withdraw <currency> <amount> [reason] [@club_role]`"))
            return

        curr_key = None
        curr_idx = -1
        for i, a in enumerate(args):
            low = a.lower().strip()
            if low in ("cash", "points", "tokens", "token", "point"):
                curr_key = "points" if "point" in low else ("tokens" if "token" in low else "cash")
                curr_idx = i
                break

        if curr_key is None:
            await ctx.send(embed=error_embed("Invalid Currency", "Currency must be `cash`, `points`, or `tokens`."))
            return

        remaining_args = [a for i, a in enumerate(args) if i != curr_idx]
        if not remaining_args:
            await ctx.send(embed=error_embed("Missing Amount", "Please specify an amount to withdraw (e.g. `5000`, `26e6`, `1m`)."))
            return

        amount_idx = -1
        parsed_amount = None
        for i, a in enumerate(remaining_args):
            val = parse_amount(a)
            if val is not None and val > 0:
                parsed_amount = val
                amount_idx = i
                break

        if parsed_amount is None:
            await ctx.send(embed=error_embed("Invalid Amount", "Please specify a valid positive amount (e.g. `5000`, `26e6`, `1m`)."))
            return

        other_args = [a for i, a in enumerate(remaining_args) if i != amount_idx]
        is_banker = is_banker_or_admin(ctx.author)

        target_club = None
        if ctx.message.role_mentions:
            target_club = await self.db.get_or_create_club_from_role(ctx.guild.id, ctx.message.role_mentions[0], default_owner_id=ctx.author.id)
            reason_words = [w for w in other_args if not (w.startswith("<@&") and w.endswith(">"))]
            reason = " ".join(reason_words).strip() or "Club Withdrawal"
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
            reason = " ".join(other_args).strip() or "Club Withdrawal"

        if not target_club:
            await ctx.send(embed=error_embed("No Club Found", "You must be in a club to withdraw funds (or mention a club role if you are a BeastlyBank Banker)!"))
            return

        if ctx.message.role_mentions and not is_banker:
            user_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
            if not user_club or user_club["id"] != target_club["id"]:
                await ctx.send(embed=error_embed("Permission Denied", "You must be a BeastlyBank Banker to withdraw from another club's vault."))
                return

        success, msg = await self.db.club_withdraw(
            club_id=target_club["id"],
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            currency=curr_key,
            amount=parsed_amount,
            reason=reason,
            is_banker=is_banker,
        )

        if not success:
            await ctx.send(embed=error_embed("Withdrawal Denied", msg))
            return

        curr_emoji = CURRENCIES.get(curr_key, {}).get("emoji", "💰")
        banker_note = " *(Authorized by BeastlyBank Banker)*" if is_banker else ""
        role_label = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**[{target_club['tag']}] {target_club['name']}**"
        embed = create_beastly_embed(
            title="📤 Club Treasury Withdrawal",
            description=(
                f"{ctx.author.mention} withdrew {curr_emoji} **{parsed_amount:,}** from "
                f"{role_label} Treasury.{banker_note}\n\n"
                f"📝 **Reason:** *{reason}*\n"
                f"🏦 *Funds credited to personal account.*"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await ctx.send(embed=embed)

    @prefix_club.command(name="list", aliases=["all", "leaderboard", "ranking", "lb"])
    async def prefix_club_list(self, ctx: commands.Context, *args):
        """bb!club list [page]"""
        await self._handle_club_list_prefix(ctx, args)

    @commands.command(name="clubs", aliases=["clublist"])
    async def prefix_standalone_clubs(self, ctx: commands.Context, *args):
        """bb!clubs [page] / bb!clublist [page]"""
        await self._handle_club_list_prefix(ctx, args)

    async def _handle_club_list_prefix(self, ctx: commands.Context, args):
        target_page = 1
        for a in args:
            clean = a.lower().replace("page", "").replace("p", "").strip()
            if clean.isdigit():
                target_page = max(1, int(clean))
                break

        clubs = await self.db.get_club_leaderboard(ctx.guild.id, limit=200)
        if not clubs:
            embed = create_beastly_embed(
                title="🏟️ BeastlyFC Club Treasuries Leaderboard",
                description=(
                    "Ranking of all registered clubs by total treasury assets:\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "*No clubs have registered with BeastlyBank yet. Be the first with `bb!club create`!*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            await send_msg(ctx, embed=embed)
            return

        per_page = 10
        total_pages = max(1, (len(clubs) + per_page - 1) // per_page)
        target_page = max(1, min(target_page, total_pages))

        start_idx = (target_page - 1) * per_page
        page_clubs = clubs[start_idx : start_idx + per_page]
        owner_map = await resolve_owner_names(self.bot, ctx.guild, page_clubs)

        async def make_page_embed(p: int) -> discord.Embed:
            p = max(1, min(p, total_pages))
            s_idx = (p - 1) * per_page
            p_clubs = clubs[s_idx : s_idx + per_page]

            missing = [c for c in p_clubs if c.get("owner_id", 0) not in owner_map]
            if missing:
                fresh = await resolve_owner_names(self.bot, ctx.guild, missing)
                owner_map.update(fresh)

            embed = create_beastly_embed(
                title="🏟️ BeastlyFC Club Treasuries Leaderboard",
                description=(
                    f"Ranking of all registered clubs by total treasury assets:\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"*Showing clubs {s_idx + 1}–{s_idx + len(p_clubs)} of {len(clubs)} registered clubs*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )

            medals = ["🥇", "🥈", "🥉"]
            for idx, c in enumerate(p_clubs, start=s_idx + 1):
                rank_str = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                owner_name = owner_map.get(c.get("owner_id", 0), "Vacant")
                embed.add_field(
                    name=f"{rank_str} [{c['tag']}] {c['name']} (Owner: {owner_name})",
                    value=(
                        f"👥 Squad: **{c.get('member_count', 1)}** | "
                        f"💵 Cash: `{c['treasury_cash']:,}` | "
                        f"⭐ Points: `{c['treasury_points']:,}` | "
                        f"🎟️ Tokens: `{c['treasury_tokens']:,}`"
                    ),
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyFC Bank")
            return embed

        initial_embed = await make_page_embed(target_page)

        if total_pages <= 1:
            await send_msg(ctx, embed=initial_embed)
            return

        view = PaginationView(
            embed_generator=make_page_embed,
            total_pages=total_pages,
            author_id=ctx.author.id,
            current_page=target_page,
        )
        await send_msg(ctx, embed=initial_embed, view=view)

    @prefix_club.command(name="roster", aliases=["members", "squadmembers"])
    async def prefix_club_roster(self, ctx: commands.Context, *args):
        """bb!club roster [@role_or_club_name] [page]"""
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        target_page = 1
        club_query = None

        for arg in args:
            clean = arg.strip()
            if clean.isdigit() and len(clean) <= 4:
                target_page = max(1, int(clean))
            elif not target_role and not clean.startswith("<@&"):
                club_query = clean

        if target_role:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, target_role, default_owner_id=ctx.author.id)
        elif club_query:
            club = await self.db.get_or_create_club_from_role(ctx.guild.id, club_query, default_owner_id=ctx.author.id)
        else:
            club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not club:
            await send_msg(ctx, embed=error_embed("Club Not Found", "Could not find the specified club."))
            return

        members = await self.db.get_club_members(club["id"])
        if not members:
            await send_msg(ctx, embed=error_embed("Empty Squad", f"No members registered in **[{club['tag']}] {club['name']}**."))
            return

        per_page = 10
        total_pages = max(1, (len(members) + per_page - 1) // per_page)
        target_page = max(1, min(target_page, total_pages))

        start_idx = (target_page - 1) * per_page
        page_members = members[start_idx : start_idx + per_page]
        page_uids = [m["user_id"] for m in page_members if m.get("user_id")]
        member_names = await resolve_user_names(self.bot, ctx.guild, page_uids)

        async def make_roster_page(p: int) -> discord.Embed:
            p = max(1, min(p, total_pages))
            s_idx = (p - 1) * per_page
            p_members = members[s_idx : s_idx + per_page]
            p_uids = [m["user_id"] for m in p_members if m.get("user_id")]
            missing = [uid for uid in p_uids if uid not in member_names]
            if missing:
                fresh = await resolve_user_names(self.bot, ctx.guild, missing)
                member_names.update(fresh)
            return club_roster_embed(club, members, member_names, page=p, total_pages=total_pages)

        initial_embed = await make_roster_page(target_page)
        if total_pages <= 1:
            await send_msg(ctx, embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_roster_page,
                total_pages=total_pages,
                author_id=ctx.author.id,
                current_page=target_page,
            )
            await send_msg(ctx, embed=initial_embed, view=view)

    @commands.command(name="roster", aliases=["squadmembers", "clubmembers"])
    async def prefix_standalone_roster(self, ctx: commands.Context, *args):
        """bb!roster [@role_or_club_name] [page]"""
        await self.prefix_club_roster(ctx, *args)

    @commands.command(name="setbranding", aliases=["clubbranding", "branding"])
    async def prefix_club_setbranding(self, ctx: commands.Context, *, args: str = ""):
        """
        Customize your club's matchday branding.
        Usage: bb!setbranding <kit_primary> | <kit_secondary> | <slogan_1> | <slogan_2> | <chant> [@role]
        Example: bb!setbranding #DA291C | #FFFFFF | LEAD. ADAPT. WIN. | UNITED IS THE WAY. | GLORY GLORY MAN UNITED. @United
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_content = ctx.message.content
        if target_role:
            clean_content = clean_content.replace(target_role.mention, "").strip()

        parts = clean_content.split(" ", 1)
        raw_args = parts[1] if len(parts) > 1 else ""
        fields = [f.strip() for f in raw_args.split("|")]

        if not fields or not fields[0]:
            await send_msg(
                ctx,
                embed=error_embed(
                    "Missing Information",
                    "**Usage:** `bb!setbranding <primary_color> | [secondary_color] | [motto_1] | [motto_2] | [chant] [@club_role]`\n"
                    "**Example:** `bb!setbranding #DA291C | #FFFFFF | LEAD. ADAPT. WIN. | UNITED IS THE WAY. | GLORY GLORY MAN UNITED. @United`"
                )
            )
            return

        kit_primary = fields[0] if len(fields) > 0 and fields[0] else None
        kit_secondary = fields[1] if len(fields) > 1 and fields[1] else None
        slogan_1 = fields[2] if len(fields) > 2 and fields[2] else None
        slogan_2 = fields[3] if len(fields) > 3 and fields[3] else None
        chant = fields[4] if len(fields) > 4 and fields[4] else None

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await send_msg(ctx, embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        is_owner = target_club.get("owner_id") == ctx.author.id
        can_admin = await is_banker_or_admin(ctx)
        if not is_owner and not can_admin:
            await send_msg(ctx, embed=error_embed("Permission Denied", "Only club owners or server administrators can edit branding."))
            return

        success, msg, updated = await self.db.set_club_branding(
            guild_id=ctx.guild.id,
            club_query=target_club["id"],
            kit_primary=kit_primary,
            kit_secondary=kit_secondary,
            slogan_1=slogan_1,
            slogan_2=slogan_2,
            chant=chant,
        )
        if not success:
            await send_msg(ctx, embed=error_embed("Branding Update Failed", msg))
            return

        embed = success_embed(
            "Club Branding Updated!",
            f"Successfully updated matchday branding for **[{updated['tag']}] {updated['name']}**.\n"
            f"Use `/lineupcard` or `bb!lineupimage` to preview!"
        )
        await send_msg(ctx, embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Clubs(bot))
    await bot.add_cog(ClubHistoryTop(bot))
    await bot.add_cog(ClubPrefixCommands(bot))
    await bot.add_cog(TransferMarket(bot))

