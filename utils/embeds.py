"""
Embed builders and BeastlyFC visual design components.
"""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import discord
from config import (
    BOT_NAME,
    COLOR_BEASTLY_GOLD,
    COLOR_PITCH_GREEN,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_INFO,
    SERVER_NAME,
    CURRENCIES,
    SUPPORTED_FORMATIONS,
    POSITION_CATEGORIES,
)


def create_beastly_embed(
    title: str,
    description: Optional[str] = None,
    color: int = COLOR_BEASTLY_GOLD,
    footer_text: Optional[str] = None,
) -> discord.Embed:
    """Base embed styled with BeastlyFC and BeastlyBank branding."""
    embed = discord.Embed(title=title, description=description, color=color)
    footer = footer_text or f"{BOT_NAME} • Official Finance of {SERVER_NAME} ⚽"
    embed.set_footer(text=footer)
    embed.timestamp = datetime.now(timezone.utc)
    return embed


def success_embed(title: str, description: str) -> discord.Embed:
    return create_beastly_embed(
        title=f"✅ {title}",
        description=description,
        color=COLOR_SUCCESS,
    )


def error_embed(title: str, description: str) -> discord.Embed:
    return create_beastly_embed(
        title=f"❌ {title}",
        description=description,
        color=COLOR_ERROR,
    )


def bank_card_embed(
    target_user: discord.User | discord.Member,
    account: Dict[str, Any],
    club: Optional[Dict[str, Any]] = None,
) -> discord.Embed:
    """Generates the official BeastlyBank account card / passbook."""
    cash_emoji = CURRENCIES["cash"]["emoji"]
    points_emoji = CURRENCIES["points"]["emoji"]
    tokens_emoji = CURRENCIES["tokens"]["emoji"]

    cash = account.get("cash", 0)
    points = account.get("points", 0)
    tokens = account.get("tokens", 0)

    embed = create_beastly_embed(
        title=f"🏦 BeastlyBank Account • {target_user.display_name}",
        description=f"Official financial status in **{SERVER_NAME}**.\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_BEASTLY_GOLD,
    )

    if target_user.avatar:
        embed.set_thumbnail(url=target_user.avatar.url)

    # Currencies breakdown
    embed.add_field(
        name=f"{cash_emoji} Cash Balance",
        value=f"**{cash:,}**\n*Main Server Currency*",
        inline=True,
    )
    embed.add_field(
        name=f"{points_emoji} Community Points",
        value=f"**{points:,}**\n*Activity & Rewards*",
        inline=True,
    )
    embed.add_field(
        name=f"{tokens_emoji} Training Tokens",
        value=f"**{tokens:,}**\n*Player Drills & Stats*",
        inline=True,
    )

    # Club affiliation
    if club:
        role_label = club.get("user_role", "Member")
        role_str = f" • <@&{club['role_id']}>" if club.get("role_id") else ""
        embed.add_field(
            name="🏟️ BeastlyFC Club",
            value=f"**[{club['tag']}] {club['name']}**{role_str}\nRole: `{role_label}`",
            inline=True,
        )
    else:
        embed.add_field(
            name="🏟️ BeastlyFC Club",
            value="*Free Agent (No Club)*",
            inline=True,
        )

    embed.set_footer(
        text=f"Account ID: {target_user.id} • BeastlyBank Vault Protected 🔒"
    )
    return embed


def transaction_history_embed(
    target_user: discord.User | discord.Member,
    txs: List[Dict[str, Any]],
    page: int,
    total_pages: int,
) -> discord.Embed:
    """Formatted transaction statement."""
    embed = create_beastly_embed(
        title=f"📜 BeastlyBank Statement • {target_user.display_name}",
        description=f"Official recorded transactions for **{target_user.mention}**.\nPage **{page}** of **{max(total_pages, 1)}**\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_PITCH_GREEN,
    )

    if not txs:
        embed.description += "\n*No recorded transactions found for this account.*"
        return embed

    for tx in txs:
        tx_id = tx["id"]
        tx_type = tx["tx_type"].replace("_", " ").title()
        currency_code = tx["currency"]
        emoji = CURRENCIES.get(currency_code, {}).get("emoji", "💰")
        amount = tx["amount"]
        reason = tx.get("reason") or "No memo provided"
        created_at = tx.get("created_at", "")[:16]

        # Determine direction
        if tx["sender_id"] == target_user.id and tx["receiver_id"]:
            prefix = "🔻 Debited"
            counterpart = f"To: <@{tx['receiver_id']}>"
        elif tx["receiver_id"] == target_user.id:
            prefix = "🔺 Credited"
            counterpart = f"From: <@{tx['sender_id']}>" if tx["sender_id"] else "System Reward"
        else:
            prefix = "💳 Transaction"
            counterpart = ""

        embed.add_field(
            name=f"#{tx_id} | {prefix} {emoji} {amount:,} ({tx_type})",
            value=f"**{counterpart}**\n📝 *{reason}* • `{created_at}`",
            inline=False,
        )

    return embed


