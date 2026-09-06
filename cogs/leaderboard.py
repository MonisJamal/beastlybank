"""
Leaderboard Cog: High-roller rankings, medal boards, and wealth statistics for BeastlyFC.
"""
from typing import Literal
import discord
from discord import app_commands
from discord.ext import commands

from config import CURRENCIES, COLOR_BEASTLY_GOLD, SERVER_NAME
from utils.checks import require_beastlyfc
from utils.embeds import create_beastly_embed


class Leaderboard(commands.Cog):
    """BeastlyBank High-Rollers and Server Rankings."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="leaderboard",
        description="View the richest players and top clubs in BeastlyFC.",
    )
    @app_commands.describe(category="Rank by Cash, Community Points, Training Tokens, or Clubs")
    @require_beastlyfc()
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        category: Literal["cash", "points", "tokens", "clubs"] = "cash",
    ):
        if category == "clubs":
            clubs = await self.db.get_club_leaderboard(interaction.guild_id, limit=10)
            embed = create_beastly_embed(
                title=f"🏆 BeastlyFC Club Treasury Leaderboard",
                description=f"Top 10 clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━",
                color=COLOR_BEASTLY_GOLD,
            )
            if not clubs:
                embed.description += "\n*No clubs registered yet.*"
            else:
                medals = ["🥇", "🥈", "🥉"]
                for i, c in enumerate(clubs, start=1):
                    rank_icon = medals[i - 1] if i <= 3 else f"`#{i}`"
                    role_str = f" • <@&{c['role_id']}>" if c.get("role_id") else ""
                    embed.add_field(
                        name=f"{rank_icon} [{c['tag']}] {c['name']}{role_str}",
                        value=(
                            f"👑 Owner: <@{c['owner_id']}> | 👥 Squad: `{c.get('member_count', 1)}`\n"
                            f"💵 Cash: `{c['treasury_cash']:,}` | ⭐ Points: `{c['treasury_points']:,}` | 🎟️ Tokens: `{c['treasury_tokens']:,}`"
                        ),
                        inline=False,
                    )
            await interaction.response.send_message(embed=embed)
            return

        # User Leaderboard
        leaders = await self.db.get_leaderboard(interaction.guild_id, currency=category, limit=10)
        curr_info = CURRENCIES.get(category, {})
        emoji = curr_info.get("emoji", "💰")
        name = curr_info.get("name", category.title())

        embed = create_beastly_embed(
            title=f"🏆 BeastlyBank {name} Leaderboard",
            description=f"Top 10 high-rollers ranked by **{emoji} {name}** in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_BEASTLY_GOLD,
        )

        if not leaders:
            embed.description += "\n*No accounts found in BeastlyBank yet.*"
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, user_entry in enumerate(leaders, start=1):
                rank_icon = medals[i - 1] if i <= 3 else f"`#{i}`"
                balance = user_entry["balance"]
                embed.add_field(
                    name=f"{rank_icon} <@{user_entry['user_id']}>",
                    value=f"{emoji} **{balance:,} {name}**",
                    inline=False,
                )

        await interaction.response.send_message(embed=embed)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def prefix_leaderboard(self, ctx: commands.Context, category: str = "cash"):
        """bb!leaderboard [cash|points|tokens|clubs]"""
        cat_clean = category.lower().strip()
        if cat_clean in ("club", "clubs", "c"):
            clubs = await self.db.get_club_leaderboard(ctx.guild.id, limit=10)
            embed = create_beastly_embed(
                title="🏆 BeastlyFC Club Treasury Leaderboard",
                description=f"Top 10 clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━",
                color=COLOR_BEASTLY_GOLD,
            )
            if not clubs:
                embed.description += "\n*No clubs registered yet.*"
            else:
                medals = ["🥇", "🥈", "🥉"]
                for i, c in enumerate(clubs, start=1):
                    rank_icon = medals[i - 1] if i <= 3 else f"`#{i}`"
                    role_str = f" • <@&{c['role_id']}>" if c.get("role_id") else ""
                    embed.add_field(
                        name=f"{rank_icon} [{c['tag']}] {c['name']}{role_str}",
                        value=(
                            f"👑 Owner: <@{c['owner_id']}> | 👥 Squad: `{c.get('member_count', 1)}`\n"
                            f"💵 Cash: `{c['treasury_cash']:,}` | ⭐ Points: `{c['treasury_points']:,}` | 🎟️ Tokens: `{c['treasury_tokens']:,}`"
                        ),
                        inline=False,
                    )
            await ctx.send(embed=embed)
            return

        cat_key = "points" if "point" in cat_clean else ("tokens" if "token" in cat_clean else "cash")
        leaders = await self.db.get_leaderboard(ctx.guild.id, currency=cat_key, limit=10)
        curr_info = CURRENCIES.get(cat_key, {})
        emoji = curr_info.get("emoji", "💰")
        name = curr_info.get("name", cat_key.title())

        embed = create_beastly_embed(
            title=f"🏆 BeastlyBank {name} Leaderboard",
            description=f"Top 10 high-rollers ranked by **{emoji} {name}** in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_BEASTLY_GOLD,
        )

        if not leaders:
            embed.description += "\n*No accounts found in BeastlyBank yet.*"
        else:
            medals = ["🥇", "🥈", "🥉"]
            for i, user_entry in enumerate(leaders, start=1):
                rank_icon = medals[i - 1] if i <= 3 else f"`#{i}`"
                balance = user_entry["balance"]
                embed.add_field(
                    name=f"{rank_icon} <@{user_entry['user_id']}>",
                    value=f"{emoji} **{balance:,} {name}**",
                    inline=False,
                )

        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))

