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
    club_lineup_embed,
    player_card_embed,
    error_embed,
    success_embed,
    formations_list_embed,
    send_msg,
)
from utils.lineup_image import generate_lineup_image

logger = logging.getLogger("BeastlyBank.Squad")


async def formation_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Autocomplete for supported football formations."""
    cur = current.strip().lower()
    choices = []
    for k in SUPPORTED_FORMATIONS:
        if not cur or cur in k.lower():
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

        if view == "image":
            # Resolve manager display name
            manager_name = "Club Manager"
            owner_id = club_info.get("owner_id")
            if owner_id and interaction.guild:
                member = interaction.guild.get_member(owner_id)
                if member:
                    manager_name = member.display_name

            team_name = f"[{club_info['tag']}] {club_info['name']}" if club_info.get("tag") else club_info.get("name", "Beastly FC")

            buf = generate_lineup_image(
                team_name=team_name,
                manager_name=manager_name,
                formation_name=formation,
                starting_players=starting_players,
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

    @app_commands.command(name="lineupcard", description="Generate a clean matchday Starting 11 pitch image for your club.")
    @app_commands.describe(club="Club role to inspect (defaults to your club)")
    async def slash_lineupcard(
        self,
        interaction: discord.Interaction,
        club: Optional[discord.Role] = None,
    ):
        await self.slash_lineup(interaction, club=club, view="image")

    @app_commands.command(name="customlineup", description="Generate a custom clean matchday Starting 11 pitch image on the fly.")
    @app_commands.describe(
        team="Team or club name (e.g. Real Madrid CF)",
        manager="Manager name (e.g. Carlo Ancelotti)",
        formation="Formation (e.g. 4-3-3 Balanced, 4-2-3-1 Wide)",
        players="Optional comma-separated player names",
    )
    @app_commands.autocomplete(formation=formation_autocomplete)
    async def slash_custom_lineup(
        self,
        interaction: discord.Interaction,
        team: str,
        manager: str,
        formation: str,
        players: Optional[str] = None,
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

        buf = generate_lineup_image(
            team_name=team,
            manager_name=manager,
            formation_name=formation,
            starting_players=player_list,
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

    @player_group.command(name="add", description="Add a player to a club squad (Starting XI or Bench).")
    @app_commands.describe(
        player="Player name or Discord mention",
        position="Primary position (e.g. ST, CB, CM, GK)",
        status="Lineup status: starting or bench",
        number="Jersey number (0-99)",
        rating="Overall player rating (1-99, default 75)",
        potential="Player potential rating (1-99, default 80)",
        alt_positions="Alternative positions separated by commas (e.g. 'pos1, pos2, pos3, .....')",
        club="Target club role (defaults to your club)",
    )
    @app_commands.autocomplete(position=position_autocomplete)
    async def slash_player_add(
        self,
        interaction: discord.Interaction,
        player: str,
        position: str,
        status: Literal["starting", "bench"] = "starting",
        number: Optional[int] = None,
        rating: Optional[app_commands.Range[int, 1, 99]] = 75,
        potential: Optional[app_commands.Range[int, 1, 99]] = 80,
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

        success, msg, p_data = await self.db.add_club_player(
            guild_id=interaction.guild_id,
            club_query=club if club else target_club["id"],
            player_name=player,
            position=position,
            status=status,
            number=number,
            rating=rating,
            potential=potential,
            alt_positions=alt_positions,
            default_owner_id=interaction.user.id,
        )
        if not success:
            await send_msg(interaction, embed=error_embed("Add Player Failed", msg), ephemeral=True)
            return

        embed = success_embed("Player Registered", msg)
        await send_msg(interaction, embed=embed)

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

        manager_name = "Club Manager"
        owner_id = club_info.get("owner_id")
        if owner_id and ctx.guild:
            member = ctx.guild.get_member(owner_id)
            if member:
                manager_name = member.display_name

        team_name = f"[{club_info['tag']}] {club_info['name']}" if club_info.get("tag") else club_info.get("name", "Beastly FC")

        buf = generate_lineup_image(
            team_name=team_name,
            manager_name=manager_name,
            formation_name=formation,
            starting_players=starting_players,
        )
        file = discord.File(fp=buf, filename="lineup.png")
        await ctx.send(file=file)

    @commands.command(name="customlineup")
    async def prefix_custom_lineup(self, ctx: commands.Context, *, args: str = ""):
        """
        Generate a custom Starting 11 pitch image.
        Usage: bb!customlineup <team> | <manager> | <formation> | [players]
        Example: bb!customlineup Real Madrid | Carlo Ancelotti | 4-3-3 Balanced | Mbappe, Vini, Bellingham
        """
        parts = [p.strip() for p in args.split("|")] if args else []
        if len(parts) < 3:
            await ctx.send(
                embed=error_embed(
                    "Missing Information",
                    "Please provide team, manager, and formation separated by `|`.\n"
                    "**Usage:** `bb!customlineup <Team Name> | <Manager Name> | <Formation> | [Players...]`\n"
                    "**Example:** `bb!customlineup Real Madrid | Carlo Ancelotti | 4-3-3 Balanced | Courtois, Mendy, Rudiger, Militao, Carvajal, Tchouameni, Bellingham, Valverde, Vini, Mbappe, Rodrygo`"
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

        buf = generate_lineup_image(
            team_name=team,
            manager_name=manager,
            formation_name=formation,
            starting_players=player_list,
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
        Add a player to a club squad (Starting XI or Bench).
        Usage: bb!addplayer <player> <position> [status] [number] [rating] [potential] ["pos1, pos2, pos3, ....."] [@club_role]
        Example: bb!addplayer Mbappe ST starting 9 91 95 "LW, RW, CAM" @RealMadrid
        """
        target_role = ctx.message.role_mentions[0] if ctx.message.role_mentions else None
        clean_args = [a for a in args if not (a.startswith("<@&") and a.endswith(">"))]

        if len(clean_args) < 2:
            await ctx.send(
                embed=error_embed(
                    "Missing Parameters",
                    "Usage: `bb!addplayer <player> <position> [status] [number] [rating] [potential] [\"pos1, pos2, pos3, .....\"] [@club_role]`\n"
                    f"Valid Positions: {', '.join(VALID_POSITIONS)}",
                )
            )
            return

        player = clean_args[0]
        position = clean_args[1]

        status = "starting"
        number = None
        rating = 75
        potential = 80
        alt_positions = None

        nums = []
        text_alts = []

        for arg in clean_args[2:]:
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
            elif rating == 75:
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

        success, msg, p_data = await self.db.add_club_player(
            guild_id=ctx.guild.id,
            club_query=target_role if target_role else target_club["id"],
            player_name=player,
            position=position,
            status=status,
            number=number,
            rating=rating,
            potential=potential,
            alt_positions=alt_positions,
            default_owner_id=ctx.author.id,
        )
        if not success:
            await ctx.send(embed=error_embed("Add Player Failed", msg))
            return

        embed = success_embed("Player Registered", msg)
        await ctx.send(embed=embed)

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
