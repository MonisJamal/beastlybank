"""
Squad & Lineup Cog: Football formations, Starting XI, Substitutes Bench, and Player Management.
Supports all formations, visual tactical embeds, custom/Discord players, and Discord role mentions.
"""
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple
import discord
from discord import app_commands
from discord.ext import commands

from config import (
    BOT_NAME,
    COLOR_BEASTLY_GOLD,
    COLOR_SUCCESS,
    COLOR_ERROR,
    COLOR_INFO,
    SERVER_NAME,
    SUPPORTED_FORMATIONS,
    POSITION_CATEGORIES,
    VALID_POSITIONS,
)
from utils.checks import require_beastlyfc, is_banker_or_admin
from utils.embeds import (
    create_beastly_embed,
    club_lineup_embed,
    club_ratings_embed,
    player_card_embed,
    error_embed,
    success_embed,
    formations_list_embed,
    send_msg,
)
from utils.lineup_image import generate_lineup_image
from utils.sofifa import fetch_sofifa_players

logger = logging.getLogger("BeastlyBank.Squad")


async def formation_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for supported football formations."""
    cur = current.strip().lower()
    cur_clean = cur.replace("-", "").replace(" ", "")
    choices = []
    for k in SUPPORTED_FORMATIONS:
        k_clean = k.lower().replace("-", "").replace(" ", "")
        if not cur or cur in k.lower() or (cur_clean and cur_clean in k_clean):
            choices.append(app_commands.Choice(name=k[:100], value=k))
    return choices[:25]


async def position_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for player positions."""
    cur = current.strip().upper()
    choices = []
    for pos, cat in POSITION_CATEGORIES.items():
        label = f"{pos} — {cat}"
        if not cur or cur in pos or cur in cat.upper():
            choices.append(app_commands.Choice(name=label[:100], value=pos))
    return choices[:25]


async def send_msg(
    target: discord.Interaction | commands.Context,
    embed: Optional[discord.Embed] = None,
    file: Optional[discord.File] = None,
    ephemeral: bool = False,
):
    """Safely send embed or file responses to interactions or contexts."""
    try:
        kwargs: Dict[str, Any] = {}
        if embed is not None:
            kwargs["embed"] = embed
        if file is not None:
            kwargs["file"] = file

        if isinstance(target, discord.Interaction):
            if target.response.is_done():
                await target.followup.send(ephemeral=ephemeral, **kwargs)
            else:
                await target.response.send_message(ephemeral=ephemeral, **kwargs)
        else:
            await target.send(**kwargs)
    except Exception as e:
        logger.error("Error in send_msg: %s", e, exc_info=True)


async def check_squad_permission(
    db,
    guild_id: int,
    user: discord.Member | discord.User,
    target_club: Dict[str, Any],
) -> Tuple[bool, str]:
    """Check if the user is authorized to manage the club's squad."""
    if is_banker_or_admin(user):
        return True, ""

    if target_club.get("owner_id") == user.id:
        return True, ""

    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT role FROM club_members WHERE club_id = ? AND user_id = ?;",
            (target_club["id"], user.id),
        )
        row = await cur.fetchone()
        if row and row["role"] in ("Owner", "Captain", "Vice-Captain", "Manager"):
            return True, ""

    return (
        False,
        "You must be a Club Owner, Captain, Vice-Captain, Manager, or BeastlyBank Banker to manage this squad.",
    )


