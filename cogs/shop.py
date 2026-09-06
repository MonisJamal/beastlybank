"""
Shop and Inventory Cog: Server store, upgrades, perks, roles, and inventory inspection.
"""
from typing import Literal, Optional
import discord
from discord import app_commands
from discord.ext import commands

from config import CURRENCIES, COLOR_BEASTLY_GOLD, COLOR_PITCH_GREEN, COLOR_SUCCESS
from utils.checks import require_beastlyfc, require_banker_or_admin
from utils.embeds import create_beastly_embed, error_embed, success_embed


class Shop(commands.Cog):
    """BeastlyBank Server Shop and Inventory Management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="shop",
        description="Browse the official BeastlyFC Server Shop for perks, roles, and boosts.",
    )
    @require_beastlyfc()
    async def shop(self, interaction: discord.Interaction):
        items = await self.db.get_shop_items(interaction.guild_id)

        embed = create_beastly_embed(
            title="🛒 BeastlyBank Official Store",
            description=(
                "Spend your **Cash**, **Community Points**, and **Training Tokens** here!\n"
                "Use `/buy <item_id>` to purchase any item.\n━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=COLOR_BEASTLY_GOLD,
        )

        if not items:
            embed.description += "\n*The BeastlyBank shop is currently being restocked!*"
            await interaction.response.send_message(embed=embed)
            return

        for itm in items:
            curr_info = CURRENCIES.get(itm["currency"], {})
            emoji = curr_info.get("emoji", "💰")
            stock_str = "Unlimited" if itm["stock"] == -1 else f"{itm['stock']} remaining"

            embed.add_field(
                name=f"#{itm['id']} • {itm['name']} — {emoji} {itm['price']:,}",
                value=f"{itm['description']}\n📦 **Stock:** `{stock_str}` | 🏷️ **Type:** `{itm.get('category', 'Perk')}`",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="buy",
        description="Purchase an item from the BeastlyBank Shop.",
    )
    @app_commands.describe(
        item_id="The ID number of the item (e.g., 1, 2, 3)",
        quantity="How many of this item to buy (default: 1)",
    )
    @require_beastlyfc()
    async def buy(
        self,
        interaction: discord.Interaction,
        item_id: int,
        quantity: int = 1,
    ):
        if quantity <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Quantity", "Quantity must be at least 1."),
                ephemeral=True,
            )
            return

        success, msg, item = await self.db.buy_item(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            item_id=item_id,
            quantity=quantity,
        )

        if not success:
            await interaction.response.send_message(
                embed=error_embed("Purchase Failed", msg),
                ephemeral=True,
            )
            return

        # Check if item includes an automatic Discord role reward
        role_reward_msg = ""
        if item and item.get("role_reward_id") and interaction.guild:
            role = interaction.guild.get_role(item["role_reward_id"])
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.add_roles(role, reason=f"BeastlyBank Shop purchase: {item['name']}")
                    role_reward_msg = f"\n🎖️ **Role Granted:** You have received the {role.mention} role!"
                except Exception:
                    role_reward_msg = f"\n⚠️ *Note: Bot lacks permissions to automatically assign role `{role.name}`.*"

        embed = create_beastly_embed(
            title="🛍️ Purchase Successful!",
            description=(
                f"**{interaction.user.mention}** successfully bought **{quantity}x {item['name']}**!\n"
                f"Item added to your `/inventory`.{role_reward_msg}\n\n"
                f"🏦 *Transaction logged in BeastlyBank ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="inventory",
        description="Inspect items, perks, and upgrades in your personal stash.",
    )
    @app_commands.describe(user="The member whose inventory to check (default: yourself)")
    @require_beastlyfc()
    async def inventory(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
    ):
        target = user or interaction.user
        items = await self.db.get_inventory(target.id, interaction.guild_id)

        embed = create_beastly_embed(
            title=f"🎒 Inventory • {target.display_name}",
            description=f"Personal perks and inventory items for {target.mention}.\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_PITCH_GREEN,
        )

        if not items:
            embed.description += "\n*Inventory is empty! Browse `/shop` to purchase items and perks.*"
            await interaction.response.send_message(embed=embed)
            return

        for itm in items:
            embed.add_field(
                name=f"{itm['name']} (x{itm['quantity']})",
                value=f"{itm['description']}\n📅 *Acquired:* `{itm['acquired_at'][:10]}`",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)


class ShopAdmin(commands.GroupCog, name="shop-admin", description="Banker & Staff Shop Management"):
    """Staff commands to maintain the store inventory."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="add",
        description="Add a new item to the BeastlyBank Shop catalogue.",
    )
    @app_commands.describe(
        name="Display name of the item",
        description="Short description of the perk or item",
        price="Price in chosen currency",
        currency="Currency accepted for purchase",
        stock="Stock quantity (-1 for unlimited)",
        role="Discord role to automatically grant upon purchase (optional)",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def shop_add(
        self,
        interaction: discord.Interaction,
        name: str,
        description: str,
        price: int,
        currency: Literal["cash", "points", "tokens"],
        stock: int = -1,
        role: Optional[discord.Role] = None,
    ):
        if price <= 0:
            await interaction.response.send_message(
                embed=error_embed("Invalid Price", "Price must be greater than 0."),
                ephemeral=True,
            )
            return

        conn = await self.db.connect()
        role_id = role.id if role else None
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO shop_items (guild_id, name, description, price, currency, role_reward_id, stock, category)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Custom');
                """,
                (interaction.guild_id, name, description, price, currency, role_id, stock),
            )
            await conn.commit()

        curr_emoji = CURRENCIES[currency]["emoji"]
        embed = success_embed(
            "Item Added to Shop",
            f"Successfully added **{name}** for {curr_emoji} **{price:,}** to the BeastlyBank catalogue.",
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="remove",
        description="Remove an item from the BeastlyBank Shop catalogue.",
    )
    @app_commands.describe(item_id="ID of the shop item to remove")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def shop_remove(
        self,
        interaction: discord.Interaction,
        item_id: int,
    ):
        conn = await self.db.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "DELETE FROM shop_items WHERE id = ? AND (guild_id = ? OR guild_id = 0);",
                (item_id, interaction.guild_id),
            )
            changes = conn.total_changes
            await conn.commit()

        embed = success_embed(
            "Item Removed",
            f"Item #{item_id} has been removed from the BeastlyBank Shop.",
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
    await bot.add_cog(ShopAdmin(bot))
