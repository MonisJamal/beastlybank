"""
Economy Cog: Balances, Payments, and Transaction Records.
"""
import math
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    CURRENCIES,
    COLOR_SUCCESS,
    COLOR_BEASTLY_GOLD,
    COLOR_PITCH_GREEN,
    SERVER_NAME,
    parse_amount,
)
from utils.checks import require_beastlyfc
from utils.embeds import (
    bank_card_embed,
    create_beastly_embed,
    error_embed,
    success_embed,
    transaction_history_embed,
    summary_overview_embed,
    summary_finance_embed,
    summary_commands_embed,
    summary_economy_embed,
    summary_squad_embed,
    help_system_guide_embed,
    resolve_user_names,
    safe_defer,
    send_msg,
)
from utils.views import PaginationView, SummaryView, HelpView


class Economy(commands.Cog):
    """Core economy features of BeastlyBank."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="balance",
        description="Check your official BeastlyBank account balances, card, and club affiliation.",
    )
    @app_commands.describe(user="The server member whose balance you want to check (default: yourself)")
    @require_beastlyfc()
    async def balance(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message(
                embed=error_embed("Invalid Account", "Automated Discord bots do not hold BeastlyBank accounts."),
                ephemeral=True,
            )
            return

        account = await self.db.get_or_create_user(target.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, target.id)

        embed = bank_card_embed(target, account, club)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="pay",
        description="Send Cash or Training Tokens to another BeastlyFC member.",
    )
    @app_commands.describe(
        recipient="The player to receive the payment",
        currency="Currency to send (Cash or Training Tokens)",
        amount="The amount of currency to send",
        reason="Optional memo for the transaction history",
    )
    @require_beastlyfc()
    async def pay(
        self,
        interaction: discord.Interaction,
        recipient: discord.Member,
        currency: Literal["cash", "tokens"],
        amount: int,
        reason: Optional[str] = None,
    ):
        settings = await self.db.get_settings(interaction.guild_id)
        if not settings.get("economy_enabled", 1):
            await interaction.response.send_message(
                embed=error_embed("Economy Paused", "The server economy is currently paused by administrators."),
                ephemeral=True,
            )
            return

        if recipient.bot:
            await interaction.response.send_message(
                embed=error_embed("Transfer Error", "You cannot transfer funds to Discord bots!"),
                ephemeral=True,
            )
            return

        if recipient.id == interaction.user.id:
            await interaction.response.send_message(
                embed=error_embed("Transfer Error", "You cannot transfer funds to yourself!"),
                ephemeral=True,
            )
            return

        if amount <= 0:
            await interaction.response.send_message(
                embed=error_embed("Transfer Error", "Transfer amount must be greater than 0."),
                ephemeral=True,
            )
            return

        success, msg = await self.db.transfer(
            sender_id=interaction.user.id,
            receiver_id=recipient.id,
            guild_id=interaction.guild_id,
            currency=currency,
            amount=amount,
            reason=reason,
        )

        curr_info = CURRENCIES.get(currency, {})
        emoji = curr_info.get("emoji", "💰")
        name = curr_info.get("name", currency.title())

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Transfer Failed", msg),
                ephemeral=True,
            )
            return

        # Success Receipt
        embed = create_beastly_embed(
            title="💸 Payment Successful",
            description=(
                f"**{interaction.user.mention}** has transferred {emoji} **{amount:,} {name}** to **{recipient.mention}**!\n\n"
                f"📝 **Memo:** *{reason or 'Player-to-player transfer'}*\n"
                f"🏦 *Transaction recorded in BeastlyBank automated ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="transactions",
        description="View official BeastlyBank transaction statement and financial history.",
    )
    @app_commands.describe(
        user="The member whose statement to inspect (default: yourself)",
        page="Page number to view (default: 1)",
    )
    @require_beastlyfc()
    async def transactions(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        page: Optional[int] = 1,
    ):
        await safe_defer(interaction)
        target = user or interaction.user
        total_txs = await self.db.get_total_transactions_count(
            target.id, interaction.guild_id
        )
        page_size = 5
        total_pages = max(1, math.ceil(total_txs / page_size))
        current_page = max(1, min(page or 1, total_pages))

        async def get_page_txs(page_num: int):
            offset = (page_num - 1) * page_size
            return await self.db.get_transactions(
                target.id, interaction.guild_id, limit=page_size, offset=offset
            )

        initial_txs = await get_page_txs(current_page)
        user_ids = {t["sender_id"] for t in initial_txs if t.get("sender_id")} | {t["receiver_id"] for t in initial_txs if t.get("receiver_id")}
        user_map = await resolve_user_names(self.bot, interaction.guild, user_ids)
        initial_embed = transaction_history_embed(
            target, initial_txs, current_page, total_pages, user_names=user_map
        )

        if total_pages <= 1:
            await send_msg(interaction, embed=initial_embed)
            return

        # Multi-page View (fully async, non-blocking)
        async def page_embed_generator(page_num: int) -> discord.Embed:
            txs = await get_page_txs(page_num)
            p_ids = {t["sender_id"] for t in txs if t.get("sender_id")} | {t["receiver_id"] for t in txs if t.get("receiver_id")}
            p_map = await resolve_user_names(self.bot, interaction.guild, p_ids)
            return transaction_history_embed(target, txs, page_num, total_pages, user_names=p_map)

        view = PaginationView(
            embed_generator=page_embed_generator,
            total_pages=total_pages,
            author_id=interaction.user.id,
            current_page=current_page,
        )
        await send_msg(interaction, embed=initial_embed, view=view)

    @app_commands.command(
        name="summary",
        description="View your personal account and financial profile summary.",
    )
    @app_commands.describe(
        user="Optional member to view their financial summary (defaults to yourself)",
    )
    @require_beastlyfc()
    async def summary(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        if target.bot:
            await interaction.response.send_message(
                embed=error_embed("Invalid Account", "Automated Discord bots do not hold BeastlyBank accounts."),
                ephemeral=True,
            )
            return

        user_data = await self.db.get_or_create_user(target.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, target.id)

        # Overview summary with interactive buttons
        embed = summary_overview_embed(target, user_data, club)
        view = SummaryView(self.db, author=interaction.user, user_data=user_data, club=club, target=target)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="help",
        description="View the interactive guide, cheatsheet, and full command reference for BeastlyBank.",
    )
    @app_commands.describe(
        category="Specific section to view (guide, squad, cheatsheet, stats, overview, finances)",
    )
    @require_beastlyfc()
    async def help_command(
        self,
        interaction: discord.Interaction,
        category: Optional[Literal["guide", "overview", "squad", "cheatsheet", "finances", "stats"]] = "guide",
    ):
        """Interactive command guide, cheatsheet, and account overview."""
        cat = (category or "guide").lower().strip()
        active_tab = "guide"
        if cat in ("squad", "lineup", "formation", "player", "players"):
            embed = summary_squad_embed()
            active_tab = "squad"
        elif cat in ("cheatsheet", "commands", "cmds", "cmd"):
            embed = summary_commands_embed()
            active_tab = "cheatsheet"
        elif cat in ("stats", "economy", "server"):
            stats = await self.db.get_economy_stats(interaction.guild_id)
            embed = summary_economy_embed(stats)
            active_tab = "stats"
        elif cat in ("finances", "finance"):
            user_data = await self.db.get_or_create_user(interaction.user.id, interaction.guild_id)
            club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
            txs = await self.db.get_transactions(interaction.user.id, interaction.guild_id, limit=4)
            embed = summary_finance_embed(interaction.user, user_data, club, txs)
            active_tab = "account"
        elif cat in ("overview", "account", "profile"):
            user_data = await self.db.get_or_create_user(interaction.user.id, interaction.guild_id)
            club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
            embed = summary_overview_embed(interaction.user, user_data, club)
            active_tab = "account"
        else:
            embed = help_system_guide_embed()
            active_tab = "guide"

        view = HelpView(self.db, author=interaction.user, active_tab=active_tab)
        await interaction.response.send_message(embed=embed, view=view)


    # ------------------ Prefix Commands (bb!) ------------------ #

    @commands.command(name="balance", aliases=["bal", "b"])
    async def prefix_balance(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """bb!balance [user]"""
        target = user or ctx.author
        if target.bot:
            await ctx.send(embed=error_embed("Invalid Account", "Bots do not hold BeastlyBank accounts."))
            return
        account = await self.db.get_or_create_user(target.id, ctx.guild.id)
        club = await self.db.get_club_by_user(ctx.guild.id, target.id)
        embed = bank_card_embed(target, account, club)
        await ctx.send(embed=embed)

    @commands.command(name="pay")
    async def prefix_pay(self, ctx: commands.Context, recipient: discord.Member, arg1: str, arg2: Optional[str] = None, *, reason: Optional[str] = None):
        """bb!pay <@user> <amount> [currency=cash] [reason] OR bb!pay <@user> <currency> <amount> [reason]"""
        curr_key = "cash"
        amount_str = None
        memo = reason

        c1 = arg1.lower().strip()
        p1 = parse_amount(arg1)

        if c1 in ("cash", "tokens", "token"):
            curr_key = "tokens" if "token" in c1 else "cash"
            if arg2:
                amount_str = arg2
            else:
                await ctx.send(embed=error_embed("Missing Amount", "Please provide the amount to transfer: `bb!pay @user [currency] <amount> [reason]`"))
                return
        elif p1 is not None and p1 > 0:
            amount_str = arg1
            if arg2:
                c2 = arg2.lower().strip()
                if c2 in ("cash", "tokens", "token"):
                    curr_key = "tokens" if "token" in c2 else "cash"
                else:
                    memo = f"{arg2} {reason}" if reason else arg2
        else:
            await ctx.send(embed=error_embed(
                "Invalid Amount",
                f"Invalid amount or format: `{arg1}`.\n\n"
                "**Supported Formats:**\n"
                "• `bb!pay @user 5000` (defaults to Cash)\n"
                "• `bb!pay @user 26e6 tokens Prize money`\n"
                "• `bb!pay @user cash 500k`"
            ))
            return

        parsed = parse_amount(amount_str)
        if parsed is None or parsed <= 0:
            await ctx.send(embed=error_embed("Invalid Amount", f"Invalid amount: `{amount_str}`"))
            return

        if recipient.bot or recipient.id == ctx.author.id:
            await ctx.send(embed=error_embed("Transfer Error", "You cannot send money to bots or yourself!"))
            return

        success, msg = await self.db.transfer(
            sender_id=ctx.author.id,
            receiver_id=recipient.id,
            guild_id=ctx.guild.id,
            currency=curr_key,
            amount=parsed,
            reason=memo,
        )
        if not success:
            await ctx.send(embed=error_embed("Transfer Failed", msg))
            return

        curr_info = CURRENCIES.get(curr_key, {})
        emoji = curr_info.get("emoji", "💰")
        embed = success_embed(
            "Transfer Completed",
            f"Successfully transferred {emoji} **{parsed:,} {curr_info.get('name', 'Cash')}** to {recipient.mention}!\n"
            f"📝 *Memo: {memo or 'Direct Transfer'}*",
        )
        await ctx.send(embed=embed)

    @commands.command(name="summary", aliases=["profile"])
    async def prefix_summary(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """bb!summary [user]"""
        target = user or ctx.author
        if target.bot:
            await ctx.send(embed=error_embed("Invalid Account", "Bots do not hold bank accounts."))
            return
        user_data = await self.db.get_or_create_user(target.id, ctx.guild.id)
        club = await self.db.get_club_by_user(ctx.guild.id, target.id)
        embed = summary_overview_embed(target, user_data, club)
        view = SummaryView(self.db, author=ctx.author, user_data=user_data, club=club, target=target)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="help", aliases=["guide"])
    async def prefix_help(self, ctx: commands.Context, category: Optional[str] = None):
        """bb!help [category: guide|squad|cheatsheet|stats|account]"""
        cat = (category or "guide").lower().strip()
        active_tab = "guide"
        if cat in ("squad", "lineup", "formation", "player", "players"):
            embed = summary_squad_embed()
            active_tab = "squad"
        elif cat in ("cheatsheet", "commands", "cmds", "cmd"):
            embed = summary_commands_embed()
            active_tab = "cheatsheet"
        elif cat in ("stats", "economy", "server"):
            stats = await self.db.get_economy_stats(ctx.guild.id)
            embed = summary_economy_embed(stats)
            active_tab = "stats"
        elif cat in ("finances", "finance", "myfinances", "balance", "bal"):
            user_data = await self.db.get_or_create_user(ctx.author.id, ctx.guild.id)
            club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
            txs = await self.db.get_transactions(ctx.author.id, ctx.guild.id, limit=4)
            embed = summary_finance_embed(ctx.author, user_data, club, txs)
            active_tab = "account"
        elif cat in ("overview", "account", "profile"):
            user_data = await self.db.get_or_create_user(ctx.author.id, ctx.guild.id)
            club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
            embed = summary_overview_embed(ctx.author, user_data, club)
            active_tab = "account"
        else:
            embed = help_system_guide_embed()
            active_tab = "guide"

        view = HelpView(self.db, author=ctx.author, active_tab=active_tab)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="transactions", aliases=["txs"])
    async def prefix_transactions(self, ctx: commands.Context, *args):
        """bb!transactions [user] [page]"""
        target = ctx.author
        target_page = 1

        for arg in args:
            clean = arg.strip()
            if clean.isdigit() and len(clean) <= 5:
                target_page = max(1, int(clean))
            elif ctx.guild:
                member_id = None
                if clean.startswith("<@") and clean.endswith(">"):
                    raw = clean.strip("<@!>")
                    if raw.isdigit():
                        member_id = int(raw)
                elif clean.isdigit() and len(clean) > 14:
                    member_id = int(clean)

                if member_id:
                    m = ctx.guild.get_member(member_id)
                    if m:
                        target = m
                else:
                    m = ctx.guild.get_member_named(clean)
                    if m:
                        target = m

        if ctx.message.mentions:
            target = ctx.message.mentions[0]

        total_txs = await self.db.get_total_transactions_count(target.id, ctx.guild.id)
        if total_txs == 0:
            await ctx.send(embed=error_embed("No History", f"No transaction history found for {target.mention}."))
            return

        page_size = 5
        total_pages = max(1, math.ceil(total_txs / page_size))
        target_page = max(1, min(target_page, total_pages))

        async def get_page_txs(page_num: int):
            offset = (page_num - 1) * page_size
            return await self.db.get_transactions(
                target.id, ctx.guild.id, limit=page_size, offset=offset
            )

        initial_txs = await get_page_txs(target_page)
        user_ids = {t["sender_id"] for t in initial_txs if t.get("sender_id")} | {t["receiver_id"] for t in initial_txs if t.get("receiver_id")}
        user_map = await resolve_user_names(self.bot, ctx.guild, user_ids)
        initial_embed = transaction_history_embed(
            target, initial_txs, target_page, total_pages, user_names=user_map
        )

        if total_pages <= 1:
            await send_msg(ctx, embed=initial_embed)
            return

        # Multi-page View (fully async, non-blocking)
        async def page_embed_generator(page_num: int) -> discord.Embed:
            txs = await get_page_txs(page_num)
            p_ids = {t["sender_id"] for t in txs if t.get("sender_id")} | {t["receiver_id"] for t in txs if t.get("receiver_id")}
            p_map = await resolve_user_names(self.bot, ctx.guild, p_ids)
            return transaction_history_embed(target, txs, page_num, total_pages, user_names=p_map)

        view = PaginationView(
            embed_generator=page_embed_generator,
            total_pages=total_pages,
            author_id=ctx.author.id,
            current_page=target_page,
        )
        await send_msg(ctx, embed=initial_embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))

