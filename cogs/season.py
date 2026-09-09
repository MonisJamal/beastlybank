"""
BeastlyFC Season Management Cog
Manages season lifecycles, Hall of Fame archives, awards, and season rollovers.
"""

import logging
import os
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import (
    COLOR_BEASTLY_GOLD,
    create_beastly_embed,
    error_embed,
    success_embed,
)
from utils.match_parser import parse_matchsimulator_html

logger = logging.getLogger("BeastlyBank.Season")


COMPETITION_CHOICES = [
    app_commands.Choice(name="League", value="league"),
    app_commands.Choice(name="Champions League (UCL)", value="ucl"),
    app_commands.Choice(name="Cup", value="cup"),
]


class Season(commands.GroupCog, name="season", description="Manage BeastlyFC Seasons & Hall of Fame"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="start", description="Launch a new season, archive previous season awards, and reset active standings.")
    @app_commands.describe(
        name="Name for the new season (e.g. 'Season 2', 'Beastly S2 League')",
        competition="Competition type (league, ucl, cup, default: league)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def season_start(
        self,
        interaction: discord.Interaction,
        name: str,
        competition: str = "league",
    ):
        await interaction.response.defer()

        # 1. Check if previous active tournament exists and archive it
        existing = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
        archived_msg = ""
        if existing:
            ok, msg, settled = await self.db.conclude_tournament(existing["id"])
            if ok:
                archived_msg = f"📦 **{existing['name']}** concluded & archived to Hall of Fame!\n"

        # 2. Determine season number for this competition
        comp_hist = await self.db.get_season_history(interaction.guild_id, competition_name=competition.lower())
        max_s = max([r["season_number"] for r in comp_hist], default=0)
        next_season_num = max_s + 1

        # 3. Create fresh season skeleton
        parsed_data = {
            "tournament_name": name,
            "season_subtitle": f"Season {next_season_num}",
            "highest_matchday": 38,
            "champion": None,
            "runner_up": None,
            "standings": [],
            "fixtures_by_matchday": {},
            "total_fixtures": 0,
            "player_stats": {"all_players": []},
        }

        saved = await self.db.save_parsed_tournament(
            guild_id=interaction.guild_id,
            tournament_data=parsed_data,
            url=None,
            season_number=next_season_num,
            competition_type=competition.lower(),
        )

        embed = success_embed(
            f"🎉 {name} Launched!",
            f"{archived_msg}"
            f"🌱 **{saved['name']}** (Season {saved['season_number']}) is now **ACTIVE**!\n"
            f"• Competition: **{competition.upper()}**\n"
            f"• Status: **Active (Season {saved['season_number']})**\n\n"
            f"📂 *Upload your season schedule & scores anytime using `/matches import`!*\n"
            f"*Club squads and treasuries remain fully intact.*",
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="conclude", description="Manually conclude an active season and immortalize awards into the Hall of Fame.")
    @app_commands.describe(competition="Competition type (league, ucl, cup, default: league)")
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def season_conclude(self, interaction: discord.Interaction, competition: str = "league"):
        await interaction.response.defer()
        t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
        if not t:
            await interaction.followup.send(embed=error_embed("No Active Tournament", f"No active `{competition}` season to conclude."), ephemeral=True)
            return

        ok, msg, res = await self.db.conclude_tournament(t["id"])
        if not ok:
            await interaction.followup.send(embed=error_embed("Error", msg), ephemeral=True)
            return

        # Fetch archived history record
        hist = await self.db.get_season_history(interaction.guild_id, season_number=res["season_number"], competition_name=competition.lower())
        record = hist[0] if hist else {}

        lines = [
            f"# 🏆 {res['name']} Concluded!\n",
            f"🥇 **Champion**: **{record.get('champion', 'TBD')}**",
            f"🥈 **Runner-Up**: **{record.get('runner_up', 'TBD')}**\n",
            f"👟 **Golden Boot**: **{record.get('golden_boot_player', 'N/A')}** ({record.get('golden_boot_goals', 0)} Goals)",
            f"🎯 **Playmaker**: **{record.get('playmaker_player', 'N/A')}** ({record.get('playmaker_assists', 0)} Assists)",
            f"🧤 **Golden Glove**: **{record.get('golden_glove_team', 'N/A')}** ({record.get('golden_glove_clean_sheets', 0)} Clean Sheets)",
            f"⭐ **Player of the Season (MVP)**: **{record.get('mvp_player', 'N/A')}** ({record.get('mvp_rating', 0.0):.2f} AVG)",
            "\n*All awards have been etched into the BeastlyFC Hall of Fame!*",
        ]

        embed = create_beastly_embed(
            title="🎖️ Season Conclusion & Awards",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="history", description="Browse the BeastlyFC Hall of Fame and past season winners.")
    @app_commands.describe(
        season="Specific season number to inspect (optional)",
        competition="Filter by competition type (optional, e.g. league, ucl)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def season_history_cmd(
        self,
        interaction: discord.Interaction,
        season: Optional[int] = None,
        competition: Optional[str] = None,
    ):
        await interaction.response.defer()
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        records = await self.db.get_season_history(interaction.guild_id, season_number=season, competition_name=competition)
        if not records:
            await interaction.followup.send(
                embed=error_embed("Hall of Fame Empty", "No concluded seasons archived in the Hall of Fame yet."),
                ephemeral=True,
            )
            return

        embeds = []
        for r in records[:5]:
            lines = [
                f"🏆 **Champion**: **{r['champion']}**",
                f"🥈 **Runner-Up**: **{r.get('runner_up', 'N/A')}**\n",
                f"• 👟 **Golden Boot**: {r.get('golden_boot_player', 'N/A')} (`{r.get('golden_boot_goals', 0)} Goals`)",
                f"• 🎯 **Golden Playmaker**: {r.get('playmaker_player', 'N/A')} (`{r.get('playmaker_assists', 0)} Assists`)",
                f"• 🧤 **Golden Glove**: {r.get('golden_glove_team', 'N/A')} (`{r.get('golden_glove_clean_sheets', 0)} Clean Sheets`)",
                f"• ⭐ **Season MVP**: {r.get('mvp_player', 'N/A')} (`{r.get('mvp_rating', 0.0):.2f} Rating`)",
            ]
            embed = create_beastly_embed(
                title=f"🏛️ Hall of Fame • Season {r['season_number']} ({r['competition_name']})",
                description="\n".join(lines),
                color=COLOR_BEASTLY_GOLD,
            )
            embeds.append(embed)

        await interaction.followup.send(embeds=embeds)


async def setup(bot: commands.Bot):
    await bot.add_cog(Season(bot))
