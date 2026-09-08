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
        current_page: int = 1,
        timeout: float = 120.0,
    ):
        super().__init__(timeout=timeout)
        self.embed_generator = embed_generator
        self.total_pages = max(1, total_pages)
        self.author_id = author_id
        self.current_page = max(1, min(current_page, self.total_pages))
        self._update_buttons()

    def _update_buttons(self) -> None:
        self.prev_button.disabled = self.current_page <= 1
        self.next_button.disabled = self.current_page >= self.total_pages

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.author_id and interaction.user.id != self.author_id:
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

    async def on_timeout(self) -> None:
        self.prev_button.disabled = True
        self.next_button.disabled = True


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


class HelpView(discord.ui.View):
    """Interactive tabs view for the official BeastlyBank /help command."""

    def __init__(
        self,
        db_manager,
        author: Optional[discord.Member] = None,
        active_tab: str = "guide",
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.db = db_manager
        self.author = author
        self.active_tab = active_tab
        self._sync_button_styles()

    def _sync_button_styles(self):
        """Highlight the currently active tab button and dim others."""
        target_tab = self.active_tab
        if target_tab in ("overview", "finances", "profile"):
            target_tab = "account"

        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == f"help_tab_{target_tab}":
                    child.style = discord.ButtonStyle.primary
                else:
                    child.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Help is a shared guide — anyone in the server can browse the reference manual
        return True

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="System Guide", style=discord.ButtonStyle.primary, emoji="📖", custom_id="help_tab_guide")
    async def guide_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import help_system_guide_embed
        self.active_tab = "guide"
        self._sync_button_styles()
        embed = help_system_guide_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cheatsheet", style=discord.ButtonStyle.secondary, emoji="📋", custom_id="help_tab_cheatsheet")
    async def cheatsheet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_commands_embed
        self.active_tab = "cheatsheet"
        self._sync_button_styles()
        embed = summary_commands_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Squad & Lineups", style=discord.ButtonStyle.secondary, emoji="⚽", custom_id="help_tab_squad")
    async def squad_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_squad_embed
        self.active_tab = "squad"
        self._sync_button_styles()
        embed = summary_squad_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Account Summary", style=discord.ButtonStyle.secondary, emoji="👤", custom_id="help_tab_account")
    async def account_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_overview_embed
        self.active_tab = "account"
        self._sync_button_styles()
        user_data = await self.db.get_or_create_user(interaction.user.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        embed = summary_overview_embed(interaction.user, user_data, club)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Server Stats", style=discord.ButtonStyle.secondary, emoji="🌐", custom_id="help_tab_stats")
    async def stats_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_economy_embed
        self.active_tab = "stats"
        self._sync_button_styles()
        stats = await self.db.get_economy_stats(interaction.guild_id)
        embed = summary_economy_embed(stats)
        await interaction.response.edit_message(embed=embed, view=self)


class SummaryView(discord.ui.View):
    """Interactive tabs view for BeastlyBank account summary and personal profile."""

    def __init__(
        self,
        db_manager,
        author: discord.Member,
        user_data: Dict[str, Any],
        club: Optional[Dict[str, Any]] = None,
        target: Optional[discord.Member] = None,
        active_tab: str = "overview",
        timeout: float = 180.0,
    ):
        super().__init__(timeout=timeout)
        self.db = db_manager
        self.author = author
        self.target = target or author
        self.user_data = user_data
        self.club = club
        self.active_tab = active_tab
        self._sync_button_styles()

    def _sync_button_styles(self):
        """Highlight active tab button and dim other tabs."""
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.custom_id == f"sum_tab_{self.active_tab}":
                    child.style = discord.ButtonStyle.primary
                else:
                    child.style = discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ You cannot control someone else's summary menu! Run `/summary` to view your own profile.",
                ephemeral=True,
            )
            return False
        return True

    async def on_timeout(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    @discord.ui.button(label="Overview", style=discord.ButtonStyle.primary, emoji="👤", custom_id="sum_tab_overview")
    async def overview_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_overview_embed
        self.active_tab = "overview"
        self._sync_button_styles()
        latest_user = await self.db.get_or_create_user(self.target.id, interaction.guild_id)
        latest_club = await self.db.get_club_by_user(interaction.guild_id, self.target.id)
        embed = summary_overview_embed(self.target, latest_user, latest_club)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Finances", style=discord.ButtonStyle.secondary, emoji="💰", custom_id="sum_tab_finances")
    async def finances_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_finance_embed
        self.active_tab = "finances"
        self._sync_button_styles()
        latest_user = await self.db.get_or_create_user(self.target.id, interaction.guild_id)
        latest_club = await self.db.get_club_by_user(interaction.guild_id, self.target.id)
        txs = await self.db.get_transactions(self.target.id, interaction.guild_id, limit=4)
        embed = summary_finance_embed(self.target, latest_user, latest_club, txs)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Squad Guide", style=discord.ButtonStyle.secondary, emoji="⚽", custom_id="sum_tab_squad")
    async def squad_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_squad_embed
        self.active_tab = "squad"
        self._sync_button_styles()
        embed = summary_squad_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Cheatsheet", style=discord.ButtonStyle.secondary, emoji="📖", custom_id="sum_tab_cheatsheet")
    async def cheatsheet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_commands_embed
        self.active_tab = "cheatsheet"
        self._sync_button_styles()
        embed = summary_commands_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stats", style=discord.ButtonStyle.secondary, emoji="🌐", custom_id="sum_tab_stats")
    async def economy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_economy_embed
        self.active_tab = "stats"
        self._sync_button_styles()
        stats = await self.db.get_economy_stats(interaction.guild_id)
        embed = summary_economy_embed(stats)
        await interaction.response.edit_message(embed=embed, view=self)


class AnnouncementView(discord.ui.View):
    """Interactive action buttons attached to official announcements."""

    def __init__(self, db_manager):
        super().__init__(timeout=None)
        self.db = db_manager

    @discord.ui.button(
        label="📖 Open /help Guide",
        style=discord.ButtonStyle.primary,
        custom_id="beastly_announcement_help_btn",
        emoji="📖",
    )
    async def help_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import help_system_guide_embed
        embed = help_system_guide_embed()
        view = HelpView(self.db, author=interaction.user, active_tab="guide")
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(
        label="💰 Check My Balance",
        style=discord.ButtonStyle.secondary,
        custom_id="beastly_announcement_bal_btn",
        emoji="💰",
    )
    async def balance_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import bank_card_embed
        account = await self.db.get_or_create_user(interaction.user.id, interaction.guild_id)
        club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)
        embed = bank_card_embed(interaction.user, account, club)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(
        label="⚽ Squad Lineup Guide",
        style=discord.ButtonStyle.success,
        custom_id="beastly_announcement_squad_btn",
        emoji="⚽",
    )
    async def squad_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        from utils.embeds import summary_squad_embed
        embed = summary_squad_embed()
        await interaction.response.send_message(embed=embed, ephemeral=True)
