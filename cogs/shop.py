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
from utils.views import PaginationView


class Shop(commands.Cog):
    """BeastlyBank Server Shop and Inventory Management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db  # type: ignore

    @app_commands.command(
        name="shop",
        description="Browse the official BeastlyFC Server Shop for perks, roles, and boosts.",
    )
    @app_commands.describe(page="Page number to view (default: 1)")
    @require_beastlyfc()
    async def shop(self, interaction: discord.Interaction, page: Optional[int] = 1):
        settings = await self.db.get_settings(interaction.guild_id)
        if not settings.get("shop_enabled", 1):
            await interaction.response.send_message(
                embed=error_embed("Shop Closed", "The BeastlyBank store is currently closed by administrators."),
                ephemeral=True,
            )
            return

        items = await self.db.get_shop_items(interaction.guild_id, include_inactive=False)

        if not items:
            embed = create_beastly_embed(
                title="🛒 BeastlyBank Official Store",
                description=(
                    "Spend your **Cash**, **Community Points**, and **Training Tokens** here!\n"
                    "Use `/buy <item_id>` to purchase any item.\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "*The BeastlyBank shop is currently being restocked!*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            await interaction.response.send_message(embed=embed)
            return

        per_page = 6
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        target_page = max(1, min(page or 1, total_pages))

        def make_shop_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_items = items[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_items)
            embed = create_beastly_embed(
                title="🛒 BeastlyBank Official Store",
                description=(
                    "Spend your **Cash**, **Community Points**, and **Training Tokens** here!\n"
                    "Use `/buy <item_id>` to purchase any item.\n"
                    f"Showing items **{start_idx + 1}–{end_idx}** of **{len(items)}** available items\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            for itm in page_items:
                curr_info = CURRENCIES.get(itm["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                stock_str = "Unlimited" if itm["stock"] == -1 else f"{itm['stock']} remaining"
                embed.add_field(
                    name=f"#{itm['id']} • {itm['name']} — {emoji} {itm['price']:,}",
                    value=f"{itm['description']}\n📦 **Stock:** `{stock_str}` | 🏷️ **Type:** `{itm.get('category', 'Perk')}`",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Store")
            return embed

        initial_embed = make_shop_page(target_page)
        if total_pages <= 1:
            await interaction.response.send_message(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_shop_page,
                total_pages=total_pages,
                author_id=interaction.user.id,
                current_page=target_page,
            )
            await interaction.response.send_message(embed=initial_embed, view=view)

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
        settings = await self.db.get_settings(interaction.guild_id)
        if not settings.get("purchases_enabled", 1):
            await interaction.response.send_message(
                embed=error_embed("Purchases Disabled", "Shop purchases are temporarily disabled by administrators."),
                ephemeral=True,
            )
            return

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
    @app_commands.describe(
        user="The member whose inventory to check (default: yourself)",
        page="Page number to view (default: 1)",
    )
    @require_beastlyfc()
    async def inventory(
        self,
        interaction: discord.Interaction,
        user: Optional[discord.Member] = None,
        page: Optional[int] = 1,
    ):
        target = user or interaction.user
        items = await self.db.get_inventory(target.id, interaction.guild_id)

        if not items:
            embed = create_beastly_embed(
                title=f"🎒 Inventory • {target.display_name}",
                description=f"Personal perks and inventory items for {target.mention}.\n━━━━━━━━━━━━━━━━━━━━━━\n\n*Inventory is empty! Browse `/shop` to purchase items and perks.*",
                color=COLOR_PITCH_GREEN,
            )
            await interaction.response.send_message(embed=embed)
            return

        per_page = 6
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        target_page = max(1, min(page or 1, total_pages))

        def make_inv_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_items = items[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_items)
            embed = create_beastly_embed(
                title=f"🎒 Inventory • {target.display_name}",
                description=(
                    f"Personal perks and inventory items for {target.mention}.\n"
                    f"Showing items **{start_idx + 1}–{end_idx}** of **{len(items)}** total items\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_PITCH_GREEN,
            )
            for itm in page_items:
                embed.add_field(
                    name=f"{itm['name']} (x{itm['quantity']})",
                    value=f"{itm['description']}\n📅 *Acquired:* `{itm['acquired_at'][:10]}`",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Inventory")
            return embed

        initial_embed = make_inv_page(target_page)
        if total_pages <= 1:
            await interaction.response.send_message(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_inv_page,
                total_pages=total_pages,
                author_id=interaction.user.id,
                current_page=target_page,
            )
            await interaction.response.send_message(embed=initial_embed, view=view)

    @commands.command(name="shop", aliases=["store"])
    async def prefix_shop(self, ctx: commands.Context, page: str = "1"):
        """bb!shop [page]"""
        settings = await self.db.get_settings(ctx.guild.id)
        if not settings.get("shop_enabled", 1):
            await ctx.send(embed=error_embed("Shop Closed", "The BeastlyBank store is currently closed by administrators."))
            return

        target_page = int(page) if page.isdigit() else 1
        items = await self.db.get_shop_items(ctx.guild.id, include_inactive=False)

        if not items:
            embed = create_beastly_embed(
                title="🛒 BeastlyBank Official Store",
                description=(
                    "Spend your **Cash**, **Community Points**, and **Training Tokens** here!\n"
                    "Use `bb!buy <item_id> [quantity]` or `/buy <item_id>` to purchase any item.\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "*The BeastlyBank shop is currently being restocked!*"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            await ctx.send(embed=embed)
            return

        per_page = 6
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        target_page = max(1, min(target_page, total_pages))

        def make_shop_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_items = items[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_items)
            embed = create_beastly_embed(
                title="🛒 BeastlyBank Official Store",
                description=(
                    "Spend your **Cash**, **Community Points**, and **Training Tokens** here!\n"
                    "Use `bb!buy <item_id> [quantity]` or `/buy <item_id>` to purchase any item.\n"
                    f"Showing items **{start_idx + 1}–{end_idx}** of **{len(items)}** available items\n"
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            for itm in page_items:
                curr_info = CURRENCIES.get(itm["currency"], {})
                emoji = curr_info.get("emoji", "💰")
                stock_str = "Unlimited" if itm["stock"] == -1 else f"{itm['stock']} remaining"
                embed.add_field(
                    name=f"#{itm['id']} • {itm['name']} — {emoji} {itm['price']:,}",
                    value=f"{itm['description']}\n📦 **Stock:** `{stock_str}` | 🏷️ **Type:** `{itm.get('category', 'Perk')}`",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Store")
            return embed

        initial_embed = make_shop_page(target_page)
        if total_pages <= 1:
            await ctx.send(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_shop_page,
                total_pages=total_pages,
                author_id=ctx.author.id,
                current_page=target_page,
            )
            await ctx.send(embed=initial_embed, view=view)

    @commands.command(name="buy", aliases=["purchase"])
    async def prefix_buy(self, ctx: commands.Context, item_id: int, quantity: int = 1):
        """bb!buy <item_id> [quantity]"""
        settings = await self.db.get_settings(ctx.guild.id)
        if not settings.get("purchases_enabled", 1):
            await ctx.send(embed=error_embed("Purchases Disabled", "Shop purchases are temporarily disabled by administrators."))
            return

        if quantity <= 0:
            await ctx.send(embed=error_embed("Invalid Quantity", "Quantity must be at least 1."))
            return

        success, msg, item = await self.db.buy_item(
            user_id=ctx.author.id,
            guild_id=ctx.guild.id,
            item_id=item_id,
            quantity=quantity,
        )

        if not success:
            await ctx.send(embed=error_embed("Purchase Failed", msg))
            return

        role_reward_msg = ""
        if item and item.get("role_reward_id") and ctx.guild:
            role = ctx.guild.get_role(item["role_reward_id"])
            if role and isinstance(ctx.author, discord.Member):
                try:
                    await ctx.author.add_roles(role, reason=f"BeastlyBank Shop purchase: {item['name']}")
                    role_reward_msg = f"\n🎖️ **Role Granted:** You have received the {role.mention} role!"
                except Exception:
                    role_reward_msg = f"\n⚠️ *Note: Bot lacks permissions to automatically assign role `{role.name}`.*"

        embed = create_beastly_embed(
            title="🛍️ Purchase Successful!",
            description=(
                f"**{ctx.author.mention}** successfully bought **{quantity}x {item['name']}**!\n"
                f"Item added to your `bb!inventory`.{role_reward_msg}\n\n"
                f"🏦 *Transaction logged in BeastlyBank ledger.*"
            ),
            color=COLOR_SUCCESS,
        )
        await ctx.send(embed=embed)

    @commands.command(name="inventory", aliases=["inv"])
    async def prefix_inventory(self, ctx: commands.Context, *args):
        """bb!inventory [user] [page]"""
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

        items = await self.db.get_inventory(target.id, ctx.guild.id)

        if not items:
            embed = create_beastly_embed(
                title=f"🎒 Inventory • {target.display_name}",
                description=f"Personal perks and inventory items for {target.mention}.\n━━━━━━━━━━━━━━━━━━━━━━\n\n*Inventory is empty! Browse `bb!shop` to purchase items and perks.*",
                color=COLOR_PITCH_GREEN,
            )
            await ctx.send(embed=embed)
            return

        per_page = 6
        total_pages = max(1, (len(items) + per_page - 1) // per_page)
        target_page = max(1, min(target_page, total_pages))

        def make_inv_page(p: int) -> discord.Embed:
            start_idx = (p - 1) * per_page
            page_items = items[start_idx : start_idx + per_page]
            end_idx = start_idx + len(page_items)
            embed = create_beastly_embed(
                title=f"🎒 Inventory • {target.display_name}",
                description=(
                    f"Personal perks and inventory items for {target.mention}.\n"
                    f"Showing items **{start_idx + 1}–{end_idx}** of **{len(items)}** total items\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                ),
                color=COLOR_PITCH_GREEN,
            )
            for itm in page_items:
                embed.add_field(
                    name=f"{itm['name']} (x{itm['quantity']})",
                    value=f"{itm['description']}\n📅 *Acquired:* `{itm['acquired_at'][:10]}`",
                    inline=False,
                )
            embed.set_footer(text=f"Page {p} of {total_pages} • BeastlyBank Inventory")
            return embed

        initial_embed = make_inv_page(target_page)
        if total_pages <= 1:
            await ctx.send(embed=initial_embed)
        else:
            view = PaginationView(
                embed_generator=make_inv_page,
                total_pages=total_pages,
                author_id=ctx.author.id,
                current_page=target_page,
            )
            await ctx.send(embed=initial_embed, view=view)


class ShopAdmin(commands.GroupCog, name="shopadmin", description="Banker & Staff Shop Management"):
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
                INSERT INTO shop_items (guild_id, name, description, price, currency, role_reward_id, stock, category, is_active)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Custom', 1);
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
        name="edit",
        description="Edit an existing shop item's details, price, or stock.",
    )
    @app_commands.describe(
        item_id="ID of the item to edit",
        name="New display name (optional)",
        description="New description (optional)",
        price="New price (optional)",
        currency="New currency (optional)",
        stock="New stock count (-1 for unlimited, optional)",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def shop_edit(
        self,
        interaction: discord.Interaction,
        item_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        price: Optional[int] = None,
        currency: Optional[Literal["cash", "points", "tokens"]] = None,
        stock: Optional[int] = None,
    ):
        success, msg = await self.db.edit_shop_item(
            guild_id=interaction.guild_id,
            item_id=item_id,
            name=name,
            description=description,
            price=price,
            currency=currency,
            stock=stock,
        )

        if not success:
            await interaction.response.send_message(embed=error_embed("Edit Failed", msg), ephemeral=True)
            return

        await interaction.response.send_message(embed=success_embed("Item Updated", msg))

    @app_commands.command(
        name="list",
        description="View all shop items including hidden/disabled items.",
    )
    @require_beastlyfc()
    @require_banker_or_admin()
    async def shop_list(self, interaction: discord.Interaction):
        items = await self.db.get_shop_items(interaction.guild_id, include_inactive=True)

        embed = create_beastly_embed(
            title="🛒 Shop Admin • Full Catalogue",
            description="All active and disabled shop items in BeastlyBank:\n━━━━━━━━━━━━━━━━━━━━━━",
            color=COLOR_BEASTLY_GOLD,
        )

        if not items:
            embed.description += "\n*No items registered in the shop.*"
            await interaction.response.send_message(embed=embed)
            return

        for itm in items:
            curr_emoji = CURRENCIES.get(itm["currency"], {}).get("emoji", "💰")
            status_icon = "🟢 Active" if itm.get("is_active", 1) == 1 else "🔴 Disabled"
            stock_str = "Unlimited" if itm["stock"] == -1 else f"{itm['stock']} left"

            embed.add_field(
                name=f"#{itm['id']} • {itm['name']} — {curr_emoji} {itm['price']:,}",
                value=f"Status: **{status_icon}** | Stock: `{stock_str}` | Curr: `{itm['currency']}`",
                inline=False,
            )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="toggle",
        description="Enable or disable a shop item from appearing in the store.",
    )
    @app_commands.describe(item_id="ID of the item to toggle on/off")
    @require_beastlyfc()
    @require_banker_or_admin()
    async def shop_toggle(self, interaction: discord.Interaction, item_id: int):
        success, msg, new_status = await self.db.toggle_shop_item(interaction.guild_id, item_id)
        if not success:
            await interaction.response.send_message(embed=error_embed("Toggle Failed", msg), ephemeral=True)
            return

        await interaction.response.send_message(embed=success_embed("Item Toggled", msg))

    @app_commands.command(
        name="remove",
        description="Permanently remove an item from the BeastlyBank Shop catalogue.",
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
            await conn.commit()

        embed = success_embed(
            "Item Removed",
            f"Item #{item_id} has been permanently removed from the BeastlyBank Shop.",
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Shop(bot))
    await bot.add_cog(ShopAdmin(bot))

