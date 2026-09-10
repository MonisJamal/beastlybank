import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Dict, Iterable, List, Optional
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

logger = logging.getLogger("BeastlyBank.Embeds")

_USER_NAME_CACHE: Dict[int, str] = {0: "Vacant"}


def formations_list_embed() -> discord.Embed:
    """Build a single embed listing all supported formations (description-based for Discord limits)."""
    groups: Dict[str, List[str]] = {"3-Back": [], "4-Back": [], "5-Back": []}
    for code, meta in SUPPORTED_FORMATIONS.items():
        group = f"{meta['def']}-Back"
        groups.setdefault(group, []).append(
            f"• `{code}` — `{meta['def']} DEF` | `{meta['mid']} MID` | `{meta['fwd']} FWD`"
        )

    sections = [
        f"All **{len(SUPPORTED_FORMATIONS)}** available tactical formations for club lineups:",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    for label in ("3-Back", "4-Back", "5-Back"):
        items = groups.get(label) or []
        if not items:
            continue
        sections.append(f"\n**{label}**")
        sections.extend(items)

    return create_beastly_embed(
        title="⚽ Supported Formations • BeastlyFC",
        description="\n".join(sections),
        color=COLOR_PITCH_GREEN,
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


async def resolve_user_names(
    bot: Any,
    guild: Optional[discord.Guild],
    user_ids: Iterable[int],
    max_fetch: int = 15,
    use_cache: bool = True,
) -> Dict[int, str]:
    """Resolve Discord user IDs to display names with in-memory caching and bounded parallel REST fallback."""
    user_map: Dict[int, str] = {}
    uncached_ids: List[int] = []

    for uid in user_ids:
        if not uid:
            user_map[uid] = "Vacant"
            continue

        # 1. In-memory global cache
        if use_cache and uid in _USER_NAME_CACHE:
            user_map[uid] = _USER_NAME_CACHE[uid]
            continue

        # 2. Guild member cache
        name = None
        if guild:
            member = guild.get_member(uid)
            if member:
                name = getattr(member, "display_name", None) or getattr(member, "name", None)

        # 3. Bot user cache
        if not name and bot and hasattr(bot, "get_user"):
            user = bot.get_user(uid)
            if user:
                name = getattr(user, "display_name", None) or getattr(user, "name", None)

        if name:
            if use_cache:
                _USER_NAME_CACHE[uid] = name
            user_map[uid] = name
        else:
            uncached_ids.append(uid)

    # 4. Fast bounded parallel fetch for uncached IDs (up to max_fetch in parallel, capped at 0.8s)
    if uncached_ids and bot and hasattr(bot, "fetch_user"):
        to_fetch = uncached_ids[:max_fetch]

        async def _fetch_one(target_id: int):
            try:
                u = await bot.fetch_user(target_id)
                if u:
                    n = getattr(u, "display_name", None) or getattr(u, "name", None)
                    if n:
                        return target_id, n
            except Exception:
                pass
            return target_id, None

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[_fetch_one(tid) for tid in to_fetch], return_exceptions=True),
                timeout=0.8,
            )
            for res in results:
                if isinstance(res, tuple) and len(res) == 2:
                    tid, n = res
                    if n:
                        if use_cache:
                            _USER_NAME_CACHE[tid] = n
                        user_map[tid] = n
        except Exception:
            pass

    # 5. Immediate non-blocking fallback for any still unresolvable IDs
    for uid in uncached_ids:
        if uid not in user_map:
            user_map[uid] = f"User-{str(uid)[-4:]}"

    return user_map


async def safe_defer(target: Any, ephemeral: bool = False) -> None:
    """Safely defer a slash interaction if not already responded, handling mocks and errors."""
    if isinstance(target, discord.Interaction) and hasattr(target, "response"):
        try:
            is_done_func = getattr(target.response, "is_done", None)
            done = is_done_func() if callable(is_done_func) else False
            if done is not True:
                defer_func = getattr(target.response, "defer", None)
                if callable(defer_func):
                    res = defer_func(ephemeral=ephemeral)
                    if asyncio.iscoroutine(res):
                        await res
        except Exception as e:
            logger.debug("safe_defer error: %s", e)


async def send_msg(
    target: Any,
    embed: Optional[discord.Embed] = None,
    ephemeral: bool = False,
    view: Optional[discord.ui.View] = None,
    file: Optional[discord.File] = None,
) -> Any:
    """Safely send embed responses and file attachments to interactions or commands.Context."""
    try:
        kwargs: Dict[str, Any] = {}
        if embed is not None:
            kwargs["embed"] = embed
        if view is not None:
            kwargs["view"] = view
        if file is not None:
            kwargs["file"] = file

        if isinstance(target, discord.Interaction):
            is_done = False
            if hasattr(target, "response") and hasattr(target.response, "is_done"):
                done_val = target.response.is_done()
                if done_val is True:
                    is_done = True

            if is_done:
                try:
                    return await target.followup.send(ephemeral=ephemeral, **kwargs)
                except Exception:
                    return await target.followup.send(**kwargs)
            else:
                if hasattr(target, "response") and hasattr(target.response, "send_message"):
                    res = target.response.send_message(ephemeral=ephemeral, **kwargs)
                    if asyncio.iscoroutine(res):
                        return await res
                    return res
        elif hasattr(target, "send"):
            return await target.send(**kwargs)
    except Exception as e:
        logger.error("Error in send_msg: %s", e, exc_info=True)


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
    user_names: Optional[Dict[int, str]] = None,
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
            rec_id = tx["receiver_id"]
            rec_name = (user_names or {}).get(rec_id)
            rec_str = f"**{rec_name}**" if rec_name else f"<@{rec_id}>"
            counterpart = f"To: {rec_str}"
        elif tx["receiver_id"] == target_user.id:
            prefix = "🔺 Credited"
            if tx["sender_id"]:
                snd_id = tx["sender_id"]
                snd_name = (user_names or {}).get(snd_id)
                snd_str = f"**{snd_name}**" if snd_name else f"<@{snd_id}>"
                counterpart = f"From: {snd_str}"
            else:
                counterpart = "From: System Reward"
        else:
            prefix = "💳 Transaction"
            counterpart = ""

        embed.add_field(
            name=f"#{tx_id} | {prefix} {emoji} {amount:,} ({tx_type})",
            value=f"**{counterpart}**\n📝 *{reason}* • `{created_at}`",
            inline=False,
        )

    embed.set_footer(text=f"Page {page} of {max(total_pages, 1)} • BeastlyBank Statement")
    return embed


