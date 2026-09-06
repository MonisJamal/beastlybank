"""
Economy Cog: Balances, Payments, Daily Salaries, Work Drills, and Transaction Records.
"""
import math
import random
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    CURRENCIES,
    FOOTBALL_JOBS,
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
)
from utils.views import PaginationView, SummaryView


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
        name="daily",
        description="Claim your daily BeastlyBank salary.",
    )
    @require_beastlyfc()
    async def daily(self, interaction: discord.Interaction):
        success, msg, data = await self.db.claim_daily(
            interaction.user.id, interaction.guild_id
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Daily Already Claimed", msg),
                ephemeral=True,
            )
            return

        cash_earned = data["cash_earned"]
        points_earned = data["points_earned"]

        embed = create_beastly_embed(
            title="📅 Daily Salary Deposited!",
            description=(
                f"Welcome back to **{SERVER_NAME}**, {interaction.user.mention}!\n\n"
                f"💵 **Cash Credited:** `+{cash_earned:,}`\n"
                f"⭐ **Community Points:** `+{points_earned:,}`\n\n"
                f"🏦 *Funds deposited into your BeastlyBank account.*"
            ),
            color=COLOR_BEASTLY_GOLD,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="work",
        description="Participate in a BeastlyFC training drill or matchday task to earn rewards.",
    )
    @require_beastlyfc()
    async def work(self, interaction: discord.Interaction):
        job = random.choice(FOOTBALL_JOBS)
        success, msg, data = await self.db.claim_work(
            interaction.user.id, interaction.guild_id, job
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Rest & Recovery", msg),
                ephemeral=True,
            )
            return

        cash_earned = data["cash_earned"]
        points_earned = data["points_earned"]
        tokens_earned = data["tokens_earned"]

        token_line = f"\n🎟️ **Bonus Training Tokens:** `+{tokens_earned:,}`" if tokens_earned > 0 else ""

        embed = create_beastly_embed(
            title=f"⚽ Drill Completed: {job['title']}",
            description=(
                f"{job['desc']}\n\n"
                f"💵 **Cash Payout:** `+{cash_earned:,}`\n"
                f"⭐ **Points Earned:** `+{points_earned:,}`"
                f"{token_line}\n\n"
                f"*Funds have been deposited into your BeastlyBank vault.*"
            ),
            color=COLOR_PITCH_GREEN,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="transactions",
        description="View official BeastlyBank transaction statement and financial history.",
    )
    @app_commands.describe(user="The member whose statement to inspect (default: yourself)")
    @require_beastlyfc()
    async def transactions(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        total_txs = await self.db.get_total_transactions_count(
            target.id, interaction.guild_id
        )
        page_size = 5
        total_pages = max(1, math.ceil(total_txs / page_size))

        async def get_page_txs(page_num: int):
            offset = (page_num - 1) * page_size
            return await self.db.get_transactions(
                target.id, interaction.guild_id, limit=page_size, offset=offset
            )

        initial_txs = await get_page_txs(1)
        initial_embed = transaction_history_embed(
            target, initial_txs, 1, total_pages
        )

        if total_pages <= 1:
            await interaction.response.send_message(embed=initial_embed)
            return

        # Multi-page View
        def page_embed_generator(page_num: int) -> discord.Embed:
            # Synchronous generator wrapper called by View
            import asyncio
            txs = asyncio.run_coroutine_threadsafe(
                get_page_txs(page_num), self.bot.loop
            ).result()
            return transaction_history_embed(target, txs, page_num, total_pages)

        view = PaginationView(
            embed_generator=page_embed_generator,
            total_pages=total_pages,
            author_id=interaction.user.id,
        )
        await interaction.response.send_message(embed=initial_embed, view=view)

    @app_commands.command(
        name="redeemcp",
        description="Convert your Community Points into Cash (Exchange rate: 1 CP = 2 Cash).",
    )
    @app_commands.describe(points="Amount of Community Points (CP) to convert into Cash")
    @require_beastlyfc()
    async def redeemcp(self, interaction: discord.Interaction, points: int):
        settings = await self.db.get_settings(interaction.guild_id)
        if not settings.get("economy_enabled", 1):
            await interaction.response.send_message(
                embed=error_embed("Economy Paused", "The server economy is currently paused by administrators."),
                ephemeral=True,
            )
            return

        success, msg, data = await self.db.redeem_cp(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            points_amount=points,
            rate=2,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Redemption Failed", msg),
                ephemeral=True,
            )
            return

        embed = create_beastly_embed(
            title="⭐ Community Points Converted!",
            description=(
                f"{interaction.user.mention} successfully converted ⭐ **{points:,} CP** "
                f"into 💵 **{data['cash_received']:,} Cash**!\n\n"
                f"📊 **New Balances:**\n"
                f"• 💵 Cash: `{data['user']['cash']:,}`\n"
                f"• ⭐ CP: `{data['user']['points']:,}`\n\n"
                f"🏦 *Transaction logged in BeastlyBank automated ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="summary",
        description="View a simple, clear summary of BeastlyBank commands and your account status.",
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

        # If inspecting someone else, show their financial statement
        if user and user.id != interaction.user.id:
            txs = await self.db.get_transactions(target.id, interaction.guild_id, limit=4)
            embed = summary_finance_embed(target, user_data, club, txs)
            await interaction.response.send_message(embed=embed)
            return

        # Main overview summary with interactive buttons
        embed = summary_overview_embed(target, user_data, club)
        view = SummaryView(self.db, target, user_data, club)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(
        name="help",
        description="View a simple guide and summary of all BeastlyBank commands.",
    )
    @require_beastlyfc()
    async def help_command(
        self,
        interaction: discord.Interaction,
    ):
        """Simple command guide and cheatsheet."""
        user_data = await self.db.get_or_create_user(interaction.user.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        embed = summary_overview_embed(interaction.user, user_data, club)
        view = SummaryView(self.db, interaction.user, user_data, club)
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
    async def prefix_pay(self, ctx: commands.Context, recipient: discord.Member, currency: str, amount: str, *, reason: Optional[str] = None):
        """bb!pay <@user> <cash|tokens> <amount> [reason]"""
        c_low = currency.lower().strip()
        if c_low not in ("cash", "tokens", "token"):
            await ctx.send(embed=error_embed("Invalid Currency", "Currency must be `cash` or `tokens`."))
            return
        curr_key = "tokens" if "token" in c_low else "cash"
        parsed = parse_amount(amount)
        if parsed is None or parsed <= 0:
            await ctx.send(embed=error_embed("Invalid Amount", f"Invalid amount: `{amount}`"))
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
            reason=reason,
        )
        if not success:
            await ctx.send(embed=error_embed("Transfer Failed", msg))
            return
        curr_info = CURRENCIES.get(curr_key, {})
        emoji = curr_info.get("emoji", "💰")
        embed = success_embed(
            "Transfer Completed",
            f"Successfully transferred {emoji} **{parsed:,}** to {recipient.mention}!\n"
            f"📝 *Memo: {reason or 'Direct Transfer'}*",
        )
        await ctx.send(embed=embed)

    @commands.command(name="daily")
    async def prefix_daily(self, ctx: commands.Context):
        """bb!daily"""
        success, msg, data = await self.db.claim_daily(ctx.author.id, ctx.guild.id)
        if not success:
            await ctx.send(embed=error_embed("Daily Claim", msg))
            return
        embed = create_beastly_embed(
            title="📅 Daily Salary Received!",
            description=(
                f"{ctx.author.mention}, your daily BeastlyFC salary has been deposited into your BeastlyBank account!\n\n"
                f"💵 **Cash Earned:** `+{data['cash_earned']:,}`\n"
                f"⭐ **Community Points:** `+{data['points_earned']:,}`\n"
                f"📊 **New Cash Balance:** `{data['user']['cash']:,}`"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="work", aliases=["drill"])
    async def prefix_work(self, ctx: commands.Context):
        """bb!work"""
        job = random.choice(FOOTBALL_JOBS)
        success, msg, data = await self.db.claim_work(ctx.author.id, ctx.guild.id, job)
        if not success:
            await ctx.send(embed=error_embed("Training Recovery", msg))
            return
        embed = create_beastly_embed(
            title=f"⚽ Training Drill: {job['title']}",
            description=(
                f"{ctx.author.mention} {job['desc']}\n\n"
                f"💵 **Cash Payout:** `+{data['cash_earned']:,}`\n"
                f"⭐ **Points Payout:** `+{data['points_earned']:,}`"
                + (f"\n🎟️ **Bonus Token:** `+{data['tokens_earned']}`" if data["tokens_earned"] > 0 else "")
                + f"\n\n📊 **Updated Cash Balance:** `{data['user']['cash']:,}`"
            ),
            color=COLOR_PITCH_GREEN,
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
        if user and user.id != ctx.author.id:
            txs = await self.db.get_transactions(target.id, ctx.guild.id, limit=4)
            embed = summary_finance_embed(target, user_data, club, txs)
            await ctx.send(embed=embed)
            return
        embed = summary_overview_embed(target, user_data, club)
        view = SummaryView(self.db, target, user_data, club)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="help", aliases=["guide"])
    async def prefix_help(self, ctx: commands.Context):
        """bb!help"""
        user_data = await self.db.get_or_create_user(ctx.author.id, ctx.guild.id)
        club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)
        embed = summary_overview_embed(ctx.author, user_data, club)
        view = SummaryView(self.db, ctx.author, user_data, club)
        await ctx.send(embed=embed, view=view)

    @commands.command(name="transactions", aliases=["txs"])
    async def prefix_transactions(self, ctx: commands.Context, user: Optional[discord.Member] = None):
        """bb!transactions [user]"""
        target = user or ctx.author
        total_txs = await self.db.get_total_transactions_count(target.id, ctx.guild.id)
        if total_txs == 0:
            await ctx.send(embed=error_embed("No History", f"No transaction history found for {target.mention}."))
            return
        txs = await self.db.get_transactions(target.id, ctx.guild.id, limit=6, offset=0)
        embed = transaction_history_embed(target, txs, page=1, total_pages=math.ceil(total_txs / 6), total_count=total_txs)
        await ctx.send(embed=embed)

    @commands.command(name="redeemcp", aliases=["rcp"])
    async def prefix_redeemcp(self, ctx: commands.Context, amount: str):
        """bb!redeemcp <amount>"""
        parsed = parse_amount(amount)
        if parsed is None or parsed <= 0:
            await ctx.send(embed=error_embed("Invalid Amount", f"Invalid amount: `{amount}`"))
            return
        success, msg, data = await self.db.redeem_cp(ctx.author.id, ctx.guild.id, parsed, rate=2)
        if not success:
            await ctx.send(embed=error_embed("Redemption Failed", msg))
            return
        embed = create_beastly_embed(
            title="⭐ Community Points Converted!",
            description=(
                f"{ctx.author.mention} converted ⭐ **{parsed:,} CP** into 💵 **{data['cash_received']:,} Cash**!\n\n"
                f"• 💵 Cash: `{data['user']['cash']:,}`\n"
                f"• ⭐ CP: `{data['user']['points']:,}`"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))