def club_info_embed(
    club: Dict[str, Any],
    members: List[Dict[str, Any]],
) -> discord.Embed:
    """Display BeastlyFC Club profile and Treasury vault status."""
    embed = create_beastly_embed(
        title=f"🏟️ Club Profile • [{club['tag']}] {club['name']}",
        description=f"Official BeastlyFC Club Treasury and Roster.\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_PITCH_GREEN,
    )

    embed.add_field(
        name="👑 Club Owner",
        value=f"<@{club['owner_id']}>",
        inline=True,
    )
    role_mention = f"<@&{club['role_id']}>" if club.get("role_id") else "*None linked*"
    embed.add_field(
        name="🏷️ Club Role",
        value=role_mention,
        inline=True,
    )
    embed.add_field(
        name="👥 Squad Roster",
        value=f"**{len(members)}** Members",
        inline=True,
    )
    embed.add_field(
        name="📅 Founded",
        value=f"`{club.get('created_at', '')[:10]}`",
        inline=True,
    )

    # Treasury balances
    embed.add_field(
        name="🏦 Club Treasury Vault",
        value=(
            f"💵 **Cash:** `{club.get('treasury_cash', 0):,}`\n"
            f"⭐ **Points:** `{club.get('treasury_points', 0):,}`\n"
            f"🎟️ **Tokens:** `{club.get('treasury_tokens', 0):,}`"
        ),
        inline=False,
    )

    # Member list preview
    if members:
        roster_lines = []
        for m in members[:12]:
            if m.get("user_id"):
                roster_lines.append(f"• <@{m['user_id']}> — `{m['role']}`")
            elif m.get("player_name"):
                roster_lines.append(f"• **{m['player_name']}** — `{m.get('role', 'Player')}`")
            else:
                roster_lines.append(f"• Unknown Player — `{m.get('role', 'Player')}`")
        if len(members) > 12:
            roster_lines.append(f"*...and {len(members) - 12} more players*")
        embed.add_field(
            name="📋 Squad Members",
            value="\n".join(roster_lines),
            inline=False,
        )

    return embed


