"""
SoFIFA Cog: FC 26 Sep 19, 2025 Database integration.
Provides player lookups with instant Discord keystroke autocomplete,
displaying photo, OVR, positions, age, market value, weekly wages, and direct links.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
import discord
from discord import app_commands
from discord.ext import commands, tasks

from utils.checks import is_banker_or_admin
from utils.embeds import error_embed, send_msg
from utils.sofifa import fetch_sofifa_players, sofifa_player_embed

logger = logging.getLogger("BeastlyBank.SoFIFA")


class SoFIFAView(discord.ui.View):
    """Interactive action row providing direct link to the player on SoFIFA."""

    def __init__(self, url: str):
        super().__init__(timeout=None)
        self.add_item(
            discord.ui.Button(
                label="View on SoFIFA",
                url=url,
                emoji="🌐",
                style=discord.ButtonStyle.link,
            )
        )


async def sofifa_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """
    Live Discord keystroke autocomplete matching FC 26 players.
    Searches local SQLite cache (<5ms response time).
    If few matches are found and user typed >=3 characters, performs quick background fetch.
    """
    clean = current.strip()
    db = interaction.client.db  # type: ignore

    # Fast cache search
    results = await db.search_cached_sofifa_players(clean, limit=25)

    # If no results found in cache and user typed >= 3 chars, attempt live fetch with strict 1.2s timeout
    if not results and len(clean) >= 3:
        try:
            fetched = await asyncio.wait_for(
                fetch_sofifa_players(keyword=clean, timeout=2),
                timeout=1.2,
            )
            if fetched:
                await db.cache_sofifa_players(fetched)
                results = await db.search_cached_sofifa_players(clean, limit=25)
        except Exception:
            pass

    choices: List[app_commands.Choice[str]] = []
    for p in results:
        label = f"{p['name']} ({p['overall_rating']} {p['primary_pos']}) • {p['team']}"
        if len(label) > 100:
            label = label[:97] + "..."
        # Value passed to command handler
        choices.append(app_commands.Choice(name=label, value=str(p["id"])))

    return choices[:25]


class SoFIFACog(commands.Cog, name="SoFIFA FC 26"):
    """Search official EA Sports FC 26 player database (Sep 19, 2025 update)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.seed_top_players.start()

    def cog_unload(self):
        self.seed_top_players.cancel()

    @property
    def db(self):
        return self.bot.db  # type: ignore

    # ------------------ Background Top Players Seeder ------------------ #

    @tasks.loop(count=1)
    async def seed_top_players(self):
        """Pre-seed top players on startup so autocomplete is populated immediately."""
        await self.bot.wait_until_ready()
        try:
            cnt = await self.db.get_cached_sofifa_player_count()
            if cnt < 200:
                logger.info("Pre-seeding top SoFIFA FC 26 players (current count: %d)...", cnt)
                for offset in (0, 60, 120, 180):
                    players = await fetch_sofifa_players(offset=offset, timeout=10)
                    if players:
                        await self.db.cache_sofifa_players(players)
                        logger.info("Cached %d players from offset %d", len(players), offset)
                    await asyncio.sleep(1)
                final_cnt = await self.db.get_cached_sofifa_player_count()
                logger.info("SoFIFA pre-seeding complete! Total cached: %d", final_cnt)
        except Exception as e:
            logger.warning("Error pre-seeding SoFIFA players: %s", e)

    @seed_top_players.before_loop
    async def before_seed(self):
        await self.bot.wait_until_ready()

    # ------------------ Common Lookup Handler ------------------ #

    async def _lookup_and_send(
        self,
        target: discord.Interaction | commands.Context,
        query: str,
    ):
        """Resolve player from ID, name, or live scraper and send player card."""
        clean = query.strip()
        if not clean:
            await send_msg(
                target,
                embed=error_embed("Missing Player", "Please provide a player name or choose from autocomplete!"),
                ephemeral=True,
            )
            return

        is_interaction = isinstance(target, discord.Interaction)
        if is_interaction and not target.response.is_done():
            await target.response.defer()

        player_data: Optional[Dict[str, Any]] = None

        # Check by numeric ID first (sent by autocomplete selection)
        if clean.isdigit():
            player_data = await self.db.get_cached_sofifa_player(clean)
        elif ":" in clean and clean.split(":")[0].isdigit():
            player_data = await self.db.get_cached_sofifa_player(clean.split(":")[0])

        # If not found by ID, search cache by name
        if not player_data:
            player_data = await self.db.get_cached_sofifa_player(clean)

        # If still not found, fetch live from SoFIFA
        if not player_data:
            results = await fetch_sofifa_players(keyword=clean, timeout=8)
            if results:
                await self.db.cache_sofifa_players(results)
                clean_lower = clean.lower()
                for r in results:
                    if clean_lower in r["name"].lower() or clean_lower in r["full_name"].lower():
                        player_data = r
                        break
                if not player_data:
                    player_data = results[0]

        if not player_data:
            await send_msg(
                target,
                embed=error_embed(
                    "Player Not Found",
                    f"No player found matching **{clean}** in the SoFIFA Sep 19, 2025 FC 26 database.",
                ),
                ephemeral=True,
            )
            return

        embed = sofifa_player_embed(player_data)
        url = player_data.get("url") or f"https://sofifa.com/player/{player_data.get('id', '')}"
        view = SoFIFAView(url)
        await send_msg(target, embed=embed, view=view)

    # ------------------ Slash Command ------------------ #

    @app_commands.command(
        name="sofifa",
        description="Search any player from the official SoFIFA Sep 19, 2025 FC 26 database.",
    )
    @app_commands.describe(player="Type player name (autocomplete will suggest matches as you type)")
    @app_commands.autocomplete(player=sofifa_autocomplete)
    async def sofifa_slash(self, interaction: discord.Interaction, player: str):
        """Slash command for player search."""
        await self._lookup_and_send(interaction, player)

    # ------------------ Prefix Command ------------------ #

    @commands.command(name="sofifa", aliases=["player", "fut", "fc26"])
    async def sofifa_prefix(self, ctx: commands.Context, *, player: str):
        """Prefix command for player search: `bb!sofifa <player_name>`."""
        await self._lookup_and_send(ctx, player)

    # ------------------ Banker Pre-seeding Command ------------------ #

    @commands.command(name="sofifaseed")
    async def sofifaseed(self, ctx: commands.Context, pages: int = 5):
        """Banker command to populate/update the local cache from SoFIFA (Sep 19, 2025)."""
        if not is_banker_or_admin(ctx.author):
            await ctx.send(embed=error_embed("Permission Denied", "Only BeastlyBank bankers or admins can run this command."))
            return

        pages = max(1, min(pages, 10))
        status_msg = await ctx.send(f"⏳ Pre-seeding SoFIFA cache with {pages} pages of top FC 26 players...")
        total_added = 0
        for i in range(pages):
            offset = i * 60
            batch = await fetch_sofifa_players(offset=offset, timeout=10)
            if batch:
                added = await self.db.cache_sofifa_players(batch)
                total_added += added
            await asyncio.sleep(0.5)

        total_count = await self.db.get_cached_sofifa_player_count()
        await status_msg.edit(
            content=f"✅ **SoFIFA Cache Seeded!**\n"
            f"• Newly cached/updated: **{total_added}** players\n"
            f"• Total database size: **{total_count:,}** players\n"
            f"• Roster Version: **Sep 19, 2025 (r=260004)**"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SoFIFACog(bot))
