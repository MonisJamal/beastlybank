"""
BeastlyFC Match Center Cog
Interactive matchday fixtures viewer, league standings, live score sync, and HTML import.
"""

import io
import logging
import re
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.checks import is_banker_or_admin
from utils.embeds import (
    COLOR_BEASTLY_GOLD,
    create_beastly_embed,
    error_embed,
    matchday_payroll_report_embed,
    success_embed,
)
from utils.match_parser import parse_matchsimulator_html

logger = logging.getLogger("BeastlyBank.Matches")


COMPETITION_CHOICES = [
    app_commands.Choice(name="League", value="league"),
    app_commands.Choice(name="Champions League (UCL)", value="ucl"),
    app_commands.Choice(name="Cup", value="cup"),
]


def format_fixture_line(f: Dict[str, Any]) -> str:
    h_team = f["home_team_name"]
    a_team = f["away_team_name"]
    if f["is_finished"]:
        g_h = f.get("goals_home", 0)
        g_a = f.get("goals_away", 0)
        pen_h = f.get("penalties_home", 0)
        pen_a = f.get("penalties_away", 0)
        pen_str = f" `({pen_h}-{pen_a} pen)`" if (pen_h > 0 or pen_a > 0) else ""
        return f"⚽ **{h_team}** `{g_h} - {g_a}` **{a_team}**{pen_str}"
    return f"⏳ **{h_team}** `vs` **{a_team}** *(Upcoming)*"


