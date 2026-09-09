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
from utils.name_matcher import autocomplete_players_search, autocomplete_clubs_search

logger = logging.getLogger("BeastlyBank.Stats")


COMPETITION_CHOICES = [
    app_commands.Choice(name="League", value="league"),
    app_commands.Choice(name="Champions League (UCL)", value="ucl"),
    app_commands.Choice(name="Cup", value="cup"),
]


async def tournament_player_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Fast keystroke autocomplete suggesting tournament players with club names."""
    db = interaction.client.db  # type: ignore
    try:
        players = await db.get_distinct_tournament_players(interaction.guild_id)
        player_pairs = [(p["player_name"], p["team_name"]) for p in players]
        matches = autocomplete_players_search(current, player_pairs, limit=25)
        return [
            app_commands.Choice(name=f"{p} ({t})"[:100], value=p)
            for p, t in matches
        ]
    except Exception as e:
        logger.debug("Player autocomplete error: %s", e)
        return []


async def tournament_club_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> List[app_commands.Choice[str]]:
    """Keystroke autocomplete suggesting tournament clubs."""
    db = interaction.client.db  # type: ignore
    try:
        clubs = await db.get_distinct_tournament_clubs(guild_id=interaction.guild_id)
        matches = autocomplete_clubs_search(current, clubs, limit=25)
        return [
            app_commands.Choice(name=c[:100], value=c)
            for c in matches
        ]
    except Exception as e:
        logger.debug("Club autocomplete error: %s", e)
        return []


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
    @app_commands.choices(competition=COMPETITION_CHOICES)
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

        lines = []
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = p["player_name"]
            c_name = p["team_name"]
            g = p["goals"]
            m_played = p.get("matches_played", 0)
            mins = p.get("minutes_played", 0) or 0
            mins_str = f" (`{mins:,}m`)" if mins > 0 else ""
            rt = p.get("rating", 6.5)
            lines.append(f"{medal} **{p_name}** ({c_name})\n    ⚽ **{g} Goals** • **{m_played} Apps**{mins_str} • ⭐ `{rt:.2f}`")

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
    @app_commands.choices(competition=COMPETITION_CHOICES)
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

        lines = []
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = p["player_name"]
            c_name = p["team_name"]
            a = p["assists"]
            m_played = p.get("matches_played", 0)
            mins = p.get("minutes_played", 0) or 0
            mins_str = f" (`{mins:,}m`)" if mins > 0 else ""
            rt = p.get("rating", 6.5)
            lines.append(f"{medal} **{p_name}** ({c_name})\n    🎯 **{a} Assists** • **{m_played} Apps**{mins_str} • ⭐ `{rt:.2f}`")

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
    @app_commands.choices(competition=COMPETITION_CHOICES)
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

        lines = []
        for r, p in enumerate(players, 1):
            medal = "🥇" if r == 1 else "🥈" if r == 2 else "🥉" if r == 3 else f"#{r:<2}"
            p_name = p["player_name"]
            c_name = p["team_name"]
            rt = p.get("rating", 6.5)
            m_played = p.get("matches_played", 0)
            mins = p.get("minutes_played", 0) or 0
            mins_str = f" (`{mins:,}m`)" if mins > 0 else ""
            g = p.get("goals", 0)
            a = p.get("assists", 0)
            lines.append(f"{medal} **{p_name}** ({c_name})\n    ⭐ **{rt:.2f} Rating** • **{m_played} Apps**{mins_str} • {g}G / {a}A")

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
    @app_commands.choices(competition=COMPETITION_CHOICES)
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
        name="Player name to search (autocomplete suggestions as you type)",
        season="Specific season number (optional, default: all-time career)",
    )
    @app_commands.autocomplete(name=tournament_player_autocomplete)
    async def stats_player(self, interaction: discord.Interaction, name: str, season: Optional[int] = None):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        profile = await self.db.get_player_profile(interaction.guild_id, name, season_number=season)
        if not profile:
            season_str = f" in Season {season}" if season else ""
            suggestions = await self.db.get_player_name_suggestions(interaction.guild_id, name, season_number=season)

            desc = f"No tournament match records found for player **{name}**{season_str}."
            if suggestions:
                sugg_str = ", ".join(f"**{s}**" for s in suggestions)
                desc += f"\n\n💡 **Did you mean**: {sugg_str}?"
            desc += "\n\n*(Tip: Use autocomplete suggestions as you type `/stats player` or check squad rosters with `/stats club`)*"

            await interaction.followup.send(
                embed=error_embed("Player Not Found", desc),
                ephemeral=True,
            )
            return

        p_name = profile["player_name"]
        t_name = profile["team_name"]
        matches = profile["total_matches"] or 0
        mins = profile["total_minutes"] or 0
        goals = profile["total_goals"] or 0
        assists = profile["total_assists"] or 0
        cs = profile["total_clean_sheets"] or 0
        yellows = profile["total_yellow_cards"] or 0
        reds = profile["total_red_cards"] or 0
        own_goals = profile["total_own_goals"] or 0
        avg_rating = profile["avg_rating"] or 6.50

        title_suffix = f"Season {season}" if season else "Career All-Time"
        mins_per_goal = f" *({round(mins / goals)} mins/goal)*" if (goals > 0 and mins > 0) else ""
        mins_per_assist = f" *({round(mins / assists)} mins/assist)*" if (assists > 0 and mins > 0) else ""

        app_str = f"**Appearances**: **{matches} Matches**"
        if mins > 0:
            app_str += f" (`{mins:,}` Minutes Played)"

        lines = [
            f"**Club**: {t_name}",
            app_str,
            f"**Average Match Rating**: ⭐ **{avg_rating:.2f} AVG**\n",
            f"• ⚽ **Goals**: **{goals}**{mins_per_goal}",
            f"• 🎯 **Assists**: **{assists}**{mins_per_assist}",
            f"• 🧤 **Clean Sheets**: **{cs}**",
            f"• 🟨 **Yellow Cards**: **{yellows}**",
            f"• 🟥 **Red Cards**: **{reds}**",
        ]
        if own_goals > 0:
            lines.append(f"• 🤦 **Own Goals**: **{own_goals}**")

        if "seasons" in profile and len(profile["seasons"]) > 1:
            lines.append("\n**Competition & Season Breakdown**:")
            for s_rec in profile["seasons"]:
                tourn_name = s_rec.get("tournament_name") or f"Season {s_rec['season_number']}"
                s_matches = s_rec.get("matches_played", 0)
                s_mins = s_rec.get("minutes_played", 0) or 0
                s_mins_str = f" (`{s_mins:,}m`)" if s_mins > 0 else ""
                lines.append(
                    f"• **{tourn_name}** ({s_rec['team_name']}): **{s_matches} Apps**{s_mins_str} • **{s_rec['goals']}G** / **{s_rec['assists']}A** • ⭐ `{s_rec['rating']:.2f}`"
                )

        embed = create_beastly_embed(
            title=f"⭐ Player Profile • {p_name} ({title_suffix})",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="club", description="Inspect all player stats, minutes, and matches for a club in a tournament.")
    @app_commands.describe(
        club="Name of the club (e.g. Manchester City, Chelsea, PSG, Bayern)",
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    @app_commands.autocomplete(club=tournament_club_autocomplete)
    async def stats_club(
        self,
        interaction: discord.Interaction,
        club: str,
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

        players = await self.db.get_club_player_stats(t["id"], club)
        if not players:
            available_clubs = await self.db.get_distinct_tournament_clubs(tournament_id=t["id"])
            clubs_sample = ", ".join(f"**{c}**" for c in available_clubs[:6])
            desc = f"No tournament match records found for club matching `{club}` in **{t['name']}**."
            if available_clubs:
                desc += f"\n\n📋 **Available clubs in this tournament**: {clubs_sample}..."
            desc += "\n*(Tip: Use autocomplete suggestions as you type `/stats club`)*"
            await interaction.followup.send(
                embed=error_embed("No Club Records", desc),
                ephemeral=True,
            )
            return

        team_display = players[0]["team_name"]
        lines = [f"**Roster Performance in {t['name']}**\n"]
        for p in players:
            p_name = p["player_name"]
            m_played = p.get("matches_played", 0)
            mins = p.get("minutes_played", 0) or 0
            mins_str = f" (`{mins:,}m`)" if mins > 0 else ""
            g = p.get("goals", 0)
            a = p.get("assists", 0)
            cs = p.get("clean_sheets", 0)
            yc = p.get("yellow_cards", 0)
            rc = p.get("red_cards", 0)
            rt = p.get("rating", 6.5)

            card_str = f" | 🟨{yc}" if yc > 0 else ""
            if rc > 0:
                card_str += f" 🟥{rc}"
            cs_str = f" | 🧤{cs}" if cs > 0 else ""

            lines.append(
                f"• **{p_name}** — **{m_played} Apps**{mins_str} • ⚽ **{g}G** / 🎯 **{a}A**{cs_str}{card_str} • ⭐ `{rt:.2f}`"
            )

        embed = create_beastly_embed(
            title=f"📋 Squad Stats • {team_display} ({t['name']})",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
