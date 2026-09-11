"""
BeastlyFC Matchday Sports Betting Cog
Interactive betting on upcoming matchday fixtures with escrow debit and auto-payouts.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from cogs.auction import parse_bid_amount_or_increment, parse_time_duration
from utils.embeds import (
    COLOR_BEASTLY_GOLD,
    create_beastly_embed,
    error_embed,
    success_embed,
)

logger = logging.getLogger("BeastlyBank.Betting")


class PlaceBetModal(discord.ui.Modal):
    def __init__(self, bot: commands.Bot, tournament_id: int, matchday: int, fixture: Dict[str, Any]):
        h = fixture["home_team_name"]
        a = fixture["away_team_name"]
        super().__init__(title=f"Bet: {fixture['home_team_short']} vs {fixture['away_team_short']}")
        self.bot = bot
        self.tournament_id = tournament_id
        self.matchday = matchday
        self.fixture = fixture

        self.choice_input = discord.ui.TextInput(
            label=f"Choice (1: {h}, 2: Draw, 3: {a})",
            placeholder="Type '1' (Home), '2' (Draw), or '3' (Away)",
            min_length=1,
            max_length=10,
            required=True,
        )
        self.amount_input = discord.ui.TextInput(
            label="Bet Amount (e.g. 5m, 10000000)",
            placeholder="Enter cash amount to wager",
            min_length=1,
            max_length=20,
            required=True,
        )
        self.add_item(self.choice_input)
        self.add_item(self.amount_input)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        raw_choice = self.choice_input.value.strip().lower()
        if raw_choice in ("1", "home", "h"):
            bet_choice = "home"
        elif raw_choice in ("2", "draw", "d", "x"):
            bet_choice = "draw"
        elif raw_choice in ("3", "away", "a"):
            bet_choice = "away"
        else:
            await interaction.followup.send(embed=error_embed("Invalid Choice", "Please enter 1 (Home Win), 2 (Draw), or 3 (Away Win)."), ephemeral=True)
            return

        amt = parse_bid_amount_or_increment(self.amount_input.value.strip())
        if not amt or amt <= 0:
            await interaction.followup.send(embed=error_embed("Invalid Amount", "Please specify a valid wager amount (e.g. `5m`, `10000000`)."), ephemeral=True)
            return

        ok, msg, bet = await self.bot.db.place_matchday_bet(
            guild_id=interaction.guild_id,
            tournament_id=self.tournament_id,
            matchday=self.matchday,
            fixture_id=self.fixture["id"],
            user_id=interaction.user.id,
            bet_type=bet_choice,
            amount=amt,
            odds=2.0,
        )

        if not ok:
            await interaction.followup.send(embed=error_embed("Bet Rejected", msg), ephemeral=True)
            return

        target_team = (
            self.fixture["home_team_name"]
            if bet_choice == "home"
            else self.fixture["away_team_name"]
            if bet_choice == "away"
            else "Draw"
        )
        potential_payout = int(amt * 2.0)
        await interaction.followup.send(
            embed=success_embed(
                "Bet Confirmed!",
                f"🎲 **Matchday {self.matchday} Wager Placed!**\n"
                f"• Match: **{self.fixture['home_team_name']} vs {self.fixture['away_team_name']}**\n"
                f"• Prediction: **{target_team}** (`{bet_choice.upper()}`)\n"
                f"• Wager: **{amt:,} Cash** ({bet.get('escrow_source', 'personal').capitalize()})\n"
                f"• Odds: **2.0x** (Potential Payout: **{potential_payout:,} Cash**)\n\n"
                f"*Winnings will be paid out automatically when match results are synced!*",
            ),
            ephemeral=True,
        )


class MatchdayBettingView(discord.ui.View):
    def __init__(self, bot: commands.Bot, tournament_id: int, matchday: int, fixtures: List[Dict[str, Any]]):
        super().__init__(timeout=None)
        self.bot = bot
        self.tournament_id = tournament_id
        self.matchday = matchday
        self.fixtures = fixtures

        options = []
        for f in fixtures[:25]:
            label = f"{f['home_team_short'] or f['home_team_name'][:3]} vs {f['away_team_short'] or f['away_team_name'][:3]}"
            desc = f"{f['home_team_name']} vs {f['away_team_name']}"
            options.append(discord.SelectOption(label=label, description=desc[:100], value=str(f["id"])))

        select = discord.ui.Select(placeholder="Select fixture to bet on...", min_values=1, max_values=1, options=options)

        async def select_cb(interaction: discord.Interaction):
            fix_id = select.values[0]
            target_fix = next((fx for fx in self.fixtures if str(fx["id"]) == fix_id), None)
            if not target_fix:
                await interaction.response.send_message("Fixture not found.", ephemeral=True)
                return
            modal = PlaceBetModal(self.bot, self.tournament_id, self.matchday, target_fix)
            await interaction.response.send_modal(modal)

        select.callback = select_cb
        self.add_item(select)


COMPETITION_CHOICES = [
    app_commands.Choice(name="League", value="league"),
    app_commands.Choice(name="Champions League (UCL)", value="ucl"),
    app_commands.Choice(name="Cup", value="cup"),
]


class Betting(commands.GroupCog, name="bet", description="BeastlyFC Matchday Sports Betting House"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="open", description="Open sports betting on an upcoming matchday with an auto-lock timer.")
    @app_commands.describe(
        matchday="Matchday number to open betting for",
        closes="Lock timer duration (e.g. 15m, 30m, 1h, 2h)",
        competition="Competition type (league, ucl, cup, default: league)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def bet_open(
        self,
        interaction: discord.Interaction,
        matchday: int,
        closes: str = "1h",
        competition: str = "league",
    ):
        await interaction.response.defer()
        t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
        if not t:
            await interaction.followup.send(embed=error_embed("No Tournament", f"No active `{competition}` tournament found."), ephemeral=True)
            return

        fixtures = await self.db.get_tournament_fixtures(t["id"], matchday=matchday)
        if not fixtures:
            await interaction.followup.send(embed=error_embed("No Fixtures", f"No fixtures found for Matchday {matchday}."), ephemeral=True)
            return

        unplayed = [f for f in fixtures if not f["is_finished"]]
        if not unplayed:
            await interaction.followup.send(
                embed=error_embed("Matchday Concluded", f"All fixtures in Matchday {matchday} have already finished! Bets cannot be placed on completed games."),
                ephemeral=True,
            )
            return

        # Get standings to identify bottom 5 teams
        standings = await self.db.get_tournament_standings(t["id"])
        bottom_5_map = {}
        if standings:
            sorted_desc = sorted(standings, key=lambda s: s["rank"], reverse=True)[:5]
            bottom_5_map = {s["name"].strip().lower(): s["rank"] for s in sorted_desc}

        eligible_fixtures = []
        locked_fixtures = []
        for f in unplayed:
            h_low = f["home_team_name"].strip().lower()
            a_low = f["away_team_name"].strip().lower()
            if h_low in bottom_5_map or a_low in bottom_5_map:
                culprit = f["home_team_name"] if h_low in bottom_5_map else f["away_team_name"]
                rk = bottom_5_map.get(h_low) or bottom_5_map.get(a_low)
                locked_fixtures.append((f, culprit, rk))
            else:
                eligible_fixtures.append(f)

        if not eligible_fixtures:
            await interaction.followup.send(
                embed=error_embed("No Eligible Fixtures", f"All fixtures in Matchday {matchday} involve bottom 5 clubs. Betting is prohibited on bottom 5 teams."),
                ephemeral=True,
            )
            return

        duration_secs = parse_time_duration(closes) or 3600
        lock_dt = datetime.now(timezone.utc) + timedelta(seconds=duration_secs)
        lock_ts = int(lock_dt.timestamp())

        lines = [
            f"🎲 **Matchday {matchday} Betting House is OPEN!**",
            f"⏳ Closes: <t:{lock_ts}:R> (<t:{lock_ts}:t>)",
            f"💰 Fixed Odds: **2.0x Return**\n",
            "**Open for Betting**:",
        ]
        for f in eligible_fixtures:
            lines.append(f"• **{f['home_team_name']}** `vs` **{f['away_team_name']}**")

        if locked_fixtures:
            lines.append("\n**🚫 Bottom 5 Restricted (No Bets)**:")
            for f, culp, rk in locked_fixtures:
                lines.append(f"• ~~{f['home_team_name']} vs {f['away_team_name']}~~ *(Locked: {culp} #{rk})*")

        lines.append("\n*Select an eligible fixture below to place your wager!*")

        embed = create_beastly_embed(
            title=f"🎰 Sports Betting • {t['name']} • Matchday {matchday}",
            description="\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )

        # Auto-deduct club matchday wages as the matchday kicks off
        try:
            await self.db.deduct_matchday_wages(interaction.guild_id, matchday=matchday, tournament_id=t["id"])
        except Exception as w_err:
            logger.debug("Auto matchday wage deduction notice on /bet open: %s", w_err)

        view = MatchdayBettingView(self.bot, t["id"], matchday, eligible_fixtures)
        msg = await interaction.followup.send(embed=embed, view=view)

        # Background task to disable buttons when closes timer expires
        async def close_timer():
            await asyncio.sleep(duration_secs)
            try:
                for child in view.children:
                    child.disabled = True
                closed_embed = create_beastly_embed(
                    title=f"🔒 Betting Closed • Matchday {matchday}",
                    description=f"Wagers for Matchday {matchday} are now locked! Results and payouts will settle upon matchday sync.",
                    color=COLOR_BEASTLY_GOLD,
                )
                await msg.edit(embed=closed_embed, view=view)
            except Exception as e:
                logger.warning("Failed to auto-close betting message: %s", e)

        asyncio.create_task(close_timer())

    @app_commands.command(name="place", description="Place a wager on an upcoming match fixture.")
    @app_commands.describe(
        matchday="Matchday number (or use /bet open for interactive fixture select)",
        choice="Bet outcome: Home win, Draw, or Away win",
        amount="Wager amount (e.g. 5m, 10000000)",
        competition="Competition type (league, ucl, cup, default: league)",
    )
    @app_commands.choices(
        competition=COMPETITION_CHOICES,
        choice=[
            app_commands.Choice(name="Home Team Win", value="home"),
            app_commands.Choice(name="Draw", value="draw"),
            app_commands.Choice(name="Away Team Win", value="away"),
        ],
    )
    async def bet_place(
        self,
        interaction: discord.Interaction,
        matchday: int,
        choice: str,
        amount: str,
        competition: str = "league",
    ):
        await interaction.response.defer(ephemeral=True)
        t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
        if not t:
            await interaction.followup.send(embed=error_embed("No Tournament", f"No active `{competition}` tournament found."), ephemeral=True)
            return

        fixtures = await self.db.get_tournament_fixtures(t["id"], matchday=matchday)
        unplayed = [f for f in fixtures if not f["is_finished"]]
        if not unplayed:
            await interaction.followup.send(embed=error_embed("No Fixtures", f"No open fixtures found for Matchday {matchday}."), ephemeral=True)
            return

        parsed_amt = parse_bid_amount_or_increment(amount)
        if not parsed_amt or parsed_amt <= 0:
            await interaction.followup.send(embed=error_embed("Invalid Amount", "Please specify a valid wager amount (e.g. 1m, 500k)."), ephemeral=True)
            return

        # If only one unplayed fixture or need select
        target_f = unplayed[0] if len(unplayed) == 1 else None
        if not target_f:
            view = MatchdayBettingView(self.bot, t["id"], matchday, unplayed)
            embed = create_beastly_embed(
                title=f"🎰 Select Fixture • Matchday {matchday}",
                description=f"Choose a match below to complete your **{parsed_amt:,} Cash** wager on **{choice.upper()}**.",
                color=COLOR_BEASTLY_GOLD,
            )
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            return

        ok, msg, bet = await self.db.place_matchday_bet(
            guild_id=interaction.guild_id,
            tournament_id=t["id"],
            matchday=matchday,
            fixture_id=target_f["id"],
            user_id=interaction.user.id,
            bet_type=choice,
            amount=parsed_amt,
        )
        if not ok:
            await interaction.followup.send(embed=error_embed("Bet Rejected", msg), ephemeral=True)
            return

        embed = success_embed(
            "Wager Placed Successfully!",
            f"🎲 **Bet #{bet['id']} Recorded**\n"
            f"• Match: **{target_f['home_team_name']} vs {target_f['away_team_name']}**\n"
            f"• Choice: **{choice.upper()}**\n"
            f"• Amount: **{parsed_amt:,} Cash**\n"
            f"• Fixed Odds: **2.0x** (Potential Payout: **{int(parsed_amt * 2.0):,} Cash**)",
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="view", description="View your active matchday wagers and recent betting results.")
    async def bet_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bets = await self.db.get_user_matchday_bets(interaction.guild_id, interaction.user.id, limit=15)
        if not bets:
            await interaction.followup.send(
                embed=error_embed("No Bets", "You have not placed any matchday bets yet. Use `/bet open` or `/matches upcoming` to find open games!"),
                ephemeral=True,
            )
            return

        lines = []
        for b in bets:
            status_icon = "⏳" if b["status"] == "pending" else "✅" if b["status"] == "won" else "❌"
            match_str = f"{b.get('home_team_name', 'Home')} vs {b.get('away_team_name', 'Away')}"
            choice_str = b["bet_type"].upper()
            amt_str = f"{b['amount']:,} Cash"
            lines.append(
                f"{status_icon} **#{b['id']}** • {match_str}\n"
                f"    Pick: **{choice_str}** | Wager: **{amt_str}** | Status: `{b['status'].upper()}`"
            )

        embed = create_beastly_embed(
            title="🎰 Your Matchday Wagers",
            description="\n\n".join(lines),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="resolve", description="Manually settle wagers for finished matchday fixtures.")
    @app_commands.describe(
        matchday="Matchday number to settle bets for",
        competition="Competition type (league, ucl, cup, default: league)",
    )
    @app_commands.choices(competition=COMPETITION_CHOICES)
    async def bet_resolve(
        self,
        interaction: discord.Interaction,
        matchday: int,
        competition: str = "league",
    ):
        await interaction.response.defer()
        t = await self.db.get_active_tournament(interaction.guild_id, competition_type=competition.lower())
        if not t:
            await interaction.followup.send(embed=error_embed("No Tournament", f"No active `{competition}` tournament found."), ephemeral=True)
            return

        payouts = await self.db.settle_matchday_bets(t["id"], matchday=matchday)
        if not payouts:
            await interaction.followup.send(
                embed=error_embed("No Pending Bets", f"No unsettled bets found for Matchday {matchday} in **{t['name']}**."),
                ephemeral=True,
            )
            return

        won_cnt = len([p for p in payouts if p["status"] == "won"])
        lost_cnt = len([p for p in payouts if p["status"] == "lost"])
        total_paid = sum(p.get("payout", 0) for p in payouts if p["status"] == "won")

        embed = success_embed(
            f"Bets Settled • Matchday {matchday}",
            f"🏁 **Settlement Complete for {t['name']}**\n"
            f"• Winning Wagers: **{won_cnt}**\n"
            f"• Losing Wagers: **{lost_cnt}**\n"
            f"• Total Payouts Disbursed: **{total_paid:,} Cash**",
        )
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Betting(bot))
