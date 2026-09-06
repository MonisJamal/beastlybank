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


def require_banker_or_admin():
    """App command check decorator for Banker/Staff operations."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return False

        # Guild Administrators always have access
        if interaction.user.guild_permissions.administrator:
            return True

        user_role_ids = {r.id for r in interaction.user.roles}
        allowed_roles = set(config.BANKER_ROLE_IDS + config.ADMIN_ROLE_IDS)

        if allowed_roles and (user_role_ids & allowed_roles):
            return True

        raise NotBankerError("You must hold a **BeastlyBank Banker** or **Staff** role to use this command.")
    return app_commands.check(predicate)

