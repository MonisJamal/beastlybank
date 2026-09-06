"""
Discord UI Views, Buttons, Select Menus, and Interactive Components.
"""
from typing import Any, Callable, Dict, List, Optional
import discord
from config import BOT_NAME, CURRENCIES


class PaginationView(discord.ui.View):
    """Universal pagination view for embeds."""

    def __init__(
        self,
        embed_generator: Callable[[int], discord.Embed],
        total_pages: int,
        author_id: int,
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.embed_generator = embed_generator
        self.total_pages = max(1, total_pages)
        self.author_id = author_id
        self.current_page = 1
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "❌ You cannot control someone else's navigation menu!", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 1:
            self.current_page -= 1
            self._update_buttons()
            embed = self.embed_generator(self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self._update_buttons()
            embed = self.embed_generator(self.current_page)
            await interaction.response.edit_message(embed=embed, view=self)


class GiveawayView(discord.ui.View):
    """Persistent Giveaway entry button."""

    def __init__(self, db_manager):
        super().__init__(timeout=None)
        self.db = db_manager

    @discord.ui.button(
        label="🎉 Enter Beastly Giveaway",
        style=discord.ButtonStyle.success,
        custom_id="beastly_giveaway_enter_btn",
    )
    async def enter_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        msg_id = interaction.message.id if interaction.message else 0
        success, message, count = await self.db.toggle_giveaway_entry(
            msg_id, interaction.user.id
        )

        if not success:
            await interaction.response.send_message(f"❌ {message}", ephemeral=True)
            return

        # Update button label to display live entries count
        button.label = f"🎉 Enter Giveaway ({count})"
        try:
            await interaction.message.edit(view=self)
        except Exception:
            pass

        await interaction.response.send_message(f"✅ {message}", ephemeral=True)


class SummaryView(discord.ui.View):
    """Interactive tabs view for BeastlyBank summary."""

    def __init__(
        self,
        db_manager,
        author: discord.Member,
        user_data: Dict[str, Any],
        club: Optional[Dict[str, Any]] = None,
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.db = db_manager
        self.author = author
        self.user_data = user_data
        self.club = club

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ You cannot control someone else's summary menu! Run `/summary` to view your own.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.primary, emoji="📋")
    async def overview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_overview_embed
        embed = summary_overview_embed(self.author, self.user_data, self.club)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Squad & Lineup", style=discord.ButtonStyle.success, emoji="⚽")
    async def squad_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_squad_embed
        embed = summary_squad_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cheatsheet", style=discord.ButtonStyle.secondary, emoji="📖")
    async def cheatsheet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_commands_embed
        embed = summary_commands_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Finances", style=discord.ButtonStyle.secondary, emoji="💰")
    async def finances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_finance_embed
        latest_user = await self.db.get_or_create_user(self.author.id, interaction.guild_id)
        latest_club = await self.db.get_club_by_user(interaction.guild_id, self.author.id)
        txs = await self.db.get_transactions(self.author.id, interaction.guild_id, limit=4)
        embed = summary_finance_embed(self.author, latest_user, latest_club, txs)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stats", style=discord.ButtonStyle.secondary, emoji="🌐")
    async def economy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_economy_embed
        stats = await self.db.get_economy_stats(interaction.guild_id)
        embed = summary_economy_embed(stats)
        await interaction.response.edit_message(embed=embed, view=self)
