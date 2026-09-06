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


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))