class FixtureSelect(discord.ui.Select):
    def __init__(self, fixtures: List[Dict[str, Any]]):
        options = []
        for i, f in enumerate(fixtures[:25]):
            score_str = f"{f['goals_home']}-{f['goals_away']}" if f["is_finished"] else "vs"
            if f.get("is_finished") and (f.get("penalties_home", 0) > 0 or f.get("penalties_away", 0) > 0):
                score_str += f" ({f['penalties_home']}-{f['penalties_away']}p)"
            label = f"{f['home_team_short'] or f['home_team_name'][:3]} {score_str} {f['away_team_short'] or f['away_team_name'][:3]}"
            desc = f"{f['home_team_name']} vs {f['away_team_name']}"
            options.append(discord.SelectOption(label=label, description=desc[:100], value=str(f["id"])))
        super().__init__(placeholder="Select a fixture for match details...", min_values=1, max_values=1, options=options)
        self.fixtures_map = {str(f["id"]): f for f in fixtures}

    async def callback(self, interaction: discord.Interaction):
        fixture_id = self.values[0]
        f = self.fixtures_map.get(fixture_id)
        if not f:
            await interaction.response.send_message("Fixture details unavailable.", ephemeral=True)
            return

        h = f["home_team_name"]
        a = f["away_team_name"]
        finished = f["is_finished"]
        gh = f.get("goals_home", 0)
        ga = f.get("goals_away", 0)
        pen_h = f.get("penalties_home", 0)
        pen_a = f.get("penalties_away", 0)

        desc_lines = []
        if finished:
            desc_lines.append(f"# {h}  `{gh} - {ga}`  {a}")
            if pen_h > 0 or pen_a > 0:
                desc_lines.append(f"🎯 **Penalty Shootout**: `{pen_h} - {pen_a}`")
            desc_lines.append("")
            if gh > ga or (gh == ga and pen_h > pen_a):
                desc_lines.append(f"🏆 **Winner**: **{h}**")
            elif gh < ga or (gh == ga and pen_h < pen_a):
                desc_lines.append(f"🏆 **Winner**: **{a}**")
            else:
                desc_lines.append("🤝 **Result**: **Draw**")

            if ga == 0:
                desc_lines.append(f"🧤 Clean Sheet: **{h}**")
            if gh == 0:
                desc_lines.append(f"🧤 Clean Sheet: **{a}**")
        else:
            desc_lines.append(f"# {h}  `vs`  {a}\nStatus: **Upcoming**")

        stage_str = f" • {f['stage_name']}" if f.get("stage_name") else ""
        embed = create_beastly_embed(
            title=f"🏟️ Match Center • Matchday {f['matchday']}{stage_str}",
            description="\n".join(desc_lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MatchdayNavigatorView(discord.ui.View):
    def __init__(self, bot: commands.Bot, tournament_id: int, current_md: int, max_md: int):
        super().__init__(timeout=180)
        self.bot = bot
        self.tournament_id = tournament_id
        self.current_md = current_md
        self.max_md = max_md

    async def refresh_embed(self, interaction: discord.Interaction):
        fixtures = await self.bot.db.get_tournament_fixtures(self.tournament_id, matchday=self.current_md)
        t = await self.bot.db.get_tournament_by_id(self.tournament_id)
        t_name = t["name"] if t else "League"

        stage = fixtures[0].get("stage_name") if (fixtures and fixtures[0].get("stage_name")) else None
        header = f"**Matchday {self.current_md} of {self.max_md}**"
        if stage and stage.lower() != f"matchday {self.current_md}":
            header = f"**Matchday {self.current_md} of {self.max_md} • {stage}**"
        lines = [f"{header}\n"]
        for f in fixtures:
            lines.append(format_fixture_line(f))

        embed = create_beastly_embed(
            title=f"📅 {t_name} • Matchday {self.current_md}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )

        # Update items
        self.clear_items()
        prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=(self.current_md <= 1))
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(self.current_md >= self.max_md))

        async def prev_cb(itx: discord.Interaction):
            self.current_md = max(1, self.current_md - 1)
            await self.refresh_embed(itx)

        async def next_cb(itx: discord.Interaction):
            self.current_md = min(self.max_md, self.current_md + 1)
            await self.refresh_embed(itx)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb
        self.add_item(prev_btn)
        self.add_item(next_btn)

        if fixtures:
            self.add_item(FixtureSelect(fixtures))

        if not interaction.response.is_done():
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_md = max(1, self.current_md - 1)
        await self.refresh_embed(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.current_md = min(self.max_md, self.current_md + 1)
        await self.refresh_embed(interaction)


class Matches(commands.GroupCog, name="matches", description="BeastlyFC Match Center & Fixtures"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="view", description="Browse matchday fixtures and detailed match reports.")
    @app_commands.describe(
        matchday="Specific matchday to inspect (optional)",
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 2, default: active season - Season 2)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def matches_view(
        self,
        interaction: discord.Interaction,
        matchday: Optional[int] = None,
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
            await interaction.followup.send(
                embed=error_embed("No Tournament", f"No {target_str} tournament found."),
                ephemeral=True,
            )
            return

        target_md = matchday or t["current_matchday"] or 1
        max_md = t["total_matchdays"] or 38
        fixtures = await self.db.get_tournament_fixtures(t["id"], matchday=target_md)

        stage = fixtures[0].get("stage_name") if (fixtures and fixtures[0].get("stage_name")) else None
        header = f"**Matchday {target_md} of {max_md}**"
        if stage and stage.lower() != f"matchday {target_md}":
            header = f"**Matchday {target_md} of {max_md} • {stage}**"
        lines = [f"{header}\n"]
        for f in fixtures:
            lines.append(format_fixture_line(f))

        embed = create_beastly_embed(
            title=f"📅 {t['name']} • Matchday {target_md}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )

        view = MatchdayNavigatorView(self.bot, t["id"], target_md, max_md)
        view.clear_items()
        prev_btn = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary, disabled=(target_md <= 1))
        next_btn = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary, disabled=(target_md >= max_md))

        async def prev_cb(itx: discord.Interaction):
            view.current_md = max(1, view.current_md - 1)
            await view.refresh_embed(itx)

        async def next_cb(itx: discord.Interaction):
            view.current_md = min(max_md, view.current_md + 1)
            await view.refresh_embed(itx)

        prev_btn.callback = prev_cb
        next_btn.callback = next_cb
        view.add_item(prev_btn)
        view.add_item(next_btn)

        if fixtures:
            view.add_item(FixtureSelect(fixtures))

        await interaction.followup.send(embed=embed, view=view)

    async def show_standings(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
    ):
        await self.db.ensure_tournament_seeded(interaction.guild_id)
        if season is not None:
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season)
        else:
            t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())

        if not t:
            target_str = f"Season {season}" if season else f"active `{competition}`"
            await interaction.followup.send(
                embed=error_embed("No Standings", f"No {target_str} tournament found."),
                ephemeral=True,
            )
            return

        standings = await self.db.get_tournament_standings(t["id"])
        if not standings:
            await interaction.followup.send(
                embed=error_embed("Empty Table", "No standings available yet for this tournament."),
                ephemeral=True,
            )
            return

        header = "`#  Team                  P   W  D  L   GD  CS  PTS`"
        lines = [header]
        for s in standings:
            r = s["rank"]
            name = (s["name"][:18]).ljust(18)
            p = str(s["played"]).rjust(2)
            w = str(s["won"]).rjust(2)
            d = str(s["drawn"]).rjust(2)
            l = str(s["lost"]).rjust(2)
            gd = f"{s['goal_difference']:+d}".rjust(4)
            cs = str(s["clean_sheets"]).rjust(2)
            pts = str(s["points"]).rjust(3)
            lines.append(f"`{r:<2} {name} {p} {w} {d} {l} {gd} {cs} {pts}`")

        embed = create_beastly_embed(
            title=f"🏆 {t['name']} • Standings Table",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="standings", description="View the tournament standings and leaderboard table.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 1, default: active season)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def matches_standings(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
    ):
        await interaction.response.defer()
        await self.show_standings(interaction, competition, season)

    @app_commands.command(name="upcoming", description="View the next upcoming matchday and unplayed fixtures.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 2, default: active season - Season 2)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def matches_upcoming(
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

        conn = await self.db.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT MIN(matchday) FROM tournament_fixtures WHERE tournament_id = ? AND is_finished = 0;",
                (t["id"],),
            )
            row = await cur.fetchone()
            next_md = row[0] if (row and row[0] is not None) else None

        if not next_md:
            await interaction.followup.send(
                embed=create_beastly_embed(
                    title=f"🏁 {t['name']} • Season Concluded",
                    description=f"All fixtures in **{t['name']}** are completed!\n\n• Browse finished matchdays with `/matches view`\n• View the final leaderboard with `/standings`\n• Launch the next season with `/season start`",
                    color=COLOR_BEASTLY_GOLD,
                )
            )
            return

        fixtures = await self.db.get_tournament_fixtures(t["id"], matchday=next_md)
        stage = fixtures[0].get("stage_name") if (fixtures and fixtures[0].get("stage_name")) else f"Matchday {next_md}"
        lines = [f"**Upcoming Fixtures • {stage}**\n"]
        for f in fixtures:
            lines.append(format_fixture_line(f))

        lines.append(f"\n💡 *Place bets on these matches using `/bet place matchday:{next_md}`!*")

        embed = create_beastly_embed(
            title=f"⏳ Upcoming Matches • {t['name']}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="import", description="Upload a saved tournament .html file from matchsimulator.com.")
    @app_commands.describe(
        file="Attach the saved .html webpage file from matchsimulator.com",
        competition="Competition type (league, ucl, cup, default: auto-detect)",
        season="Specific season number to import into (e.g. 2, default: auto-detect from file or S2)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def matches_import(
        self,
        interaction: discord.Interaction,
        file: discord.Attachment,
        competition: str = "league",
        season: Optional[int] = None,
    ):
        await interaction.response.defer()
        if not file.filename.endswith((".html", ".htm")):
            await interaction.followup.send(embed=error_embed("Invalid File", "Please upload a valid `.html` file."), ephemeral=True)
            return

        try:
            content_bytes = await file.read()
            html_text = content_bytes.decode("utf-8", errors="replace")
            parsed = parse_matchsimulator_html(html_text)

            # Auto-detect competition type if default 'league' passed
            comp_type = competition.lower()
            name_lower = parsed.get("tournament_name", "").lower()
            if comp_type == "league":
                if "ucl" in name_lower or "champions" in name_lower:
                    comp_type = "ucl"
                elif "cup" in name_lower and "league" not in name_lower:
                    comp_type = "cup"

            # Determine season number:
            if season is not None:
                season_num = season
            else:
                s_match = re.search(r'\b(?:s|season)\s*(\d+)\b', name_lower)
                if s_match:
                    season_num = int(s_match.group(1))
                else:
                    active_t = await self.db.get_active_tournament(interaction.guild_id, competition_type=comp_type)
                    season_num = (active_t.get("season_number") or 2) if active_t else 2

            saved = await self.db.save_parsed_tournament(
                guild_id=interaction.guild_id,
                tournament_data=parsed,
                season_number=season_num,
                competition_type=comp_type,
            )

            # Auto-settle pending bets for finished matchdays
            settled_total = 0
            for md in range(1, parsed.get("highest_matchday", 38) + 1):
                payouts = await self.db.settle_matchday_bets(saved["id"], matchday=md)
                settled_total += len([p for p in payouts if p["status"] == "won"])
                # Auto-settle matchday wages if not yet processed
                try:
                    await self.db.deduct_matchday_wages(interaction.guild_id, matchday=md, tournament_id=saved["id"])
                except Exception as w_err:
                    logger.debug("Auto matchday wage settlement on import notice: %s", w_err)

            champ_msg = f"• Champion: **{saved.get('champion', 'TBD')}**\n" if saved.get("champion") else ""
            await interaction.followup.send(
                embed=success_embed(
                    "Tournament Imported Successfully!",
                    f"🏆 **{saved['name']}**\n"
                    f"• Competition: **{comp_type.upper()}** (Season {season_num})\n"
                    f"• Fixtures Loaded: **{parsed['total_fixtures']}**\n"
                    f"• Total Matchdays: **{saved['total_matchdays']}**\n"
                    f"• Teams: **{len(parsed['standings'])}**\n"
                    f"{champ_msg}"
                    f"• Winning Bets Settled: **{settled_total}**\n"
                    f"• Matchday Payrolls: **Auto-Synced**",
                )
            )
        except Exception as e:
            logger.error("Error importing tournament HTML: %s", e, exc_info=True)
            await interaction.followup.send(embed=error_embed("Import Failed", f"Could not parse file: `{str(e)}`"), ephemeral=True)

    @app_commands.command(name="startmd", description="Officially kick off a matchday and settle all club squad wage deductions.")
    @app_commands.describe(matchday="Matchday number to kick off (e.g. 1)")
    async def matches_startmd(self, interaction: discord.Interaction, matchday: int):
        await interaction.response.defer()
        if not is_banker_or_admin(interaction.user):
            await interaction.followup.send(
                embed=error_embed("Permission Denied", "Only BeastlyBank Bankers or Server Admins can kick off a matchday payroll."),
                ephemeral=True,
            )
            return

        success, msg, report = await self.db.deduct_matchday_wages(interaction.guild_id, matchday)
        if not success:
            await interaction.followup.send(embed=error_embed("Matchday Payroll Error", msg), ephemeral=True)
            return

        embed = matchday_payroll_report_embed(report)
        await interaction.followup.send(embed=embed)


class Matchday(commands.GroupCog, name="matchday", description="BeastlyFC Matchday Operations & Kickoff"):
    """Matchday kickoff and automatic club squad payroll settlements."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="start", description="Kick off a matchday and automatically settle all squad wage deductions.")
    @app_commands.describe(matchday="Matchday number to kick off (e.g. 1)")
    async def matchday_start(self, interaction: discord.Interaction, matchday: int):
        await interaction.response.defer()
        if not is_banker_or_admin(interaction.user):
            await interaction.followup.send(
                embed=error_embed("Permission Denied", "Only BeastlyBank Bankers or Server Admins can kick off a matchday."),
                ephemeral=True,
            )
            return

        success, msg, report = await self.db.deduct_matchday_wages(interaction.guild_id, matchday)
        if not success:
            await interaction.followup.send(embed=error_embed("Matchday Payroll Error", msg), ephemeral=True)
            return

        embed = matchday_payroll_report_embed(report)
        await interaction.followup.send(embed=embed)

    @commands.group(name="matchday", invoke_without_command=True)
    async def prefix_matchday(self, ctx: commands.Context, sub: Optional[str] = None):
        """Matchday operations. Usage: bb!matchday start <matchday>"""
        await ctx.send(embed=error_embed("Matchday Command", "Usage: `bb!matchday start <matchday>` or `bb!startmd <matchday>`"))

    @prefix_matchday.command(name="start")
    async def prefix_matchday_start(self, ctx: commands.Context, matchday: int):
        """Kick off matchday and settle wages. Usage: bb!matchday start <matchday>"""
        if not is_banker_or_admin(ctx.author):
            await ctx.send(embed=error_embed("Permission Denied", "Only BeastlyBank Bankers or Server Admins can kick off a matchday."))
            return

        success, msg, report = await self.db.deduct_matchday_wages(ctx.guild.id, matchday)
        if not success:
            await ctx.send(embed=error_embed("Matchday Payroll Error", msg))
            return

        embed = matchday_payroll_report_embed(report)
        await ctx.send(embed=embed)

    @commands.command(name="startmd")
    async def prefix_startmd(self, ctx: commands.Context, matchday: int):
        """Kick off matchday and settle club wages. Usage: bb!startmd <matchday>"""
        await self.prefix_matchday_start(ctx, matchday=matchday)


class Standings(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="standings", description="View the league standings and leaderboard table.")
    @app_commands.describe(
        competition="Competition type (league, ucl, cup, default: league)",
        season="Specific season number to view (e.g. 2, default: active season - Season 2)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def standings_cmd(
        self,
        interaction: discord.Interaction,
        competition: str = "league",
        season: Optional[int] = None,
    ):
        await interaction.response.defer()
        matches_cog = self.bot.get_cog("matches")
        if matches_cog and hasattr(matches_cog, "show_standings"):
            await matches_cog.show_standings(interaction, competition, season)
        else:
            await self.db.ensure_tournament_seeded(interaction.guild_id)
            t = await self.db.get_tournament_by_season(interaction.guild_id, competition_type=competition.lower(), season_number=season) if season else await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
            if not t:
                await interaction.followup.send(embed=error_embed("No Standings", "No active tournament found."), ephemeral=True)
                return
            standings = await self.db.get_tournament_standings(t["id"])
            header = "`#  Team                  P   W  D  L   GD  CS  PTS`"
            lines = [header]
            for s in standings:
                lines.append(f"`{s['rank']:<2} {(s['name'][:18]).ljust(18)} {str(s['played']).rjust(2)} {str(s['won']).rjust(2)} {str(s['drawn']).rjust(2)} {str(s['lost']).rjust(2)} {s['goal_difference']:+4d} {str(s['clean_sheets']).rjust(2)} {str(s['points']).rjust(3)}`")
            embed = create_beastly_embed(title=f"🏆 {t['name']} • Standings Table", description="\n".join(lines), color=COLOR_BEASTLY_GOLD)
            await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Matches(bot))
    await bot.add_cog(Standings(bot))
    await bot.add_cog(Matchday(bot))
