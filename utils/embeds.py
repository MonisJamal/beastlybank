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
        embed.add_field(
            name="🏟️ BeastlyFC Club",
            value=f"**[{club['tag']}] {club['name']}**\nRole: `{role_label}`",
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
