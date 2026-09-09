"""
BeastlyFC Player & League Stats Cog
Leaderboards for Goals, Assists, Match Ratings, Clean Sheets, and Comprehensive Player Profiles.
"""

import logging
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    COLOR_BEASTLY_GOLD,
    create_beastly_embed,
    error_embed,
)

logger = logging.getLogger("BeastlyBank.Stats")


class Stats(commands.GroupCog, name="stats", description="BeastlyFC Tournament Player Stats & Leaderboards"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="topscorers", description="View the Golden Boot top goalscorers leaderboard.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
        limit="Number of players to show (default: 10, max: 25)",
    )
    async def stats_topscorers(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
        limit: int = 10,
    ):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        if season is not None:
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season)
        else:
            t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())

        if not t:
            target_str = f"Season {season}" if season else f"active `{competition}`"
            await interaction.followup.send(embed=error_embed("No Tournament", f"No {target_str} tournament found."), ephemeral=True)
            return

        players = await self.db.get_tournament_leaderboard(t["id"], category="goals", limit=min(25, max(1, limit)))
        if not players:
            await interaction.followup.send(embed=error_embed("No Stats", "No goal records found yet for this tournament."), ephemeral=True)
            return

        lines = ["`Rank  Player                   Club               Goals`"]
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = (p["player_name"][:22]).ljust(22)
            c_name = (p["team_name"][:16]).ljust(16)
            g = str(p["goals"]).rjust(3)
            lines.append(f"{medal} `{p_name} {c_name}` **{g}** ⚽")

        embed = create_beastly_embed(
            title=f"👟 Golden Boot • {t['name']}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="assists", description="View the Golden Playmaker top assists leaderboard.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
        limit="Number of players to show (default: 10, max: 25)",
    )
    async def stats_assists(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
        limit: int = 10,
    ):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        if season is not None:
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season)
        else:
            t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())

        if not t:
            target_str = f"Season {season}" if season else f"active `{competition}`"
            await interaction.followup.send(embed=error_embed("No Tournament", f"No {target_str} tournament found."), ephemeral=True)
            return

        players = await self.db.get_tournament_leaderboard(t["id"], category="assists", limit=min(25, max(1, limit)))
        if not players:
            await interaction.followup.send(embed=error_embed("No Stats", "No assist records found yet for this tournament."), ephemeral=True)
            return

        lines = ["`Rank  Player                   Club               Assists`"]
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = (p["player_name"][:22]).ljust(22)
            c_name = (p["team_name"][:16]).ljust(16)
            a = str(p["assists"]).rjust(3)
            lines.append(f"{medal} `{p_name} {c_name}` **{a}** 🎯")

        embed = create_beastly_embed(
            title=f"🎯 Golden Playmaker • {t['name']}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="ratings", description="View the Player of the Season MVP ratings leaderboard.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
        limit="Number of players to show (default: 10, max: 25)",
    )
    async def stats_ratings(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
        limit: int = 10,
    ):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        if season is not None:
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season)
        else:
            t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())

        if not t:
            target_str = f"Season {season}" if season else f"active `{competition}`"
            await interaction.followup.send(embed=error_embed("No Tournament", f"No {target_str} tournament found."), ephemeral=True)
            return

        players = await self.db.get_tournament_leaderboard(t["id"], category="rating", limit=min(25, max(1, limit)))
        if not players:
            await interaction.followup.send(embed=error_embed("No Stats", "No rating records found yet for this tournament."), ephemeral=True)
            return

        lines = ["`Rank  Player                   Club               Rating`"]
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = (p["player_name"][:22]).ljust(22)
            c_name = (p["team_name"][:16]).ljust(16)
            rt = f"{p['rating']:.2f}"
            lines.append(f"{medal} `{p_name} {c_name}` ⭐ **{rt}**")

        embed = create_beastly_embed(
            title=f"⭐ Player of the Season (MVP) • {t['name']}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="cleansheets", description="View the Golden Glove clean sheets leaderboard.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
    )
    async def stats_cleansheets(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
    ):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        if season is not None:
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season)
        else:
            t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())

        if not t:
            target_str = f"Season {season}" if season else f"active `{competition}`"
            await interaction.followup.send(embed=error_embed("No Tournament", f"No {target_str} tournament found."), ephemeral=True)
            return

        standings = await self.db.get_tournament_standings(t["id"])
        sorted_by_cs = sorted(standings, key=lambda s: s["clean_sheets"], reverse=True)[:10]

        lines = ["`Rank  Club                      Matches  Clean Sheets`"]
        for r, s in enumerate(sorted_by_cs, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            c_name = (s["name"][:24]).ljust(24)
            p = str(s["played"]).rjust(3)
            cs = str(s["clean_sheets"]).rjust(3)
            lines.append(f"{medal} `{c_name} {p}` 🧤 **{cs}**")

        embed = create_beastly_embed(
            title=f"🧤 Golden Glove Clean Sheets • {t['name']}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="player", description="Inspect complete performance stats, minutes, and rating for a player.")
    @app_commands.describe(
        name="Player name to search",
        season="Specific season number (optional, default: all-time career)",
    )
    async def stats_player(self, interaction: discord.Interaction, name: str, season: Optional[int] = None):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        profile = await self.db.get_player_profile(interaction.guild_id, name, season_number=season)
        if not profile:
            season_str = f" in Season {season}" if season else ""
            await interaction.followup.send(
                embed=error_embed("Player Not Found", f"No tournament match records found for player `{name}`{season_str}."),
                ephemeral=True,
            )
            return

        p_name = profile["player_name"]
        t_name = profile["team_name"]
        matches = profile["total_matches"] or 0
        mins = profile["total_minutes"] or (matches * 90)
        goals = profile["total_goals"] or 0
        assists = profile["total_assists"] or 0
        cs = profile["total_clean_sheets"] or 0
        yellows = profile["total_yellow_cards"] or 0
        reds = profile["total_red_cards"] or 0
        own_goals = profile["total_own_goals"] or 0
        avg_rating = profile["avg_rating"] or 6.50

        title_suffix = f"Season {season}" if season else "Career All-Time"
        lines = [
            f"**Club**: {t_name}",
            f"**Appearances**: {matches} Matches (`{mins:,}` Minutes)",
            f"**Average Match Rating**: ⭐ **{avg_rating:.2f} AVG**\n",
            f"• ⚽ **Goals**: **{goals}**",
            f"• 🎯 **Assists**: **{assists}**",
            f"• 🧤 **Clean Sheets**: **{cs}**",
            f"• 🟨 **Yellow Cards**: **{yellows}**",
            f"• 🟥 **Red Cards**: **{reds}**",
        ]
        if own_goals > 0:
            lines.append(f"• 🤦 **Own Goals**: **{own_goals}**")

        if "seasons" in profile and len(profile["seasons"]) > 1:
            lines.append("\n**Season-by-Season Breakdown**:")
            for s_rec in profile["seasons"]:
                lines.append(f"• **S{s_rec['season_number']}** ({s_rec['team_name']}): **{s_rec['goals']}G** / **{s_rec['assists']}A** (⭐ {s_rec['rating']:.2f})")

        embed = create_beastly_embed(
            title=f"⭐ Player Profile • {p_name} ({title_suffix})",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