def summary_overview_embed(
    user: discord.Member,
    user_data: Dict[str, Any],
    club: Optional[Dict[str, Any]] = None,
) -> discord.Embed:
    """Simple, elegant overview summary of BeastlyBank, commands, and account status."""
    embed = create_beastly_embed(
        title="🏦 BeastlyBank • Simple System & Command Summary",
        description=(
            f"Welcome to **BeastlyBank**, the automated central bank and transfer market for **BeastlyFC**!\n"
            f"Here is your simple summary of how everything works and available commands.\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    # Account status field
    club_role_str = f" • <@&{club['role_id']}>" if club and club.get("role_id") else ""
    club_str = f"**[{club['tag']}] {club['name']}**{club_role_str} (`{club.get('user_role', 'Member')}`)" if club else "*Free Agent (No Club)*"
    embed.add_field(
        name="👤 Your Account Summary",
        value=(
            f"• 💵 **Cash:** `{user_data.get('cash', 0):,}`\n"
            f"• ⭐ **Points:** `{user_data.get('points', 0):,}`\n"
            f"• 🎟️ **Tokens:** `{user_data.get('tokens', 0):,}`\n"
            f"• 🏟️ **Club:** {club_str}"
        ),
        inline=False,
    )

    # Normal User Commands field
    embed.add_field(
        name="👤 Normal User Commands",
        value=(
            "**💰 Balance & Payments**\n"
            "• `/balance` — View Cash, Community Points & Training Tokens.\n"
            "• `/pay <user> <currency> <amount>` — Send Cash or Tokens to another user.\n"
            "• `/transactions` — View your recent transaction history.\n"
            "• `/shop` & `/buy <id>` — Browse and purchase items from the BeastlyBank Store.\n"
            "• `/inventory` — Inspect your items, perks, and roles.\n\n"
            "**🏟️ Club & Transfers**\n"
            "• `/transfer <player> <@from_role> <@to_role> <amount>` — Transfer player with fee disbursement (supports `26e6`, `30m`).\n"
            "• `/club create <name> <tag> [@role]` — Form your club and vault (100% Free!).\n"
            "• `/club info [@role]` — View squad roster and treasury balances.\n"
            "• `/club deposit <currency> <amount> [@role]` & `/club withdraw` — Manage your team's treasury vault.\n"
            "• `/clubhistory [@role]` — View your club's ledger history.\n\n"
            "**🏆 Competitions & Leaderboards**\n"
            "• `/leaderboard` — View the wealthiest players and clubs.\n"
            "• `/giveaway start/end` — Server giveaways with instant payouts."
        ),
        inline=False,
    )

    # Banker & Admin Commands field
    embed.add_field(
        name="👑 BeastlyBank Banker & Admin Commands",
        value=(
            "• `/manage add/remove/set` — Credit, debit, or override a user's currency.\n"
            "• `/manage vault <@club_role> <currency> <action> <amount>` — Add, remove, or set club vaults (`26e6`, `30m`, `500k`).\n"
            "• `/shopadmin add/edit/list/toggle/remove` — Manage the store catalogue.\n"
            "• `/bank announce` & `/bank audit` — Server announcements & user audits."
        ),
        inline=False,
    )

    embed.set_footer(text="Click the buttons below to switch views • BeastlyFC Bank")
    return embed


def summary_finance_embed(
    user: discord.Member,
    user_data: Dict[str, Any],
    club: Optional[Dict[str, Any]] = None,
    txs: Optional[List[Dict[str, Any]]] = None,
) -> discord.Embed:
    """Detailed personal financial summary for a player."""
    embed = create_beastly_embed(
        title=f"📊 Financial Summary • {user.display_name}",
        description=f"Detailed financial statement for {user.mention} in **BeastlyFC**:\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_PITCH_GREEN,
    )

    embed.add_field(
        name="💵 Cash",
        value=f"`{user_data.get('cash', 0):,}`",
        inline=True,
    )
    embed.add_field(
        name="⭐ Community Points",
        value=f"`{user_data.get('points', 0):,}`",
        inline=True,
    )
    embed.add_field(
        name="🎟️ Training Tokens",
        value=f"`{user_data.get('tokens', 0):,}`",
        inline=True,
    )

    if club:
        role_mention_str = f" (<@&{club['role_id']}>)" if club.get("role_id") else ""
        embed.add_field(
            name="🏟️ Club Affiliation",
            value=(
                f"**[{club['tag']}] {club['name']}**{role_mention_str}\n"
                f"Role: `{club.get('user_role', 'Member')}`\n"
                f"Vault Cash: `{club.get('treasury_cash', 0):,}`"
            ),
            inline=True,
        )
    else:
        embed.add_field(
            name="🏟️ Club Affiliation",
            value="*Free Agent*\nJoin or create a club with `/club create`!",
            inline=True,
        )

    # Total net worth calculation
    net_worth = user_data.get("cash", 0) + (user_data.get("points", 0) * 2)
    embed.add_field(
        name="💼 Estimated Net Worth",
        value=f"💵 **{net_worth:,}** *(Cash + CP value)*",
        inline=True,
    )

    # Recent transactions snippet
    if txs:
        lines = []
        for t in txs[:4]:
            t_type = t["tx_type"].replace("_", " ").title()
            amount = f"{t['amount']:,}"
            reason = t.get("reason") or "No memo"
            lines.append(f"• **#{t['id']}** `{t_type}` — **{amount}** ({reason[:30]})")
        embed.add_field(name="📜 Recent Activity", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="📜 Recent Activity", value="*No recorded transactions yet.*", inline=False)

    return embed


def summary_commands_embed() -> discord.Embed:
    """Clean cheatsheet of all available commands in BeastlyBank."""
    embed = create_beastly_embed(
        title="📖 BeastlyBank • Command Cheatsheet",
        description="Quick reference guide for every command in the server:\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(
        name="💰 Economy & Banking",
        value=(
            "• `/balance [user]` | `bb!bal` — Check bank cards and balances\n"
            "• `/pay <user> <currency> <amount>` | `bb!pay` — Send money to another player\n"
            "• `/transfer <player> <@from> <@to> <amount>` | `bb!transfer` — Transfer custom player with fee\n"
            "• `/transactions [user]` | `bb!txs` — View transaction records\n"
            "• `/shop` | `bb!shop` — Browse official BeastlyBank Store\n"
            "• `/buy <id> [qty]` | `bb!buy` — Purchase store items & perks\n"
            "• `/inventory [user]` | `bb!inv` — Inspect personal item stash"
        ),
        inline=False,
    )

    embed.add_field(
        name="🏟️ Football Clubs",
        value=(
            "• `/club create <name> <tag> [@role]` | `bb!club create` — Register a club (100% Free)\n"
            "• `/club info [@role]` | `bb!club info` — Inspect club treasury & squad roster\n"
            "• `/club deposit <currency> <amount> [@role]` | `bb!club deposit` — Fund club treasury\n"
            "• `/club withdraw <currency> <amount> <reason> [@role]` | `bb!club withdraw` — Withdraw from club vault\n"
            "• `/club list` | `bb!club list` — Wealthiest club treasuries leaderboard\n"
            "• `/clubhistory [@role]` | `bb!clubhistory` — Club transaction ledger"
        ),
        inline=False,
    )

    embed.add_field(
        name="👑 BeastlyBank Bankers & Admins",
        value=(
            "• `/manage add <user> <currency> <amount>` — Grant currency\n"
            "• `/manage remove <user> <currency> <amount>` — Deduct currency\n"
            "• `/manage set <user> <currency> <amount>` — Set exact balance\n"
            "• `/manage vault <@club_role> <currency> <action> <amount>` | `bb!vault` — Operate club vault\n"
            "• `/bank announce` — Send official announcement\n"
            "• `/bank audit <user>` — Full financial audit"
        ),
        inline=False,
    )

    return embed


def summary_economy_embed(stats: Dict[str, Any]) -> discord.Embed:
    """Server-wide BeastlyFC economy overview."""
    embed = create_beastly_embed(
        title="🌐 BeastlyFC • Server Economy Summary",
        description="Live aggregate metrics across the entire server economy:\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(
        name="💵 Total Circulating Cash",
        value=f"**{stats.get('total_cash', 0):,}**\n*(Users: {stats.get('user_cash', 0):,} | Vaults: {stats.get('vault_cash', 0):,})*",
        inline=True,
    )
    embed.add_field(
        name="⭐ Total Community Points",
        value=f"**{stats.get('total_points', 0):,}**",
        inline=True,
    )
    embed.add_field(
        name="🎟️ Total Training Tokens",
        value=f"**{stats.get('total_tokens', 0):,}**",
        inline=True,
    )
    embed.add_field(
        name="👥 Registered Players",
        value=f"**{stats.get('total_users', 0):,}** Players",
        inline=True,
    )
    embed.add_field(
        name="🏟️ Registered Clubs",
        value=f"**{stats.get('total_clubs', 0):,}** Clubs",
        inline=True,
    )
    embed.add_field(
        name="🏃 Custom Players",
        value=f"**{stats.get('total_players', 0):,}** Players",
        inline=True,
    )
    embed.add_field(
        name="📜 Total Transactions",
        value=f"**{stats.get('total_txs', 0):,}** Logged",
        inline=True,
    )

    return embed


def club_lineup_embed(
    club: Dict[str, Any],
    formation: str,
    starting_players: List[Dict[str, Any]],
    bench_players: List[Dict[str, Any]],
) -> discord.Embed:
    """Renders the official tactical pitch lineup and substitutes bench for a club."""
    form_meta = SUPPORTED_FORMATIONS.get(formation, {"name": formation, "desc": "Custom"})
    role_str = f"<@&{club['role_id']}>" if club.get("role_id") else f"**[{club['tag']}] {club['name']}**"

    embed = create_beastly_embed(
        title=f"📋 Squad Lineup • [{club['tag']}] {club['name']}",
        description=(
            f"Club: {role_str}\n"
            f"Tactical Formation: **{formation}** ({form_meta.get('name', formation)})\n"
            f"*{form_meta.get('desc', '')}*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_PITCH_GREEN,
    )

    # Group starting players by pitch line
    gks = []
    defs = []
    mids = []
    fwds = []

    for p in starting_players:
        num = f"#{p['number']} " if p.get("number") is not None else ""
        name = p.get("player_name") or (f"<@{p['user_id']}>" if p.get("user_id") else "Player")
        line_item = f"`{num}{p.get('position', '??')}` **{name}**"

        pos = (p.get("position") or "").upper()
        cat = POSITION_CATEGORIES.get(pos, "Midfield")
        if pos == "GK":
            gks.append(line_item)
        elif cat == "Defense":
            defs.append(line_item)
        elif cat == "Midfield":
            mids.append(line_item)
        elif cat == "Attack":
            fwds.append(line_item)
        else:
            mids.append(line_item)

    # Pitch Lines
    embed.add_field(
        name=f"🧤 Goalkeeper ({len(gks)}/1)",
        value="\n".join(f"• {x}" for x in gks) if gks else "*Vacant*",
        inline=False,
    )
    def_target = form_meta.get("def", 4)
    embed.add_field(
        name=f"🛡️ Defense ({len(defs)}/{def_target})",
        value="\n".join(f"• {x}" for x in defs) if defs else "*Vacant*",
        inline=False,
    )
    mid_target = form_meta.get("mid", 3)
    embed.add_field(
        name=f"⚙️ Midfield ({len(mids)}/{mid_target})",
        value="\n".join(f"• {x}" for x in mids) if mids else "*Vacant*",
        inline=False,
    )
    fwd_target = form_meta.get("fwd", 3)
    embed.add_field(
        name=f"⚡ Attack ({len(fwds)}/{fwd_target})",
        value="\n".join(f"• {x}" for x in fwds) if fwds else "*Vacant*",
        inline=False,
    )

    # Substitutes Bench
    bench_items = []
    for p in bench_players:
        num = f"#{p['number']} " if p.get("number") is not None else ""
        name = p.get("player_name") or (f"<@{p['user_id']}>" if p.get("user_id") else "Player")
        bench_items.append(f"`{num}{p.get('position', '??')}` **{name}**")

    bench_text = "\n".join(f"• {x}" for x in bench_items) if bench_items else "*No bench players registered*"
    embed.add_field(
        name=f"💺 Substitutes Bench ({len(bench_players)})",
        value=bench_text,
        inline=False,
    )

    embed.set_footer(
        text=f"Total Squad: {len(starting_players) + len(bench_players)} players • Starters: {len(starting_players)}/11"
    )
    return embed


def player_card_embed(player: Dict[str, Any], club: Optional[Dict[str, Any]] = None) -> discord.Embed:
    """Generates a player information profile card."""
    pos = (player.get("position") or "ST").upper()
    cat = POSITION_CATEGORIES.get(pos, "Player")
    status = player.get("status", "starting")
    status_str = "Starting XI 🟢" if status == "starting" else "Substitutes Bench 🟡"
    num = f"#{player['number']}" if player.get("number") is not None else "Unassigned"

    club_str = "Free Agent"
    if club:
        if club.get("role_id"):
            club_str = f"<@&{club['role_id']}>"
        else:
            club_str = f"**[{club.get('tag', 'FC')}] {club.get('name', 'Club')}**"

    embed = create_beastly_embed(
        title=f"🏃 Player Profile • {player.get('player_name', 'Player')}",
        description=f"Official BeastlyFC registered player profile.\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(name="🛡️ Club Affiliation", value=club_str, inline=True)
    embed.add_field(name="📍 Position", value=f"**{pos}** ({cat})", inline=True)
    embed.add_field(name="🔢 Jersey Number", value=f"**{num}**", inline=True)
    embed.add_field(name="📊 Lineup Status", value=f"**{status_str}**", inline=True)

    if player.get("user_id"):
        embed.add_field(name="👤 Discord Member", value=f"<@{player['user_id']}>", inline=True)

    joined = player.get("transferred_at") or player.get("joined_at")
    if joined:
        embed.add_field(name="📅 Registered / Transferred", value=f"`{joined[:10]}`", inline=True)

    return embed

