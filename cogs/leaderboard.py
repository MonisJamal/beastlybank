"""
Leaderboard Cog: High-roller rankings, medal boards, and wealth statistics for BeastlyFC.
"""
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import CURRENCIES, COLOR_BEASTLY_GOLD, SERVER_NAME
from utils.checks import require_beastlyfc
from utils.embeds import create_beastly_embed, resolve_user_names
from utils.views import PaginationView
from cogs.clubs import resolve_owner_names


class Leaderboard(commands.Cog):
    """BeastlyBank High-Rollers and Server Rankings."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="leaderboard",
        description="View the richest players and top clubs in BeastlyFC.",
    )
    @app_commands.describe(
        category="Rank by Cash, Community Points, Training Tokens, or Clubs",
        page="Page number to view (default: 1)",
    )
    @require_beastlyfc()
    async def leaderboard(
        self,
        interaction: discord.Interaction,
        category: Literal["cash", "points", "tokens", "clubs"] = "cash",
        page: Optional[int] = 1,
    ):
        if category == "clubs":
            clubs = await self.db.get_club_leaderboard(interaction.guild_id, limit=200)
            if not clubs:
                embed = create_beastly_embed(
                    title="🏆 BeastlyFC Club Treasury Leaderboard",
                    description=f"Top clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━\n\n*No clubs registered yet.*",
                    color=COLOR_BEASTLY_GOLD,
                )
                await interaction.response.send_message(embed=embed)
                return

            owner_map = await resolve_owner_names(self.bot, interaction.guild, clubs)
            per_page = 10
            total_pages = max(1, (len(clubs) + per_page - 1) // per_page)
            target_page = max(1, min(page or 1, total_pages))

            def make_club_page(p: int) -> discord.Embed:
                start_idx = (p - 1) * per_page
                page_clubs = clubs[start_idx : start_idx + per_page]
                end_idx = start_idx + len(page_clubs)
                embed = create_beastly_embed(
                    title="🏆 BeastlyFC Club Treasury Leaderboard",
                    description=(
                        f"Clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n"
                        f"Showing clubs **{start_idx + 1}–{end_idx}** of **{len(clubs)}** registered clubs\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    color=COLOR_BEASTLY_GOLD,
                )
                medals = ["🥇", "🥈", "🥉"]
                for idx, c in enumerate(page_clubs, start=start_idx + 1):
                    rank_icon = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                    role_str = f" • <@&{c['role_id']}>" if c.get("role_id") else ""
                    owner_name = owner_map.get(c.get("owner_id", 0), "Vacant")
                    embed.add_field(
                        name=f"{rank_icon} [{c['tag']}] {c['name']}{role_str}",
                        value=(
                            f"👑 Owner: **{owner_name}** | 👥 Squad: `{c.get('member_count', 1)}`\n"
                            f"💵 Cash: `{c['treasury_cash']:,}` | ⭐ Points: `{c['treasury_points']:,}` | 🎟️ Tokens: `{c['treasury_tokens']:,}`"
                        ),
                        inline=False,
                    )
                embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyFC Club Leaderboard")
                return embed

            initial_embed = make_club_page(target_page)
            if total_pages <= 1:
                await interaction.response.send_message(embed=initial_embed)
            else:
                view = PaginationView(
                    embed_generator=make_club_page,
                    total_pages=total_pages,
                    author_id=interaction.user.id,
                    current_page=target_page,
                )
                await interaction.response.send_message(embed=initial_embed, view=view)
            return

        # User Leaderboard (cash, points, tokens)
        leaders = await self.db.get_leaderboard(interaction.guild_id, currency=category, limit=200)
        curr_info = CURRENCIES.get(category, {})
        emoji = curr_info.get("emoji", "💰")
        curr_name = curr_info.get("name", category.title())

        if not leaders:
            embed = create_beastly_embed(
                title=f"🏆 BeastlyBank {curr_name} Leaderboard",
                description=f"Top high-rollers ranked by **{emoji} {curr_name}** in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━\n\n*No accounts found in BeastlyBank yet.*",
                color=COLOR_BEASTLY_GOLD,
            )
            await interaction.response.send_message(embed=embed)
            return

        user_map = await resolve_user_names(self.bot, interaction.guild, [u["user_id"] for u in leaders])
        per_page = 10
        total_pages = max(1, (len(leaders) + per_page - 1) // per_page)
        target_page = max(1, min(page or 1, total_pages))

        def make_user_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_users = leaders[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_users)
            embed = create_beastly_embed(
                title=f"🏆 BeastlyBank {curr_name} Leaderboard",
                description=(
                    f"High-rollers ranked by **{emoji} {curr_name}** in **{SERVER_NAME}**:\n"
                    f"Showing players **{start_idx + 1}–{end_idx}** of **{len(leaders)}** accounts\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            medals = ["🥇", "🥈", "🥉"]
            for idx, user_entry in enumerate(page_users, start=start_idx + 1):
                rank_icon = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                uid = user_entry["user_id"]
                display_name = user_map.get(uid, f"User-{str(uid)[-4:]}")
                balance = user_entry["balance"]
                embed.add_field(
                    name=f"{rank_icon} {display_name}",
                    value=f"{emoji} **{balance:,} {curr_name}**",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Leaderboard")
            return embed

        initial_embed = make_user_page(target_page)
        if total_pages <= 1:
            await interaction.response.send_message(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_user_page,
                total_pages=total_pages,
                author_id=interaction.user.id,
                current_page=target_page,
            )
            await interaction.response.send_message(embed=initial_embed, view=view)

    @commands.command(name="leaderboard", aliases=["lb", "top"])
    async def prefix_leaderboard(self, ctx: commands.Context, *args):
        """bb!leaderboard [category: cash|points|tokens|clubs] [page]"""
        category = "cash"
        target_page = 1

        for arg in args:
            clean = arg.lower().strip()
            if clean.isdigit():
                target_page = max(1, int(clean))
            elif clean in ("club", "clubs", "c"):
                category = "clubs"
            elif "point" in clean:
                category = "points"
            elif "token" in clean:
                category = "tokens"
            elif clean in ("cash", "money", "$"):
                category = "cash"

        if category == "clubs":
            clubs = await self.db.get_club_leaderboard(ctx.guild.id, limit=200)
            if not clubs:
                embed = create_beastly_embed(
                    title="🏆 BeastlyFC Club Treasury Leaderboard",
                    description=f"Top clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━\n\n*No clubs registered yet.*",
                    color=COLOR_BEASTLY_GOLD,
                )
                await ctx.send(embed=embed)
                return

            owner_map = await resolve_owner_names(self.bot, ctx.guild, clubs)
            per_page = 10
            total_pages = max(1, (len(clubs) + per_page - 1) // per_page)
            target_page = max(1, min(target_page, total_pages))

            def make_club_page(p: int) -> discord.Embed:
                start_idx = (p - 1) * per_page
                page_clubs = clubs[start_idx : start_idx + per_page]
                end_idx = start_idx + len(page_clubs)
                embed = create_beastly_embed(
                    title="🏆 BeastlyFC Club Treasury Leaderboard",
                    description=(
                        f"Clubs ranked by total treasury wealth in **{SERVER_NAME}**:\n"
                        f"Showing clubs **{start_idx + 1}–{end_idx}** of **{len(clubs)}** registered clubs\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━"
                    ),
                    color=COLOR_BEASTLY_GOLD,
                )
                medals = ["🥇", "🥈", "🥉"]
                for idx, c in enumerate(page_clubs, start=start_idx + 1):
                    rank_icon = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                    role_str = f" • <@&{c['role_id']}>" if c.get("role_id") else ""
                    owner_name = owner_map.get(c.get("owner_id", 0), "Vacant")
                    embed.add_field(
                        name=f"{rank_icon} [{c['tag']}] {c['name']}{role_str}",
                        value=(
                            f"👑 Owner: **{owner_name}** | 👥 Squad: `{c.get('member_count', 1)}`\n"
                            f"💵 Cash: `{c['treasury_cash']:,}` | ⭐ Points: `{c['treasury_points']:,}` | 🎟️ Tokens: `{c['treasury_tokens']:,}`"
                        ),
                        inline=False,
                    )
                embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyFC Club Leaderboard")
                return embed

            initial_embed = make_club_page(target_page)
            if total_pages <= 1:
                await ctx.send(embed=initial_embed)
            else:
                view = PaginationView(
                    embed_generator=make_club_page,
                    total_pages=total_pages,
                    author_id=ctx.author.id,
                    current_page=target_page,
                )
                await ctx.send(embed=initial_embed, view=view)
            return

        # User Leaderboard (cash, points, tokens)
        leaders = await self.db.get_leaderboard(ctx.guild.id, currency=category, limit=200)
        curr_info = CURRENCIES.get(category, {})
        emoji = curr_info.get("emoji", "💰")
        curr_name = curr_info.get("name", category.title())

        if not leaders:
            embed = create_beastly_embed(
                title=f"🏆 BeastlyBank {curr_name} Leaderboard",
                description=f"Top high-rollers ranked by **{emoji} {curr_name}** in **{SERVER_NAME}**:\n━━━━━━━━━━━━━━━━━━━━━━\n\n*No accounts found in BeastlyBank yet.*",
                color=COLOR_BEASTLY_GOLD,
            )
            await ctx.send(embed=embed)
            return

        user_map = await resolve_user_names(self.bot, ctx.guild, [u["user_id"] for u in leaders])
        per_page = 10
        total_pages = max(1, (len(leaders) + per_page - 1) // per_page)
        target_page = max(1, min(target_page, total_pages))

        def make_user_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_users = leaders[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_users)
            embed = create_beastly_embed(
                title=f"🏆 BeastlyBank {curr_name} Leaderboard",
                description=(
                    f"High-rollers ranked by **{emoji} {curr_name}** in **{SERVER_NAME}**:\n"
                    f"Showing players **{start_idx + 1}–{end_idx}** of **{len(leaders)}** accounts\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            medals = ["🥇", "🥈", "🥉"]
            for idx, user_entry in enumerate(page_users, start=start_idx + 1):
                rank_icon = medals[idx - 1] if idx <= 3 else f"`#{idx}`"
                uid = user_entry["user_id"]
                display_name = user_map.get(uid, f"User-{str(uid)[-4:]}")
                balance = user_entry["balance"]
                embed.add_field(
                    name=f"{rank_icon} {display_name}",
                    value=f"{emoji} **{balance:,} {curr_name}**",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Leaderboard")
            return embed

        initial_embed = make_user_page(target_page)
        if total_pages <= 1:
            await ctx.send(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_user_page,
                total_pages=total_pages,
                author_id=ctx.author.id,
                current_page=target_page,
            )
            await ctx.send(embed=initial_embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Leaderboard(bot))