def club_info_embed(
    club: Dict[str, Any],
    members: List[Dict[str, Any]],
    owner_name: Optional[str] = None,
    member_names: Optional[Dict[int, str]] = None,
) -> discord.Embed:
    """Display BeastlyFC Club profile and Treasury vault status."""
    embed = create_beastly_embed(
        title=f"🏟️ Club Profile • [{club['tag']}] {club['name']}",
        description=f"Official BeastlyFC Club Treasury and Roster.\n━━━━━━━━━━━━━━━━━━━━━━",
        color=COLOR_PITCH_GREEN,
    )

    owner_id = club.get("owner_id", 0)
    if owner_name:
        owner_val = f"**{owner_name}** (<@{owner_id}>)" if owner_id else "*Vacant*"
    else:
        owner_val = f"<@{owner_id}>" if owner_id else "*Vacant*"

    embed.add_field(
        name="👑 Club Owner",
        value=owner_val,
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
        name_map = member_names or {}
        for m in members[:12]:
            uid = m.get("user_id")
            if uid:
                dname = name_map.get(uid)
                if dname:
                    roster_lines.append(f"• **{dname}** (<@{uid}>) — `{m['role']}`")
                else:
                    roster_lines.append(f"• <@{uid}> — `{m['role']}`")
            elif m.get("player_name"):
                roster_lines.append(f"• **{m['player_name']}** — `{m.get('role', 'Player')}`")
            else:
                roster_lines.append(f"• Unknown Player — `{m.get('role', 'Player')}`")
        if len(members) > 12:
            roster_lines.append(f"*...and {len(members) - 12} more players (use `/club roster`)*")
        embed.add_field(
            name="📋 Squad Members",
            value="\n".join(roster_lines),
            inline=False,
        )

    return embed


def club_roster_embed(
    club: Dict[str, Any],
    members: List[Dict[str, Any]],
    member_names: Dict[int, str],
    page: int = 1,
    total_pages: int = 1,
) -> discord.Embed:
    """Paginated embed displaying a club's full squad roster with usernames and roles."""
    role_mention = f"<@&{club['role_id']}>" if club.get("role_id") else f"**[{club['tag']}] {club['name']}**"
    embed = create_beastly_embed(
        title=f"📋 Squad Roster • [{club['tag']}] {club['name']}",
        description=(
            f"Club: {role_mention}\n"
            f"Total Squad: **{len(members)}** registered players & staff\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_PITCH_GREEN,
    )

    if not members:
        embed.description += "\n*No members registered in this club.*"
        return embed

    per_page = 10
    start_idx = (page - 1) * per_page
    page_members = members[start_idx : start_idx + per_page]

    for idx, m in enumerate(page_members, start=start_idx + 1):
        uid = m.get("user_id")
        role = m.get("role", "Member")
        if uid:
            display_name = member_names.get(uid, f"User-{str(uid)[-4:]}")
            embed.add_field(
                name=f"`#{idx}` {display_name} — `{role}`",
                value=f"👤 Mention: <@{uid}>",
                inline=False,
            )
        elif m.get("player_name"):
            embed.add_field(
                name=f"`#{idx}` {m['player_name']} — `{role}`",
                value="🏃 Registered Squad Member",
                inline=False,
            )

    embed.set_footer(text=f"Page {page} of {total_pages} • BeastlyFC Squad Roster")
    return embed


def help_system_guide_embed() -> discord.Embed:
    """Official interactive System Guide & Manual for BeastlyBank."""
    embed = create_beastly_embed(
        title="🏦 BeastlyBank • Official System Guide & Manual ⚽",
        description=(
            "Welcome to **BeastlyBank**, the financial vault, store, and tactical squad management ecosystem for **BeastlyFC**!\n\n"
            "💡 *Every feature supports both Slash Commands (`/`) and traditional Prefix Commands (`bb!`)*.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(
        name="💵 Multi-Currency Banking",
        value=(
            "• 💵 **Cash** — Primary currency for transfers, store items, and match prize payouts.\n"
            "• ⭐ **Community Points (CP)** — Earned through server events, competitions, and matches.\n"
            "• 🎟️ **Training Tokens** — Specialized currency for player development drills.\n"
            "• **Key Commands:** `/balance [user]` | `bb!bal`, `/pay <user> <amount>` | `bb!pay`, `/summary` | `bb!summary`"
        ),
        inline=False,
    )

    embed.add_field(
        name="🏟️ 100% Free Clubs & Role-Linked Vaults",
        value=(
            "• **Free Registration:** Register your club with `/club create <name> <tag> <@role>` (zero creation fee!).\n"
            "• **Role Mentions:** Mention your club's Discord role (`@Role`) directly in all commands!\n"
            "• **Vault Operations:** `/club deposit`, `/club withdraw`, `/club info [@role]`, `/club list`, `/clubhistory [@role]`\n"
            "• **Management:** `/club addmanager <user> [@role]` & `/club removemanager` (or Banker `/manage manager`)"
        ),
        inline=False,
    )

    embed.add_field(
        name="💸 Official Player Transfer Market",
        value=(
            "• **Transfers:** `/transfer <player> <@from_role> <@to_role> <amount>` | `bb!transfer`\n"
            "• **Auto-Settlement:** Automatically debits the buying club vault and deposits into the selling club vault!\n"
            "• **Number Formats:** Supports standard (`5000000`), human notation (`30m`, `500k`), and scientific (`26e6`, `3e7`, or `0` for free transfers).\n"
            "• **Full Attribute Preservation:** OVR rating, potential, alternate positions, and jersey numbers remain 100% intact!"
        ),
        inline=False,
    )

    embed.add_field(
        name=f"⚽ Tactical Squads & {len(SUPPORTED_FORMATIONS)} Formations",
        value=(
            f"• **{len(SUPPORTED_FORMATIONS)} Formations:** `/formation set <form>` | `/formation list`\n"
            "• **Pitch Lineup:** `/lineup [@role]` displays visual pitch positions (GK, DEF, MID, FWD) with OVR ratings & bench.\n"
            "• **Register Players:** `/player add <name> <pos> [rating] [pot] [\"alt_positions\"]` | `bb!addplayer`\n"
            "• **Switch Positions:** `/player switchpos <player> <pos>` | `bb!switchpos <player> <pos>` (or swap 2 players with `bb!switchpos <p1> <p2>`)\n"
            "• **Edit & Substitutions:** `/player edit`, `/player swap <p1> <p2>`, `/player start`, `/player bench`, `/player remove`"
        ),
        inline=False,
    )

    embed.add_field(
        name="🛒 Store, Giveaways & Leaderboards",
        value=(
            "• **Store & Inventory:** Browse items with `/shop`, buy with `/buy <id>`, inspect with `/inventory`.\n"
            "• **Server Giveaways:** Bankers host automated giveaways with `/giveaway start`, `/giveaway end`, `/giveaway reroll`.\n"
            "• **Rankings:** Check richest accounts and clubs with `/leaderboard` | `bb!lb`."
        ),
        inline=False,
    )

    embed.set_footer(text="Click the interactive buttons below to explore Cheatsheet, Squad Guide, and Server Stats • BeastlyFC Bank")
    return embed


def summary_overview_embed(
    user: discord.Member,
    user_data: Dict[str, Any],
    club: Optional[Dict[str, Any]] = None,
) -> discord.Embed:
    """Personal account summary of BeastlyBank balances, club standing, and quick actions."""
    embed = create_beastly_embed(
        title=f"🏦 BeastlyBank • Account Summary • {user.display_name}",
        description=(
            f"Official account status and financial overview for {user.mention} in **{SERVER_NAME}**.\n"
            f"💡 *All commands support both Slash (`/command`) and Prefix (`bb!command`) formats!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    if hasattr(user, "display_avatar") and user.display_avatar:
        embed.set_thumbnail(url=user.display_avatar.url)
    elif hasattr(user, "avatar") and user.avatar:
        embed.set_thumbnail(url=user.avatar.url)

    # Account status field
    club_role_str = f" • <@&{club['role_id']}>" if club and club.get("role_id") else ""
    club_str = f"**[{club['tag']}] {club['name']}**{club_role_str} (`{club.get('user_role', 'Member')}`)" if club else "*Free Agent (No Club)*"
    net_worth = user_data.get("cash", 0) + (user_data.get("points", 0) * 2)

    embed.add_field(
        name="👤 Your Account Summary",
        value=(
            f"• 💵 **Cash:** `{user_data.get('cash', 0):,}`\n"
            f"• ⭐ **Points:** `{user_data.get('points', 0):,}`\n"
            f"• 🎟️ **Tokens:** `{user_data.get('tokens', 0):,}`\n"
            f"• 💼 **Net Worth:** `{net_worth:,}` *(Cash + CP value)*\n"
            f"• 🏟️ **Club:** {club_str}"
        ),
        inline=False,
    )

    # Quick Actions field (< 400 chars)
    embed.add_field(
        name="⚡ Quick Shortcuts",
        value=(
            "• **Balance & Pay:** `/balance` | `bb!bal`, `/pay <user> <amount>`\n"
            "• **Club Standing:** `/club info [@role]` | `bb!club info`\n"
            "• **Tactical Lineup:** `/lineup [@role]` | `bb!lineup`\n"
            "• **Switch Positions:** `/switchpos <player> <pos>` | `bb!switchpos`\n"
            "• **Transfers:** `/transfer <player> <@from> <@to> <amount>`\n"
            "• **Shop & Perks:** `/shop` & `/buy <id>` | `/inventory`"
        ),
        inline=False,
    )

    # Interactive tabs navigation (< 400 chars)
    embed.add_field(
        name="📑 Interactive Menus",
        value=(
            "• 💰 **Finances:** Live breakdown of cash, points, tokens & transactions.\n"
            "• ⚽ **Squad Guide:** Tactical formations, starting XI & player management.\n"
            "• 📖 **Cheatsheet:** Complete directory of all commands.\n"
            "• 🌐 **Stats:** Server-wide circulation and top wealth rankings."
        ),
        inline=False,
    )

    embed.set_footer(text="Click the interactive buttons below to explore detailed tabs • BeastlyFC Bank")
    return embed



def summary_squad_embed() -> discord.Embed:
    """Detailed guide and reference for Squad, Lineups, Formations, and Player Management."""
    embed = create_beastly_embed(
        title="⚽ Squad, Formations & Lineup Guide",
        description=(
            "Complete tactical reference for managing your football squad in **BeastlyFC**.\n"
            "Supports both Discord Slash commands (`/`) and traditional Prefix commands (`bb!`).\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_PITCH_GREEN,
    )

    embed.add_field(
        name=f"📐 Tactical Formations ({len(SUPPORTED_FORMATIONS)} Supported)",
        value=(
            "• `/formation set <formation> [club: @role]` — set your squad's active formation\n"
            "• `/formation list` — browse every supported shape\n"
            "  **3-Back:** `3-1-4-2`, `3-2-4-1`, `3-4-1-2`, `3-4-2-1`, `3-4-3 Diamond`, `3-4-3 Flat`, `3-5-1-1`, `3-5-2`\n"
            "  **4-Back:** `4-1-2-1-2 Narrow/Wide`, `4-1-3-2`, `4-1-3-2 Attacking`, `4-1-4-1`, `4-2-1-3`, `4-2-2-2`, `4-2-3-1 Narrow/Wide`, `4-2-4`, `4-3-1-2`, `4-3-2-1`, `4-3-3 Attack/Balanced/Defend/False 9/Flat/Holding`, `4-4-1-1 Attack/Midfield`, `4-4-2 Flat/Holding`, `4-5-1 Attack/Flat`\n"
            "  **5-Back:** `5-2-1-2`, `5-2-3`, `5-3-2`, `5-4-1 Diamond`, `5-4-1 Flat`"
        ),
        inline=False,
    )

    embed.add_field(
        name="📋 Tactical Pitch Lineup",
        value=(
            "• `/lineup [club: @role]` | `bb!lineup [@role]`\n"
            "  *Displays the full visual pitch lineup (🧤 GK, 🛡️ Defense, ⚙️ Midfield, ⚡ Attack) with `[OVR]` rating tags, plus the Substitutes Bench.*"
        ),
        inline=False,
    )

    embed.add_field(
        name="🏃 Registering & Adding Players",
        value=(
            "• `/player add <player> <pos> [status] [number] [rating] [potential] [alt_positions] [club: @role]`\n"
            "• `bb!addplayer <player> <pos> [status] [number] [rating] [potential] [\"pos1, pos2, pos3, .....\"] [@role]`\n"
            "  *Register a custom player or Discord user. Attributes:*:\n"
            "  - **Primary Position:** `GK`, `CB`, `LB`, `RB`, `LWB`, `RWB`, `CDM`, `CM`, `CAM`, `LM`, `RM`, `LW`, `RW`, `ST`, `CF`\n"
            "  - **Overall Rating (OVR):** `1` to `99` (defaults to `75`)\n"
            "  - **Growth Potential (POT):** `1` to `99` (defaults to `80`)\n"
            "  - **Alternate Positions:** Comma-separated list `\"pos1, pos2, pos3, .....\"` (e.g. `\"LW, RW, CAM\"`)\n"
            "  - **Lineup Status:** `starting` (max 11 starters) or `bench`\n"
            "  - *Example:* `bb!addplayer Mbappe ST starting 9 91 95 \"LW, RW, CAM\" @RealMadrid`"
        ),
        inline=False,
    )

    embed.add_field(
        name="✏️ Editing Player Details",
        value=(
            "• `/player edit <player> [name] [pos] [status] [number] [rating] [potential] [alt_positions] [club: @role]`\n"
            "• `bb!editplayer <player> <field> <value> [@role]`\n"
            "  *Fields:* `rating` (or `ovr`), `potential` (or `pot`), `alt` (or `altpos`), `pos`, `status`, `number`, `name`\n"
            "  - *Example:* `bb!editplayer Mbappe rating 92 @RealMadrid`\n"
            "  - *Example:* `bb!editplayer Mbappe alt \"LW, RW, CAM, RM\" @RealMadrid`\n"
            "  *(Changing primary position automatically cleans that position from alternate positions)*"
        ),
        inline=False,
    )

    embed.add_field(
        name="🔄 Tactical Substitutions & Transfers",
        value=(
            "• `/player swap <p1> <p2> [club: @role]` | `bb!swap <p1> <p2> [@role]`\n"
            "  *Tactical substitution (starter ⇄ bench swaps lineup status) or position swap (starter ⇄ starter swaps pitch positions).*\n"
            "• `/player start <player>` | `bb!start <player>` — Promote a bench player into the Starting XI.\n"
            "• `/player bench <player>` | `bb!bench <player>` — Move a player to the Substitutes Bench.\n"
            "• `/player remove <player>` | `bb!removeplayer <player>` — Remove a player from the squad.\n"
            "• `/transfer <player> <@from_role> <@to_role> <amt>` | `bb!transfer`\n"
            "  *Official club transfer — debits buying club vault, deposits into selling club vault, and preserves all player attributes (rating, potential, alt positions, number)!*"
        ),
        inline=False,
    )

    embed.set_footer(text="Click the interactive buttons below to switch sections • BeastlyFC Bank")
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
            "• `/summary [user]` | `bb!summary` — View personal account summary & profile\n"
            "• `/help [category]` | `bb!help` — Interactive guide & command reference\n"
            "• `/transfer <player> <@from> <@to> <amount>` | `bb!transfer` — Official player transfer\n"
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
            "• `/club create <name> <tag> <@role>` | `bb!club create` — Register a club (100% Free)\n"
            "• `/club info [@role]` | `bb!club info` — Inspect club treasury & squad roster\n"
            "• `/club deposit <currency> <amount> [@role]` | `bb!club deposit` — Fund club treasury\n"
            "• `/club withdraw <currency> <amount> <reason> [@role]` | `bb!club withdraw` — Withdraw from club vault\n"
            "• `/club addmanager <user> [@role]` | `/club removemanager` — Appoint/demote manager\n"
            "• `/club list` | `bb!club list` — Wealthiest club treasuries leaderboard\n"
            "• `/clubhistory [@role]` | `bb!clubhistory` — Club transaction ledger"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚽ Squad & Lineup Management",
        value=(
            "• `/lineup [@role]` | `bb!lineup` — View tactical pitch layout & bench\n"
            "• `/formation set <form>` | `bb!setformation` — Set tactical formation (realigns XI)\n"
            "• `/formation list` | `bb!formations` — Browse all 37 formations\n"
            "• `/player switchpos <player> <pos>` | `bb!switchpos` — Switch pitch position or swap 2 players\n"
            "• `/player info <player>` | `bb!player` — Player profile with OVR, POT, alt positions\n"
            "• `/player add <player> <pos>` | `bb!addplayer` — Register player to XI or bench\n"
            "• `/player edit <player> [field] [val]` | `bb!editplayer` — Edit player rating, potential, alts\n"
            "• `/player swap <p1> <p2>` | `bb!swap` — Tactical substitution or position switch\n"
            "• `/player start` / `/player bench` | `bb!start` / `bb!bench` — Promote to XI or bench\n"
            "• `/player remove <player>` | `bb!removeplayer` — Remove player from squad"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎁 Community, Giveaways & Leaderboard",
        value=(
            "• `/leaderboard [currency]` | `bb!lb` — View richest members and clubs\n"
            "• `/giveaway start <prize> <duration> [currency]` — Start official giveaway\n"
            "• `/giveaway end <message_id>` — Conclude an active giveaway early\n"
            "• `/giveaway reroll <message_id>` — Reroll giveaway winner"
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
            "• `/manage manager <add|remove> <@club_role> <user>` | `bb!manager` — Appoint/remove manager\n"
            "• `/manage owner <add|remove|change> <@role> [user]` | `bb!owner` — Manage club owner\n"
            "• `/manage deleteclub <@role>` | `bb!deleteclub` — Disband & delete club\n"
            "• `/bank backup` | `bb!backup` — Backup database to cloud channel\n"
            "• `/bank restore` | `bb!restore` — Restore database from backup file\n"
            "• `/shopadmin add/edit/list/toggle/remove` — Manage store catalogue\n"
            "• `/settings economy/purchases/shop/view` — Configure server-wide economy settings\n"
            "• `/bank audit <user>` — Full financial audit"
        ),
        inline=False,
    )

    embed.set_footer(text="Click the interactive buttons below to switch sections • BeastlyFC Bank")
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


def make_rating_bar(rating: int, total: int = 10) -> str:
    """Renders a visually pleasing progress bar for an OVR rating."""
    clamped = max(0, min(100, int(rating)))
    filled = int(round((clamped / 100.0) * total))
    filled = max(0, min(total, filled))
    empty = total - filled
    if clamped >= 85:
        block = "🟩"
    elif clamped >= 75:
        block = "🟦"
    elif clamped >= 65:
        block = "🟨"
    else:
        block = "🟧"
    return f"{block * filled}{'▫️' * empty}"


def club_lineup_embed(
    club: Dict[str, Any],
    formation: str,
    starting_players: List[Dict[str, Any]],
    bench_players: List[Dict[str, Any]],
) -> discord.Embed:
    """Renders the official tactical pitch lineup and substitutes bench for a club."""
    form_meta = SUPPORTED_FORMATIONS.get(formation, {"name": formation, "desc": "Custom"})
    role_str = f"<@&{club['role_id']}>" if club.get("role_id") else f"**[{club['tag']}] {club['name']}**"

    # Compute department & team overall ratings for Starting XI
    att_ratings = [
        int(p["rating"]) for p in starting_players
        if p.get("rating") is not None and POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Attack"
    ]
    mid_ratings = [
        int(p["rating"]) for p in starting_players
        if p.get("rating") is not None and POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Midfield"
    ]
    def_ratings = [
        int(p["rating"]) for p in starting_players
        if p.get("rating") is not None and (
            POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Defense"
            or (p.get("position") or "").upper() == "GK"
        )
    ]
    all_starter_ratings = [int(p["rating"]) for p in starting_players if p.get("rating") is not None]

    att_avg = round(sum(att_ratings) / len(att_ratings)) if att_ratings else None
    mid_avg = round(sum(mid_ratings) / len(mid_ratings)) if mid_ratings else None
    def_avg = round(sum(def_ratings) / len(def_ratings)) if def_ratings else None
    ovr_avg = round(sum(all_starter_ratings) / len(all_starter_ratings)) if all_starter_ratings else None

    att_str = f"{att_avg}" if att_avg is not None else "--"
    mid_str = f"{mid_avg}" if mid_avg is not None else "--"
    def_str = f"{def_avg}" if def_avg is not None else "--"
    ovr_str = f"{ovr_avg}" if ovr_avg is not None else "--"

    embed = create_beastly_embed(
        title=f"📋 Squad Lineup • [{club['tag']}] {club['name']}",
        description=(
            f"Club: {role_str}\n"
            f"Tactical Formation: **{formation}**\n"
            f"*{form_meta.get('desc', '')}*\n"
            f"📊 **Team Rating:** ⚡ ATT: **{att_str}** | ⚙️ MID: **{mid_str}** | 🛡️ DEF: **{def_str}** | ⭐ OVR: **{ovr_str}**\n"
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
        r_tag = f" `[{p['rating']}]`" if p.get("rating") else ""
        line_item = f"`{num}{p.get('position', '??')}` **{name}**{r_tag}"

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
    def_hdr = f"🛡️ Defense ({len(defs)}/{def_target})" + (f" • `{def_str} DEF`" if def_avg is not None else "")
    embed.add_field(
        name=def_hdr,
        value="\n".join(f"• {x}" for x in defs) if defs else "*Vacant*",
        inline=False,
    )
    mid_target = form_meta.get("mid", 3)
    mid_hdr = f"⚙️ Midfield ({len(mids)}/{mid_target})" + (f" • `{mid_str} MID`" if mid_avg is not None else "")
    embed.add_field(
        name=mid_hdr,
        value="\n".join(f"• {x}" for x in mids) if mids else "*Vacant*",
        inline=False,
    )
    fwd_target = form_meta.get("fwd", 3)
    fwd_hdr = f"⚡ Attack ({len(fwds)}/{fwd_target})" + (f" • `{att_str} ATT`" if att_avg is not None else "")
    embed.add_field(
        name=fwd_hdr,
        value="\n".join(f"• {x}" for x in fwds) if fwds else "*Vacant*",
        inline=False,
    )

    # Substitutes Bench
    bench_items = []
    for p in bench_players:
        num = f"#{p['number']} " if p.get("number") is not None else ""
        name = p.get("player_name") or (f"<@{p['user_id']}>" if p.get("user_id") else "Player")
        r_tag = f" `[{p['rating']}]`" if p.get("rating") else ""
        bench_items.append(f"`{num}{p.get('position', '??')}` **{name}**{r_tag}")

    bench_text = "\n".join(f"• {x}" for x in bench_items) if bench_items else "*No bench players registered*"
    embed.add_field(
        name=f"💺 Substitutes Bench ({len(bench_players)})",
        value=bench_text,
        inline=False,
    )

    footer_ovr = f" • Team OVR: {ovr_str}" if ovr_avg is not None else ""
    embed.set_footer(
        text=f"Total Squad: {len(starting_players) + len(bench_players)} players • Starters: {len(starting_players)}/11{footer_ovr}"
    )
    return embed


def club_ratings_embed(
    club: Dict[str, Any],
    formation: str,
    starting_players: List[Dict[str, Any]],
    bench_players: List[Dict[str, Any]],
) -> discord.Embed:
    """Renders a comprehensive TV-broadcast style Team Ratings & Department Strength card."""
    role_str = f"<@&{club['role_id']}>" if club.get("role_id") else f"**[{club['tag']}] {club['name']}**"

    # Separate starting players by department
    att_players = [
        p for p in starting_players
        if p.get("rating") is not None and POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Attack"
    ]
    mid_players = [
        p for p in starting_players
        if p.get("rating") is not None and POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Midfield"
    ]
    def_players = [
        p for p in starting_players
        if p.get("rating") is not None and (
            POSITION_CATEGORIES.get((p.get("position") or "").upper()) == "Defense"
            or (p.get("position") or "").upper() == "GK"
        )
    ]
    all_starters = [p for p in starting_players if p.get("rating") is not None]
    all_bench = [p for p in bench_players if p.get("rating") is not None]
    all_squad = all_starters + all_bench

    att_avg = round(sum(int(p["rating"]) for p in att_players) / len(att_players)) if att_players else None
    mid_avg = round(sum(int(p["rating"]) for p in mid_players) / len(mid_players)) if mid_players else None
    def_avg = round(sum(int(p["rating"]) for p in def_players) / len(def_players)) if def_players else None
    ovr_avg = round(sum(int(p["rating"]) for p in all_starters) / len(all_starters)) if all_starters else None
    bench_avg = round(sum(int(p["rating"]) for p in all_bench) / len(all_bench)) if all_bench else None

    # Star player of the squad (highest rating)
    star_player = max(all_squad, key=lambda p: int(p.get("rating") or 0)) if all_squad else None
    star_str = (
        f"🌟 **{star_player.get('player_name')}** (`{star_player.get('position', '??')}`) — **{star_player.get('rating')} OVR**"
        if star_player and star_player.get("rating")
        else "None registered"
    )

    ovr_val = ovr_avg if ovr_avg is not None else 75
    ovr_bar = make_rating_bar(ovr_val)

    embed = create_beastly_embed(
        title=f"⭐ Team Ratings • [{club['tag']}] {club['name']}",
        description=(
            f"Club: {role_str}\n"
            f"Tactical Formation: **{formation}**\n"
            f"Squad Star: {star_str}\n\n"
            f"### 🏆 Overall Team Rating: **{ovr_avg if ovr_avg is not None else '--'} OVR**\n"
            f"`{ovr_bar}`\n"
            f"━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    # ⚡ Attack Field
    if att_players:
        top_att = max(att_players, key=lambda p: int(p.get("rating") or 0))
        att_bar = make_rating_bar(att_avg or 0, total=8)
        att_desc = (
            f"**Rating:** `{att_avg} ATT` {att_bar}\n"
            f"**Star Forward:** {top_att.get('player_name')} (`{top_att.get('position', 'FWD')}`) • `{top_att.get('rating')} OVR`\n"
            f"**Starters:** {len(att_players)} attackers"
        )
    else:
        att_desc = "*No starting attackers registered*"
    embed.add_field(name="⚡ Attack (ATT)", value=att_desc, inline=False)

    # ⚙️ Midfield Field
    if mid_players:
        top_mid = max(mid_players, key=lambda p: int(p.get("rating") or 0))
        mid_bar = make_rating_bar(mid_avg or 0, total=8)
        mid_desc = (
            f"**Rating:** `{mid_avg} MID` {mid_bar}\n"
            f"**Engine Room Star:** {top_mid.get('player_name')} (`{top_mid.get('position', 'MID')}`) • `{top_mid.get('rating')} OVR`\n"
            f"**Starters:** {len(mid_players)} midfielders"
        )
    else:
        mid_desc = "*No starting midfielders registered*"
    embed.add_field(name="⚙️ Midfield (MID)", value=mid_desc, inline=False)

    # 🛡️ Defense & Goalkeeper Field
    if def_players:
        top_def = max(def_players, key=lambda p: int(p.get("rating") or 0))
        def_bar = make_rating_bar(def_avg or 0, total=8)
        def_desc = (
            f"**Rating:** `{def_avg} DEF` {def_bar}\n"
            f"**Defensive Anchor:** {top_def.get('player_name')} (`{top_def.get('position', 'DEF')}`) • `{top_def.get('rating')} OVR`\n"
            f"**Starters:** {len(def_players)} defenders & GK"
        )
    else:
        def_desc = "*No starting defenders or GK registered*"
    embed.add_field(name="🛡️ Defense & Goalkeeper (DEF)", value=def_desc, inline=False)

    # 💺 Squad Depth Field
    depth_val = f"`{bench_avg} AVG`" if bench_avg is not None else "*No rated bench*"
    depth_desc = (
        f"**Bench Size:** {len(bench_players)} players ({depth_val})\n"
        f"**Total Squad:** {len(starting_players) + len(bench_players)} registered players"
    )
    embed.add_field(name="💺 Squad Depth", value=depth_desc, inline=False)

    embed.set_footer(
        text=f"Tactical Engine • Starting XI OVR: {ovr_avg if ovr_avg is not None else '--'} • {BOT_NAME}"
    )
    return embed


def player_card_embed(player: Dict[str, Any], club: Optional[Dict[str, Any]] = None) -> discord.Embed:
    """Generates a player information profile card."""
    pos = (player.get("position") or "ST").upper()
    cat = POSITION_CATEGORIES.get(pos, "Player")
    status = player.get("status", "starting")
    status_str = "Starting XI 🟢" if status == "starting" else "Substitutes Bench 🟡"
    num = f"#{player['number']}" if player.get("number") is not None else "Unassigned"
    rating = player.get("rating", 75)
    potential = player.get("potential", 80)
    alt_pos = player.get("alt_positions") or "None"

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
    embed.add_field(name="📍 Primary Position", value=f"**{pos}** ({cat})", inline=True)
    embed.add_field(name="🔄 Alt Positions", value=f"**{alt_pos}**", inline=True)
    embed.add_field(name="⭐ Overall Rating", value=f"**{rating}** OVR", inline=True)
    embed.add_field(name="🚀 Potential Rating", value=f"**{potential}** POT", inline=True)
    embed.add_field(name="🔢 Jersey Number", value=f"**{num}**", inline=True)
    embed.add_field(name="📊 Lineup Status", value=f"**{status_str}**", inline=True)

    if player.get("user_id"):
        member_name = player.get("display_name")
        if member_name:
            embed.add_field(name="👤 Discord Member", value=f"**{member_name}** (<@{player['user_id']}>)", inline=True)
        else:
            embed.add_field(name="👤 Discord Member", value=f"<@{player['user_id']}>", inline=True)

    joined = player.get("transferred_at") or player.get("joined_at")
    if joined:
        embed.add_field(name="📅 Registered / Transferred", value=f"`{joined[:10]}`", inline=True)

    return embed


def beastlybank_announcement_embed() -> discord.Embed:
    """Creates the official comprehensive BeastlyBank system guide & launch announcement embed."""
    embed = create_beastly_embed(
        title="🏦 OFFICIAL BEASTLYBANK SYSTEM GUIDE & OVERVIEW ⚽",
        description=(
            "Welcome to **BeastlyBank**, the automated financial infrastructure, treasury vault, and squad management ecosystem engineered exclusively for **BeastlyFC**! 💰\n\n"
            "Below is your complete guide to all features, currencies, clubs, squad management, and commands.\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        ),
        color=COLOR_BEASTLY_GOLD,
    )

    embed.add_field(
        name="💡 Slash (/) & Prefix (bb!) Commands",
        value=(
            "Every command in BeastlyBank can be triggered via standard Discord **Slash Commands (`/`)** or traditional **Prefix Commands (`bb!`)**:\n"
            "• Examples: `/balance` or `bb!balance` (or `bb!bal`), `/transfer` or `bb!transfer`, `/help` or `bb!help`\n"
            "*(Note: If `bb!` commands don't respond, ensure 'Message Content Intent' is enabled in the Discord Developer Portal, or simply use `/` slash commands).* "
        ),
        inline=False,
    )

    embed.add_field(
        name="💵 Multi-Currency Economy",
        value=(
            "• 💵 **Cash** — Primary currency used for player transfers, store items, and club prize payouts.\n"
            "• ⭐ **Community Points (CP)** — Earned through server activities, competitions, and matches.\n"
            "• 🎟️ **Training Tokens** — Specialized currency for player development drills and club training.\n"
            "• **Commands:** `/balance [user]` | `bb!bal`, `/pay <user> <currency> <amount>` | `bb!pay`, `/transactions` | `bb!txs`."
        ),
        inline=False,
    )

    embed.add_field(
        name="🏟️ 100% Free Clubs & Role-Linked Treasuries",
        value=(
            "• **Free Club Registration:** Register your team with `/club create <name> <tag> <role: @role>` (or `bb!club create`). Zero creation fee!\n"
            "• **Role Mentions Everywhere:** Mention your club's role (`@Role`) directly in all commands (`/club info [@role]`, `/club deposit`, `/club withdraw`, `/clubhistory [@role]`).\n"
            "• **Secure Vaults:** Clubs hold dedicated vaults to finance operations and sign new star players."
        ),
        inline=False,
    )

    embed.add_field(
        name="💸 Official Player Transfer Market",
        value=(
            "• **Official Transfer:** `/transfer <player> <from_club: @role> <to_club: @role> <amount>`\n"
            "• **Prefix Transfer:** `bb!transfer <player> <@from_role> <@to_role> <amount>`\n"
            "• **Automated Vault Settlement:** Automatically debits the buying club's vault and deposits into the selling club's vault!\n"
            "• **Number Formats:** Supports standard (`5000000`), human notation (`30m`, `500k`), and scientific (`26e6`, `3e7`, or `0` for free transfers).\n"
            "• **Attribute Preservation:** Position, jersey number, overall rating (OVR), potential (POT), and alternate positions are 100% preserved!"
        ),
        inline=False,
    )

    embed.add_field(
        name="⚽ Squad Lineups, Formations & Player Management",
        value=(
            "• **Tactical Pitch Lineup:** `/lineup [club: @role]` displays tactical pitch layout (🧤 GK, 🛡️ DEF, ⚙️ MID, ⚡ ATT) with `[OVR]` rating tags + Substitutes Bench!\n"
            f"• **{len(SUPPORTED_FORMATIONS)} Supported Formations:** `/formation set <form>`. Browse with `/formation list`.\n"
            "  **3-Back:** `3-1-4-2`, `3-2-4-1`, `3-4-1-2`, `3-4-2-1`, `3-4-3 Diamond/Flat`, `3-5-1-1`, `3-5-2`\n"
            "  **4-Back:** `4-1-2-1-2 Narrow/Wide`, `4-1-3-2`, `4-1-3-2 Attacking`, `4-1-4-1`, `4-2-1-3`, `4-2-2-2`, `4-2-3-1 Narrow/Wide`, `4-2-4`, `4-3-1-2`, `4-3-2-1`, `4-3-3 Attack/Balanced/Defend/False 9/Flat/Holding`, `4-4-1-1 Attack/Midfield`, `4-4-2 Flat/Holding`, `4-5-1 Attack/Flat`\n"
            "  **5-Back:** `5-2-1-2`, `5-2-3`, `5-3-2`, `5-4-1 Diamond/Flat`\n"
            "• **Player Creation:** `/player add` | `bb!addplayer` registers custom or Discord players with:\n"
            "  - Primary Position (`GK`, `CB`, `LB`, `RB`, `CDM`, `CM`, `CAM`, `LW`, `RW`, `ST`, etc.)\n"
            "  - Overall Rating (`1–99 OVR`, default 75)\n"
            "  - Growth Potential (`1–99 POT`, default 80)\n"
            "  - Alternate Positions: Comma-separated list `\"pos1, pos2, pos3, .....\"` (e.g. `\"LW, RW, CAM\"`)\n"
            "  - Lineup Status: `starting` (enforces max 11 starters) or `bench`\n"
            "• **Player Editing:** `/player edit` | `bb!editplayer <player> <field> <value>` (edit `rating`, `potential`, `alt`, `pos`, `number`, `status`).\n"
            "• **Tactical Swaps:** `/player swap <p1> <p2>` | `bb!swap` (tactical substitution starter ⇄ bench or pitch position switch starter ⇄ starter)."
        ),
        inline=False,
    )

    embed.add_field(
        name="🛒 BeastlyBank Store & Stash",
        value=(
            "• Browse custom roles, VIP perks, and server boosts with `/shop` or `bb!shop`.\n"
            "• Purchase items with `/buy <item_id> [quantity]` or `bb!buy`.\n"
            "• Inspect your collected inventory with `/inventory` or `bb!inv`."
        ),
        inline=False,
    )

    embed.add_field(
        name="📖 Interactive Help & Summary Menu",
        value=(
            "• Run `/help` or `bb!help` anytime to open the interactive 5-tab menu (**Overview**, **Squad & Lineup**, **Cheatsheet**, **Finances**, **Stats**)!\n"
            "• Jump directly to any section: `/help category:squad`, `/help category:cheatsheet` (or `bb!help squad`).\n"
            "• Check your personal profile card with `/summary` or `bb!summary`."
        ),
        inline=False,
    )

    embed.set_footer(text="Official Announcement • BeastlyBank System • BeastlyFC")
    return embed

