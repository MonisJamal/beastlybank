"""
Auction Cog: Live BeastlyFC Transfer Market Auction House.
Features interactive quick-bid buttons, automated treasury/personal escrow,
instant outbid refunds, SoFIFA autocomplete, and background auto-settlement.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import (
    COLOR_BEASTLY_GOLD,
    COLOR_ERROR,
    COLOR_PITCH_GREEN,
    COLOR_SUCCESS,
    parse_amount,
)
from utils.checks import is_banker_or_admin, require_beastlyfc
from utils.embeds import (
    create_beastly_embed,
    error_embed,
    send_msg,
    success_embed,
)

logger = logging.getLogger("BeastlyBank.Auction")


def calculate_auction_increments(max_inc: int) -> List[int]:
    """
    Calculate up to 5 increment options up to max_inc.
    - If max_inc <= 5: [1, 2, 3, 4, 5][:max_inc]
    - If max_inc is 10 (or 10M): [+2, +4, +6, +8, +10] (skipping one number)
    - If divisible by 5: 5 steps of (max_inc // 5)
    - Otherwise evenly spaced up to 5 distinct integer values ending at max_inc.
    """
    if max_inc <= 0:
        return [1]
    if max_inc <= 5:
        return list(range(1, max_inc + 1))
    if max_inc % 5 == 0:
        step = max_inc // 5
        return [step * i for i in range(1, 6)]
    steps = sorted(list(set(max(1, int(round(max_inc * i / 5))) for i in range(1, 6))))
    if steps[-1] != max_inc:
        steps[-1] = max_inc
    return steps


def format_increment_label(amt: int) -> str:
    """Format an increment integer as a clean button label like +1M, +2M, +500K."""
    if amt >= 1_000_000:
        if amt % 1_000_000 == 0:
            return f"+{amt // 1_000_000}M"
        return f"+{amt / 1_000_000:.1f}M"
    if amt >= 1_000:
        if amt % 1_000 == 0:
            return f"+{amt // 1_000}K"
        return f"+{amt / 1_000:.1f}K"
    return f"+{amt:,}"


def parse_bid_amount_or_increment(val: str, reference_amount: int = 0) -> Optional[int]:
    """
    Parse a bid amount or increment.
    If reference_amount >= 100_000 and user inputs a small integer <= 100,
    interpret it as millions (e.g., '5' -> 5,000,000, '10' -> 10,000,000).
    """
    clean = str(val).strip().lower()
    parsed = parse_amount(clean)
    if parsed is not None:
        if reference_amount >= 100_000 and parsed <= 100 and not (clean.endswith("k") or clean.endswith("m") or clean.endswith("b")):
            return parsed * 1_000_000
        return parsed
    return None


def parse_time_duration(val: Optional[str]) -> Optional[int]:
    """Parse time string like 5m, 10m, 1h, 24h into total seconds."""
    if not val:
        return None
    s = str(val).strip().lower()
    try:
        if s.endswith("m"):
            return int(float(s[:-1]) * 60)
        elif s.endswith("h"):
            return int(float(s[:-1]) * 3600)
        elif s.endswith("d"):
            return int(float(s[:-1]) * 86400)
        elif s.endswith("s"):
            return int(float(s[:-1]))
        return int(float(s))
    except (ValueError, TypeError):
        return None


def auction_embed(auction: Dict[str, Any], seller_club: Optional[Dict[str, Any]] = None) -> discord.Embed:
    """Generate a broadcast-tier Discord Embed for a market auction."""
    status = auction.get("status", "active")
    p_name = auction["player_name"]
    ovr = auction["ovr"]
    pot = auction["potential"]
    pos = auction.get("position", "ST")
    current_bid = auction["current_bid"]
    starting_bid = auction["starting_bid"]
    max_inc = auction["max_increment"]

    if status == "active":
        title = f"🔨 LIVE MARKET AUCTION • {p_name}"
        desc = (
            f"Official **BeastlyFC Transfer Market Auction** is active!\n"
            f"Use the quick-bid buttons below to place a bid. Highest bid when time expires wins the player!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        color = COLOR_BEASTLY_GOLD
    elif status == "completed":
        title = f"🏆 AUCTION COMPLETED • SOLD! • {p_name}"
        winner_id = auction.get("highest_bidder_id")
        desc = (
            f"**AUCTION FINALIZED!**\n"
            f"Player **{p_name}** has officially been transferred to <@{winner_id}> for **{current_bid:,} Cash**!\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        color = COLOR_SUCCESS
    elif status == "cancelled":
        title = f"🛑 AUCTION CANCELLED • {p_name}"
        desc = f"This auction was cancelled by the seller/administrator. All escrowed funds were refunded.\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        color = COLOR_ERROR
    else:  # expired
        title = f"⌛ AUCTION EXPIRED • {p_name}"
        desc = f"This auction closed with no valid bids placed.\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        color = 0x78909C

    embed = create_beastly_embed(
        title=title,
        description=desc,
        color=color,
    )

    if auction.get("photo_url"):
        embed.set_thumbnail(url=auction["photo_url"])

    embed.add_field(
        name="🏃 Player",
        value=f"**{p_name}**\n`{ovr} OVR` • `{pot} POT` • `{pos}`",
        inline=True,
    )

    if current_bid > 0:
        high_bidder = f"<@{auction['highest_bidder_id']}>"
        embed.add_field(
            name="💵 Current High Bid",
            value=f"**{current_bid:,} Cash**\nHeld by: {high_bidder}",
            inline=True,
        )
    else:
        embed.add_field(
            name="💵 Starting Base Price",
            value=f"**{starting_bid:,} Cash**\n*(No bids placed yet)*",
            inline=True,
        )

    increments = calculate_auction_increments(max_inc)
    inc_labels = [format_increment_label(i) for i in increments]
    embed.add_field(
        name="📈 Quick-Bid Raises",
        value=f"`{'` `'.join(inc_labels)}`",
        inline=True,
    )

    # Expiration details
    exp_dt = datetime.fromisoformat(auction["expires_at"])
    if exp_dt.tzinfo is None:
        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
    exp_ts = int(exp_dt.timestamp())

    time_val = f"<t:{exp_ts}:R> (<t:{exp_ts}:T>)"
    if auction.get("idle_timeout_seconds") and status == "active":
        idle_mins = auction["idle_timeout_seconds"] // 60
        last_dt = datetime.fromisoformat(auction["last_bid_at"])
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        idle_exp_ts = int((last_dt + timedelta(seconds=auction["idle_timeout_seconds"])).timestamp())
        time_val += f"\n*Inactivity Timeout:* <t:{idle_exp_ts}:R> (if no new bids for {idle_mins}m)"

    embed.add_field(
        name="⏱️ Expiration",
        value=time_val,
        inline=False,
    )

    # Seller information
    seller_tag = f"[{seller_club['tag']}] {seller_club['name']}" if seller_club else "Open Market"
    embed.add_field(
        name="👤 Seller",
        value=f"<@{auction['seller_id']}> • {seller_tag}",
        inline=True,
    )

    embed.set_footer(text=f"BeastlyFC Market Auction • ID #{auction['id']} • Escrow Guaranteed")
    return embed


class AuctionBidButton(discord.ui.Button):
    """Button to place a specific increment bid."""

    def __init__(self, increment: int, label: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.success,
            custom_id=f"auc_bid:{increment}",
        )
        self.increment = increment

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        cog: Auction = interaction.client.get_cog("Auction")  # type: ignore
        if not cog:
            await interaction.followup.send("Auction system unavailable.", ephemeral=True)
            return

        auction_view: MarketAuctionView = self.view  # type: ignore
        auction_id = auction_view.auction_id

        success, msg, updated_auction, outbid_info = await interaction.client.db.place_auction_bid(  # type: ignore
            auction_id=auction_id,
            bidder_id=interaction.user.id,
            increment=self.increment,
            guild_id=interaction.guild_id,
        )

        if not success:
            await interaction.followup.send(
                embed=error_embed("Bid Rejected", msg),
                ephemeral=True,
            )
            return

        # Refresh message embed
        seller_club = None
        if updated_auction.get("seller_club_id"):
            conn = await interaction.client.db.connect()  # type: ignore
            async with conn.cursor() as cur:
                await cur.execute("SELECT * FROM clubs WHERE id = ?;", (updated_auction["seller_club_id"],))
                r = await cur.fetchone()
                if r:
                    seller_club = dict(r)

        new_embed = auction_embed(updated_auction, seller_club=seller_club)
        try:
            await interaction.message.edit(embed=new_embed, view=auction_view)
        except Exception as e:
            logger.warning("Failed to edit auction message: %s", e)

        await interaction.followup.send(
            embed=success_embed(
                "Bid Accepted!",
                f"You successfully placed a bid of **{format_increment_label(self.increment)}**!\n"
                f"• Current high bid: **{updated_auction['current_bid']:,} Cash**\n"
                f"• Escrow deducted from: **{updated_auction.get('escrow_source', 'treasury').capitalize()}**",
            ),
            ephemeral=True,
        )

        # Notify outbid user
        if outbid_info and interaction.channel:
            src_desc = "Club Treasury" if outbid_info["source"] == "treasury" else "Personal Balance"
            try:
                await interaction.channel.send(
                    f"🔔 <@{outbid_info['user_id']}>, you have been outbid on **{updated_auction['player_name']}**! "
                    f"Your escrowed bid of **{outbid_info['amount']:,} Cash** has been refunded to your **{src_desc}**."
                )
            except Exception:
                pass


class AuctionHistoryButton(discord.ui.Button):
    """Button to view recent bids."""

    def __init__(self):
        super().__init__(
            label="Bid History",
            emoji="📜",
            style=discord.ButtonStyle.secondary,
            custom_id="auc_hist",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        auction_view: MarketAuctionView = self.view  # type: ignore
        db = interaction.client.db  # type: ignore
        bids = await db.get_auction_bids(auction_view.auction_id, limit=10)

        if not bids:
            await interaction.response.send_message(
                embed=create_beastly_embed(
                    title="📜 Bid History",
                    description="No bids have been placed on this auction yet.",
                    color=COLOR_BEASTLY_GOLD,
                ),
                ephemeral=True,
            )
            return

        lines = []
        for i, b in enumerate(bids, 1):
            amt = b["bid_amount"]
            inc = b["increment"]
            bidder = f"<@{b['bidder_id']}>"
            src = b.get("escrow_source", "treasury").capitalize()
            dt = datetime.fromisoformat(b["created_at"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            ts = int(dt.timestamp())
            lines.append(f"**#{i}** • **{amt:,} Cash** (+{format_increment_label(inc)}) by {bidder} ({src}) • <t:{ts}:R>")

        embed = create_beastly_embed(
            title=f"📜 Bid History • Auction #{auction_view.auction_id}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class AuctionCancelButton(discord.ui.Button):
    """Button to cancel the auction (seller or admin)."""

    def __init__(self):
        super().__init__(
            label="Cancel Auction",
            emoji="❌",
            style=discord.ButtonStyle.danger,
            custom_id="auc_cancel",
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        auction_view: MarketAuctionView = self.view  # type: ignore
        auction_id = auction_view.auction_id
        db = interaction.client.db  # type: ignore
        auction = await db.get_auction(auction_id)

        if not auction:
            await interaction.response.send_message("Auction not found.", ephemeral=True)
            return

        is_admin = is_banker_or_admin(interaction.user)
        if not is_admin and interaction.user.id != auction["seller_id"]:
            await interaction.response.send_message(
                embed=error_embed("Permission Denied", "Only the seller or an administrator can cancel this auction."),
                ephemeral=True,
            )
            return

        success, msg, updated_auction = await db.cancel_market_auction(
            auction_id=auction_id,
            caller_id=interaction.user.id,
            is_admin=is_admin,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Cannot Cancel", msg), ephemeral=True)
            return

        # Disable all buttons
        for child in auction_view.children:
            child.disabled = True

        cancelled_embed = auction_embed(updated_auction)
        try:
            await interaction.message.edit(embed=cancelled_embed, view=auction_view)
        except Exception:
            pass

        await interaction.response.send_message(
            embed=success_embed("Auction Cancelled", f"Auction #{auction_id} for **{auction['player_name']}** was cancelled."),
            ephemeral=True,
        )


class MarketAuctionView(discord.ui.View):
    """Dynamic interactive view for live player auctions."""

    def __init__(self, auction_id: int, max_increment: int, is_active: bool = True):
        super().__init__(timeout=None)
        self.auction_id = auction_id
        self.max_increment = max_increment

        increments = calculate_auction_increments(max_increment)
        for inc in increments:
            btn = AuctionBidButton(increment=inc, label=format_increment_label(inc))
            btn.disabled = not is_active
            self.add_item(btn)

        hist_btn = AuctionHistoryButton()
        cancel_btn = AuctionCancelButton()
        cancel_btn.disabled = not is_active
        self.add_item(hist_btn)
        self.add_item(cancel_btn)


class Auction(commands.GroupCog, name="auction", description="Manage BeastlyFC Market Auctions"):
    """BeastlyFC Transfer Market Live Auction House."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore
        self.watcher_task.start()

    def cog_unload(self):
        self.watcher_task.cancel()

    @tasks.loop(seconds=15)
    async def watcher_task(self):
        """Background loop checking for expired auctions and settling them."""
        await self.bot.wait_until_ready()
        try:
            active_auctions = await self.db.get_all_active_auctions()
            now = datetime.now(timezone.utc)
            for auc in active_auctions:
                exp_dt = datetime.fromisoformat(auc["expires_at"])
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)

                is_expired = now >= exp_dt
                if not is_expired and auc.get("idle_timeout_seconds"):
                    last_dt = datetime.fromisoformat(auc["last_bid_at"])
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if (now - last_dt).total_seconds() >= auc["idle_timeout_seconds"]:
                        is_expired = True

                if is_expired:
                    logger.info("Settling expired auction ID #%s (%s)", auc["id"], auc["player_name"])
                    success, msg, settled_auc = await self.db.settle_auction(auc["id"])
                    if not success:
                        continue

                    # Update Discord message
                    channel = self.bot.get_channel(auc["channel_id"])
                    if channel and auc.get("message_id"):
                        try:
                            msg_obj = await channel.fetch_message(auc["message_id"])
                            view = MarketAuctionView(auc["id"], auc["max_increment"], is_active=False)
                            for item in view.children:
                                item.disabled = True
                            final_embed = auction_embed(settled_auc)
                            await msg_obj.edit(embed=final_embed, view=view)

                            if settled_auc.get("highest_bidder_id") and settled_auc["current_bid"] > 0:
                                await channel.send(
                                    f"🎉 **AUCTION CONCLUDED!** **{auc['player_name']}** has been sold to "
                                    f"<@{settled_auc['highest_bidder_id']}> for **{settled_auc['current_bid']:,} Cash**! "
                                    f"The player has been transferred directly into their club squad!"
                                )
                        except Exception as e:
                            logger.warning("Failed to update settled auction message: %s", e)
        except Exception as e:
            logger.error("Error in auction watcher task: %s", e, exc_info=True)

    @app_commands.command(
        name="create",
        description="Launch a live market auction for a football player with quick-bid raise buttons.",
    )
    @app_commands.describe(
        player="Name of the player to auction",
        starting_bid="Starting base price (e.g. 50m, 10000000)",
        max_increment="Max increment per bid (e.g. 5m for [+1M]..[+5M], or 10m for [+2M]..[+10M])",
        ovr="Overall rating (1-99, optional - auto-filled from SoFIFA/squad)",
        potential="Potential rating (1-99, optional - auto-filled from SoFIFA/squad)",
        duration="Total auction duration (e.g. 15m, 30m, 1h, 6h, 12h, 24h, default: 1h)",
        idle_timeout="Close if no one bids for this long (e.g. 5m, 10m, 15m)",
        position="Primary position (e.g. ST, CM, CB, RW)",
        club="Selling club role mention (optional, defaults to your club)",
    )
    @require_beastlyfc()
    async def auction_create(
        self,
        interaction: discord.Interaction,
        player: str,
        starting_bid: str,
        max_increment: str,
        ovr: Optional[int] = None,
        potential: Optional[int] = None,
        duration: Optional[str] = "1h",
        idle_timeout: Optional[str] = None,
        position: Optional[str] = None,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()

        parsed_start = parse_amount(starting_bid)
        if parsed_start is None or parsed_start <= 0:
            await interaction.followup.send(
                embed=error_embed("Invalid Starting Bid", f"Invalid starting price: `{starting_bid}`. Use `50m`, `10000000`, etc."),
                ephemeral=True,
            )
            return

        parsed_inc = parse_bid_amount_or_increment(max_increment, reference_amount=parsed_start)
        if parsed_inc is None or parsed_inc <= 0:
            await interaction.followup.send(
                embed=error_embed("Invalid Max Increment", f"Invalid maximum increment: `{max_increment}`. Use `5m`, `10m`, `5`, `10`, etc."),
                ephemeral=True,
            )
            return

        # Parse duration
        duration_secs = parse_time_duration(duration) or 3600
        if duration_secs < 60 or duration_secs > 7 * 86400:
            await interaction.followup.send(
                embed=error_embed("Invalid Duration", "Duration must be between 1 minute and 7 days."),
                ephemeral=True,
            )
            return

        idle_secs = parse_time_duration(idle_timeout)
        if idle_secs and (idle_secs < 30 or idle_secs > duration_secs):
            await interaction.followup.send(
                embed=error_embed("Invalid Idle Timeout", "Idle timeout must be between 30 seconds and total auction duration."),
                ephemeral=True,
            )
            return

        # Resolve seller club
        seller_club = None
        if club:
            seller_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            seller_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        # Check if player exists in SoFIFA or squad to auto-fill OVR/POT/photo
        import re
        clean_name = re.sub(r"^custom\s*(?:player)?\s*:\s*['\"]?", "", player.strip(), flags=re.IGNORECASE).rstrip("'\"").strip()

        photo_url = None
        resolved_pos = position.upper() if position else "ST"

        # Check SoFIFA
        sofifa_data = await self.db.get_cached_sofifa_player(clean_name)
        if sofifa_data:
            if ovr is None:
                ovr = sofifa_data.get("overall_rating", 75)
            if potential is None:
                potential = sofifa_data.get("potential", 80)
            if not position and sofifa_data.get("primary_pos"):
                resolved_pos = sofifa_data["primary_pos"]
            photo_url = sofifa_data.get("avatar_url")
            clean_name = sofifa_data.get("full_name") or sofifa_data.get("name") or clean_name
        else:
            # Check if player exists in seller's squad
            if seller_club:
                conn = await self.db.connect()
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                        (seller_club["id"], clean_name),
                    )
                    row = await cur.fetchone()
                    if row:
                        if ovr is None:
                            ovr = row["rating"]
                        if potential is None:
                            potential = row["potential"]
                        if not position and row["position"]:
                            resolved_pos = row["position"]

        if ovr is None:
            ovr = 75
        if potential is None:
            potential = max(ovr, 80)

        # Calculate expires_at
        now = datetime.now(timezone.utc)
        expires_at_dt = now + timedelta(seconds=duration_secs)

        # Create auction in database
        auction = await self.db.create_market_auction(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            seller_id=interaction.user.id,
            seller_club_id=seller_club["id"] if seller_club else None,
            player_name=clean_name,
            ovr=ovr,
            potential=potential,
            starting_bid=parsed_start,
            max_increment=parsed_inc,
            expires_at=expires_at_dt.isoformat(),
            idle_timeout_seconds=idle_secs,
            position=resolved_pos,
            photo_url=photo_url,
        )

        view = MarketAuctionView(auction["id"], parsed_inc, is_active=True)
        embed = auction_embed(auction, seller_club=seller_club)

        msg = await interaction.followup.send(embed=embed, view=view)
        await self.db.set_auction_message_id(auction["id"], msg.id)

    @auction_create.autocomplete("player")
    async def auction_player_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> List[app_commands.Choice[str]]:
        """Autocomplete players from user's club squad and SoFIFA, with custom player support."""
        import re
        clean = re.sub(r"^custom\s*(?:player)?\s*:\s*['\"]?", "", current.strip(), flags=re.IGNORECASE).rstrip("'\"").strip()
        choices: List[app_commands.Choice[str]] = []
        added_names = set()

        # 1. First priority: Check user's club squad players
        try:
            user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
            if user_club:
                conn = await self.db.connect()
                async with conn.cursor() as cur:
                    if clean:
                        await cur.execute(
                            "SELECT player_name, position, rating FROM club_players WHERE club_id = ? AND LOWER(player_name) LIKE ? LIMIT 10;",
                            (user_club["id"], f"%{clean.lower()}%"),
                        )
                    else:
                        await cur.execute(
                            "SELECT player_name, position, rating FROM club_players WHERE club_id = ? LIMIT 10;",
                            (user_club["id"],),
                        )
                    squad_rows = await cur.fetchall()
                    for r in squad_rows:
                        p_name = r["player_name"]
                        lbl = f"⭐ {p_name} ({r['rating']} {r['position']}) • Your Squad"
                        choices.append(app_commands.Choice(name=lbl[:100], value=p_name))
                        added_names.add(p_name.lower())
        except Exception as e:
            logger.debug("Squad autocomplete error: %s", e)

        # 2. SoFIFA players
        if clean:
            results = await self.db.search_cached_sofifa_players(clean, limit=15)
            for p in results:
                if p["name"].lower() not in added_names:
                    label = f"{p['name']} ({p['overall_rating']} {p['primary_pos']}) • {p['team']}"
                    choices.append(app_commands.Choice(name=label[:100], value=p["name"]))
                    added_names.add(p["name"].lower())

        # 3. Custom player option
        if clean and clean.lower() not in added_names:
            choices.append(app_commands.Choice(name=f"➕ Custom: '{clean[:40]}'", value=clean))

        return choices[:25]

    @app_commands.command(name="list", description="List all currently active player auctions.")
    @require_beastlyfc()
    async def auction_list(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        active_auctions = await self.db.get_active_market_auctions(interaction.guild_id)

        if not active_auctions:
            await interaction.followup.send(
                embed=create_beastly_embed(
                    title="🔨 Active Market Auctions",
                    description="There are currently no active auctions on the transfer market.\nUse `/auction create` to list a player!",
                    color=COLOR_BEASTLY_GOLD,
                ),
                ephemeral=True,
            )
            return

        lines = []
        for a in active_auctions:
            p_name = a["player_name"]
            cur_bid = a["current_bid"]
            start_bid = a["starting_bid"]
            price_str = f"💵 **{cur_bid:,} Cash**" if cur_bid > 0 else f"Base: **{start_bid:,} Cash**"
            exp_dt = datetime.fromisoformat(a["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            ts = int(exp_dt.timestamp())
            lines.append(f"• **#{a['id']}** | **{p_name}** (`{a['ovr']} OVR` • `{a['position']}`) — {price_str} — Closes <t:{ts}:R>")

        embed = create_beastly_embed(
            title="🔨 Live Transfer Market Auctions",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="cancel", description="Cancel an active auction (Seller or Banker/Admin only).")
    @app_commands.describe(auction_id="ID number of the auction to cancel")
    @require_beastlyfc()
    async def auction_cancel(self, interaction: discord.Interaction, auction_id: int):
        await interaction.response.defer(ephemeral=True)
        is_admin = is_banker_or_admin(interaction.user)
        success, msg, updated_auction = await self.db.cancel_market_auction(
            auction_id=auction_id,
            caller_id=interaction.user.id,
            is_admin=is_admin,
        )

        if not success:
            await interaction.followup.send(embed=error_embed("Cannot Cancel", msg), ephemeral=True)
            return

        await interaction.followup.send(
            embed=success_embed("Auction Cancelled", f"Auction #{auction_id} for **{updated_auction['player_name']}** has been cancelled."),
            ephemeral=True,
        )

    # ── Prefix Commands ──

    @commands.command(name="auction", aliases=["marketauction", "auc"])
    async def prefix_auction(self, ctx: commands.Context, *args):
        """
        Create a market auction via prefix command:
        bb!auction <player> <starting_bid> <max_increment> [ovr] [potential] [duration] [idle_timeout]
        e.g. bb!auction Mbappe 50m 5m 91 94 1h 10m
        """
        if len(args) < 3:
            embed = error_embed(
                "Invalid Auction Usage",
                "**Usage:** `bb!auction <player> <starting_bid> <max_increment> [ovr] [potential] [duration] [idle_timeout]`\n"
                "**Example:** `bb!auction Mbappe 50m 5m 91 94 1h 10m`",
            )
            await ctx.send(embed=embed)
            return

        player = args[0]
        start_str = args[1]
        inc_str = args[2]

        parsed_start = parse_amount(start_str)
        if not parsed_start or parsed_start <= 0:
            await ctx.send(embed=error_embed("Invalid Starting Bid", f"Invalid starting price: `{start_str}`"))
            return

        parsed_inc = parse_bid_amount_or_increment(inc_str, reference_amount=parsed_start)
        if not parsed_inc or parsed_inc <= 0:
            await ctx.send(embed=error_embed("Invalid Increment", f"Invalid increment: `{inc_str}`"))
            return

        clean_name = player.strip()
        if clean_name.lower().startswith("custom:"):
            clean_name = clean_name[7:].strip().strip("'\"")
        elif clean_name.lower().startswith("custom: '") and clean_name.endswith("'"):
            clean_name = clean_name[9:-1].strip()

        photo_url = None
        resolved_pos = "ST"

        ovr = int(args[3]) if len(args) > 3 and args[3].isdigit() else None
        potential = int(args[4]) if len(args) > 4 and args[4].isdigit() else None
        duration = args[5] if len(args) > 5 else "1h"
        idle_timeout = args[6] if len(args) > 6 else None

        duration_secs = parse_time_duration(duration) or 3600
        idle_secs = parse_time_duration(idle_timeout)

        seller_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        # Check SoFIFA
        sofifa_data = await self.db.get_cached_sofifa_player(clean_name)
        if sofifa_data:
            if ovr is None:
                ovr = sofifa_data.get("overall_rating", 75)
            if potential is None:
                potential = sofifa_data.get("potential", 80)
            if sofifa_data.get("primary_pos"):
                resolved_pos = sofifa_data["primary_pos"]
            photo_url = sofifa_data.get("avatar_url")
            clean_name = sofifa_data.get("full_name") or sofifa_data.get("name") or clean_name
        else:
            if seller_club:
                conn = await self.db.connect()
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                        (seller_club["id"], clean_name),
                    )
                    row = await cur.fetchone()
                    if row:
                        if ovr is None:
                            ovr = row["rating"]
                        if potential is None:
                            potential = row["potential"]
                        if row["position"]:
                            resolved_pos = row["position"]

        if ovr is None:
            ovr = 75
        if potential is None:
            potential = max(ovr, 80)

        now = datetime.now(timezone.utc)
        expires_at_dt = now + timedelta(seconds=duration_secs)

        auction = await self.db.create_market_auction(
            guild_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            seller_id=ctx.author.id,
            seller_club_id=seller_club["id"] if seller_club else None,
            player_name=clean_name,
            ovr=ovr,
            potential=potential,
            starting_bid=parsed_start,
            max_increment=parsed_inc,
            expires_at=expires_at_dt.isoformat(),
            idle_timeout_seconds=idle_secs,
            position=resolved_pos,
            photo_url=photo_url,
        )

        view = MarketAuctionView(auction["id"], parsed_inc, is_active=True)
        embed = auction_embed(auction, seller_club=seller_club)
        msg = await ctx.send(embed=embed, view=view)
        await self.db.set_auction_message_id(auction["id"], msg.id)

    @commands.command(name="auctions", aliases=["auclist"])
    async def prefix_auctions(self, ctx: commands.Context):
        """List active auctions: bb!auctions"""
        active_auctions = await self.db.get_active_market_auctions(ctx.guild.id)
        if not active_auctions:
            await ctx.send(embed=create_beastly_embed(
                title="🔨 Active Market Auctions",
                description="No active auctions on the transfer market.",
                color=COLOR_BEASTLY_GOLD,
            ))
            return

        lines = []
        for a in active_auctions:
            cur_bid = a["current_bid"]
            start_bid = a["starting_bid"]
            price_str = f"💵 **{cur_bid:,} Cash**" if cur_bid > 0 else f"Base: **{start_bid:,} Cash**"
            exp_dt = datetime.fromisoformat(a["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            ts = int(exp_dt.timestamp())
            lines.append(f"• **#{a['id']}** | **{a['player_name']}** (`{a['ovr']} OVR`) — {price_str} — Closes <t:{ts}:R>")

        embed = create_beastly_embed(
            title="🔨 Live Transfer Market Auctions",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Auction(bot))
