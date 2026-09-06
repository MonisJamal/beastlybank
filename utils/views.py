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