async def squad_player_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete suggesting SoFIFA FC 26 players, plus a custom player option."""
    clean = current.strip()
    db = interaction.client.db  # type: ignore

    results = await db.search_cached_sofifa_players(clean, limit=20)
    choices: list[app_commands.Choice[str]] = []
    for p in results:
        label = f"{p['name']} ({p['overall_rating']} {p['primary_pos']}) • {p['team']}"
        if len(label) > 100:
            label = label[:97] + "..."
        choices.append(app_commands.Choice(name=label, value=str(p["id"])))

    if clean and not any(p["name"].lower() == clean.lower() for p in results):
        custom_label = f"➕ Custom: '{clean[:40]}'"
        choices.append(app_commands.Choice(name=custom_label, value=f"custom:{clean}"))

    return choices[:25]


class AddAsCustomPlayerView(discord.ui.View):
    """Interactive button to confirm adding as custom player when not in SoFIFA."""

    def __init__(
        self,
        squad_cog,
        target_club: Dict[str, Any],
        raw_name: str,
        position: str,
        status: str,
        number: Optional[int],
        rating: int,
        potential: int,
        alt_positions: Optional[str],
        user: discord.User | discord.Member,
    ):
        super().__init__(timeout=120)
        self.squad_cog = squad_cog
        self.target_club = target_club
        self.raw_name = raw_name
        self.position = position
        self.status = status
        self.number = number
        self.rating = rating
        self.potential = potential
        self.alt_positions = alt_positions
        self.user = user

    @discord.ui.button(label="Register as Custom Player", emoji="➕", style=discord.ButtonStyle.success)
    async def confirm_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Only the manager who initiated this can confirm.", ephemeral=True)
            return

        success, msg, p_data = await self.squad_cog.db.add_club_player(
            guild_id=interaction.guild_id,
            club_query=self.target_club["id"],
            player_name=self.raw_name,
            position=self.position,
            status=self.status,
            number=self.number,
            rating=self.rating,
            potential=self.potential,
            alt_positions=self.alt_positions,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await interaction.response.edit_message(
                embed=error_embed("Registration Failed", msg),
                view=None,
            )
            return

        embed = create_beastly_embed(
            title="👤 Custom Player Registered",
            description=(
                f"✅ **{self.raw_name}** successfully registered as a **Custom Player**!\n\n"
                f"• **Position:** `{self.position}`\n"
                f"• **Rating:** ⭐ **{self.rating} OVR** (Potential: **{self.potential}**)\n"
                f"• **Lineup Status:** `{self.status.title()}`" + (f" (Jersey #{self.number})" if self.number is not None else "") + "\n"
                f"• **Club:** **[{self.target_club['tag']}] {self.target_club['name']}**\n\n"
                f"💡 *You can edit this player anytime with `/player edit` or `bb!editplayer`.*"
            ),
            color=COLOR_SUCCESS,
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Cancel", emoji="✖️", style=discord.ButtonStyle.secondary)
    async def cancel_custom(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Only the manager who initiated this can cancel.", ephemeral=True)
            return
        await interaction.response.edit_message(
            embed=error_embed("Cancelled", "Player addition cancelled."),
            view=None,
        )


class SquadCog(commands.Cog, name="Squad & Lineup"):
    """Manage club formations, starting lineups, bench, and player profiles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db  # type: ignore

    # ==========================================
    # SLASH COMMANDS: FORMATION
    # ==========================================

    formation_group = app_commands.Group(
        name="formation",
        description="Manage club tactical formations.",
    )

    @formation_group.command(name="set", description="Set tactical formation for your club.")
    @app_commands.describe(
        formation="Formation to set (e.g. 4-3-3 Balanced, 4-2-3-1 Wide)",
        club="Target club role (Bankers or if managing a specific club)",
    )
    @app_commands.autocomplete(formation=formation_autocomplete)
    async def slash_formation_set(
        self,
        interaction: discord.Interaction,
        formation: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or specify a club role to set the formation.",
                ),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg = await self.db.set_club_formation(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            formation=formation,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Failed to Set Formation", msg), ephemeral=True)
            return

        embed = success_embed("Formation Updated", msg)
        role_mention = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**{target_club['name']}**"
        embed.description = f"Tactical layout for {role_mention} updated successfully!\n\n{msg}"
        await send_msg(interaction, embed=embed)

    @formation_group.command(name="list", description="List all supported football formations.")
    async def slash_formation_list(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=formations_list_embed())

    # ==========================================
    # SLASH COMMAND: LINEUP
    # ==========================================

    async def _handle_lineup(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
        view: str = "image",
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role (`/lineup club:@Role`) to view its lineup.",
                ),
                ephemeral=True,
            )
            return

        success, msg, data = await self.db.get_club_lineup(
            interaction.guild_id, club if club else target_club["id"]
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Lineup Unavailable", msg), ephemeral=True)
            return

        club_info = data["club"]
        formation = data["formation"]
        starting_players = data["starting"]
        bench_players = data.get("bench") or []

        if view == "image":
            # Resolve manager display name and avatar
            manager_name = "Club Manager"
            manager_avatar_bytes = None
            owner_id = club_info.get("owner_id")
            if owner_id and interaction.guild:
                member = interaction.guild.get_member(owner_id)
                if member:
                    manager_name = member.display_name
                    try:
                        manager_avatar_bytes = await member.display_avatar.read()
                    except Exception:
                        pass

            # Resolve role color
            role_color = None
            if club and hasattr(club, "color") and club.color.value != 0:
                role_color = f"#{club.color.value:06x}"
            elif club_info.get("role_id") and interaction.guild:
                guild_role = interaction.guild.get_role(club_info["role_id"])
                if guild_role and guild_role.color.value != 0:
                    role_color = f"#{guild_role.color.value:06x}"

            # Custom branding fields from database
            custom_branding = {
                "kit_primary": club_info.get("kit_primary"),
                "kit_secondary": club_info.get("kit_secondary"),
                "slogan_1": club_info.get("slogan_1"),
                "slogan_2": club_info.get("slogan_2"),
                "chant": club_info.get("chant"),
                "logo_url": club_info.get("logo_url"),
            }

            team_name = f"[{club_info['tag']}] {club_info['name']}" if club_info.get("tag") else club_info.get("name", "Beastly FC")

            buf = generate_lineup_image(
                team_name=team_name,
                manager_name=manager_name,
                formation_name=formation,
                starting_players=starting_players,
                bench_players=bench_players,
                role_color=role_color,
                custom_branding=custom_branding,
                manager_avatar_bytes=manager_avatar_bytes,
            )
            file = discord.File(fp=buf, filename="lineup.png")
            await send_msg(interaction, file=file)
        else:
            embed = club_lineup_embed(
                club=club_info,
                formation=formation,
                starting_players=starting_players,
                bench_players=data["bench"],
            )
            await send_msg(interaction, embed=embed)

    @app_commands.command(name="lineup", description="View clean matchday pitch lineup for a club.")
    @app_commands.describe(
        club="Club role to inspect (defaults to your club)",
        view="Display style: image (clean minimal pitch) or embed (text layout)",
    )
    async def slash_lineup(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
        view: Literal["image", "embed"] = "image",
    ):
        await self._handle_lineup(interaction, club=club, view=view)

    @app_commands.command(name="lineupcard", description="Generate a clean matchday Starting 11 pitch image for your club.")
    @app_commands.describe(club="Club role to inspect (defaults to your club)")
    async def slash_lineupcard(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        await self._handle_lineup(interaction, club=club, view="image")

    @app_commands.command(name="ovr", description="View a club's overall team rating and department breakdown (ATT, MID, DEF).")
    @app_commands.describe(club="Club role to inspect (defaults to your club)")
    async def slash_ovr(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role (`/ovr club:@Role`) to view ratings.",
                ),
                ephemeral=True,
            )
            return

        success, msg, data = await self.db.get_club_lineup(
            interaction.guild_id, club if club else target_club["id"]
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Ratings Unavailable", msg), ephemeral=True)
            return

        embed = club_ratings_embed(
            club=data["club"],
            formation=data["formation"],
            starting_players=data["starting"],
            bench_players=data.get("bench") or [],
        )
        await send_msg(interaction, embed=embed)


    @app_commands.command(name="customlineup", description="Generate a custom clean matchday Starting 11 & Bench image on the fly.")
    @app_commands.describe(
        team="Team or club name (e.g. Manchester United, Real Madrid, Arsenal)",
        manager="Manager name (e.g. Carlo Ancelotti, Erik ten Hag)",
        formation="Formation (e.g. 3-4-1-2 / 3-5-2, 4-3-3 Balanced)",
        players="Optional comma-separated starting 11 player names",
        bench="Optional comma-separated bench player names",
    )
    @app_commands.autocomplete(formation=formation_autocomplete)
    async def slash_custom_lineup(
        self,
        interaction: discord.Interaction,
        team: str,
        manager: str,
        formation: str,
        players: Optional[str] = None,
        bench: Optional[str] = None,
    ):
        await interaction.response.defer()
        player_list = []
        if players:
            raw_names = [p.strip() for p in players.split(",") if p.strip()]
            for idx, p_name in enumerate(raw_names[:11], start=1):
                player_list.append({
                    "player_name": p_name,
                    "number": idx,
                    "position": None,
                    "rating": None,
                })

        bench_list = []
        if bench:
            bench_names = [p.strip() for p in bench.split(",") if p.strip()]
            for idx, b_name in enumerate(bench_names[:10], start=12):
                bench_list.append({
                    "player_name": b_name,
                    "number": idx,
                    "position": "SUB",
                    "rating": None,
                })

        manager_avatar_bytes = None
        try:
            manager_avatar_bytes = await interaction.user.display_avatar.read()
        except Exception:
            pass

        buf = generate_lineup_image(
            team_name=team,
            manager_name=manager,
            formation_name=formation,
            starting_players=player_list,
            bench_players=bench_list,
            manager_avatar_bytes=manager_avatar_bytes,
        )
        file = discord.File(fp=buf, filename="lineup.png")
        await send_msg(interaction, file=file)


    # ==========================================
    # SLASH COMMANDS: PLAYER MANAGEMENT
    # ==========================================

    player_group = app_commands.Group(
        name="player",
        description="View and manage club players.",
    )

    @player_group.command(name="info", description="View full profile of a specific player.")
    @app_commands.describe(
        player="Player name or Discord mention",
        club="Optional club role to filter search",
    )
    async def slash_player_info(
        self,
        interaction: discord.Interaction,
        player: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        success, msg, data = await self.db.get_player_info(
            guild_id=interaction.guild_id,
            player_name=player,
            club_query=club if club else None,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Player Not Found", msg), ephemeral=True)
            return

        embed = player_card_embed(player=data["player"], club=data["club"])
        await send_msg(interaction, embed=embed)

    @player_group.command(name="add", description="Add a player to your club squad (SoFIFA auto-fill or Custom).")
    @app_commands.describe(
        player="Player name or SoFIFA search (autocomplete suggestions available)",
        source="Player source: SoFIFA FC 26 database (auto-fills stats) or Custom Player",
        position="Primary position (optional - auto-filled from SoFIFA if recognized)",
        status="Lineup status: starting (Starting XI) or bench (Substitutes)",
        number="Jersey number (0-99)",
        rating="Overall rating (1-99, auto-filled from SoFIFA if recognized)",
        potential="Potential rating (1-99, auto-filled from SoFIFA if recognized)",
        alt_positions="Alternative positions separated by commas (optional - auto-filled from SoFIFA)",
        club="Target club role (defaults to your club)",
    )
    @app_commands.autocomplete(
        player=squad_player_autocomplete,
        position=position_autocomplete,
    )
    async def slash_player_add(
        self,
        interaction: discord.Interaction,
        player: str,
        source: Literal["SoFIFA FC 26 (Auto)", "Custom Player"] = "SoFIFA FC 26 (Auto)",
        position: Optional[str] = None,
        status: Literal["starting", "bench"] = "starting",
        number: Optional[int] = None,
        rating: Optional[app_commands.Range[int, 1, 99]] = None,
        potential: Optional[app_commands.Range[int, 1, 99]] = None,
        alt_positions: Optional[str] = None,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or specify a club role to add a player.",
                ),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        clean_p = player.strip()
        is_explicit_custom = (
            source == "Custom Player"
            or clean_p.lower().startswith("custom:")
            or (clean_p.startswith("<@") and clean_p.endswith(">"))
        )

        sofifa_data = None
        if not is_explicit_custom:
            # Check numeric ID from autocomplete choice value
            if clean_p.isdigit():
                sofifa_data = await self.db.get_cached_sofifa_player(clean_p)
            elif ":" in clean_p and clean_p.split(":")[0].isdigit():
                sofifa_data = await self.db.get_cached_sofifa_player(clean_p.split(":")[0])

            if not sofifa_data:
                sofifa_data = await self.db.get_cached_sofifa_player(clean_p)

            if not sofifa_data and len(clean_p) >= 3:
                try:
                    fetched = await fetch_sofifa_players(keyword=clean_p, timeout=5)
                    if fetched:
                        await self.db.cache_sofifa_players(fetched)
                        clean_lower = clean_p.lower()
                        for r in fetched:
                            if clean_lower in r["name"].lower() or clean_lower in r["full_name"].lower():
                                sofifa_data = r
                                break
                        if not sofifa_data:
                            sofifa_data = fetched[0]
                except Exception as e:
                    logger.debug("Live fetch error during squad add: %s", e)

        # Player not found in SoFIFA and user selected SoFIFA Auto
        if not is_explicit_custom and not sofifa_data:
            view = AddAsCustomPlayerView(
                squad_cog=self,
                target_club=target_club,
                raw_name=clean_p,
                position=position.upper().strip() if position else "ST",
                status=status,
                number=number,
                rating=rating if rating is not None else 75,
                potential=potential if potential is not None else 80,
                alt_positions=alt_positions,
                user=interaction.user,
            )
            embed = create_beastly_embed(
                title="🔍 Player Not Found in SoFIFA FC 26",
                description=(
                    f"Could not find **{clean_p}** in the official SoFIFA Sep 19, 2025 FC 26 database.\n\n"
                    f"Would you like to register them as a **Custom Player** in **[{target_club['tag']}] {target_club['name']}**?"
                ),
                color=COLOR_BEASTLY_GOLD,
            )
            embed.add_field(name="Assigned Position", value=f"`{position or 'ST'}`", inline=True)
            embed.add_field(name="Rating / Potential", value=f"`{rating or 75}` / `{potential or 80}`", inline=True)
            embed.add_field(name="Lineup Status", value=f"`{status.title()}`", inline=True)
            embed.set_footer(text="Click below to register as a custom player, or cancel to try another name.")
            await send_msg(interaction, embed=embed, view=view)
            return

        # Prepare player fields
        if sofifa_data:
            final_name = clean_p if not clean_p.isdigit() else (sofifa_data.get("full_name") or sofifa_data["name"])
            final_pos = (position.upper().strip() if position else None) or sofifa_data.get("primary_pos", "ST")
            final_rating = rating if rating is not None else sofifa_data.get("overall_rating", 75)
            final_pot = potential if potential is not None else sofifa_data.get("potential", final_rating)
            if alt_positions is not None:
                final_alts = alt_positions
            else:
                raw_positions = [x.strip() for x in sofifa_data.get("positions", "").split(",") if x.strip()]
                alts = [p for p in raw_positions if p != final_pos]
                final_alts = ", ".join(alts) if alts else None
            avatar_url = sofifa_data.get("avatar")
            team_origin = sofifa_data.get("team")
        else:
            final_name = clean_p[7:].strip() if clean_p.lower().startswith("custom:") else clean_p
            final_pos = position.upper().strip() if position else "ST"
            final_rating = rating if rating is not None else 75
            final_pot = potential if potential is not None else 80
            final_alts = alt_positions
            avatar_url = None
            team_origin = None

        success, msg, p_data = await self.db.add_club_player(
            guild_id=interaction.guild_id,
            club_query=target_club["id"],
            player_name=final_name,
            position=final_pos,
            status=status,
            number=number,
            rating=final_rating,
            potential=final_pot,
            alt_positions=final_alts,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Add Player Failed", msg), ephemeral=True)
            return

        if sofifa_data:
            desc = (
                f"✅ **{final_name}** successfully registered from SoFIFA FC 26 database!\n\n"
                f"• **Position:** `{final_pos}`" + (f" *(Alts: `{final_alts}`)*" if final_alts else "") + "\n"
                f"• **Rating:** ⭐ **{final_rating} OVR** (Potential: **{final_pot}**)\n"
                f"• **Original Club:** {team_origin or 'Free Agent'}\n"
                f"• **Lineup Status:** `{status.title()}`" + (f" (Jersey #{number})" if number is not None else "") + "\n"
                f"• **Club:** **[{target_club['tag']}] {target_club['name']}**\n\n"
                f"💡 *You can edit this player anytime with `/player edit` or `bb!editplayer`.*"
            )
            embed = create_beastly_embed(
                title="⭐ Player Registered (SoFIFA FC 26)",
                description=desc,
                color=COLOR_SUCCESS,
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
        else:
            desc = (
                f"✅ **{final_name}** successfully registered as a **Custom Player**!\n\n"
                f"• **Position:** `{final_pos}`" + (f" *(Alts: `{final_alts}`)*" if final_alts else "") + "\n"
                f"• **Rating:** ⭐ **{final_rating} OVR** (Potential: **{final_pot}**)\n"
                f"• **Lineup Status:** `{status.title()}`" + (f" (Jersey #{number})" if number is not None else "") + "\n"
                f"• **Club:** **[{target_club['tag']}] {target_club['name']}**\n\n"
                f"💡 *You can edit this player anytime with `/player edit` or `bb!editplayer`.*"
            )
            embed = create_beastly_embed(
                title="👤 Custom Player Registered",
                description=desc,
                color=COLOR_SUCCESS,
            )

        await send_msg(interaction, embed=embed)

    @player_group.command(name="addcustom", description="Directly add a custom or server player to your club squad.")
    @app_commands.describe(
        player="Custom player name or Discord mention",
        position="Primary position (e.g. ST, CB, CM, GK, default: ST)",
        status="Lineup status: starting (Starting XI) or bench (Substitutes)",
        number="Jersey number (0-99)",
        rating="Overall rating (1-99, default: 75)",
        potential="Potential rating (1-99, default: 80)",
        alt_positions="Alternative positions separated by commas (e.g. 'pos1, pos2, pos3, .....')",
        club="Target club role (defaults to your club)",
    )
    @app_commands.autocomplete(position=position_autocomplete)
    async def slash_player_addcustom(
        self,
        interaction: discord.Interaction,
        player: str,
        position: Optional[str] = "ST",
        status: Literal["starting", "bench"] = "starting",
        number: Optional[int] = None,
        rating: Optional[app_commands.Range[int, 1, 99]] = 75,
        potential: Optional[app_commands.Range[int, 1, 99]] = 80,
        alt_positions: Optional[str] = None,
        club: Optional[discord.Role] = None,
    ):
        """Direct shortcut to add a custom player without SoFIFA lookup."""
        await self.slash_player_add(
            interaction=interaction,
            player=player,
            source="Custom Player",
            position=position,
            status=status,
            number=number,
            rating=rating,
            potential=potential,
            alt_positions=alt_positions,
            club=club,
        )

    @player_group.command(name="edit", description="Edit an existing player's details.")
    @app_commands.describe(
        player="Player name or Discord mention to edit",
        new_name="New name for the player",
        position="New primary position (e.g. ST, CB, CM, GK)",
        status="Lineup status: starting or bench",
        number="New jersey number (0-99)",
        rating="New overall rating (1-99)",
        potential="New potential rating (1-99)",
        alt_positions="New alternative positions separated by commas (e.g. 'pos1, pos2, pos3, .....')",
        club="Target club role (defaults to your club)",
    )
    @app_commands.autocomplete(position=position_autocomplete)
    async def slash_player_edit(
        self,
        interaction: discord.Interaction,
        player: str,
        new_name: Optional[str] = None,
        position: Optional[str] = None,
        status: Optional[Literal["starting", "bench"]] = None,
        number: Optional[int] = None,
        rating: Optional[app_commands.Range[int, 1, 99]] = None,
        potential: Optional[app_commands.Range[int, 1, 99]] = None,
        alt_positions: Optional[str] = None,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or specify a club role to edit a player.",
                ),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg, p_data = await self.db.edit_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_name=player,
            new_name=new_name,
            position=position,
            status=status,
            number=number,
            rating=rating,
            potential=potential,
            alt_positions=alt_positions,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Edit Player Failed", msg), ephemeral=True)
            return

        embed = success_embed("Player Updated", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="remove", description="Remove a player from the club squad.")
    @app_commands.describe(
        player="Player name or Discord mention to remove",
        club="Target club role (defaults to your club)",
    )
    async def slash_player_remove(
        self,
        interaction: discord.Interaction,
        player: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or specify a club role to remove a player.",
                ),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg = await self.db.remove_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_name=player,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Remove Failed", msg), ephemeral=True)
            return

        embed = success_embed("Player Removed", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="start", description="Move a player to the Starting XI.")
    @app_commands.describe(
        player="Player name or Discord mention",
        position="Optional tactical position",
        club="Target club role (defaults to your club)",
    )
    @app_commands.autocomplete(position=position_autocomplete)
    async def slash_player_start(
        self,
        interaction: discord.Interaction,
        player: str,
        position: Optional[str] = None,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or specify a club role."),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg, _ = await self.db.edit_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_name=player,
            status="starting",
            position=position,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Action Failed", msg), ephemeral=True)
            return

        embed = success_embed("Promoted to Starting XI", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="bench", description="Move a player to the Substitutes Bench.")
    @app_commands.describe(
        player="Player name or Discord mention",
        club="Target club role (defaults to your club)",
    )
    async def slash_player_bench(
        self,
        interaction: discord.Interaction,
        player: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or specify a club role."),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg, _ = await self.db.edit_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_name=player,
            status="bench",
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Action Failed", msg), ephemeral=True)
            return

        embed = success_embed("Moved to Bench", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="swap", description="Swap two players (substitute or switch positions).")
    @app_commands.describe(
        player1="First player name or Discord mention",
        player2="Second player name or Discord mention",
        club="Target club role (defaults to your club)",
    )
    async def slash_player_swap(
        self,
        interaction: discord.Interaction,
        player1: str,
        player2: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or specify a club role."),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        # Check if player2 is a tactical pitch position (e.g. /player swap player1: Vinicius player2: LW)
        p2_pos_check = player2.strip().upper()
        if p2_pos_check in VALID_POSITIONS:
            success, msg, _ = await self.db.switch_lineup_position(
                guild_id=interaction.guild_id,
                club_query=club if club else target_club["id"],
                player_query=player1,
                new_position=p2_pos_check,
                default_owner_id=interaction.user.id,
            )
            if not success:
                await send_msg(interaction, embed=error_embed("Switch Position Failed", msg), ephemeral=True)
                return
            embed = success_embed("Tactical Swap", msg)
            await send_msg(interaction, embed=embed)
            return

        success, msg = await self.db.swap_club_players(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player1_name=player1,
            player2_name=player2,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Swap Failed", msg), ephemeral=True)
            return

        embed = success_embed("Tactical Swap", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="sub", description="Substitute a starting player with a bench player.")
    @app_commands.describe(
        off="Player coming off the pitch (starter)",
        on="Player coming onto the pitch (bencher)",
        club="Target club role (defaults to your club)",
    )
    async def slash_player_sub(
        self,
        interaction: discord.Interaction,
        off: str,
        on: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or specify a club role."),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg = await self.db.substitute_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_off_name=off,
            player_on_name=on,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Substitution Failed", msg), ephemeral=True)
            return

        embed = success_embed("Tactical Substitution", msg)
        await send_msg(interaction, embed=embed)

    @player_group.command(name="switchpos", description="Switch a player's tactical position in the lineup.")
    @app_commands.describe(
        player="Player name or Discord mention",
        position="Target tactical position (e.g. GK, CB, LB, RB, CDM, CM, CAM, LM, RM, LW, RW, ST, CF)",
        club="Target club role (defaults to your club)",
    )
    async def slash_player_switchpos(
        self,
        interaction: discord.Interaction,
        player: str,
        position: str,
        club: Optional[discord.Role] = None,
    ):
        await interaction.response.defer()
        if club:
            target_club = await self.db.get_or_create_club_from_role(
                interaction.guild_id, club, default_owner_id=interaction.user.id
            )
        else:
            target_club = await self.db.get_club_by_user(interaction.guild_id, interaction.user.id)

        if not target_club:
            await send_msg(
                interaction,
                embed=error_embed("Club Not Found", "You must belong to a club or specify a club role."),
                ephemeral=True,
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, interaction.guild_id, interaction.user, target_club
        )
        if not has_perm:
            await send_msg(interaction, embed=error_embed("Permission Denied", perm_msg), ephemeral=True)
            return

        success, msg, _ = await self.db.switch_lineup_position(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_query=player,
            new_position=position,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Switch Position Failed", msg), ephemeral=True)
            return

        embed = success_embed("Position Switched", msg)
        await send_msg(interaction, embed=embed)

    @app_commands.command(name="switchpos", description="Switch a player's tactical position in the lineup.")
    @app_commands.describe(
        player="Player name or Discord mention",
        position="Target tactical position (e.g. GK, CB, LB, RB, CDM, CM, CAM, LM, RM, LW, RW, ST, CF)",
        club="Target club role (defaults to your club)",
    )
    async def slash_switchpos(
        self,
        interaction: discord.Interaction,
        player: str,
        position: str,
        club: Optional[discord.Role] = None,
    ):
        await self.slash_player_switchpos(interaction, player, position, club)

    @app_commands.command(name="switch", description="Switch a player's tactical position in the lineup.")
    @app_commands.describe(
        player="Player name or Discord mention",
        position="Target tactical position (e.g. GK, CB, LB, RB, CDM, CM, CAM, LM, RM, LW, RW, ST, CF)",
        club="Target club role (defaults to your club)",
    )
    async def slash_switch(
        self,
        interaction: discord.Interaction,
        player: str,
        position: str,
        club: Optional[discord.Role] = None,
    ):
        await self.slash_player_switchpos(interaction, player, position, club)

    # ==========================================
    # PREFIX COMMANDS (bb!)
    # ==========================================

    @commands.command(name="lineup", aliases=["squad"])
    async def prefix_lineup(self, ctx: commands.Context, *args):
        """
        View tactical pitch lineup and bench for a club.
        Usage:
          bb!lineup [@club_role or club_name]
          bb!lineup image [@club_role]
          bb!lineup switch <player> <position>
        """
        if args and args[0].lower() in ("switch", "switchpos", "setpos", "swap"):
            return await self.prefix_switchpos.callback(self, ctx, *args)

        if args and args[0].lower() in ("sub", "substitute", "subplayer"):
            sub_args = list(args[1:])
            return await self.prefix_sub.callback(self, ctx, *sub_args)

        if args and args[0].lower() in ("ovr", "ratings", "rating", "teamrating", "teamovr"):
            sub_args = list(args[1:])
            return await self.prefix_ovr.callback(self, ctx, *sub_args)

        if args and args[0].lower() in ("image", "card", "pitch", "img"):
            sub_args = list(args[1:])
            return await self.prefix_lineupimage.callback(self, ctx, *sub_args)

        target_club = None
        if ctx.message.role_mentions:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, ctx.message.role_mentions[0], default_owner_id=ctx.author.id
            )
        elif args:
            club_query = " ".join(args)
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, club_query, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role (`bb!lineup @Role`) to view its lineup.",
                )
            )
            return

        success, msg, data = await self.db.get_club_lineup(ctx.guild.id, target_club["id"])
        if not success:
            await ctx.send(embed=error_embed("Lineup Unavailable", msg))
            return

        embed = club_lineup_embed(
            club=data["club"],
            formation=data["formation"],
            starting_players=data["starting"],
            bench_players=data["bench"],
        )
        await ctx.send(embed=embed)

    @commands.command(name="lineupimage", aliases=["lineupcard", "pitch", "starting11"])
    async def prefix_lineupimage(self, ctx: commands.Context, *args):
        """
        Generate a clean matchday Starting 11 pitch image for a club.
        Usage: bb!lineupimage [@club_role or club_name]
        """
        target_club = None
        if ctx.message.role_mentions:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, ctx.message.role_mentions[0], default_owner_id=ctx.author.id
            )
        elif args:
            club_query = " ".join(args)
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, club_query, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role (`bb!lineupimage @Role`) to generate its pitch image.",
                )
            )
            return

        success, msg, data = await self.db.get_club_lineup(ctx.guild.id, target_club["id"])
        if not success:
            await ctx.send(embed=error_embed("Lineup Unavailable", msg))
            return

        club_info = data["club"]
        formation = data["formation"]
        starting_players = data["starting"]
        bench_players = data.get("bench") or []

        manager_name = "Club Manager"
        manager_avatar_bytes = None
        owner_id = club_info.get("owner_id")
        if owner_id and ctx.guild:
            member = ctx.guild.get_member(owner_id)
            if member:
                manager_name = member.display_name
                try:
                    manager_avatar_bytes = await member.display_avatar.read()
                except Exception:
                    pass

        role_color = None
        if ctx.message.role_mentions and ctx.message.role_mentions[0].color.value != 0:
            role_color = f"#{ctx.message.role_mentions[0].color.value:06x}"
        elif club_info.get("role_id") and ctx.guild:
            gr = ctx.guild.get_role(club_info["role_id"])
            if gr and gr.color.value != 0:
                role_color = f"#{gr.color.value:06x}"

        custom_branding = {
            "kit_primary": club_info.get("kit_primary"),
            "kit_secondary": club_info.get("kit_secondary"),
            "slogan_1": club_info.get("slogan_1"),
            "slogan_2": club_info.get("slogan_2"),
            "chant": club_info.get("chant"),
            "logo_url": club_info.get("logo_url"),
        }

        team_name = f"[{club_info['tag']}] {club_info['name']}" if club_info.get("tag") else club_info.get("name", "Beastly FC")

        buf = generate_lineup_image(
            team_name=team_name,
            manager_name=manager_name,
            formation_name=formation,
            starting_players=starting_players,
            bench_players=bench_players,
            role_color=role_color,
            custom_branding=custom_branding,
            manager_avatar_bytes=manager_avatar_bytes,
        )
        file = discord.File(fp=buf, filename="lineup.png")
        await ctx.send(file=file)

    @commands.command(name="ovr", aliases=["ratings", "teamrating", "teamovr"])
    async def prefix_ovr(self, ctx: commands.Context, *args):
        """
        View a club's overall team rating and department breakdown (ATT, MID, DEF).
        Usage: bb!ovr [@club_role or club_name]
        Aliases: bb!ratings, bb!teamrating, bb!teamovr
        """
        target_club = None
        if ctx.message.role_mentions:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, ctx.message.role_mentions[0], default_owner_id=ctx.author.id
            )
        elif args:
            club_query = " ".join(args)
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, club_query, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role (`bb!ovr @Role`) to view ratings.",
                )
            )
            return

        success, msg, data = await self.db.get_club_lineup(ctx.guild.id, target_club["id"])
        if not success:
            await ctx.send(embed=error_embed("Ratings Unavailable", msg))
            return

        embed = club_ratings_embed(
            club=data["club"],
            formation=data["formation"],
            starting_players=data["starting"],
            bench_players=data.get("bench") or [],
        )
        await ctx.send(embed=embed)

    @commands.command(name="customlineup")
    async def prefix_custom_lineup(self, ctx: commands.Context, *, args: str = ""):
        """
        Generate a custom Starting 11 pitch image.
        Usage: bb!customlineup <team> | <manager> | <formation> | [players] | [bench]
        Example: bb!customlineup Manchester United | Desti | 3-4-1-2 / 3-5-2 | Benzema, Schick, Marmoush | Zirkzee, Delap
        """
        parts = [p.strip() for p in args.split("|")] if args else []
        if len(parts) < 3:
            await ctx.send(
                embed=error_embed(
                    "Missing Information",
                    "Please provide team, manager, and formation separated by `|`.\n"
                    "**Usage:** `bb!customlineup <Team Name> | <Manager Name> | <Formation> | [Players...] | [Bench...]`\n"
                    "**Example:** `bb!customlineup Manchester United | Desti | 3-4-1-2 / 3-5-2 | Benzema, Schick, Marmoush, Kerkez, Barrios, Zaire-Emery, Greenwood, Martinez, Maldini, Alaba, Svilar`"
                )
            )
            return

        team = parts[0]
        manager = parts[1]
        formation = parts[2]
        player_list = []
        if len(parts) >= 4 and parts[3]:
            raw_names = [p.strip() for p in parts[3].split(",") if p.strip()]
            for idx, p_name in enumerate(raw_names[:11], start=1):
                player_list.append({
                    "player_name": p_name,
                    "number": idx,
                    "position": None,
                    "rating": None,
                })

        bench_list = []
        if len(parts) >= 5 and parts[4]:
            raw_bench = [p.strip() for p in parts[4].split(",") if p.strip()]
            for idx, b_name in enumerate(raw_bench[:10], start=12):
                bench_list.append({
                    "player_name": b_name,
                    "number": idx,
                    "position": "SUB",
                    "rating": None,
                })

        manager_avatar_bytes = None
        try:
            manager_avatar_bytes = await ctx.author.display_avatar.read()
        except Exception:
            pass

        buf = generate_lineup_image(
            team_name=team,
            manager_name=manager,
            formation_name=formation,
            starting_players=player_list,
            bench_players=bench_list,
            manager_avatar_bytes=manager_avatar_bytes,
        )
        file = discord.File(fp=buf, filename="lineup.png")
        await ctx.send(file=file)


    @commands.command(name="setformation", aliases=["formation"])
    async def prefix_setformation(self, ctx: commands.Context, *args):
        """
        Set tactical formation for a club.
        Usage: bb!setformation <formation> [@club_role]
        Example: bb!setformation 4-3-3 @RealMadrid
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed(
                    "Missing Formation",
                    f"Please provide a formation.\nUsage: `bb!setformation <formation> [@club_role]`\nSupported: {', '.join(SUPPORTED_FORMATIONS.keys())}",
                )
            )
            return

        formation = clean_args[0]

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role to set the formation.",
                )
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg = await self.db.set_club_formation(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            formation=formation,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Failed to Set Formation", msg))
            return

        role_mention = f"<@&{target_club['role_id']}>" if target_club.get("role_id") else f"**{target_club['name']}**"
        embed = success_embed("Formation Updated", f"Tactical layout for {role_mention} updated successfully!\n\n{msg}")
        await ctx.send(embed=embed)

    @commands.command(name="formations")
    async def prefix_formations(self, ctx: commands.Context):
        """List all supported football formations."""
        await ctx.send(embed=formations_list_embed())

    @commands.command(name="player", aliases=["playerinfo"])
    async def prefix_player_info(self, ctx: commands.Context, *args):
        """
        View full profile of a specific player.
        Usage: bb!player <player_name> [@club_role]
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed("Missing Player Name", "Usage: `bb!player <player_name> [@club_role]`")
            )
            return

        player_query = " ".join(clean_args)
        success, msg, data = await self.db.get_player_info(
            guild_id=ctx.guild.id,
            player_name=player_query,
            club_query=target_role if target_role else None,
        )
        if not success:
            await ctx.send(embed=error_embed("Player Not Found", msg))
            return

        embed = player_card_embed(player=data["player"], club=data["club"])
        await ctx.send(embed=embed)

    @commands.command(name="addplayer")
    async def prefix_addplayer(self, ctx: commands.Context, *args):
        """
        Add a player to a club squad (SoFIFA FC 26 auto-fill or Custom Player).
        Usage:
        • bb!addplayer <player_name> [@club_role]
        • bb!addplayer <player_name> <position> [status] [number] [rating] [potential] [@club_role]
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed(
                    "Missing Player Name",
                    "**Usage:** `bb!addplayer <player_name> [position] [status] [number] [rating] [potential] [@club_role]`\n\n"
                    "**Examples:**\n"
                    "• `bb!addplayer Mbappe` *(auto-fills 91 ST from SoFIFA)*\n"
                    "• `bb!addplayer Haaland 9 starting`\n"
                    "• `bb!addplayer \"Custom Guy\" ST 80 85`\n"
                    "• `bb!addcustomplayer <name> <pos>` *(direct custom player)*",
                )
            )
            return

        raw_player = clean_args[0]
        remaining = clean_args[1:]

        # Check if next argument is an explicit position
        position = None
        if remaining and remaining[0].upper().strip() in VALID_POSITIONS:
            position = remaining[0].upper().strip()
            remaining = remaining[1:]

        status = "starting"
        number = None
        rating = None
        potential = None
        alt_positions = None

        nums = []
        text_alts = []

        for arg in remaining:
            al = arg.lower().strip()
            if al in ("starting", "bench"):
                status = al
            elif al.startswith(("num:", "number:", "jersey:")):
                v = al.split(":", 1)[1]
                if v.isdigit():
                    number = int(v)
            elif al.startswith(("rating:", "rate:", "ovr:")):
                v = al.split(":", 1)[1]
                if v.isdigit():
                    rating = int(v)
            elif al.startswith(("pot:", "potential:")):
                v = al.split(":", 1)[1]
                if v.isdigit():
                    potential = int(v)
            elif al.startswith(("alt:", "alts:", "alt_pos:", "alt_positions:")):
                v = arg.split(":", 1)[1]
                if v:
                    text_alts.append(v)
            elif al.isdigit():
                nums.append(int(al))
            else:
                text_alts.append(arg)

        if len(nums) == 1:
            if number is None:
                number = nums[0]
            elif rating is None:
                rating = nums[0]
        elif len(nums) == 2:
            if number is None:
                number = nums[0]
                rating = nums[1]
            else:
                rating = nums[0]
                potential = nums[1]
        elif len(nums) >= 3:
            if number is None:
                number = nums[0]
                rating = nums[1]
                potential = nums[2]
            else:
                rating = nums[0]
                potential = nums[1]

        if text_alts:
            alt_positions = " ".join(text_alts)

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role to add a player.",
                )
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        # Check SoFIFA if not Discord mention or explicit custom
        sofifa_data = None
        clean_name = raw_player.strip()
        is_custom_prefix = clean_name.lower().startswith("custom:")
        is_mention = clean_name.startswith("<@") and clean_name.endswith(">")

        if not is_custom_prefix and not is_mention:
            if clean_name.isdigit():
                sofifa_data = await self.db.get_cached_sofifa_player(clean_name)
            elif ":" in clean_name and clean_name.split(":")[0].isdigit():
                sofifa_data = await self.db.get_cached_sofifa_player(clean_name.split(":")[0])

            if not sofifa_data:
                sofifa_data = await self.db.get_cached_sofifa_player(clean_name)

            if not sofifa_data and len(clean_name) >= 3:
                try:
                    fetched = await fetch_sofifa_players(keyword=clean_name, timeout=5)
                    if fetched:
                        await self.db.cache_sofifa_players(fetched)
                        clean_lower = clean_name.lower()
                        for r in fetched:
                            if clean_lower in r["name"].lower() or clean_lower in r["full_name"].lower():
                                sofifa_data = r
                                break
                        if not sofifa_data:
                            sofifa_data = fetched[0]
                except Exception:
                    pass

        if sofifa_data:
            final_name = clean_name if not clean_name.isdigit() else (sofifa_data.get("full_name") or sofifa_data["name"])
            final_pos = position or sofifa_data.get("primary_pos", "ST")
            final_rating = rating if rating is not None else sofifa_data.get("overall_rating", 75)
            final_pot = potential if potential is not None else sofifa_data.get("potential", final_rating)
            if alt_positions is not None:
                final_alts = alt_positions
            else:
                raw_positions = [x.strip() for x in sofifa_data.get("positions", "").split(",") if x.strip()]
                alts = [p for p in raw_positions if p != final_pos]
                final_alts = ", ".join(alts) if alts else None
            avatar_url = sofifa_data.get("avatar")
            team_origin = sofifa_data.get("team")
        else:
            final_name = clean_name[7:].strip() if is_custom_prefix else clean_name
            final_pos = position or "ST"
            final_rating = rating if rating is not None else 75
            final_pot = potential if potential is not None else 80
            final_alts = alt_positions
            avatar_url = None
            team_origin = None

        success, msg, p_data = await self.db.add_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=final_name,
            position=final_pos,
            status=status,
            number=number,
            rating=final_rating,
            potential=final_pot,
            alt_positions=final_alts,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Add Player Failed", msg))
            return

        if sofifa_data:
            desc = (
                f"✅ **{final_name}** registered from SoFIFA FC 26 database!\n\n"
                f"• **Position:** `{final_pos}`" + (f" *(Alts: `{final_alts}`)*" if final_alts else "") + "\n"
                f"• **Rating:** ⭐ **{final_rating} OVR** (Potential: **{final_pot}**)\n"
                f"• **Original Club:** {team_origin or 'Free Agent'}\n"
                f"• **Lineup Status:** `{status.title()}`" + (f" (Jersey #{number})" if number is not None else "") + "\n"
                f"• **Club:** **[{target_club['tag']}] {target_club['name']}**\n\n"
                f"💡 *You can edit this player anytime with `/player edit` or `bb!editplayer`.*"
            )
            embed = create_beastly_embed(
                title="⭐ Player Registered (SoFIFA FC 26)",
                description=desc,
                color=COLOR_SUCCESS,
            )
            if avatar_url:
                embed.set_thumbnail(url=avatar_url)
        else:
            desc = (
                f"✅ **{final_name}** registered as a **Custom Player**!\n\n"
                f"• **Position:** `{final_pos}`" + (f" *(Alts: `{final_alts}`)*" if final_alts else "") + "\n"
                f"• **Rating:** ⭐ **{final_rating} OVR** (Potential: **{final_pot}**)\n"
                f"• **Lineup Status:** `{status.title()}`" + (f" (Jersey #{number})" if number is not None else "") + "\n"
                f"• **Club:** **[{target_club['tag']}] {target_club['name']}**\n\n"
                f"💡 *You can edit this player anytime with `/player edit` or `bb!editplayer`.*"
            )
            embed = create_beastly_embed(
                title="👤 Custom Player Registered",
                description=desc,
                color=COLOR_SUCCESS,
            )

        await ctx.send(embed=embed)

    @commands.command(name="addcustomplayer", aliases=["customplayer"])
    async def prefix_addcustomplayer(self, ctx: commands.Context, *args):
        """
        Directly add a custom or server player to your squad.
        Usage: bb!addcustomplayer <name> [position] [status] [number] [rating] [potential] [@club]
        Example: bb!addcustomplayer "John Doe" CAM starting 10 82 86
        """
        if not args:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "**Usage:** `bb!addcustomplayer <player_name> [position] [status] [number] [rating] [potential] [@club]`\n"
                    "**Example:** `bb!addcustomplayer \"John Doe\" CAM starting 10 82 86`",
                )
            )
            return
        new_args = list(args)
        new_args[0] = f"custom:{new_args[0]}"
        await self.prefix_addplayer.callback(self, ctx, *new_args)

    @commands.command(name="editplayer")
    async def prefix_editplayer(self, ctx: commands.Context, *args):
        """
        Edit an existing player's details.
        Usage: bb!editplayer <player> <field> <value> [@club_role]
        Fields: name, position (or pos), status, number, rating, potential, alt (or altpos)
        Example: bb!editplayer Messi pos RW @Barca
        Example: bb!editplayer Mbappe rating 91 @RealMadrid
        Example: bb!editplayer Mbappe alt "LW, RW, CAM, RM" @RealMadrid
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if len(clean_args) < 3:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "Usage: `bb!editplayer <player> <field> <value> [@club_role]`\n"
                    "Fields: `name`, `pos`, `status`, `number`, `rating`, `potential`, `alt`\n"
                    "Alt Positions Format: `\"pos1, pos2, pos3, .....\"` (e.g. `\"LW, RW, CAM\"`)",
                )
            )
            return

        player = clean_args[0]
        field = clean_args[1].lower()
        val = " ".join(clean_args[2:])

        new_name = None
        new_pos = None
        new_status = None
        new_num = None
        new_rating = None
        new_pot = None
        new_alt = None

        if field in ("name", "newname"):
            new_name = val
        elif field in ("pos", "position"):
            new_pos = val
        elif field in ("status", "lineup"):
            new_status = val
        elif field in ("num", "number", "jersey"):
            if not val.isdigit():
                await ctx.send(embed=error_embed("Invalid Number", "Jersey number must be a number from 0 to 99."))
                return
            new_num = int(val)
        elif field in ("rating", "rate", "ovr"):
            if not val.isdigit() or not (1 <= int(val) <= 99):
                await ctx.send(embed=error_embed("Invalid Rating", "Player rating must be a number from 1 to 99."))
                return
            new_rating = int(val)
        elif field in ("potential", "pot"):
            if not val.isdigit() or not (1 <= int(val) <= 99):
                await ctx.send(embed=error_embed("Invalid Potential", "Player potential must be a number from 1 to 99."))
                return
            new_pot = int(val)
        elif field in ("alt", "altpos", "alt_positions", "alts"):
            new_alt = val
        else:
            await ctx.send(
                embed=error_embed(
                    "Invalid Field",
                    f"Unknown field '{field}'. Valid fields are: `name`, `pos`, `status`, `number`, `rating`, `potential`, `alt`.",
                )
            )
            return

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role to edit a player.",
                )
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg, p_data = await self.db.edit_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=player,
            new_name=new_name,
            position=new_pos,
            status=new_status,
            number=new_num,
            rating=new_rating,
            potential=new_pot,
            alt_positions=new_alt,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Edit Player Failed", msg))
            return

        embed = success_embed("Player Updated", msg)
        await ctx.send(embed=embed)

    @commands.command(name="removeplayer")
    async def prefix_removeplayer(self, ctx: commands.Context, *args):
        """
        Remove a player from a club squad.
        Usage: bb!removeplayer <player> [@club_role]
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed("Missing Player Name", "Usage: `bb!removeplayer <player> [@club_role]`")
            )
            return

        player = clean_args[0]
        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(
                embed=error_embed(
                    "Club Not Found",
                    "You must belong to a club or mention a club role to remove a player.",
                )
            )
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg = await self.db.remove_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=player,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Remove Failed", msg))
            return

        embed = success_embed("Player Removed", msg)
        await ctx.send(embed=embed)

    @commands.command(name="start")
    async def prefix_start(self, ctx: commands.Context, *args):
        """
        Promote/move a player to the Starting XI.
        Usage: bb!start <player> [position] [@club_role]
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed("Missing Player Name", "Usage: `bb!start <player> [position] [@club_role]`")
            )
            return

        player = clean_args[0]
        pos = clean_args[1] if len(clean_args) > 1 else None

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg, _ = await self.db.edit_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=player,
            status="starting",
            position=pos,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Action Failed", msg))
            return

        embed = success_embed("Promoted to Starting XI", msg)
        await ctx.send(embed=embed)

    @commands.command(name="bench")
    async def prefix_bench(self, ctx: commands.Context, *args):
        """
        Move a player to the Substitutes Bench.
        Usage: bb!bench <player> [@club_role]
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed("Missing Player Name", "Usage: `bb!bench <player> [@club_role]`")
            )
            return

        player = clean_args[0]
        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg, _ = await self.db.edit_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=player,
            status="bench",
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Action Failed", msg))
            return

        embed = success_embed("Moved to Bench", msg)
        await ctx.send(embed=embed)

    @commands.command(name="swap")
    async def prefix_swap(self, ctx: commands.Context, *args):
        """
        Swap two players (substitute starter & bench or switch positions).
        Usage: bb!swap <player1> <player2> [@club_role]
        Example: bb!swap Cristiano Benzema @RealMadrid
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if len(clean_args) < 2:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "Usage: `bb!swap <player1> <player2> [@club_role]`",
                )
            )
            return

        player1 = clean_args[0]
        player2 = clean_args[1]

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        # Check if the second argument is a tactical position (e.g. bb!swap Vinicius LW or bb!swap Mbappe to RW)
        if clean_args[-1].upper() in VALID_POSITIONS and len(clean_args) >= 2:
            target_pos = clean_args[-1].upper()
            player_tokens = clean_args[:-1]
            if player_tokens and player_tokens[-1].lower() == "to":
                player_tokens = player_tokens[:-1]
            player_query = " ".join(player_tokens).strip()

            success, msg, _ = await self.db.switch_lineup_position(
                guild_id=ctx.guild.id,
                club_query=target_role if target_role else target_club["id"],
                player_query=player_query,
                new_position=target_pos,
                default_owner_id=ctx.author.id,
            )
            if not success:
                await ctx.send(embed=error_embed("Switch Position Failed", msg))
                return
            embed = success_embed("Tactical Swap", msg)
            await ctx.send(embed=embed)
            return

        success, msg = await self.db.swap_club_players(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player1_name=player1,
            player2_name=player2,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Swap Failed", msg))
            return

        embed = success_embed("Tactical Swap", msg)
        await ctx.send(embed=embed)

    @commands.command(name="sub", aliases=["substitute", "subplayer"])
    async def prefix_sub(self, ctx: commands.Context, *args):
        """
        Substitute a starting player with a bench player.
        Usage:
          bb!sub <player_off> <player_on> [@club_role]
          bb!sub off <player_off> on <player_on> [@club_role]
          bb!sub <player_on> for <player_off> [@club_role]
        Aliases: bb!substitute, bb!subplayer
        Example: bb!sub Haaland Alvarez @ManCity
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a.strip() for a in args if a.strip() and not (a.startswith("<@&") and a.endswith(">"))]

        if not clean_args:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "**Usage:** `bb!sub <player_off> <player_on> [@club_role]`\n"
                    "**Aliases:** `bb!substitute`, `bb!subplayer`\n"
                    "**Example:** `bb!sub Haaland Alvarez @ManCity`\n"
                    "*(Subs out starter Haaland and brings in bench player Alvarez)*",
                )
            )
            return

        # Parse potential syntax like "off Haaland on Alvarez" or "Alvarez for Haaland"
        off_name = None
        on_name = None
        lower_tokens = [w.lower() for w in clean_args]

        if "off" in lower_tokens and "on" in lower_tokens:
            off_idx = lower_tokens.index("off")
            on_idx = lower_tokens.index("on")
            if off_idx < on_idx:
                off_name = " ".join(clean_args[off_idx + 1:on_idx]).strip()
                on_name = " ".join(clean_args[on_idx + 1:]).strip()
            else:
                on_name = " ".join(clean_args[on_idx + 1:off_idx]).strip()
                off_name = " ".join(clean_args[off_idx + 1:]).strip()
        elif "for" in lower_tokens:
            for_idx = lower_tokens.index("for")
            # e.g. "Alvarez for Haaland" -> on is Alvarez, off is Haaland
            on_name = " ".join(clean_args[:for_idx]).strip()
            off_name = " ".join(clean_args[for_idx + 1:]).strip()
        elif len(clean_args) >= 2:
            off_name = clean_args[0]
            on_name = " ".join(clean_args[1:]).strip()
        else:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "Please specify both the player coming **off** and the player coming **on**.\n"
                    "**Usage:** `bb!sub <player_off> <player_on> [@club_role]`",
                )
            )
            return

        if not off_name or not on_name:
            await ctx.send(
                embed=error_embed(
                    "Invalid Parameters",
                    "Please specify both the player coming **off** and the player coming **on**.\n"
                    "**Usage:** `bb!sub <player_off> <player_on> [@club_role]`",
                )
            )
            return

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        success, msg = await self.db.substitute_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_off_name=off_name,
            player_on_name=on_name,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Substitution Failed", msg))
            return

        embed = success_embed("Tactical Substitution", msg)
        await ctx.send(embed=embed)

    @commands.command(name="switchpos", aliases=["switch", "setpos"])
    async def prefix_switchpos(self, ctx: commands.Context, *args):
        """
        Switch a player's position or swap positions between two players in the lineup.
        Usage:
          bb!switchpos <player> <new_position> [@club_role]
          bb!switchpos <player1> <player2> [@club_role]
        Examples:
          bb!switchpos Mbappe ST @RealMadrid
          bb!switchpos Vinicius Rodrygo @RealMadrid
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a.strip() for a in args if a.strip() and not (a.startswith("<@&") and a.endswith(">"))]

        # Strip leading command/subcommand words if user typed e.g. "bb!lineup switch ...", "bb!switchpos position ..."
        while clean_args and clean_args[0].lower() in ("switch", "switchpos", "setpos", "position", "pos"):
            clean_args.pop(0)
        while clean_args and clean_args[0].lower() in ("position", "pos"):
            clean_args.pop(0)

        if not clean_args:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "**Usage:**\n"
                    "• Switch position: `bb!switchpos <player> <new_position> [@club_role]`\n"
                    "• Swap 2 players: `bb!switchpos <player1> <player2> [@club_role]`\n"
                    f"*Supported Positions:* {', '.join(VALID_POSITIONS)}",
                )
            )
            return

        if target_role:
            target_club = await self.db.get_or_create_club_from_role(
                ctx.guild.id, target_role, default_owner_id=ctx.author.id
            )
        else:
            target_club = await self.db.get_club_by_user(ctx.guild.id, ctx.author.id)

        if not target_club:
            await ctx.send(embed=error_embed("Club Not Found", "You must belong to a club or mention a club role."))
            return

        has_perm, perm_msg = await check_squad_permission(
            self.db, ctx.guild.id, ctx.author, target_club
        )
        if not has_perm:
            await ctx.send(embed=error_embed("Permission Denied", perm_msg))
            return

        # Case 1: Last token is a valid position (e.g. `Kylian Mbappe LW` or `Mbappe to LW`)
        if clean_args[-1].upper() in VALID_POSITIONS and len(clean_args) >= 2:
            target_pos = clean_args[-1].upper()
            player_tokens = clean_args[:-1]
            if player_tokens and player_tokens[-1].lower() == "to":
                player_tokens = player_tokens[:-1]
            player_query = " ".join(player_tokens).strip()

            success, msg, _ = await self.db.switch_lineup_position(
                guild_id=ctx.guild.id,
                club_query=target_role if target_role else target_club["id"],
                player_query=player_query,
                new_position=target_pos,
                default_owner_id=ctx.author.id,
            )
            if not success:
                await ctx.send(embed=error_embed("Switch Position Failed", msg))
                return
            await ctx.send(embed=success_embed("Position Switched", msg))
            return

        # Case 2: First token is a valid position (e.g. `LW Kylian Mbappe`)
        if clean_args[0].upper() in VALID_POSITIONS and len(clean_args) >= 2:
            target_pos = clean_args[0].upper()
            player_query = " ".join(clean_args[1:]).strip()

            success, msg, _ = await self.db.switch_lineup_position(
                guild_id=ctx.guild.id,
                club_query=target_role if target_role else target_club["id"],
                player_query=player_query,
                new_position=target_pos,
                default_owner_id=ctx.author.id,
            )
            if not success:
                await ctx.send(embed=error_embed("Switch Position Failed", msg))
                return
            await ctx.send(embed=success_embed("Position Switched", msg))
            return

        # Case 3: Swapping 2 players
        raw_text = " ".join(clean_args)
        p1 = None
        p2 = None
        if "," in raw_text:
            parts = [p.strip() for p in raw_text.split(",") if p.strip()]
            if len(parts) >= 2:
                p1, p2 = parts[0], parts[1]
        elif " and " in raw_text.lower():
            idx = raw_text.lower().find(" and ")
            p1, p2 = raw_text[:idx].strip(), raw_text[idx + 5:].strip()
        elif " with " in raw_text.lower():
            idx = raw_text.lower().find(" with ")
            p1, p2 = raw_text[:idx].strip(), raw_text[idx + 6:].strip()
        elif " for " in raw_text.lower():
            idx = raw_text.lower().find(" for ")
            p1, p2 = raw_text[:idx].strip(), raw_text[idx + 5:].strip()
        elif len(clean_args) == 2:
            p1, p2 = clean_args[0], clean_args[1]

        if p1 and p2:
            success, msg = await self.db.swap_club_players(
                guild_id=ctx.guild.id,
                club_query=target_role if target_role else target_club["id"],
                player1_name=p1,
                player2_name=p2,
                default_owner_id=ctx.author.id,
            )
            if not success:
                await ctx.send(embed=error_embed("Swap Failed", msg))
                return
            await ctx.send(embed=success_embed("Tactical Swap", msg))
            return

        await ctx.send(
            embed=error_embed(
                "Invalid Format",
                "Could not determine player or target position.\n\n"
                "**Usage Examples:**\n"
                "• `bb!switchpos Kylian Mbappe LW`\n"
                "• `bb!switchpos Mbappe ST @ClubRole`\n"
                "• `bb!switchpos Mbappe Vinicius` *(swap two players)*\n"
                f"*Valid Positions:* {', '.join(VALID_POSITIONS)}",
            )
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SquadCog(bot))
