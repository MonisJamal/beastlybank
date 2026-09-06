"""
Club Treasuries Cog: Club vaults, formations, deposits, withdrawals, and leaderboards.
"""
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import CURRENCIES, COLOR_BEASTLY_GOLD, COLOR_PITCH_GREEN, COLOR_SUCCESS
from utils.checks import require_beastlyfc
from utils.embeds import (
    club_info_embed,
    create_beastly_embed,
    error_embed,
    success_embed,
)


class Clubs(commands.GroupCog, name="club", description="Manage BeastlyFC Club Treasuries and Squads"):
    """BeastlyFC Club Finance and Treasury Management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="create",
        description="Register a new BeastlyFC football club with its own official BeastlyBank Treasury.",
    )
    @app_commands.describe(
        name="Full name of your club (e.g. Red Dragons FC)",
        tag="Short abbreviation tag (up to 5 letters, e.g. RDF)",
    )
    @require_beastlyfc()
    async def club_create(
        self,
        interaction: discord.Interaction,
        name: str,
        tag: str,
    ):
        success, msg, club = await self.db.create_club(
            guild_id=interaction.guild_id,
            name=name,
            tag=tag,
            owner_id=interaction.user.id,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Club Registration Failed", msg),
                ephemeral=True,
            )
            return

        embed = create_beastly_embed(
            title="🏟️ Club Registered Successfully!",
            description=(
                f"Congratulations {interaction.user.mention}! **[{club['tag']}] {club['name']}** is now officially affiliated with BeastlyFC!\n\n"
                f"🏦 **Club Treasury Vault Activated:**\n"
                f"• 💵 **Cash:** `500`\n"
                f"• ⭐ **Points:** `100`\n"
                f"• 🎟️ **Tokens:** `2`\n\n"
                f"Use `/club deposit` to fund your treasury or `/club info` to view your squad!"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="info",
        description="Inspect a club's treasury balance, squad roster, and official details.",
    )
    @app_commands.describe(club_query="Club name or tag to lookup (defaults to your own club)")
    @require_beastlyfc()
    async def club_info(
        self,
        interaction: discord.Interaction,
        club_query: Optional[str] = None,
    ):
        if club_query:
            club = await self.db.get_club_by_name(interaction.guild_id, club_query)
        else:
            club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not club:
            target_text = f"matching '{club_query}'" if club_query else "for your account"
            await interaction.response.send_message(
                embed=error_embed("Club Not Found", f"Could not find an active club {target_text}."),
                ephemeral=True,
            )
            return

        members = await self.db.get_club_members(club["id"])
        embed = club_info_embed(club, members)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="deposit",
        description="Deposit personal Cash, Points, or Tokens into your club's treasury vault.",
    )
    @app_commands.describe(
        currency="Currency type to deposit into the treasury",
        amount="Amount to deposit",
    )
    @require_beastlyfc()
    async def club_deposit(
        self,
        interaction: discord.Interaction,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
    ):
        user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        if not user_club:
            await interaction.response.send_message(
                embed=error_embed("No Club Affiliation", "You must be a member of a club to deposit funds!"),
                ephemeral=True,
            )
            return

        success, msg = await self.db.club_deposit(
            club_id=user_club["id"],
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=amount,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Deposit Failed", msg),
                ephemeral=True,
            )
            return

        curr_emoji = CURRENCIES.get(currency, {}).get("emoji", "💰")
        embed = create_beastly_embed(
            title="📥 Club Treasury Deposit",
            description=(
                f"{interaction.user.mention} contributed {curr_emoji} **{amount:,}** into the "
                f"**[{user_club['tag']}] {user_club['name']}** Treasury!\n\n"
                f"🏦 *Recorded in BeastlyBank automated club ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="withdraw",
        description="Withdraw funds from your club treasury into your personal account (Owner/Captain only).",
    )
    @app_commands.describe(
        currency="Currency type to withdraw",
        amount="Amount to withdraw",
        reason="Official memo explaining the treasury withdrawal",
    )
    @require_beastlyfc()
    async def club_withdraw(
        self,
        interaction: discord.Interaction,
        currency: Literal["cash", "points", "tokens"],
        amount: int,
        reason: str,
    ):
        user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        if not user_club:
            await interaction.response.send_message(
                embed=error_embed("No Club Affiliation", "You must be in a club to withdraw funds!"),
                ephemeral=True,
            )
            return

        success, msg = await self.db.club_withdraw(
            club_id=user_club["id"],
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=amount,
            reason=reason,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Withdrawal Denied", msg),
                ephemeral=True,
            )
            return

        curr_emoji = CURRENCIES.get(currency, {}).get("emoji", "💰")
        embed = create_beastly_embed(
            title="📤 Club Treasury Withdrawal",
            description=(
                f"{interaction.user.mention} withdrew {curr_emoji} **{amount:,}** from "
                f"**[{user_club['tag']}] {user_club['name']}** Treasury.\n\n"
                f"📝 **Reason:** *{reason}*\n"
                f"🏦 *Funds credited to personal account.*"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="list",
        description="View the wealthiest BeastlyFC Club Treasuries leaderboard.",
    )
    @require_beastlyfc()
    async def club_list(self, interaction: discord.Interaction):
        clubs = await self.db.get_club_leaderboard(interaction.guild_id, limit=10)

        embed = create_beastly_embed(
            title="🏟️ BeastlyFC Club Treasuries Leaderboard",
            description="Ranking of all registered clubs by total treasury assets:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_BEASTLY_GOLD,
        )

        if not clubs:
            embed.description += "\n*No clubs have registered with BeastlyBank yet. Be the first with `/club create`!*"
            await interaction.response.send_message(embed=embed)
            return

        medals = ["🥇", "🥈", "🥉"]
        for idx, c in enumerate(clubs, start=1):
            rank_str = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
            embed.add_field(
                name=f"{rank_str} [{c['tag']}] {c['name']} (Owner: <@{c['owner_id']}>)",
                value=(
                    f"👥 Squad: **{c.get('member_count', 1)}** | "
                    f"💵 Cash: `{c['treasury_cash']:,}` | "
                    f"⭐ Points: `{c['treasury_points']:,}` | "
                    f"🎟️ Tokens: `{c['treasury_tokens']:,}`"
                ),
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="addmanager",
        description="Promote a squad member to Club Manager (Owner only).",
    )
    @app_commands.describe(user="The squad member to promote to Manager")
    @require_beastlyfc()
    async def club_addmanager(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        if not user_club:
            await interaction.response.send_message(
                embed=error_embed("No Club", "You are not in a club!"), ephemeral=True
            )
            return

        success, msg = await self.db.set_club_manager(
            club_id=user_club["id"],
            owner_id=interaction.user.id,
            target_user_id=user.id,
            is_manager=True,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Action Failed", msg), ephemeral=True
            )
            return

        embed = success_embed("Manager Promoted", msg)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="removemanager",
        description="Demote a Club Manager back to normal squad member (Owner only).",
    )
    @app_commands.describe(user="The manager to demote")
    @require_beastlyfc()
    async def club_removemanager(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ):
        user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        if not user_club:
            await interaction.response.send_message(
                embed=error_embed("No Club", "You are not in a club!"), ephemeral=True
            )
            return

        success, msg = await self.db.set_club_manager(
            club_id=user_club["id"],
            owner_id=interaction.user.id,
            target_user_id=user.id,
            is_manager=False,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Action Failed", msg), ephemeral=True
            )
            return

        embed = success_embed("Manager Demoted", msg)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="history",
        description="View recent transactions and activity for your club treasury.",
    )
    @require_beastlyfc()
    async def club_history(
        self,
        interaction: discord.Interaction,
    ):
        user_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        if not user_club:
            await interaction.response.send_message(
                embed=error_embed("No Club", "You are not a member of any club!"), ephemeral=True
            )
            return

        txs = await self.db.get_club_transactions(user_club["id"], interaction.guild_id, limit=8)

        embed = create_beastly_embed(
            title=f"📜 Club Treasury History • [{user_club['tag']}] {user_club['name']}",
            description=f"Recent deposits, withdrawals, and club activity:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not txs:
            embed.description += "\n*No recorded transactions found for this club.*"
        else:
            for t in txs:
                curr_info = CURRENCIES.get(t["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                tx_type = t["tx_type"].replace("_", " ").title()
                reason = t.get("reason") or "No memo"
                time_str = t.get("created_at", "")[:16]
                embed.add_field(
                    name=f"#{t['id']} | {tx_type} — {emoji} {t['amount']:,}",
                    value=f"📝 *{reason}* • `{time_str}`",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)


class ClubHistoryTop(commands.Cog):
    """Top-level /clubhistory command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="clubhistory",
        description="View recent transactions and ledger history for your club treasury.",
    )
    @app_commands.describe(club_query="Club name or tag (defaults to your own club)")
    @require_beastlyfc()
    async def clubhistory_top(
        self,
        interaction: discord.Interaction,
        club_query: Optional[str] = None,
    ):
        if club_query:
            club = await self.db.get_club_by_name(interaction.guild_id, club_query)
        else:
            club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not club:
            target_str = f"matching '{club_query}'" if club_query else "for your account"
            await interaction.response.send_message(
                embed=error_embed("Club Not Found", f"No club found {target_str}."),
                ephemeral=True,
            )
            return

        txs = await self.db.get_club_transactions(club["id"], interaction.guild_id, limit=8)

        embed = create_beastly_embed(
            title=f"📜 Club Treasury History • [{club['tag']}] {club['name']}",
            description=f"Official treasury activity for **[{club['tag']}] {club['name']}**:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not txs:
            embed.description += "\n*No recorded transactions found for this club.*"
        else:
            for t in txs:
                curr_info = CURRENCIES.get(t["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                tx_type = t["tx_type"].replace("_", " ").title()
                reason = t.get("reason") or "No memo"
                time_str = t.get("created_at", "")[:16]
                embed.add_field(
                    name=f"#{t['id']} | {tx_type} — {emoji} {t['amount']:,}",
                    value=f"📝 *{reason}* • `{time_str}`",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Clubs(bot))
    await bot.add_cog(ClubHistoryTop(bot))

