"""
Security checks, guild lock enforcement, and staff permission helpers.
"""
from typing import Callable
import discord
from discord import app_commands
import config
from config import SERVER_NAME


class NotInBeastlyFCError(app_commands.AppCommandError):
    """Raised when a command is run outside of BeastlyFC."""
    pass


class NotBankerError(app_commands.AppCommandError):
    """Raised when a user lacks Banker/Staff credentials."""
    pass


def is_beastlyfc_guild_check(interaction: discord.Interaction) -> bool:
    """Verifies interaction is within the authorized BeastlyFC guild."""
    if not interaction.guild:
        return False

    # If guild lock is active, enforce strictly
    if config.BEASTLYFC_GUILD_ID != 0 and interaction.guild.id != config.BEASTLYFC_GUILD_ID:
        return False

    return True


def require_beastlyfc():
    """App command check decorator for BeastlyFC guild lock."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not is_beastlyfc_guild_check(interaction):
            raise NotInBeastlyFCError(
                f"BeastlyBank is strictly locked to **{SERVER_NAME}**! Commands cannot be used in other servers."
            )
        return True
    return app_commands.check(predicate)


def is_banker_or_admin(user: discord.User | discord.Member) -> bool:
    """Check if a member holds BeastlyBank Banker, Admin, or Staff permissions."""
    if not isinstance(user, discord.Member):
        return False

    # Guild Administrators or Manage Guild
    if user.guild_permissions.administrator or user.guild_permissions.manage_guild:
        return True

    # Role IDs from config
    user_role_ids = {r.id for r in user.roles}
    allowed_ids = set(config.BANKER_ROLE_IDS + config.ADMIN_ROLE_IDS)
    if allowed_ids and (user_role_ids & allowed_ids):
        return True

    # Role Name matching (e.g. "BeastlyBank Banker", "Banker", "Admin", "Staff")
    for role in user.roles:
        r_name = role.name.strip().lower()
        if (
            "beastlybank banker" in r_name
            or "banker" in r_name
            or "admin" in r_name
            or "staff" in r_name
        ):
            return True

    return False


def require_banker_or_admin():
    """App command check decorator for Banker/Staff operations."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False

        if is_banker_or_admin(interaction.user):
            return True

        raise NotBankerError("You must hold the **BeastlyBank Banker** role or **Administrator** permissions to use this command.")
    return app_commands.check(predicate)

