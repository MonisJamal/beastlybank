"""
Automated unit and integration test suite for BeastlyBank.
Validates multi-currency ACID ledger, transfers, club treasuries, shop, and giveaways.
"""
import os
import tempfile
from unittest.mock import MagicMock
import discord
import pytest
import pytest_asyncio

from database.db import DatabaseManager
from config import parse_amount, SUPPORTED_FORMATIONS
from utils.checks import is_beastlyfc_guild_check


@pytest_asyncio.fixture
async def db():
    """Create an isolated temporary database for testing."""
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    manager = DatabaseManager(temp_db_path)
    await manager.init_db()
    yield manager

    await manager.close()
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


@pytest.mark.asyncio
async def test_user_default_zero_balances(db: DatabaseManager):
    """Verify new users start with 0 Cash, 0 Points, 0 Tokens by default."""
    user_id = 111111111
    guild_id = 999999999

    user = await db.get_or_create_user(user_id, guild_id)
    assert user["cash"] == 0
    assert user["points"] == 0
    assert user["tokens"] == 0
    assert user["daily_streak"] == 0

    # No starter bonus transaction
    txs = await db.get_transactions(user_id, guild_id)
    assert len(txs) == 0


@pytest.mark.asyncio
async def test_player_to_player_transfer(db: DatabaseManager):
    """Test person-to-person transfers for Cash and Tokens."""
    sender_id = 101
    receiver_id = 102
    guild_id = 999999999

    # Preload sender with funds
    await db.update_balance(sender_id, guild_id, "cash", 1000, "test_deposit")
    await db.update_balance(sender_id, guild_id, "tokens", 10, "test_deposit")

    # Transfer 500 cash
    success, msg = await db.transfer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        guild_id=guild_id,
        currency="cash",
        amount=500,
        reason="P2P Cash Test",
    )
    assert success is True

    sender = await db.get_or_create_user(sender_id, guild_id)
    receiver = await db.get_or_create_user(receiver_id, guild_id)
    assert sender["cash"] == 500
    assert receiver["cash"] == 500

    # Transfer 4 tokens
    success, msg = await db.transfer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        guild_id=guild_id,
        currency="tokens",
        amount=4,
        reason="P2P Token Test",
    )
    assert success is True

    sender = await db.get_or_create_user(sender_id, guild_id)
    receiver = await db.get_or_create_user(receiver_id, guild_id)
    assert sender["tokens"] == 6
    assert receiver["tokens"] == 4

    # Insufficient funds check
    fail_success, fail_msg = await db.transfer(
        sender_id=sender_id,
        receiver_id=receiver_id,
        guild_id=guild_id,
        currency="cash",
        amount=9999,
        reason="Overdraft attempt",
    )
    assert fail_success is False
    assert "Insufficient" in fail_msg


@pytest.mark.asyncio
async def test_club_treasury_lifecycle(db: DatabaseManager):
    """Test club formation, initial treasury, deposits, and captain withdrawals."""
    owner_id = 401
    guild_id = 999999999

    # Fund owner so they can afford 2,000 registration fee
    await db.update_balance(owner_id, guild_id, "cash", 5000, "test_credit")

    # Create club
    success, msg, club = await db.create_club(
        guild_id=guild_id,
        name="Beastly Strikers",
        tag="BST",
        owner_id=owner_id,
    )
    assert success is True
    assert club is not None
    assert club["name"] == "Beastly Strikers"
    assert club["treasury_cash"] == 0  # 0 default club treasury

    # Deposit into club treasury
    dep_success, dep_msg = await db.club_deposit(
        club_id=club["id"],
        user_id=owner_id,
        guild_id=guild_id,
        currency="cash",
        amount=1000,
    )
    assert dep_success is True

    updated_club = await db.get_club_by_name(guild_id, "BST")
    assert updated_club["treasury_cash"] == 1000

    # Withdraw from club treasury
    w_success, w_msg = await db.club_withdraw(
        club_id=club["id"],
        user_id=owner_id,
        guild_id=guild_id,
        currency="cash",
        amount=400,
        reason="Player boot purchase",
    )
    assert w_success is True

    final_club = await db.get_club_by_name(guild_id, "BST")
    assert final_club["treasury_cash"] == 600

    # Unauthorized withdrawal attempt
    fake_user = 999
    unauth_success, unauth_msg = await db.club_withdraw(
        club_id=club["id"],
        user_id=fake_user,
        guild_id=guild_id,
        currency="cash",
        amount=100,
        reason="Theft attempt",
    )
    assert unauth_success is False
    assert "Only Club Owners" in unauth_msg





@pytest.mark.asyncio
async def test_giveaways_and_payouts(db: DatabaseManager):
    """Test giveaway entry, winner selection, and automatic bank disbursement."""
    host_id = 601
    entrant1 = 602
    entrant2 = 603
    guild_id = 999999999
    msg_id = 88888888

    await db.create_giveaway(
        message_id=msg_id,
        channel_id=123,
        guild_id=guild_id,
        host_id=host_id,
        prize_name="Super Cup Bonus",
        prize_currency="cash",
        prize_amount=2500,
        winner_count=1,
        end_time="2026-01-01T00:00:00+00:00",
    )

    # Entrants join
    await db.toggle_giveaway_entry(msg_id, entrant1)
    await db.toggle_giveaway_entry(msg_id, entrant2)

    # Conclude giveaway
    success, msg, winners, gw = await db.end_giveaway(msg_id)
    assert success is True
    assert len(winners) == 1
    assert winners[0] in (entrant1, entrant2)

    # Verify winner was credited with 2500 Cash prize (default 0 + 2500)
    winner_acc = await db.get_or_create_user(winners[0], guild_id)
    assert winner_acc["cash"] == 2500


@pytest.mark.asyncio
async def test_admin_balance_and_audit(db: DatabaseManager):
    """Test bank staff balance overrides and transaction logging."""
    user_id = 701
    admin_id = 999
    guild_id = 999999999

    success, msg, acc = await db.admin_set_balance(
        user_id=user_id,
        guild_id=guild_id,
        currency="cash",
        amount=50000,
        reason="Tournament Prize Pool",
        admin_id=admin_id,
    )
    assert success is True
    assert acc["cash"] == 50000

    # Verify audit trail has recorded admin override
    txs = await db.get_transactions(user_id, guild_id)
    admin_tx = next(t for t in txs if t["tx_type"] == "admin_set")
    assert admin_tx["amount"] == 50000
    assert str(admin_id) in admin_tx["reason"]


def test_server_lock_check():
    """Verify guild lock validator."""
    # Mock Interaction
    mock_interaction = MagicMock()
    mock_interaction.guild = MagicMock()
    mock_interaction.guild.id = 12345

    import config
    original_guild = config.BEASTLYFC_GUILD_ID

    try:
        config.BEASTLYFC_GUILD_ID = 12345
        assert is_beastlyfc_guild_check(mock_interaction) is True

        mock_interaction.guild.id = 99999
        assert is_beastlyfc_guild_check(mock_interaction) is False
    finally:
        config.BEASTLYFC_GUILD_ID = original_guild


@pytest.mark.asyncio
async def test_shop_and_purchases(db: DatabaseManager):
    """Verify adding items to shop, purchasing, and stock tracking."""
    user_id = 801
    guild_id = 999999999

    # Add item
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO shop_items (guild_id, name, description, price, currency, stock, is_active)
            VALUES (?, 'VIP Role', 'Special server role', 500, 'cash', 5, 1);
            """,
            (guild_id,),
        )
        await conn.commit()

    items = await db.get_shop_items(guild_id)
    assert len(items) >= 1
    item = next(i for i in items if i["name"] == "VIP Role")
    assert item["price"] == 500

    # User with 0 cash fails to buy
    fail_buy, msg, _ = await db.buy_item(user_id, guild_id, item["id"], quantity=1)
    assert fail_buy is False
    assert "Insufficient" in msg

    # Grant cash and purchase
    await db.update_balance(user_id, guild_id, "cash", 1000, "test_grant")
    success, msg, _ = await db.buy_item(user_id, guild_id, item["id"], quantity=1)
    assert success is True

    # Check inventory
    inv = await db.get_inventory(user_id, guild_id)
    assert len(inv) == 1
    assert inv[0]["name"] == "VIP Role"
    assert inv[0]["quantity"] == 1


@pytest.mark.asyncio
async def test_server_settings(db: DatabaseManager):
    """Test getting and toggling server settings."""
    guild_id = 999999999

    settings = await db.get_settings(guild_id)
    assert settings["economy_enabled"] == 1

    # Disable economy
    await db.update_setting(guild_id, "economy", False)
    updated = await db.get_settings(guild_id)
    assert updated["economy_enabled"] == 0

    # Re-enable economy
    await db.update_setting(guild_id, "economy", True)
    re_enabled = await db.get_settings(guild_id)
    assert re_enabled["economy_enabled"] == 1


@pytest.mark.asyncio
async def test_club_managers_and_history(db: DatabaseManager):
    """Test appointing club managers and fetching club treasury history."""
    owner_id = 901
    member_id = 902
    guild_id = 999999999

    await db.update_balance(owner_id, guild_id, "cash", 5000, "credit")
    _, _, club = await db.create_club(guild_id, "Thunder FC", "THN", owner_id)

    # Join member to club
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO club_members (club_id, user_id, guild_id, role) VALUES (?, ?, ?, 'Member');",
            (club["id"], member_id, guild_id),
        )
        await conn.commit()

    # Promote to Manager
    success, msg = await db.set_club_manager(club["id"], owner_id, member_id, is_manager=True)
    assert success is True
    assert "promoted" in msg

    # Fund club treasury with 500 cash for withdrawal test
    await db.club_deposit(club["id"], owner_id, guild_id, "cash", 500)

    # Manager can withdraw from treasury
    w_success, w_msg = await db.club_withdraw(
        club["id"], member_id, guild_id, "cash", 100, "Manager kit purchase"
    )
    assert w_success is True

    # History shows transaction
    txs = await db.get_club_transactions(club["id"], guild_id)
    assert len(txs) >= 1
    assert any("Manager kit purchase" in str(t["reason"]) for t in txs)


@pytest.mark.asyncio
async def test_free_club_creation(db: DatabaseManager):
    """Verify club registration is 100% free (no fee deducted, works with 0 cash)."""
    user_id = 999111
    guild_id = 999999999

    # User starts with 0 cash by default
    user = await db.get_or_create_user(user_id, guild_id)
    assert user["cash"] == 0

    # User creates club without paying fee
    success, msg, club = await db.create_club(guild_id, "Free Kings FC", "FKF", user_id)
    assert success is True
    assert club is not None
    assert club["name"] == "Free Kings FC"
    assert club["tag"] == "FKF"
    assert club["treasury_cash"] == 0  # 0 default club treasury

    # User still has 0 cash (no deduction)
    user_after = await db.get_or_create_user(user_id, guild_id)
    assert user_after["cash"] == 0


@pytest.mark.asyncio
async def test_parse_amount_scientific_and_human():
    """Verify scientific notation and human suffix parsing."""
    assert parse_amount("26e6") == 26_000_000
    assert parse_amount("3e7") == 30_000_000
    assert parse_amount("1.5e6") == 1_500_000
    assert parse_amount("26m") == 26_000_000
    assert parse_amount("500k") == 500_000
    assert parse_amount("1b") == 1_000_000_000
    assert parse_amount("10,000,000") == 10_000_000
    assert parse_amount("0") == 0
    assert parse_amount("-100") is None
    assert parse_amount("xyz") is None


@pytest.mark.asyncio
async def test_transfer_player_flow(db: DatabaseManager):
    """Test full player transfer flow: custom player name, scientific amount, vault-to-vault payment without recipient, roster relocation."""
    guild_id = 999999999
    seller_owner = 1001
    buyer_owner = 1002
    custom_player = "Erling Haaland"

    # Create selling club and buying club (starting with 0 vault balance)
    _, _, seller_club = await db.create_club(guild_id, "Real Stars", "RST", seller_owner)
    _, _, buyer_club = await db.create_club(guild_id, "Blue Hawks", "BHW", buyer_owner)
    assert seller_club["treasury_cash"] == 0
    assert buyer_club["treasury_cash"] == 0

    # Put custom player in selling club
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, role) VALUES (?, ?, ?, 'Player');",
            (seller_club["id"], guild_id, custom_player),
        )
        await conn.commit()

    # Fund buying club treasury with 30M cash
    transfer_fee = parse_amount("26e6")  # 26,000,000
    assert transfer_fee == 26_000_000
    await db.update_balance(buyer_owner, guild_id, "cash", 30_000_000, "admin_grant")
    await db.club_deposit(buyer_club["id"], buyer_owner, guild_id, "cash", 30_000_000)

    # Execute transfer WITHOUT recipient (recipient_id=None)
    success, msg, data = await db.transfer_player(
        guild_id=guild_id,
        player_name=custom_player,
        from_club_query="RST",
        to_club_query="BHW",
        amount=transfer_fee,
        payer_id=buyer_owner,
        recipient_id=None,
    )
    assert success is True
    assert data["amount"] == 26_000_000
    assert data["player_name"] == custom_player

    # Verify selling club vault received 26M cash (started from 0)
    seller_after = await db.get_club_by_name(guild_id, "RST")
    assert seller_after["treasury_cash"] == 26_000_000

    # Verify buyer club treasury debited by 26M (started from 0 + 30M - 26M = 4M)
    buyer_after = await db.get_club_by_name(guild_id, "BHW")
    assert buyer_after["treasury_cash"] == 4_000_000

    # Verify player moved from seller roster to buyer roster
    seller_members = await db.get_club_members(seller_club["id"])
    buyer_members = await db.get_club_members(buyer_club["id"])
    assert not any(m.get("player_name") == custom_player for m in seller_members)
    assert any(m.get("player_name") == custom_player for m in buyer_members)


@pytest.mark.asyncio
async def test_role_mention_and_object_club_lookup(db: DatabaseManager):
    """Test club resolution using Discord Role objects, role mentions, bracket tags, and auto-linking role_id."""
    guild_id = 999999999
    owner1 = 1111
    owner2 = 2222

    # Create two clubs
    _, _, club1 = await db.create_club(guild_id, "Red Dragons", "RDF", owner1)
    _, _, club2 = await db.create_club(guild_id, "Thunder FC", "TFC", owner2)

    # Mock Discord Role objects
    mock_from_role = MagicMock()
    mock_from_role.id = 1222195412295745501
    mock_from_role.name = "[RDF] Red Dragons"
    mock_from_role.mention = "<@&1222195412295745501>"

    mock_to_role = MagicMock()
    mock_to_role.id = 1222195412295745502
    mock_to_role.name = "Thunder FC"
    mock_to_role.mention = "<@&1222195412295745502>"

    # 1. Resolve club by Role object (matches tag in bracket or name)
    resolved_from = await db.get_club_by_name(guild_id, mock_from_role)
    assert resolved_from is not None
    assert resolved_from["id"] == club1["id"]
    assert resolved_from["role_id"] == mock_from_role.id

    resolved_to = await db.get_club_by_name(guild_id, mock_to_role)
    assert resolved_to is not None
    assert resolved_to["id"] == club2["id"]
    assert resolved_to["role_id"] == mock_to_role.id

    # 2. Resolve by string mention "<@&...>"
    mention_match = await db.get_club_by_name(guild_id, "<@&1222195412295745501>")
    assert mention_match is not None
    assert mention_match["id"] == club1["id"]

    # 3. Transfer using role objects directly
    # Add player to Red Dragons
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, role) VALUES (?, ?, ?, 'Player');",
            (club1["id"], guild_id, "Kylian Mbappe"),
        )
        await conn.commit()

    # Fund Thunder FC vault
    await db.update_club_treasury(guild_id, "TFC", "cash", "add", 50_000_000, owner2, "Seed")

    success, msg, data = await db.transfer_player(
        guild_id=guild_id,
        player_name="Kylian Mbappe",
        from_club_query=mock_from_role,
        to_club_query=mock_to_role,
        amount=30_000_000,
        payer_id=owner2,
        recipient_id=None,
    )
    assert success is True
    assert data["amount"] == 30_000_000
    assert data["player_name"] == "Kylian Mbappe"

    # Verify Red Dragons vault gained 30M
    c1_after = await db.get_club_by_name(guild_id, mock_from_role)
    assert c1_after["treasury_cash"] == 30_000_000

    # Verify Thunder FC vault debited 30M (50M - 30M = 20M)
    c2_after = await db.get_club_by_name(guild_id, mock_to_role)
    assert c2_after["treasury_cash"] == 20_000_000



@pytest.mark.asyncio
async def test_banker_vault_operations(db: DatabaseManager):
    """Test BeastlyBank Banker permissions to operate club vaults and manage vault balances."""
    guild_id = 999999999
    banker_id = 777777777
    owner_id = 888888888

    # Create club with 0 default vault
    _, _, club = await db.create_club(guild_id, "Apex Legends FC", "ALF", owner_id)
    assert club["treasury_cash"] == 0
    assert club["treasury_points"] == 0
    assert club["treasury_tokens"] == 0

    # 1. Banker /manage vault add
    success, msg, res = await db.update_club_treasury(
        guild_id=guild_id,
        club_query="ALF",
        currency="cash",
        action="add",
        amount=50_000_000,
        admin_id=banker_id,
        reason="Official BeastlyBank Sponsorship Grant",
    )
    assert success is True
    assert res["new_balance"] == 50_000_000

    # 2. Banker /manage vault remove
    success, msg, res = await db.update_club_treasury(
        guild_id=guild_id,
        club_query="ALF",
        currency="cash",
        action="remove",
        amount=10_000_000,
        admin_id=banker_id,
        reason="League Registration Fee",
    )
    assert success is True
    assert res["new_balance"] == 40_000_000

    # 3. Banker /manage vault set
    success, msg, res = await db.update_club_treasury(
        guild_id=guild_id,
        club_query="ALF",
        currency="cash",
        action="set",
        amount=100_000,
        admin_id=banker_id,
        reason="Vault Audit Reset",
    )
    assert success is True
    assert res["new_balance"] == 100_000

    # 4. Banker direct withdrawal from club vault (even if not in club squad)
    w_success, w_msg = await db.club_withdraw(
        club_id=club["id"],
        user_id=banker_id,
        guild_id=guild_id,
        currency="cash",
        amount=25_000,
        reason="Official Banker Treasury Draw",
        is_banker=True,
    )
    assert w_success is True
    banker_user = await db.get_or_create_user(banker_id, guild_id)
    assert banker_user["cash"] == 25_000

    # 5. Non-banker, non-member withdrawal rejected
    unauth_success, unauth_msg = await db.club_withdraw(
        club_id=club["id"],
        user_id=9999,
        guild_id=guild_id,
        currency="cash",
        amount=1000,
        reason="Unlawful withdrawal",
        is_banker=False,
    )
    assert unauth_success is False
    assert "Only Club Owners" in unauth_msg


@pytest.mark.asyncio
async def test_summary_system(db: DatabaseManager):
    """Test economy stats aggregation and summary embed generation."""
    from utils.embeds import (
        summary_overview_embed,
        summary_finance_embed,
        summary_commands_embed,
        summary_economy_embed,
    )

    guild_id = 999999999
    user_id = 12345

    # 1. Setup user and club
    await db.get_or_create_user(user_id, guild_id)
    await db.update_balance(user_id, guild_id, "cash", 50000, "test_salary")
    await db.update_balance(user_id, guild_id, "points", 1200, "test_points")
    await db.create_club(guild_id, "Titans FC", "TTN", user_id)

    # 2. Economy stats check
    stats = await db.get_economy_stats(guild_id)
    assert stats["total_users"] >= 1
    assert stats["total_clubs"] >= 1
    assert stats["total_cash"] >= 50000

    # 3. Create mock discord member
    mock_member = MagicMock()
    mock_member.id = user_id
    mock_member.display_name = "TestCaptain"
    mock_member.mention = "<@12345>"
    mock_member.display_avatar.url = "https://example.com/avatar.png"

    user_data = await db.get_or_create_user(user_id, guild_id)
    club = await db.get_club_by_user(guild_id, user_id)
    txs = await db.get_transactions(user_id, guild_id, limit=4)

    # 4. Generate all summary embeds
    embed_overview = summary_overview_embed(mock_member, user_data, club)
    assert "BeastlyBank" in embed_overview.title
    assert any("Account Summary" in f.name for f in embed_overview.fields)
    assert any("Quick Shortcuts" in f.name for f in embed_overview.fields)
    assert all(len(f.value) <= 1024 for f in embed_overview.fields)

    embed_finance = summary_finance_embed(mock_member, user_data, club, txs)
    assert "Financial Summary" in embed_finance.title
    assert any("Estimated Net Worth" in f.name for f in embed_finance.fields)

    embed_commands = summary_commands_embed()
    assert "Command Cheatsheet" in embed_commands.title

    embed_econ = summary_economy_embed(stats)
    assert "Economy Summary" in embed_econ.title
    assert any("Circulating Cash" in f.name for f in embed_econ.fields)

    # 5. Generate squad guide embed
    from utils.embeds import summary_squad_embed
    embed_squad = summary_squad_embed()
    assert "Squad, Formations & Lineup Guide" in embed_squad.title
    assert any("Tactical Formations" in f.name for f in embed_squad.fields)
    assert any("Registering & Adding Players" in f.name for f in embed_squad.fields)

    # 6. Test prefix_help command routing
    from unittest.mock import AsyncMock
    from cogs.economy import Economy
    bot = MagicMock()
    bot.db = db
    econ_cog = Economy(bot)

    ctx = MagicMock()
    ctx.author = mock_member
    ctx.guild.id = guild_id
    ctx.send = AsyncMock()

    # Default help
    await econ_cog.prefix_help.callback(econ_cog, ctx)
    ctx.send.assert_called_once()
    assert "BeastlyBank" in ctx.send.call_args[1]["embed"].title

    # Squad help
    ctx.send.reset_mock()
    await econ_cog.prefix_help.callback(econ_cog, ctx, "squad")
    ctx.send.assert_called_once()
    assert "Squad, Formations & Lineup Guide" in ctx.send.call_args[1]["embed"].title

    # Cheatsheet help
    ctx.send.reset_mock()
    await econ_cog.prefix_help.callback(econ_cog, ctx, "cheatsheet")
    ctx.send.assert_called_once()
    assert "Command Cheatsheet" in ctx.send.call_args[1]["embed"].title


@pytest.mark.asyncio
async def test_transfer_auto_registers_unknown_club_roles(db: DatabaseManager):
    """Verify transfer succeeds even when club roles were never pre-created in the database."""
    guild_id = 999999999
    role1 = MagicMock()
    role1.id = 555111222333444
    role1.name = "[MCI] Manchester City"
    role1.mention = "<@&555111222333444>"

    role2 = MagicMock()
    role2.id = 555999888777666
    role2.name = "Arsenal FC"
    role2.mention = "<@&555999888777666>"

    # Execute 30M transfer with neither club pre-existing in DB
    success, msg, data = await db.transfer_player(
        guild_id=guild_id,
        player_name="Kevin De Bruyne",
        from_club_query=role1,
        to_club_query=role2,
        amount=30_000_000,
        payer_id=123,
    )
    assert success is True
    assert data["amount"] == 30_000_000
    assert data["player_name"] == "Kevin De Bruyne"

    # Selling club received 30M
    seller = await db.get_club_by_name(guild_id, role1)
    assert seller is not None
    assert seller["name"] == "Manchester City"
    assert seller["tag"] == "MCI"
    assert seller["treasury_cash"] == 30_000_000

    # Buying club was debited 30M
    buyer = await db.get_club_by_name(guild_id, role2)
    assert buyer is not None
    assert buyer["treasury_cash"] == -30_000_000


@pytest.mark.asyncio
async def test_prefix_commands_resolution():
    """Verify that bb! prefix commands (balance, transfer, club, leaderboard) are properly registered."""
    from bot import BeastlyBankBot
    import asyncio
    from unittest.mock import MagicMock
    import discord

    bot = BeastlyBankBot()
    loop = asyncio.get_running_loop()
    bot.loop = loop
    bot.http.loop = loop
    bot._connection.loop = loop
    mock_user = MagicMock(spec=discord.ClientUser)
    mock_user.id = 999999999
    bot._connection.user = mock_user

    await bot.setup_hook()

    guild = MagicMock(spec=discord.Guild)
    guild.id = 1222195412295745536
    author = MagicMock(spec=discord.Member)
    author.id = 12345
    author.bot = False

    commands_to_check = [
        ("bb!balance", "balance"),
        ("bb!bal", "balance"),
        ("bb!transfer Player @ClubA @ClubB 26e6", "transfer"),
        ("bb!club", "club"),
        ("bb!clubhistory", "clubhistory"),
        ("bb!leaderboard", "leaderboard"),
        ("bb!summary", "summary"),
        ("bb!help", "help"),
        ("bb!shop", "shop"),
        ("bb!inventory", "inventory"),
        ("bb!vault @ClubRole cash add 10m Bonus", "vault"),
    ]

    for text, expected_name in commands_to_check:
        msg = MagicMock(spec=discord.Message)
        msg.content = text
        msg.guild = guild
        msg.author = author
        ctx = await bot.get_context(msg)
        assert ctx.command is not None, f"Command not found for '{text}'"
        assert ctx.command.name == expected_name

    await bot.close()


@pytest.mark.asyncio
async def test_role_mentionable_clubs(db: DatabaseManager):
    """Test full role mention support for club creation, info, treasury management, and transfers."""
    guild_id = 1122334455
    owner_id = 9988776655
    banker_id = 5544332211
    role_id = 123456789012345678

    # 1. Create club with linked role_id
    success, msg, club = await db.create_club(
        guild_id=guild_id,
        name="Galacticos FC",
        tag="GFC",
        owner_id=owner_id,
        role_id=role_id,
    )
    assert success is True
    assert club["role_id"] == role_id

    # 2. Look up club by Mock discord.Role
    class MockRole:
        def __init__(self, id, name):
            self.id = id
            self.name = name
            self.mention = f"<@&{id}>"

    mock_role = MockRole(role_id, "Galacticos FC")
    found = await db.get_club_by_name(guild_id, mock_role)
    assert found is not None
    assert found["id"] == club["id"]

    # 3. Look up club by mention string <@&123456789012345678>
    mention_str = f"<@&{role_id}>"
    found_by_mention = await db.get_club_by_name(guild_id, mention_str)
    assert found_by_mention is not None
    assert found_by_mention["id"] == club["id"]

    # 4. Look up club by snowflake role_id string
    found_by_id = await db.get_club_by_name(guild_id, str(role_id))
    assert found_by_id is not None
    assert found_by_id["id"] == club["id"]

    # 5. Look up club by database integer id
    found_by_db_id = await db.get_club_by_name(guild_id, club["id"])
    assert found_by_db_id is not None
    assert found_by_db_id["id"] == club["id"]

    # 6. Update club treasury via Mock discord.Role
    u_success, u_msg, u_res = await db.update_club_treasury(
        guild_id=guild_id,
        club_query=mock_role,
        currency="cash",
        action="add",
        amount=75_000_000,
        admin_id=banker_id,
        reason="Role mention treasury injection",
    )
    assert u_success is True
    assert u_res["new_balance"] == 75_000_000

    # 7. Update club treasury via role mention string <@&123456789012345678>
    u_success2, u_msg2, u_res2 = await db.update_club_treasury(
        guild_id=guild_id,
        club_query=mention_str,
        currency="cash",
        action="remove",
        amount=25_000_000,
        admin_id=banker_id,
        reason="Role mention treasury deduction",
    )
    assert u_success2 is True
    assert u_res2["new_balance"] == 50_000_000

    # 8. Unregistered role auto-creation in update_club_treasury
    new_role = MockRole(987654321098765432, "Super Strikers")
    auto_success, auto_msg, auto_res = await db.update_club_treasury(
        guild_id=guild_id,
        club_query=new_role,
        currency="cash",
        action="set",
        amount=100_000_000,
        admin_id=banker_id,
        reason="Brand new squad initial vault",
    )
    assert auto_success is True
    assert auto_res["new_balance"] == 100_000_000
    assert auto_res["club"]["role_id"] == new_role.id


@pytest.mark.asyncio
async def test_squad_lineup_and_formation_management(db: DatabaseManager):
    """
    Comprehensive test for:
    - All supported football formations (set_club_formation, rejection of invalid formations)
    - Adding players to Starting XI (up to 11) and Bench with positions and jersey numbers
    - Starting XI 11-player limit enforcement
    - Editing player details (name, position, status, jersey number)
    - Viewing lineup (get_club_lineup) and specific player info (get_player_info)
    - Swapping players (starter <-> bench substitution, starter <-> starter position swap)
    - Removing players
    - Transfer preserving position and number
    - Lineup and player card embed rendering
    """
    from config import DEFAULT_FORMATION, SUPPORTED_FORMATIONS, VALID_POSITIONS
    from utils.embeds import club_lineup_embed, player_card_embed

    guild_id = 123456789
    owner_id = 999111

    # 1. Create a club
    c_ok, c_msg, club = await db.create_club(guild_id, "Real Madrid", "RMA", owner_id, 1001)
    assert c_ok is True
    assert club["formation"] == DEFAULT_FORMATION

    # 2. Test setting all supported formations
    for form_key in SUPPORTED_FORMATIONS.keys():
        f_ok, f_msg = await db.set_club_formation(guild_id, club["id"], form_key)
        assert f_ok is True
        assert form_key in f_msg

    # Rejection of invalid formation
    bad_ok, bad_msg = await db.set_club_formation(guild_id, club["id"], "2-2-6")
    assert bad_ok is False
    assert "not supported" in bad_msg

    # Set default formation for testing
    await db.set_club_formation(guild_id, club["id"], DEFAULT_FORMATION)

    # 3. Add 11 Starting XI players
    starter_data = [
        ("Courtois", "GK", 1),
        ("Carvajal", "RB", 2),
        ("Militao", "CB", 3),
        ("Alaba", "CB", 4),
        ("Mendy", "LB", 23),
        ("Tchouameni", "CDM", 18),
        ("Valverde", "CM", 15),
        ("Bellingham", "CAM", 5),
        ("Rodrygo", "RW", 11),
        ("Mbappe", "ST", 9),
        ("Vinicius", "LW", 7),
    ]

    for name, pos, num in starter_data:
        ok, msg, p = await db.add_club_player(
            guild_id=guild_id,
            club_query=club["id"],
            player_name=name,
            position=pos,
            status="starting",
            number=num,
            default_owner_id=owner_id,
        )
        assert ok is True, f"Failed to add {name}: {msg}"
        assert p["player_name"] == name
        assert p["position"] == pos
        assert p["status"] == "starting"
        assert p["number"] == num

    # 4. Attempting to add 12th starter to Starting XI must fail (11 max limit)
    twelfth_ok, twelfth_msg, _ = await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Guler",
        position="CAM",
        status="starting",
        number=15,
    )
    assert twelfth_ok is False
    assert "already has 11 players" in twelfth_msg

    # 5. Add Guler as bench player (should succeed)
    guler_ok, guler_msg, guler = await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Guler",
        position="CAM",
        status="bench",
        number=15,
    )
    assert guler_ok is True
    assert guler["status"] == "bench"

    # Add Modric to bench
    modric_ok, _, modric = await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Modric",
        position="CM",
        status="bench",
        number=10,
    )
    assert modric_ok is True

    # 6. Verify Lineup
    l_ok, l_msg, lineup = await db.get_club_lineup(guild_id, club["id"])
    assert l_ok is True
    assert len(lineup["starting"]) == 11
    assert len(lineup["bench"]) == 2
    assert lineup["formation"] == DEFAULT_FORMATION

    # 7. Test Player Info
    info_ok, info_msg, p_info = await db.get_player_info(guild_id, "Mbappe")
    assert info_ok is True
    assert p_info["player"]["player_name"] == "Mbappe"
    assert p_info["player"]["position"] == "ST"
    assert p_info["player"]["number"] == 9
    assert p_info["club"]["name"] == "Real Madrid"

    # 8. Test Edit Player (Change position and number)
    e_ok, e_msg, e_p = await db.edit_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Mbappe",
        position="CF",
        number=10,
    )
    assert e_ok is True
    assert e_p["position"] == "CF"
    assert e_p["number"] == 10

    # 9. Test Tactical Swap: Substitution (Starter Mbappe and Bench Modric)
    swap_ok, swap_msg = await db.swap_club_players(
        guild_id=guild_id,
        club_query=club["id"],
        player1_name="Mbappe",
        player2_name="Modric",
    )
    assert swap_ok is True
    assert "Substitution Complete" in swap_msg

    # Verify Mbappe is now bench, Modric is now starting
    _, _, mbappe_check = await db.get_player_info(guild_id, "Mbappe")
    _, _, modric_check = await db.get_player_info(guild_id, "Modric")
    assert mbappe_check["player"]["status"] == "bench"
    assert modric_check["player"]["status"] == "starting"

    # Test Tactical Swap: Position Swap (Starter Vinicius and Starter Rodrygo)
    pos_swap_ok, pos_swap_msg = await db.swap_club_players(
        guild_id=guild_id,
        club_query=club["id"],
        player1_name="Vinicius",
        player2_name="Rodrygo",
    )
    assert pos_swap_ok is True
    assert "Position Swap Complete" in pos_swap_msg

    # 10. Test Remove Player
    rem_ok, rem_msg = await db.remove_club_player(guild_id, club["id"], "Guler")
    assert rem_ok is True
    rem_info_ok, _, _ = await db.get_player_info(guild_id, "Guler", club_query=club["id"])
    assert rem_info_ok is False

    # 11. Test Lineup and Player Card Embed generation
    _, _, final_lineup = await db.get_club_lineup(guild_id, club["id"])
    l_embed = club_lineup_embed(
        club=final_lineup["club"],
        formation=final_lineup["formation"],
        starting_players=final_lineup["starting"],
        bench_players=final_lineup["bench"],
    )
    assert l_embed.title is not None
    assert "Real Madrid" in l_embed.title
    assert len(l_embed.fields) >= 5  # GK, DEF, MID, ATTACK, BENCH

    p_embed = player_card_embed(player=final_lineup["starting"][0], club=final_lineup["club"])
    assert p_embed.title is not None
    assert len(p_embed.fields) >= 4


@pytest.mark.asyncio
async def test_squad_cog_loading(db: DatabaseManager):
    """Verify SquadCog loads onto commands.Bot with prefix commands and slash commands."""
    import discord
    from discord.ext import commands
    from cogs.squad import SquadCog

    bot = commands.Bot(command_prefix="bb!", intents=discord.Intents.default())
    bot.db = db  # type: ignore

    await bot.add_cog(SquadCog(bot))

    # Verify prefix commands registered
    cmd_names = [c.name for c in bot.commands]
    assert "lineup" in cmd_names
    assert "setformation" in cmd_names
    assert "formations" in cmd_names
    assert "player" in cmd_names
    assert "addplayer" in cmd_names
    assert "editplayer" in cmd_names
    assert "removeplayer" in cmd_names
    assert "start" in cmd_names
    assert "bench" in cmd_names
    assert "swap" in cmd_names


@pytest.mark.asyncio
async def test_mandatory_club_role_on_create(db: DatabaseManager):
    """Verify mandatory role handling and duplicate role protection in club creation."""
    from unittest.mock import AsyncMock, MagicMock
    from cogs.clubs import ClubPrefixCommands, Clubs

    guild_id = 999888
    owner1 = 111
    owner2 = 222
    role_id = 888123456789012345

    # 1. Create first club with role
    ok1, msg1, c1 = await db.create_club(guild_id, "Apex Legends FC", "ALF", owner1, role_id)
    assert ok1 is True
    assert c1["role_id"] == role_id

    # 2. Attempt to create another club with the same role should fail
    ok2, msg2, c2 = await db.create_club(guild_id, "Beta Squad FC", "BSF", owner2, role_id)
    assert ok2 is False
    assert "already linked" in msg2

    # 3. Test ClubsCog prefix_club_create requires role mention
    bot = MagicMock()
    bot.db = db
    cog = ClubPrefixCommands(bot)

    ctx_no_role = MagicMock()
    ctx_no_role.guild.id = guild_id
    ctx_no_role.author.id = 333
    ctx_no_role.message.role_mentions = []
    ctx_no_role.send = AsyncMock()

    # Call bb!club create without role
    await cog.prefix_club_create.callback(cog, ctx_no_role, "Gamma FC", "GFC")
    ctx_no_role.send.assert_called_once()
    sent_embed = ctx_no_role.send.call_args[1]["embed"]
    assert "Club Role Required" in sent_embed.title

    # Call bb!club create with role mention
    mock_role = MagicMock()
    mock_role.id = 777999888111222333
    mock_role.mention = f"<@&{mock_role.id}>"

    ctx_with_role = MagicMock()
    ctx_with_role.guild.id = guild_id
    ctx_with_role.author.id = 333
    ctx_with_role.message.role_mentions = [mock_role]
    ctx_with_role.author.mention = "<@333>"
    ctx_with_role.send = AsyncMock()

    await cog.prefix_club_create.callback(cog, ctx_with_role, "Gamma FC", "GFC", mock_role.mention)
    ctx_with_role.send.assert_called_once()
    success_embed = ctx_with_role.send.call_args[1]["embed"]
    assert "Club Registered Successfully" in success_embed.title


@pytest.mark.asyncio
async def test_player_ratings_potential_and_alt_positions(db: DatabaseManager):
    """
    Test ratings (1-99), potential (1-99), and alt_positions for custom players:
    - Adding with custom rating, potential, and alternate positions
    - Alternate positions normalization (stripping, uppercasing, filtering valid, deduping, primary exclusion)
    - Rating & potential bounds validation (1 to 99)
    - Default values (75 OVR, 80 POT, None alt)
    - Editing rating, potential, alt_positions via edit_club_player
    - Official transfer preserving rating, potential, and alt_positions
    - Embed display verification (player_card_embed and club_lineup_embed)
    - Prefix command handling (bb!addplayer and bb!editplayer)
    """
    from unittest.mock import AsyncMock, MagicMock
    from cogs.squad import SquadCog
    from utils.embeds import player_card_embed, club_lineup_embed

    guild_id = 777666555
    owner_id = 12345
    role_id = 999000111222333444

    # 1. Create club
    c_ok, _, club = await db.create_club(guild_id, "Manchester City", "MCI", owner_id, role_id)
    assert c_ok is True

    # 2. Add player with rating, potential, and alternate positions
    ok, msg, p = await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="De Bruyne",
        position="CAM",
        status="starting",
        number=17,
        rating=91,
        potential=91,
        alt_positions="cm / cdm ; CAM, rw, INVALID_POS",
    )
    assert ok is True
    assert p["rating"] == 91
    assert p["potential"] == 91
    # CAM is primary so excluded; INVALID_POS is excluded; cm & cdm & rw kept
    assert p["alt_positions"] == "CM, CDM, RW"

    # 3. Test rating and potential bounds validation
    bad_r1, bad_msg1, _ = await db.add_club_player(
        guild_id=guild_id, club_query=club["id"], player_name="Bad1", position="ST", rating=0
    )
    assert bad_r1 is False
    assert "between 1 and 99" in bad_msg1

    bad_r2, bad_msg2, _ = await db.add_club_player(
        guild_id=guild_id, club_query=club["id"], player_name="Bad2", position="ST", rating=100
    )
    assert bad_r2 is False
    assert "between 1 and 99" in bad_msg2

    bad_p1, bad_msg3, _ = await db.add_club_player(
        guild_id=guild_id, club_query=club["id"], player_name="Bad3", position="ST", potential=0
    )
    assert bad_p1 is False
    assert "between 1 and 99" in bad_msg3

    bad_p2, bad_msg4, _ = await db.add_club_player(
        guild_id=guild_id, club_query=club["id"], player_name="Bad4", position="ST", potential=105
    )
    assert bad_p2 is False
    assert "between 1 and 99" in bad_msg4

    # 4. Add player with default rating, potential, alt_positions
    def_ok, _, def_p = await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Foden",
        position="LW",
        status="starting",
        number=47,
    )
    assert def_ok is True
    assert def_p["rating"] == 75
    assert def_p["potential"] == 80
    assert def_p["alt_positions"] is None

    # 5. Edit player details (rating, potential, alt_positions)
    e_ok, e_msg, e_p = await db.edit_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Foden",
        rating=88,
        potential=92,
        alt_positions="CAM, RW",
    )
    assert e_ok is True
    assert e_p["rating"] == 88
    assert e_p["potential"] == 92
    assert e_p["alt_positions"] == "CAM, RW"
    assert "88 OVR" in e_msg
    assert "92 POT" in e_msg

    # 6. Test Embed Generation
    card = player_card_embed(e_p, club)
    field_dict = {f.name: f.value for f in card.fields}
    assert "⭐ Overall Rating" in field_dict
    assert "**88** OVR" in field_dict["⭐ Overall Rating"]
    assert "🚀 Potential Rating" in field_dict
    assert "**92** POT" in field_dict["🚀 Potential Rating"]
    assert "🔄 Alt Positions" in field_dict
    assert "**CAM, RW**" in field_dict["🔄 Alt Positions"]

    # Lineup embed has [88] tag
    lineup_emb = club_lineup_embed(
        club=club,
        formation="4-3-3 Balanced",
        starting_players=[e_p],
        bench_players=[],
    )
    attack_or_mid_fields = [f.value for f in lineup_emb.fields if "[88]" in f.value]
    assert len(attack_or_mid_fields) > 0

    # 7. Official Transfer Preserves Rating, Potential, and Alt Positions
    dest_role_id = 999000111222333555
    _, _, dest_club = await db.create_club(guild_id, "Arsenal", "ARS", 99999, dest_role_id)
    await db.update_club_treasury(guild_id, dest_club["id"], "cash", "set", 100_000_000, 99999)

    tx_ok, tx_msg, _ = await db.transfer_player(
        guild_id=guild_id,
        player_name="Foden",
        from_club_query=club["id"],
        to_club_query=dest_club["id"],
        amount=50_000_000,
        payer_id=99999,
    )
    assert tx_ok is True

    # Check transferred player in Arsenal
    _, _, foden_info = await db.get_player_info(guild_id, "Foden", club_query=dest_club["id"])
    assert foden_info["player"]["rating"] == 88
    assert foden_info["player"]["potential"] == 92
    assert foden_info["player"]["alt_positions"] == "CAM, RW"
    assert foden_info["player"]["number"] == 47

    # 8. Prefix Command Testing (bb!addplayer and bb!editplayer)
    bot = MagicMock()
    bot.db = db
    squad_cog = SquadCog(bot)

    mock_dest_role = MagicMock()
    mock_dest_role.id = dest_role_id
    mock_dest_role.mention = f"<@&{dest_role_id}>"

    ctx = MagicMock()
    ctx.guild.id = guild_id
    ctx.author.id = 99999
    ctx.message.role_mentions = [mock_dest_role]
    ctx.send = AsyncMock()

    # Call bb!addplayer Saka RW starting 7 87 90 "RM, LW" @Arsenal
    await squad_cog.prefix_addplayer.callback(
        squad_cog,
        ctx,
        "Saka",
        "RW",
        "starting",
        "7",
        "87",
        "90",
        "RM,",
        "LW",
        mock_dest_role.mention,
    )
    ctx.send.assert_called_once()
    add_embed = ctx.send.call_args[1]["embed"]
    assert "Success" in add_embed.title or "Player Added" in add_embed.title or "87 OVR" in add_embed.description

    _, _, saka_info = await db.get_player_info(guild_id, "Saka", club_query=dest_club["id"])
    assert saka_info["player"]["rating"] == 87
    assert saka_info["player"]["potential"] == 90
    assert saka_info["player"]["number"] == 7
    assert saka_info["player"]["alt_positions"] == "RM, LW"

    # Call bb!editplayer Saka rating 89 @Arsenal
    ctx.send.reset_mock()
    await squad_cog.prefix_editplayer.callback(
        squad_cog,
        ctx,
        "Saka",
        "rating",
        "89",
        mock_dest_role.mention,
    )
    ctx.send.assert_called_once()
    _, _, saka_edited = await db.get_player_info(guild_id, "Saka", club_query=dest_club["id"])
    assert saka_edited["player"]["rating"] == 89

    # 9. Test normalize_alt_positions helper with "pos1, pos2, pos3, ....."
    from database.db import normalize_alt_positions
    # Standard comma-separated with multiple positions
    assert normalize_alt_positions("LW, RW, CAM, CF, RM", "ST") == "LW, RW, CAM, CF, RM"
    # Space separated without commas
    assert normalize_alt_positions("LW RW CAM", "ST") == "LW, RW, CAM"
    # Trailing dots and quotes
    assert normalize_alt_positions('"LW, RW, CAM, RM....."', "ST") == "LW, RW, CAM, RM"
    # Primary position excluded
    assert normalize_alt_positions("ST, LW, RW, CAM", "ST") == "LW, RW, CAM"
    # Deduplication and whitespace cleanup
    assert normalize_alt_positions("LW,   rw  , LW, CAM, CF", "ST") == "LW, RW, CAM, CF"
    # Clearing / none
    assert normalize_alt_positions("none", "ST") is None
    assert normalize_alt_positions("clear", "ST") is None
    assert normalize_alt_positions("", "ST") is None

    # 10. Test bb!addplayer with named tags (num:, rating:, pot:, alt:)
    ctx.send.reset_mock()
    await squad_cog.prefix_addplayer.callback(
        squad_cog,
        ctx,
        "Odegaard",
        "CAM",
        "starting",
        "num:8",
        "rating:89",
        "pot:92",
        "alt:CM,",
        "RM,",
        "RW",
        mock_dest_role.mention,
    )
    ctx.send.assert_called_once()
    _, _, ode_info = await db.get_player_info(guild_id, "Odegaard", club_query=dest_club["id"])
    assert ode_info["player"]["rating"] == 89
    assert ode_info["player"]["potential"] == 92
    assert ode_info["player"]["number"] == 8
    assert ode_info["player"]["alt_positions"] == "CM, RM, RW"

    # 11. Test bb!editplayer editing multiple alt positions separated with "pos1, pos2, pos3, ....."
    ctx.send.reset_mock()
    await squad_cog.prefix_editplayer.callback(
        squad_cog,
        ctx,
        "Odegaard",
        "alt",
        "CM,",
        "RW,",
        "LW,",
        "CF",
        mock_dest_role.mention,
    )
    ctx.send.assert_called_once()
    _, _, ode_edited = await db.get_player_info(guild_id, "Odegaard", club_query=dest_club["id"])
    assert ode_edited["player"]["alt_positions"] == "CM, RW, LW, CF"

    # 12. Test changing primary position automatically cleans it out of alt_positions
    # Odegaard has alt_positions "CM, RW, LW, CF". If we change primary pos to CM:
    await db.edit_club_player(
        guild_id=guild_id,
        club_query=dest_club["id"],
        player_name="Odegaard",
        position="CM",
    )
    _, _, ode_new_pos = await db.get_player_info(guild_id, "Odegaard", club_query=dest_club["id"])
    assert ode_new_pos["player"]["position"] == "CM"
    # CM must now be excluded from alt_positions
    assert ode_new_pos["player"]["alt_positions"] == "RW, LW, CF"


@pytest.mark.asyncio
async def test_announcement_embed(db: DatabaseManager):
    """Verify official BeastlyBank announcement embed structure and content."""
    from utils.embeds import beastlybank_announcement_embed
    from utils.views import AnnouncementView

    # 1. Validate the announcement embed fields
    embed = beastlybank_announcement_embed()
    assert "BEASTLYBANK SYSTEM GUIDE & OVERVIEW" in embed.title
    field_names = [f.name for f in embed.fields]
    assert any("Slash" in name and "Prefix" in name for name in field_names)
    assert any("Multi-Currency" in name for name in field_names)
    assert any("Free Clubs" in name for name in field_names)
    assert any("Transfer Market" in name for name in field_names)
    assert any("Squad Lineups, Formations" in name for name in field_names)
    assert any("Store & Stash" in name for name in field_names)
    assert any("Interactive Help" in name for name in field_names)

    # 2. Validate key content in embed
    combined_text = embed.description + " " + " ".join(f.value for f in embed.fields)
    assert "bb!" in combined_text
    assert "Message Content Intent" in combined_text
    assert "26e6" in combined_text
    assert f"{len(SUPPORTED_FORMATIONS)} Supported Formations" in combined_text
    assert "pos1, pos2, pos3, ....." in combined_text
    assert "1–99 OVR" in combined_text
    assert "1–99 POT" in combined_text

    # 3. Validate AnnouncementView persistent buttons
    view = AnnouncementView(db)
    assert len(view.children) == 3
    custom_ids = [btn.custom_id for btn in view.children]
    assert "beastly_announcement_help_btn" in custom_ids
    assert "beastly_announcement_bal_btn" in custom_ids
    assert "beastly_announcement_squad_btn" in custom_ids


@pytest.mark.asyncio
async def test_formation_change_realigns_starters_positions(db: DatabaseManager):
    """Test that changing club formation adapts starting XI players' positions to the new formation."""
    guild_id = 999999999
    club_owner = 12345
    role_id = 888777666

    # 1. Create club
    _, _, club = await db.create_club(guild_id, "Tactics FC", "TAC", club_owner, role_id=role_id)

    # 2. Add players for 4-3-3 Balanced
    # 4-3-3 has: GK, LB, CB, CB, RB, CM, CM, CM, LW, ST, RW
    players_data = [
        ("Courtois", "GK", "starting", 1, 90, 90, None),
        ("Davies", "LB", "starting", 19, 85, 89, "LM"),
        ("Rudiger", "CB", "starting", 22, 87, 87, None),
        ("Militao", "CB", "starting", 3, 86, 88, "RB"),
        ("Carvajal", "RB", "starting", 2, 85, 85, "RWB"),
        ("Tchouameni", "CM", "starting", 14, 85, 89, "CDM"),
        ("Valverde", "CM", "starting", 15, 88, 91, "RW, RM"),
        ("Bellingham", "CM", "starting", 5, 90, 95, "CAM"),
        ("Vinicius", "LW", "starting", 7, 91, 95, "LM, ST"),
        ("Mbappe", "ST", "starting", 9, 91, 95, "LW, RW, CF"),
        ("Rodrygo", "RW", "starting", 11, 86, 91, "RM, LW, CAM"),
    ]

    for name, pos, status, num, rating, pot, alts in players_data:
        await db.add_club_player(
            guild_id=guild_id,
            club_query=club["id"],
            player_name=name,
            position=pos,
            status=status,
            number=num,
            rating=rating,
            potential=pot,
            alt_positions=alts,
        )

    # Verify initial lineup
    _, _, initial_lineup = await db.get_club_lineup(guild_id, club["id"])
    assert len(initial_lineup["starting"]) == 11

    # 3. Change formation to 3-5-2 (3 DEF, 5 MID, 2 FWD)
    # Target slots: GK, CB, CB, CB, LWB, CDM, CDM, RWB, CAM, ST, ST
    ok, msg = await db.set_club_formation(guild_id, club["id"], "3-5-2")
    assert ok is True
    assert "3-5-2" in msg

    _, _, updated_lineup = await db.get_club_lineup(guild_id, club["id"])
    assert updated_lineup["formation"] == "3-5-2"

    starters_map = {p["player_name"]: p for p in updated_lineup["starting"]}
    # Player data must remain completely untouched!
    assert starters_map["Mbappe"]["rating"] == 91
    assert starters_map["Mbappe"]["potential"] == 95
    assert starters_map["Mbappe"]["number"] == 9

    # Check that positions are aligned with 3-5-2
    # In 3-5-2: there are 3 DEF, 5 MID, 2 FWD
    def_count = sum(1 for p in updated_lineup["starting"] if p["position"] in ("CB", "LB", "RB", "LWB", "RWB") and p["position"] not in ("LM", "RM", "CDM", "CM", "CAM"))
    # The positions assigned should strictly match 3-5-2 target positions:
    from config import get_formation_positions
    expected_352_positions = sorted(get_formation_positions("3-5-2"))
    actual_positions = sorted([p["position"] for p in updated_lineup["starting"]])
    assert actual_positions == expected_352_positions


@pytest.mark.asyncio
async def test_switch_lineup_position(db: DatabaseManager):
    """Test switching a player's position in the lineup without touching other attributes."""
    guild_id = 999999999
    club_owner = 12345
    role_id = 888777666

    _, _, club = await db.create_club(guild_id, "Madrid FC", "RMA", club_owner, role_id=role_id)
    await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Bellingham",
        position="CM",
        status="starting",
        number=5,
        rating=90,
        potential=95,
        alt_positions="CAM, CF",
    )

    # 1. Switch Bellingham to CAM
    ok, msg, updated = await db.switch_lineup_position(guild_id, club["id"], "Bellingham", "CAM")
    assert ok is True
    assert updated["position"] == "CAM"
    assert updated["rating"] == 90
    assert updated["potential"] == 95
    assert updated["number"] == 5
    # CAM should be cleaned from alt_positions since it is now primary
    assert updated["alt_positions"] == "CF"

    # 2. Test invalid position rejection
    bad_ok, bad_msg, _ = await db.switch_lineup_position(guild_id, club["id"], "Bellingham", "INVALID_POS")
    assert bad_ok is False
    assert "Invalid position" in bad_msg


@pytest.mark.asyncio
async def test_help_and_summary_views_and_embeds(db: DatabaseManager):
    """Verify HelpView, SummaryView, help_system_guide_embed, and active tab states."""
    from utils.embeds import help_system_guide_embed, summary_commands_embed, summary_overview_embed
    from utils.views import HelpView, SummaryView

    guild_id = 123456
    user_id = 654321
    user_data = await db.get_or_create_user(user_id, guild_id)

    mock_member = MagicMock()
    mock_member.id = user_id
    mock_member.display_name = "TestPlayer"
    mock_member.mention = "<@654321>"
    mock_member.display_avatar.url = "https://example.com/avatar.png"

    # 1. System guide embed content
    guide_embed = help_system_guide_embed()
    assert "Official System Guide & Manual" in guide_embed.title
    combined = guide_embed.description + " " + " ".join(f.name + " " + f.value for f in guide_embed.fields)
    assert "Multi-Currency Banking" in combined
    assert "Free Clubs" in combined
    assert "Transfer Market" in combined
    assert "Tactical Squads" in combined
    assert "37 Formations" in combined

    # 2. Command cheatsheet content
    cmd_embed = summary_commands_embed()
    combined_cmd = " ".join(f.name + " " + f.value for f in cmd_embed.fields)
    assert "/summary" in combined_cmd
    assert "/help" in combined_cmd
    assert "/leaderboard" in combined_cmd
    assert "/giveaway" in combined_cmd
    assert "/bank announce" not in combined_cmd

    # 3. HelpView tab switching and highlighting
    help_view = HelpView(db, author=mock_member, active_tab="guide")
    assert len(help_view.children) == 5
    guide_btn = next(b for b in help_view.children if b.custom_id == "help_tab_guide")
    cheat_btn = next(b for b in help_view.children if b.custom_id == "help_tab_cheatsheet")
    acct_btn = next(b for b in help_view.children if b.custom_id == "help_tab_account")
    assert guide_btn.style == discord.ButtonStyle.primary
    assert cheat_btn.style == discord.ButtonStyle.secondary
    assert acct_btn.style == discord.ButtonStyle.secondary

    # 4. SummaryView tab switching and target inspection
    sum_view = SummaryView(db, author=mock_member, user_data=user_data, target=mock_member, active_tab="overview")
    assert len(sum_view.children) == 5
    overview_btn = next(b for b in sum_view.children if b.custom_id == "sum_tab_overview")
    finances_btn = next(b for b in sum_view.children if b.custom_id == "sum_tab_finances")
    assert overview_btn.style == discord.ButtonStyle.primary
    assert finances_btn.style == discord.ButtonStyle.secondary


@pytest.mark.asyncio
async def test_prefix_switchpos_command(db: DatabaseManager):
    """Test bb!switchpos prefix command switching position and swapping players."""
    from unittest.mock import AsyncMock
    from cogs.squad import SquadCog

    bot = MagicMock()
    bot.db = db
    squad_cog = SquadCog(bot)

    guild_id = 999999999
    club_owner = 12345
    role_id = 888777666
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = role_id
    mock_role.mention = f"<@&{role_id}>"

    _, _, club = await db.create_club(guild_id, "Tactics FC", "TAC", club_owner, role_id=role_id)
    await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Rodrygo",
        position="RW",
        status="starting",
        rating=86,
    )
    await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Vinicius",
        position="LW",
        status="starting",
        rating=91,
    )

    ctx = MagicMock()
    ctx.author.id = club_owner
    ctx.guild.id = guild_id
    ctx.message.role_mentions = [mock_role]
    ctx.send = AsyncMock()

    # 1. Switch Rodrygo position to ST via bb!switchpos Rodrygo ST @Role
    await squad_cog.prefix_switchpos.callback(squad_cog, ctx, "Rodrygo", "ST", mock_role.mention)
    ctx.send.assert_called_once()
    assert "Position Switched" in ctx.send.call_args[1]["embed"].title
    _, _, p_info = await db.get_player_info(guild_id, "Rodrygo", club_query=club["id"])
    assert p_info["player"]["position"] == "ST"
    assert p_info["player"]["rating"] == 86

    # 2. Swap Vinicius and Rodrygo via bb!switchpos Vinicius Rodrygo @Role
    ctx.send.reset_mock()
    await squad_cog.prefix_switchpos.callback(squad_cog, ctx, "Vinicius", "Rodrygo", mock_role.mention)
    ctx.send.assert_called_once()
    assert "Tactical Swap" in ctx.send.call_args[1]["embed"].title
    _, _, v_info = await db.get_player_info(guild_id, "Vinicius", club_query=club["id"])
    _, _, r_info = await db.get_player_info(guild_id, "Rodrygo", club_query=club["id"])
    assert v_info["player"]["position"] == "ST"
    # 3. Multi-word player switch: bb!switchpos Kylian Mbappe CF @Role
    await db.add_club_player(
        guild_id=guild_id,
        club_query=club["id"],
        player_name="Kylian Mbappe",
        position="ST",
        status="starting",
        rating=91,
    )
    ctx.send.reset_mock()
    # User types "Kylian", "Mbappe", "CF" without quotes
    await squad_cog.prefix_switchpos.callback(squad_cog, ctx, "Kylian", "Mbappe", "CF", mock_role.mention)
    ctx.send.assert_called_once()
    assert "Position Switched" in ctx.send.call_args[1]["embed"].title
    _, _, k_info = await db.get_player_info(guild_id, "Kylian Mbappe", club_query=club["id"])
    assert k_info["player"]["position"] == "CF"
    assert k_info["player"]["rating"] == 91

    # 4. Routing from bb!lineup switch Mbappe ST
    ctx.send.reset_mock()
    await squad_cog.prefix_lineup.callback(squad_cog, ctx, "switch", "Mbappe", "ST", mock_role.mention)
    ctx.send.assert_called_once()
    assert "Position Switched" in ctx.send.call_args[1]["embed"].title
    _, _, k_info = await db.get_player_info(guild_id, "Kylian Mbappe", club_query=club["id"])
    assert k_info["player"]["position"] == "ST"

    # 5. Switching starter to an occupied position auto-swaps the starters!
    # Mbappe is ST, Vinicius is ST -> switching Mbappe to LW (where Rodrygo is)
    ctx.send.reset_mock()
    await squad_cog.prefix_switchpos.callback(squad_cog, ctx, "Mbappe", "LW", mock_role.mention)
    ctx.send.assert_called_once()
    assert "Swapped" in ctx.send.call_args[1]["embed"].title or "Position" in ctx.send.call_args[1]["embed"].title
    _, _, k_info2 = await db.get_player_info(guild_id, "Kylian Mbappe", club_query=club["id"])
    _, _, r_info2 = await db.get_player_info(guild_id, "Rodrygo", club_query=club["id"])
    assert k_info2["player"]["position"] == "LW"
    assert r_info2["player"]["position"] == "ST"


@pytest.mark.asyncio
async def test_embed_1024_limits():
    """Verify that NO embed field across all summary and help embeds exceeds 1024 chars."""
    import utils.embeds as emb
    from unittest.mock import MagicMock

    user = MagicMock()
    user.id = 123
    user.display_name = "LongUsernameTest"
    user.mention = "<@123>"
    user.display_avatar.url = "https://example.com/avatar.png"

    user_data = {"cash": 100000, "points": 50000, "tokens": 1000}
    club = {"tag": "TEST", "name": "Test Club", "role_id": 123, "owner_id": 123, "user_role": "Manager"}
    stats = {
        "total_cash": 1000000,
        "total_points": 500000,
        "total_tokens": 100000,
        "total_wealth": 2000000,
        "user_count": 50,
        "club_count": 8,
        "richest_user": {"user_id": 123, "cash": 500000},
        "richest_club": {"name": "Test Club", "tag": "TEST", "treasury_cash": 500000},
    }
    txs = [{"id": 1, "sender_id": 123, "receiver_id": 456, "currency": "cash", "amount": 100, "tx_type": "pay", "reason": "test", "created_at": "2026-09-07 00:00:00"}]

    embeds_to_test = [
        emb.help_system_guide_embed(),
        emb.summary_overview_embed(user, user_data, club),
        emb.summary_commands_embed(),
        emb.summary_squad_embed(),
        emb.summary_finance_embed(user, user_data, club, txs),
        emb.summary_economy_embed(stats),
    ]

    for embed in embeds_to_test:
        assert len(embed.title) <= 256
        if embed.description:
            assert len(embed.description) <= 4096
        for f in embed.fields:
            assert len(f.name) <= 256
            assert len(f.value) <= 1024, f"Field '{f.name}' length {len(f.value)} exceeds 1024!"


@pytest.mark.asyncio
async def test_admin_set_club_manager_database_and_data_preservation(db: DatabaseManager):
    """Verify admin_set_club_manager adds and removes managers with zero data loss."""
    guild_id = 1222195412295745536
    owner_id = 1001
    member_id = 1002
    free_agent_id = 1003
    other_owner_id = 1004
    admin_id = 9999

    # Set initial balances
    await db.update_balance(owner_id, guild_id, "cash", 10000, "credit")
    await db.update_balance(member_id, guild_id, "cash", 5000, "credit")
    await db.update_balance(member_id, guild_id, "points", 250, "credit")
    await db.update_balance(free_agent_id, guild_id, "cash", 3000, "credit")
    await db.update_balance(free_agent_id, guild_id, "tokens", 100, "credit")

    # Create Club 1
    _, _, club1 = await db.create_club(guild_id, "Kings FC", "KNG", owner_id, role_id=555001)
    await db.club_deposit(club1["id"], owner_id, guild_id, "cash", 2000)

    # Join member to Club 1
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO club_members (club_id, user_id, guild_id, role) VALUES (?, ?, ?, 'Member');",
            (club1["id"], member_id, guild_id),
        )
        await conn.commit()

    # Also register member as a squad player on pitch
    await db.add_club_player(
        guild_id, club1["id"], "MemberStar", "ST", status="starting",
        number=9, rating=88, potential=92, alt_positions="CF, LW", user_id=member_id
    )

    # 1. Admin promotes existing member to Manager
    success, msg, c_data = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=member_id, is_manager=True, admin_id=admin_id
    )
    assert success is True
    assert "promoted to **Club Manager**" in msg

    # Verify ZERO DATA LOSS for member and club
    mem_club = await db.get_club_by_user(guild_id, member_id)
    assert mem_club["user_role"] == "Manager"
    mem_user = await db.get_or_create_user(member_id, guild_id)
    assert mem_user["cash"] == 5000
    assert mem_user["points"] == 250
    # Club treasury check
    c1_fresh = await db.get_club_by_name(guild_id, "Kings FC")
    assert c1_fresh["treasury_cash"] == 2000
    # Squad player check
    p_success, _, p_info = await db.get_player_info(guild_id, "MemberStar", club_query=club1["id"])
    assert p_success is True
    assert p_info["player"]["rating"] == 88
    assert p_info["player"]["status"] == "starting"

    # 2. Cannot re-add existing manager
    dup_success, dup_msg, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=member_id, is_manager=True, admin_id=admin_id
    )
    assert dup_success is False
    assert "already a **Club Manager**" in dup_msg

    # 3. Cannot demote or re-promote club owner
    own_success, own_msg, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=owner_id, is_manager=True, admin_id=admin_id
    )
    assert own_success is False
    assert "already the **Club Owner**" in own_msg
    own_demote_s, own_demote_m, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=owner_id, is_manager=False, admin_id=admin_id
    )
    assert own_demote_s is False
    assert "Cannot remove management permissions from the **Club Owner**" in own_demote_m

    # 4. Admin appoints a Free Agent directly as Manager
    fa_success, fa_msg, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=free_agent_id, is_manager=True, admin_id=admin_id
    )
    assert fa_success is True
    fa_club = await db.get_club_by_user(guild_id, free_agent_id)
    assert fa_club["id"] == club1["id"]
    assert fa_club["user_role"] == "Manager"
    fa_user = await db.get_or_create_user(free_agent_id, guild_id)
    assert fa_user["cash"] == 3000
    assert fa_user["tokens"] == 100

    # 5. Prevent assigning member of another club without transfer
    _, _, club2 = await db.create_club(guild_id, "Wolves FC", "WLV", other_owner_id, role_id=555002)
    cross_success, cross_msg, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555002, target_user_id=member_id, is_manager=True, admin_id=admin_id
    )
    assert cross_success is False
    assert "currently enrolled in another club" in cross_msg

    # 6. Admin demotes manager back to squad member
    demote_success, demote_msg, _ = await db.admin_set_club_manager(
        guild_id=guild_id, club_query=555001, target_user_id=member_id, is_manager=False, admin_id=admin_id
    )
    assert demote_success is True
    assert "demoted from Club Manager to **Squad Member**" in demote_msg

    # Verify zero data loss on demotion
    mem_club_demoted = await db.get_club_by_user(guild_id, member_id)
    assert mem_club_demoted["user_role"] == "Member"
    mem_user_demoted = await db.get_or_create_user(member_id, guild_id)
    assert mem_user_demoted["cash"] == 5000
    p_success_dem, _, p_info_dem = await db.get_player_info(guild_id, "MemberStar", club_query=club1["id"])
    assert p_success_dem is True
    assert p_info_dem["player"]["rating"] == 88

    # 7. Check audit log in transactions
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM transactions WHERE tx_type = 'admin_manager_change';")
        rows = await cur.fetchall()
        assert len(rows) >= 3


@pytest.mark.asyncio
async def test_admin_manager_commands_and_views(db: DatabaseManager):
    """Verify slash commands /manage manager, /bank manager, /club addmanager and prefix commands."""
    from unittest.mock import AsyncMock
    from cogs.admin import ManageCurrency, BankAdmin, BankerPrefixCommands
    from cogs.clubs import Clubs
    from cogs.economy import Economy
    from utils.views import HelpView, SummaryView, AnnouncementView

    guild_id = 1222195412295745536
    owner_id = 2001
    member_id = 2002
    admin_id = 2003

    bot = MagicMock()
    bot.db = db

    admin_cog = ManageCurrency(bot)
    bank_cog = BankAdmin(bot)
    prefix_cog = BankerPrefixCommands(bot)
    clubs_cog = Clubs(bot)
    econ_cog = Economy(bot)

    _, _, club = await db.create_club(guild_id, "Titans FC", "TTN", owner_id, role_id=777001)

    # Roles and members mocks
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 777001
    mock_role.name = "Titans FC"
    mock_role.mention = "<@&777001>"

    mock_member = MagicMock(spec=discord.Member)
    mock_member.id = member_id
    mock_member.display_name = "TitanStriker"
    mock_member.mention = "<@2002>"

    mock_admin = MagicMock(spec=discord.Member)
    mock_admin.id = admin_id
    mock_admin.display_name = "HeadBanker"
    mock_admin.mention = "<@2003>"
    mock_admin.guild_permissions.administrator = True

    # 1. Test /manage manager action:add
    interaction1 = MagicMock(spec=discord.Interaction)
    interaction1.guild_id = guild_id
    interaction1.user = mock_admin
    interaction1.response = MagicMock()
    interaction1.response.send_message = AsyncMock()

    await admin_cog.manage_manager.callback(
        admin_cog, interaction1, action="add", club=mock_role, user=mock_member, reason="Official Appointment"
    )
    interaction1.response.send_message.assert_called_once()
    sent_embed1 = interaction1.response.send_message.call_args[1]["embed"]
    assert "Club Manager Update" in sent_embed1.title
    assert "Zero data loss" in sent_embed1.description

    # 2. Test /bank manager action:remove
    interaction2 = MagicMock(spec=discord.Interaction)
    interaction2.guild_id = guild_id
    interaction2.user = mock_admin
    interaction2.response = MagicMock()
    interaction2.response.send_message = AsyncMock()

    await bank_cog.bank_manager.callback(
        bank_cog, interaction2, action="remove", club=mock_role, user=mock_member, reason="Routine Rotation"
    )
    interaction2.response.send_message.assert_called_once()
    sent_embed2 = interaction2.response.send_message.call_args[1]["embed"]
    assert "Manager Removed" in sent_embed2.title

    # 3. Test /club addmanager with banker override and role
    interaction3 = MagicMock(spec=discord.Interaction)
    interaction3.guild_id = guild_id
    interaction3.user = mock_admin
    interaction3.response = MagicMock()
    interaction3.response.send_message = AsyncMock()

    await clubs_cog.club_addmanager.callback(
        clubs_cog, interaction3, user=mock_member, club=mock_role
    )
    interaction3.response.send_message.assert_called_once()

    # 4. Test bb!manager prefix command
    ctx = MagicMock()
    ctx.guild.id = guild_id
    ctx.author = mock_admin
    ctx.message.role_mentions = [mock_role]
    ctx.message.mentions = [mock_member]
    ctx.send = AsyncMock()

    await prefix_cog.prefix_manager.callback(prefix_cog, ctx, "add")
    ctx.send.assert_called_once()

    # 5. Test AnnouncementView help_btn opening HelpView
    ann_view = AnnouncementView(db)
    ann_interaction = MagicMock(spec=discord.Interaction)
    ann_interaction.user = mock_member
    ann_interaction.response = MagicMock()
    ann_interaction.response.send_message = AsyncMock()

    await ann_view.help_btn.callback(ann_interaction)
    ann_interaction.response.send_message.assert_called_once()
    ann_args = ann_interaction.response.send_message.call_args[1]
    assert "Official System Guide & Manual" in ann_args["embed"].title
    assert isinstance(ann_args["view"], HelpView)

    # 6. Test HelpView on_timeout and SummaryView on_timeout
    help_v = HelpView(db, author=mock_member)
    await help_v.on_timeout()
    assert all(b.disabled for b in help_v.children if isinstance(b, discord.ui.Button))

    sum_v = SummaryView(db, author=mock_member, user_data={"cash": 0})
    await sum_v.on_timeout()
    assert all(b.disabled for b in sum_v.children if isinstance(b, discord.ui.Button))

    # 7. Test /help categories routing through HelpView
    for cat in ("guide", "squad", "cheatsheet", "stats", "overview", "finances"):
        help_inter = MagicMock(spec=discord.Interaction)
        help_inter.guild_id = guild_id
        help_inter.user = mock_member
        help_inter.response = MagicMock()
        help_inter.response.send_message = AsyncMock()

        await econ_cog.help_command.callback(econ_cog, help_inter, category=cat)
        help_inter.response.send_message.assert_called_once()
        v = help_inter.response.send_message.call_args[1]["view"]
        assert isinstance(v, HelpView)
        assert len(v.children) == 5


@pytest.mark.asyncio
async def test_admin_owner_management_acid(db: DatabaseManager):
    """Verify admin owner management (add, change, remove) and club deletion with zero data loss."""
    guild_id = 999999999
    admin_id = 888888888
    owner1_id = 901
    member1_id = 902
    free_agent_id = 903
    other_owner_id = 904
    other_member_id = 905

    # 1. Setup initial user balances and clubs
    await db.update_balance(owner1_id, guild_id, "cash", 25000, "owner1_seed")
    await db.update_balance(member1_id, guild_id, "cash", 15000, "member1_seed")
    await db.update_balance(free_agent_id, guild_id, "cash", 8000, "free_agent_seed")
    await db.update_balance(other_owner_id, guild_id, "cash", 50000, "other_owner_seed")
    await db.update_balance(other_member_id, guild_id, "cash", 7000, "other_member_seed")

    # Create Club 1 (Real Madrid)
    c1_ok, _, club1 = await db.create_club(guild_id, "Madrid FC", "RMA", owner1_id, role_id=888001)
    assert c1_ok is True
    # Seed Club 1 treasury directly via banker vault operation
    await db.update_club_treasury(guild_id, club1["id"], "cash", "set", 100000, admin_id)
    await db.update_club_treasury(guild_id, club1["id"], "points", "set", 5000, admin_id)
    await db.update_club_treasury(guild_id, club1["id"], "tokens", "set", 50, admin_id)

    # Enroll member1 into Club 1 with a player card
    p_add_ok, _, p_data = await db.add_club_player(
        guild_id=guild_id,
        club_query=club1["id"],
        player_name="Ronaldo",
        position="ST",
        status="starting",
        number=7,
        rating=92,
        potential=95,
        user_id=member1_id,
    )
    assert p_add_ok is True

    # Create Club 2 (Barca FC)
    c2_ok, _, club2 = await db.create_club(guild_id, "Barca FC", "BAR", other_owner_id, role_id=888002)
    assert c2_ok is True
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO club_members (club_id, user_id, guild_id, role) VALUES (?, ?, ?, 'Member');",
            (club2["id"], other_member_id, guild_id),
        )
    await conn.commit()

    # 2. Transfer ownership of Club 1 from owner1 to member1
    change_ok, change_msg, c1_updated = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=member1_id,
        admin_id=admin_id,
        reason="Board Decision",
    )
    assert change_ok is True
    assert "transferred ownership" in change_msg
    assert c1_updated["owner_id"] == member1_id

    # Verify Club 1 state in DB
    club1_db = await db.get_club_by_name(guild_id, club1["id"])
    assert club1_db["owner_id"] == member1_id
    assert club1_db["treasury_cash"] == 100000
    assert club1_db["treasury_points"] == 5000
    assert club1_db["treasury_tokens"] == 50

    # Verify member roles in club_members
    mem1_club = await db.get_club_by_user(guild_id, member1_id)
    assert mem1_club["user_role"] == "Owner"
    own1_club = await db.get_club_by_user(guild_id, owner1_id)
    assert own1_club["user_role"] == "Member"

    # Verify ZERO data loss on personal balances and player cards
    mem1_user = await db.get_or_create_user(member1_id, guild_id)
    assert mem1_user["cash"] == 15000
    own1_user = await db.get_or_create_user(owner1_id, guild_id)
    assert own1_user["cash"] == 25000

    p_chk_ok, _, p_chk = await db.get_player_info(guild_id, "Ronaldo", club_query=club1["id"])
    assert p_chk_ok is True
    assert p_chk["player"]["rating"] == 92
    assert p_chk["player"]["user_id"] == member1_id

    # 3. Transfer ownership to a Free Agent directly
    fa_ok, fa_msg, c1_fa = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=free_agent_id,
        admin_id=admin_id,
        reason="Acquisition",
    )
    assert fa_ok is True
    assert c1_fa["owner_id"] == free_agent_id
    fa_club = await db.get_club_by_user(guild_id, free_agent_id)
    assert fa_club["user_role"] == "Owner"
    fa_user = await db.get_or_create_user(free_agent_id, guild_id)
    assert fa_user["cash"] == 8000

    # 4. Conflict & Error handling
    # A. User already owner of this club
    same_ok, same_msg, _ = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=free_agent_id,
        admin_id=admin_id,
    )
    assert same_ok is False
    assert "already the **Club Owner**" in same_msg

    # B. User already owns another club
    other_own_ok, other_own_msg, _ = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=other_owner_id,
        admin_id=admin_id,
    )
    assert other_own_ok is False
    assert "already the owner of another club" in other_own_msg

    # C. User enrolled in another club
    cross_mem_ok, cross_mem_msg, _ = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=other_member_id,
        admin_id=admin_id,
    )
    assert cross_mem_ok is False
    assert "currently enrolled in another club" in cross_mem_msg

    # 5. Remove / Vacate club owner
    rm_ok, rm_msg, c1_vacant = await db.admin_remove_club_owner(
        guild_id=guild_id,
        club_query=888001,
        admin_id=admin_id,
        reason="Owner stepped down",
    )
    assert rm_ok is True
    assert c1_vacant["owner_id"] == 0
    c1_after_rm = await db.get_club_by_name(guild_id, club1["id"])
    assert c1_after_rm["owner_id"] == 0
    # Former owner demoted to Member
    fa_after_rm = await db.get_club_by_user(guild_id, free_agent_id)
    assert fa_after_rm["user_role"] == "Member"

    # Removing owner when already vacant should fail cleanly
    rm_again_ok, rm_again_msg, _ = await db.admin_remove_club_owner(
        guild_id=guild_id,
        club_query=888001,
        admin_id=admin_id,
    )
    assert rm_again_ok is False
    assert "currently has no assigned owner" in rm_again_msg

    # 6. Assign (add) owner to a vacant club
    add_ok, add_msg, c1_reassigned = await db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=888001,
        new_owner_id=owner1_id,
        admin_id=admin_id,
        reason="Reappointment",
        is_add_action=True,
    )
    assert add_ok is True
    assert "appointed as **Club Owner**" in add_msg
    assert c1_reassigned["owner_id"] == owner1_id

    # 7. Delete / Disband club completely
    del_ok, del_msg, _ = await db.admin_delete_club(
        guild_id=guild_id,
        club_query=888002,
        admin_id=admin_id,
        reason="Club dissolved",
    )
    assert del_ok is True
    assert "successfully disbanded" in del_msg
    # Club 2 should no longer exist
    c2_lookup = await db.get_club_by_name(guild_id, club2["id"])
    assert c2_lookup is None
    # Former owner and member personal balances intact
    other_own_u = await db.get_or_create_user(other_owner_id, guild_id)
    assert other_own_u["cash"] == 50000
    other_mem_u = await db.get_or_create_user(other_member_id, guild_id)
    assert other_mem_u["cash"] == 7000

    # 8. Check audit logs in transactions table
    conn = await db.connect()
    async with conn.cursor() as cur:
        await cur.execute("SELECT tx_type FROM transactions WHERE tx_type LIKE 'admin_%';")
        rows = [r["tx_type"] for r in await cur.fetchall()]
        assert "admin_owner_change" in rows
        assert "admin_owner_remove" in rows
        assert "admin_owner_add" in rows
        assert "admin_club_delete" in rows


@pytest.mark.asyncio
async def test_admin_owner_and_deleteclub_commands(db: DatabaseManager):
    """Verify slash and prefix commands for owner management and club deletion."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.admin import ManageCurrency, BankAdmin, BankerPrefixCommands

    mock_bot = MagicMock()
    mock_bot.db = db

    manage_cog = ManageCurrency(mock_bot)
    bank_cog = BankAdmin(mock_bot)
    prefix_cog = BankerPrefixCommands(mock_bot)

    guild_id = 999999999
    admin_user = MagicMock(spec=discord.Member)
    admin_user.id = 888888888
    admin_user.mention = "<@888888888>"
    admin_user.display_name = "AdminBanker"

    target_user = MagicMock(spec=discord.Member)
    target_user.id = 777777777
    target_user.mention = "<@777777777>"
    target_user.display_name = "TargetUser"

    club_role = MagicMock(spec=discord.Role)
    club_role.id = 888111
    club_role.name = "[VAL] Valencia CF"
    club_role.mention = "<@&888111>"

    # 1. /manage owner add
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.user = admin_user
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()

    await manage_cog.manage_owner.callback(
        manage_cog, inter, action="add", club=club_role, user=target_user, reason="Appointing initial owner"
    )
    inter.response.send_message.assert_called_once()
    embed = inter.response.send_message.call_args[1]["embed"]
    assert "Club Owner Update" in embed.title
    assert "ADD" in embed.description

    # 2. /manage owner without user when action is add/change
    inter_fail = MagicMock(spec=discord.Interaction)
    inter_fail.guild_id = guild_id
    inter_fail.user = admin_user
    inter_fail.response = MagicMock()
    inter_fail.response.send_message = AsyncMock()

    await manage_cog.manage_owner.callback(
        manage_cog, inter_fail, action="change", club=club_role, user=None
    )
    inter_fail.response.send_message.assert_called_once()
    assert "Missing Target User" in inter_fail.response.send_message.call_args[1]["embed"].title

    # 3. /bank owner change
    new_user = MagicMock(spec=discord.Member)
    new_user.id = 666666666
    new_user.mention = "<@666666666>"
    new_user.display_name = "NewOwner"

    inter_bank = MagicMock(spec=discord.Interaction)
    inter_bank.guild_id = guild_id
    inter_bank.user = admin_user
    inter_bank.response = MagicMock()
    inter_bank.response.send_message = AsyncMock()

    await bank_cog.bank_owner.callback(
        bank_cog, inter_bank, action="change", club=club_role, user=new_user, reason="Transferring club"
    )
    inter_bank.response.send_message.assert_called_once()
    b_embed = inter_bank.response.send_message.call_args[1]["embed"]
    assert "Owner Transferred" in b_embed.title

    # 4. /manage owner remove
    inter_rm = MagicMock(spec=discord.Interaction)
    inter_rm.guild_id = guild_id
    inter_rm.user = admin_user
    inter_rm.response = MagicMock()
    inter_rm.response.send_message = AsyncMock()

    await manage_cog.manage_owner.callback(
        manage_cog, inter_rm, action="remove", club=club_role, user=None, reason="Vacating club"
    )
    inter_rm.response.send_message.assert_called_once()
    rm_embed = inter_rm.response.send_message.call_args[1]["embed"]
    assert "Owner Removed" in rm_embed.title

    # 5. Prefix commands: bb!owner add, bb!setowner, bb!removeowner
    # Setup mock Context
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = admin_user
    ctx.send = AsyncMock()
    ctx.invoked_with = "owner"
    ctx.message = MagicMock()
    ctx.message.role_mentions = [club_role]
    ctx.message.mentions = [target_user]

    await prefix_cog.prefix_owner.callback(prefix_cog, ctx, "add", "<@&888111>", "<@777777777>", "Staff Appointment")
    ctx.send.assert_called_once()
    assert "Club Owner Update" in ctx.send.call_args[1]["embed"].title

    # bb!changeowner
    ctx_ch = MagicMock(spec=commands.Context)
    ctx_ch.guild = mock_guild
    ctx_ch.author = admin_user
    ctx_ch.send = AsyncMock()
    ctx_ch.invoked_with = "changeowner"
    ctx_ch.message = MagicMock()
    ctx_ch.message.role_mentions = [club_role]
    ctx_ch.message.mentions = [new_user]

    await prefix_cog.prefix_owner.callback(prefix_cog, ctx_ch, "change", "<@&888111>", "<@666666666>", "Swap Owner")
    ctx_ch.send.assert_called_once()
    assert "Owner Transferred" in ctx_ch.send.call_args[1]["embed"].title

    # bb!removeowner
    ctx_rm = MagicMock(spec=commands.Context)
    ctx_rm.guild = mock_guild
    ctx_rm.author = admin_user
    ctx_rm.send = AsyncMock()
    ctx_rm.invoked_with = "removeowner"
    ctx_rm.message = MagicMock()
    ctx_rm.message.role_mentions = [club_role]
    ctx_rm.message.mentions = []

    await prefix_cog.prefix_removeowner.callback(prefix_cog, ctx_rm, "<@&888111>", "Removing for restructuring")
    ctx_rm.send.assert_called_once()
    assert "Owner Removed" in ctx_rm.send.call_args[1]["embed"].title

    # 6. /manage deleteclub and bb!deleteclub
    inter_del = MagicMock(spec=discord.Interaction)
    inter_del.guild_id = guild_id
    inter_del.user = admin_user
    inter_del.response = MagicMock()
    inter_del.response.send_message = AsyncMock()

    await manage_cog.manage_deleteclub.callback(
        manage_cog, inter_del, club=club_role, reason="Club disband"
    )
    inter_del.response.send_message.assert_called_once()
    del_embed = inter_del.response.send_message.call_args[1]["embed"]
    assert "Club Disbanded" in del_embed.title

    # /bank deleteclub on non-existent club returns error
    inter_bank_del = MagicMock(spec=discord.Interaction)
    inter_bank_del.guild_id = guild_id
    inter_bank_del.user = admin_user
    inter_bank_del.response = MagicMock()
    inter_bank_del.response.send_message = AsyncMock()

    # Create another club to delete via bb!deleteclub
    _, _, del_club = await db.create_club(guild_id, "Delete FC", "DEL", 999111, role_id=888222)
    del_role = MagicMock(spec=discord.Role)
    del_role.id = 888222
    del_role.name = "[DEL] Delete FC"
    del_role.mention = "<@&888222>"

    ctx_del = MagicMock(spec=commands.Context)
    ctx_del.guild = mock_guild
    ctx_del.author = admin_user
    ctx_del.send = AsyncMock()
    ctx_del.invoked_with = "deleteclub"
    ctx_del.message = MagicMock()
    ctx_del.message.role_mentions = [del_role]
    ctx_del.message.mentions = []

    await prefix_cog.prefix_deleteclub.callback(prefix_cog, ctx_del, "<@&888222>", "Disbanding club")
    ctx_del.send.assert_called_once()
    assert "Club Disbanded" in ctx_del.send.call_args[1]["embed"].title


@pytest.mark.asyncio
async def test_club_list_pagination(db: DatabaseManager):
    """Verify club list displays all clubs across multiple pages with 10 per page and interactive view."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.clubs import Clubs, ClubPrefixCommands
    from utils.views import PaginationView

    guild_id = 999999999
    user_id = 123456789
    mock_bot = MagicMock()
    mock_bot.db = db

    clubs_cog = Clubs(mock_bot)
    prefix_cog = ClubPrefixCommands(mock_bot)

    # 1. Test empty state
    inter_empty = MagicMock(spec=discord.Interaction)
    inter_empty.guild_id = guild_id
    inter_empty.user = MagicMock()
    inter_empty.user.id = user_id
    inter_empty.response = MagicMock()
    inter_empty.response.send_message = AsyncMock()

    await clubs_cog.club_list.callback(clubs_cog, inter_empty)
    inter_empty.response.send_message.assert_called_once()
    empty_embed = inter_empty.response.send_message.call_args[1]["embed"]
    assert "No clubs have registered" in empty_embed.description

    # 2. Register 14 clubs (Page 1 = 10 clubs, Page 2 = 4 clubs)
    for i in range(1, 15):
        tag = f"C{i:02d}"
        name = f"Club {i:02d}"
        owner_id = 1000 + i
        role_id = 50000 + i
        await db.create_club(guild_id, name, tag, owner_id, role_id=role_id)
        # Give varying wealth so ranking is distinct
        await db.update_club_treasury(guild_id, role_id, "cash", "set", (15 - i) * 10000, 888888888)

    all_clubs = await db.get_club_leaderboard(guild_id, limit=200)
    assert len(all_clubs) == 14

    # 3. Test slash command /club list (default page 1)
    inter_p1 = MagicMock(spec=discord.Interaction)
    inter_p1.guild_id = guild_id
    inter_p1.user = MagicMock()
    inter_p1.user.id = user_id
    inter_p1.response = MagicMock()
    inter_p1.response.send_message = AsyncMock()

    await clubs_cog.club_list.callback(clubs_cog, inter_p1, page=1)
    inter_p1.response.send_message.assert_called_once()
    embed_p1 = inter_p1.response.send_message.call_args[1]["embed"]
    view_p1 = inter_p1.response.send_message.call_args[1]["view"]

    assert len(embed_p1.fields) == 10
    assert "Showing clubs 1–10 of 14 registered clubs" in embed_p1.description
    assert "Page 1 of 2" in embed_p1.footer.text
    assert isinstance(view_p1, PaginationView)
    assert view_p1.total_pages == 2
    assert view_p1.current_page == 1
    assert view_p1.prev_button.disabled is True
    assert view_p1.next_button.disabled is False

    # 4. Test slash command /club list page=2
    inter_p2 = MagicMock(spec=discord.Interaction)
    inter_p2.guild_id = guild_id
    inter_p2.user = MagicMock()
    inter_p2.user.id = user_id
    inter_p2.response = MagicMock()
    inter_p2.response.send_message = AsyncMock()

    await clubs_cog.club_list.callback(clubs_cog, inter_p2, page=2)
    inter_p2.response.send_message.assert_called_once()
    embed_p2 = inter_p2.response.send_message.call_args[1]["embed"]
    view_p2 = inter_p2.response.send_message.call_args[1]["view"]

    assert len(embed_p2.fields) == 4
    assert "Showing clubs 11–14 of 14 registered clubs" in embed_p2.description
    assert "Page 2 of 2" in embed_p2.footer.text
    assert view_p2.current_page == 2
    assert view_p2.prev_button.disabled is False
    assert view_p2.next_button.disabled is True

    # 5. Test button interaction on PaginationView
    button_inter = MagicMock(spec=discord.Interaction)
    button_inter.user = MagicMock()
    button_inter.user.id = user_id
    button_inter.response = MagicMock()
    button_inter.response.edit_message = AsyncMock()

    # Click Next on Page 1 View
    await view_p1.next_button.callback(button_inter)
    assert view_p1.current_page == 2
    button_inter.response.edit_message.assert_called_once()
    next_embed = button_inter.response.edit_message.call_args[1]["embed"]
    assert "Page 2 of 2" in next_embed.footer.text
    assert view_p1.prev_button.disabled is False
    assert view_p1.next_button.disabled is True

    # Click Previous on Page 2 View
    button_inter.response.edit_message.reset_mock()
    await view_p1.prev_button.callback(button_inter)
    assert view_p1.current_page == 1
    button_inter.response.edit_message.assert_called_once()
    prev_embed = button_inter.response.edit_message.call_args[1]["embed"]
    assert "Page 1 of 2" in prev_embed.footer.text
    assert view_p1.prev_button.disabled is True
    assert view_p1.next_button.disabled is False

    # 6. Test prefix command bb!club list and bb!clubs
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id
    ctx_pref = MagicMock(spec=commands.Context)
    ctx_pref.guild = mock_guild
    ctx_pref.author = MagicMock()
    ctx_pref.author.id = user_id
    ctx_pref.send = AsyncMock()

    # Default prefix call
    await prefix_cog.prefix_club_list.callback(prefix_cog, ctx_pref)
    ctx_pref.send.assert_called_once()
    pref_embed1 = ctx_pref.send.call_args[1]["embed"]
    assert len(pref_embed1.fields) == 10
    assert "Page 1 of 2" in pref_embed1.footer.text

    # Page 2 call: bb!club list 2
    ctx_pref.send.reset_mock()
    await prefix_cog.prefix_club_list.callback(prefix_cog, ctx_pref, "2")
    ctx_pref.send.assert_called_once()
    pref_embed2 = ctx_pref.send.call_args[1]["embed"]
    assert len(pref_embed2.fields) == 4
    assert "Page 2 of 2" in pref_embed2.footer.text

    # Standalone command bb!clubs 2
    ctx_pref.send.reset_mock()
    await prefix_cog.prefix_standalone_clubs.callback(prefix_cog, ctx_pref, "page", "2")
    ctx_pref.send.assert_called_once()
    pref_embed3 = ctx_pref.send.call_args[1]["embed"]
    assert len(pref_embed3.fields) == 4
    assert "Page 2 of 2" in pref_embed3.footer.text


@pytest.mark.asyncio
async def test_club_owner_username_display(db: DatabaseManager):
    """Verify club list and leaderboard resolve and display owner usernames instead of raw user IDs or mentions."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.clubs import Clubs, ClubPrefixCommands, resolve_owner_names
    from cogs.leaderboard import Leaderboard

    guild_id = 1222195412295745536
    owner_id = 9876543210

    # Create club
    await db.create_club(guild_id, "Apex Predators", "APX", owner_id, role_id=888111)

    # Setup mock bot and guild with member
    mock_bot = MagicMock()
    mock_bot.db = db

    mock_member = MagicMock()
    mock_member.display_name = "Destinix"
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id
    mock_guild.get_member.side_effect = lambda uid: mock_member if uid == owner_id else None

    # 1. Direct unit test of resolve_owner_names
    clubs = await db.get_club_leaderboard(guild_id)
    owner_map = await resolve_owner_names(mock_bot, mock_guild, clubs)
    assert owner_map[owner_id] == "Destinix"
    assert owner_map[0] == "Vacant"

    # Test fallback to bot.fetch_user
    from utils.embeds import _USER_NAME_CACHE
    _USER_NAME_CACHE.clear()
    _USER_NAME_CACHE[0] = "Vacant"

    mock_guild_empty = MagicMock(spec=discord.Guild)
    mock_guild_empty.get_member.return_value = None
    mock_bot.get_user.return_value = None
    mock_fetched_user = MagicMock()
    mock_fetched_user.display_name = "FetchedOwner"
    mock_bot.fetch_user = AsyncMock(return_value=mock_fetched_user)

    owner_map_fetched = await resolve_owner_names(mock_bot, mock_guild_empty, clubs)
    assert owner_map_fetched[owner_id] == "FetchedOwner"

    # Reset cache so mock_guild's Destinix is tested
    _USER_NAME_CACHE.clear()
    _USER_NAME_CACHE[0] = "Vacant"

    # 2. Test /club list shows username in field name
    clubs_cog = Clubs(mock_bot)
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = 111111
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()

    await clubs_cog.club_list.callback(clubs_cog, inter, page=1)
    inter.response.send_message.assert_called_once()
    list_embed = inter.response.send_message.call_args[1]["embed"]
    assert len(list_embed.fields) >= 1
    # Field name format: 🥇 [APX] Apex Predators (Owner: Destinix)
    field_title = list_embed.fields[0].name
    assert f"<@{owner_id}>" not in field_title
    assert "Owner: Destinix" in field_title

    # 3. Test prefix bb!club list shows username in field name
    prefix_cog = ClubPrefixCommands(mock_bot)
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = MagicMock()
    ctx.author.id = 111111
    ctx.send = AsyncMock()

    await prefix_cog.prefix_club_list.callback(prefix_cog, ctx, "1")
    ctx.send.assert_called_once()
    pref_embed = ctx.send.call_args[1]["embed"]
    assert f"<@{owner_id}>" not in pref_embed.fields[0].name
    assert "Owner: Destinix" in pref_embed.fields[0].name

    # 4. Test leaderboard clubs shows username
    lb_cog = Leaderboard(mock_bot)
    inter_lb = MagicMock(spec=discord.Interaction)
    inter_lb.guild_id = guild_id
    inter_lb.guild = mock_guild
    inter_lb.user = MagicMock()
    inter_lb.user.id = 111111
    inter_lb.response = MagicMock()
    inter_lb.response.send_message = AsyncMock()

    await lb_cog.leaderboard.callback(lb_cog, inter_lb, category="clubs")
    inter_lb.response.send_message.assert_called_once()
    lb_embed = inter_lb.response.send_message.call_args[1]["embed"]
    assert f"<@{owner_id}>" not in lb_embed.fields[0].value
    assert "👑 Owner: **Destinix**" in lb_embed.fields[0].value


@pytest.mark.asyncio
async def test_user_leaderboard_pagination_and_usernames(db: DatabaseManager):
    """Verify user leaderboard shows resolved usernames instead of user IDs, with 10 per page pagination."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.leaderboard import Leaderboard
    from utils.views import PaginationView

    guild_id = 12340001
    mock_bot = MagicMock()
    mock_bot.db = db

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    # Create 15 users with varying balances
    for i in range(1, 16):
        uid = 5000 + i
        await db.get_or_create_user(uid, guild_id)
        await db.update_balance(uid, guild_id, "cash", i * 10000, tx_type="deposit")

    # Set member display name mock
    def mock_get_member(uid):
        m = MagicMock()
        m.display_name = f"Player_{uid}"
        return m

    mock_guild.get_member.side_effect = mock_get_member

    lb_cog = Leaderboard(mock_bot)

    # 1. Test slash command /leaderboard category=cash (default page 1)
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = 999999
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()

    await lb_cog.leaderboard.callback(lb_cog, inter, category="cash", page=1)
    inter.response.send_message.assert_called_once()
    embed = inter.response.send_message.call_args[1]["embed"]
    view = inter.response.send_message.call_args[1].get("view")

    assert len(embed.fields) == 10
    assert "Page 1 of 2" in embed.footer.text
    # Check that field titles contain display name and do NOT contain user IDs/mentions
    assert "Player_" in embed.fields[0].name
    assert "<@" not in embed.fields[0].name
    assert isinstance(view, PaginationView)
    assert view.total_pages == 2
    assert view.current_page == 1

    # 2. Test button navigation to Page 2
    button_inter = MagicMock(spec=discord.Interaction)
    button_inter.user = MagicMock()
    button_inter.user.id = 999999
    button_inter.response = MagicMock()
    button_inter.response.edit_message = AsyncMock()

    await view.next_button.callback(button_inter)
    assert view.current_page == 2
    button_inter.response.edit_message.assert_called_once()
    page2_embed = button_inter.response.edit_message.call_args[1]["embed"]
    assert len(page2_embed.fields) == 5
    assert "Page 2 of 2" in page2_embed.footer.text
    assert "<@" not in page2_embed.fields[0].name

    # 3. Test prefix command bb!lb 2
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = MagicMock()
    ctx.author.id = 999999
    ctx.send = AsyncMock()

    await lb_cog.prefix_leaderboard.callback(lb_cog, ctx, "2")
    ctx.send.assert_called_once()
    pref_embed = ctx.send.call_args[1]["embed"]
    assert len(pref_embed.fields) == 5
    assert "Page 2 of 2" in pref_embed.footer.text


@pytest.mark.asyncio
async def test_club_roster_and_info_pagination(db: DatabaseManager):
    """Verify club info and club roster display resolved usernames and paginated squad members."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.clubs import Clubs, ClubPrefixCommands
    from utils.views import PaginationView

    guild_id = 12340002
    owner_id = 9001
    mock_bot = MagicMock()
    mock_bot.db = db

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    # Create club
    await db.create_club(guild_id, "Galacticos FC", "GLC", owner_id, role_id=77701)
    club = await db.get_club_by_user(guild_id, owner_id)
    assert club is not None

    # Add 12 squad members
    conn = await db.connect()
    async with conn.cursor() as cur:
        for i in range(1, 13):
            uid = 8000 + i
            await cur.execute(
                """
                INSERT INTO club_members (club_id, user_id, guild_id, role)
                VALUES (?, ?, ?, 'Player');
                """,
                (club["id"], uid, guild_id),
            )
    await conn.commit()

    def mock_get_member(uid):
        m = MagicMock()
        if uid == owner_id:
            m.display_name = "BossZidane"
        else:
            m.display_name = f"RosterPlayer_{uid}"
        return m

    mock_guild.get_member.side_effect = mock_get_member

    clubs_cog = Clubs(mock_bot)
    prefix_cog = ClubPrefixCommands(mock_bot)

    # 1. Test /club info shows resolved owner name and member names
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = owner_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()

    await clubs_cog.club_info.callback(clubs_cog, inter)
    inter.response.send_message.assert_called_once()
    info_embed = inter.response.send_message.call_args[1]["embed"]
    # Check that owner field has BossZidane
    assert any("BossZidane" in f.value for f in info_embed.fields if "Owner" in f.name)

    # 2. Test /club roster pagination (13 total members: owner + 12 players = Page 1 has 10, Page 2 has 3)
    inter_roster = MagicMock(spec=discord.Interaction)
    inter_roster.guild_id = guild_id
    inter_roster.guild = mock_guild
    inter_roster.user = MagicMock()
    inter_roster.user.id = owner_id
    inter_roster.response = MagicMock()
    inter_roster.response.send_message = AsyncMock()

    await clubs_cog.club_roster.callback(clubs_cog, inter_roster, page=1)
    inter_roster.response.send_message.assert_called_once()
    roster_embed = inter_roster.response.send_message.call_args[1]["embed"]
    roster_view = inter_roster.response.send_message.call_args[1]["view"]

    assert len(roster_embed.fields) == 10
    assert "Page 1 of 2" in roster_embed.footer.text
    assert isinstance(roster_view, PaginationView)
    assert roster_view.total_pages == 2

    # 3. Test prefix bb!club roster 2
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.message = MagicMock()
    ctx.message.role_mentions = []
    ctx.author = MagicMock()
    ctx.author.id = owner_id
    ctx.send = AsyncMock()

    await prefix_cog.prefix_club_roster.callback(prefix_cog, ctx, "2")
    ctx.send.assert_called_once()
    pref_roster_embed = ctx.send.call_args[1]["embed"]
    assert len(pref_roster_embed.fields) == 3
    assert "Page 2 of 2" in pref_roster_embed.footer.text


@pytest.mark.asyncio
async def test_shop_and_inventory_pagination(db: DatabaseManager):
    """Verify shop and inventory commands paginate multiple items cleanly with PaginationView."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.shop import Shop
    from utils.views import PaginationView

    guild_id = 12340003
    user_id = 888888
    mock_bot = MagicMock()
    mock_bot.db = db

    # Insert 8 shop items and 7 inventory items into database
    conn = await db.connect()
    async with conn.cursor() as cur:
        for i in range(1, 9):
            await cur.execute(
                """
                INSERT INTO shop_items (guild_id, name, description, price, currency, stock, category)
                VALUES (?, ?, ?, ?, 'cash', -1, 'Perk');
                """,
                (guild_id, f"Shop Perk {i}", f"Perk description {i}", i * 100),
            )
            if i <= 7:
                await cur.execute(
                    """
                    INSERT INTO inventory (user_id, guild_id, item_id, quantity)
                    VALUES (?, ?, ?, 1);
                    """,
                    (user_id, guild_id, i),
                )
    await conn.commit()

    shop_cog = Shop(mock_bot)

    # 1. Test /shop slash command page 1
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.user = MagicMock()
    inter.user.id = user_id
    inter.response = MagicMock()
    inter.response.send_message = AsyncMock()

    await shop_cog.shop.callback(shop_cog, inter, page=1)
    inter.response.send_message.assert_called_once()
    shop_embed = inter.response.send_message.call_args[1]["embed"]
    shop_view = inter.response.send_message.call_args[1]["view"]

    assert len(shop_embed.fields) == 6
    assert "Page 1 of 2" in shop_embed.footer.text
    assert isinstance(shop_view, PaginationView)
    assert shop_view.total_pages == 2

    # 2. Test user inventory with 7 items
    inter_inv = MagicMock(spec=discord.Interaction)
    inter_inv.guild_id = guild_id
    inter_inv.user = MagicMock()
    inter_inv.user.id = user_id
    inter_inv.user.display_name = "CollectorGuy"
    inter_inv.response = MagicMock()
    inter_inv.response.send_message = AsyncMock()

    await shop_cog.inventory.callback(shop_cog, inter_inv, page=1)
    inter_inv.response.send_message.assert_called_once()
    inv_embed = inter_inv.response.send_message.call_args[1]["embed"]
    inv_view = inter_inv.response.send_message.call_args[1]["view"]

    assert len(inv_embed.fields) == 6
    assert "Page 1 of 2" in inv_embed.footer.text
    assert isinstance(inv_view, PaginationView)
    assert inv_view.total_pages == 2


@pytest.mark.asyncio
async def test_prefix_transactions_pagination(db: DatabaseManager):
    """Verify prefix bb!transactions paginates multi-page statements with interactive buttons."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from cogs.economy import Economy
    from utils.views import PaginationView

    guild_id = 12340004
    user_id = 777111
    mock_bot = MagicMock()
    mock_bot.db = db

    # Log 12 transactions (page_size = 5, total_pages = 3)
    conn = await db.connect()
    async with conn.cursor() as cur:
        for i in range(1, 13):
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, 'cash', ?, 'test_tx', ?);
                """,
                (guild_id, user_id, i * 50, f"Statement item {i}"),
            )
    await conn.commit()

    economy_cog = Economy(mock_bot)
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = MagicMock()
    ctx.author.id = user_id
    ctx.author.display_name = "FinanceUser"
    ctx.author.mention = f"<@{user_id}>"
    ctx.message = MagicMock()
    ctx.message.mentions = []
    ctx.send = AsyncMock()

    # Call bb!transactions (default page 1)
    await economy_cog.prefix_transactions.callback(economy_cog, ctx)
    ctx.send.assert_called_once()
    tx_embed = ctx.send.call_args[1]["embed"]
    tx_view = ctx.send.call_args[1].get("view")

    assert len(tx_embed.fields) == 5
    assert "Page 1 of 3" in tx_embed.footer.text
    assert isinstance(tx_view, PaginationView)
    assert tx_view.total_pages == 3

    # Call bb!transactions 2
    ctx.send.reset_mock()
    await economy_cog.prefix_transactions.callback(economy_cog, ctx, "2")
    ctx.send.assert_called_once()
    tx_embed2 = ctx.send.call_args[1]["embed"]
    assert len(tx_embed2.fields) == 5
    assert "Page 2 of 3" in tx_embed2.footer.text

    # 3. Test interactive button click on prefix view (must be async without deadlock!)
    button_inter = MagicMock(spec=discord.Interaction)
    button_inter.user = ctx.author
    button_inter.response = MagicMock()
    button_inter.response.edit_message = AsyncMock()

    await tx_view.next_button.callback(button_inter)
    assert tx_view.current_page == 2
    button_inter.response.edit_message.assert_called_once()
    edited_embed = button_inter.response.edit_message.call_args[1]["embed"]
    assert "Page 2 of 3" in edited_embed.footer.text


@pytest.mark.asyncio
async def test_slash_transactions_async_pagination_and_usernames(db: DatabaseManager):
    """Verify /transactions slash command defers, resolves usernames, and paginates asynchronously without deadlock."""
    from unittest.mock import AsyncMock, MagicMock
    from cogs.economy import Economy
    from utils.views import PaginationView

    guild_id = 12340005
    user_id = 999888
    sender_id = 888777
    mock_bot = MagicMock()
    mock_bot.db = db

    # Create members
    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    def mock_get_member(uid):
        m = MagicMock()
        if uid == sender_id:
            m.display_name = "TransferSender"
        elif uid == user_id:
            m.display_name = "TargetAccount"
        else:
            m.display_name = f"User_{uid}"
        return m

    mock_guild.get_member.side_effect = mock_get_member

    # Insert 7 transactions with sender_id to verify username resolution
    conn = await db.connect()
    async with conn.cursor() as cur:
        for i in range(1, 8):
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', ?, 'transfer', ?);
                """,
                (guild_id, sender_id, user_id, i * 100, f"Fee payment #{i}"),
            )
    await conn.commit()

    economy_cog = Economy(mock_bot)

    # 1. Execute /transactions slash command
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = user_id
    inter.response = MagicMock()
    inter.response.is_done.return_value = False

    async def mock_defer(*args, **kwargs):
        inter.response.is_done.return_value = True

    inter.response.defer = AsyncMock(side_effect=mock_defer)
    inter.response.send_message = AsyncMock()
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()

    await economy_cog.transactions.callback(economy_cog, inter, page=1)

    # Verify defer was called immediately (preventing 3s timeout)
    assert inter.response.defer.called is True

    # Verify followup response contains embed and PaginationView
    assert inter.followup.send.called is True
    tx_embed = inter.followup.send.call_args[1]["embed"]
    tx_view = inter.followup.send.call_args[1].get("view")

    assert len(tx_embed.fields) == 5
    assert "Page 1 of 2" in tx_embed.footer.text
    # Verify counterpart displays resolved username "TransferSender"
    assert any("TransferSender" in f.value for f in tx_embed.fields)
    assert isinstance(tx_view, PaginationView)
    assert tx_view.total_pages == 2

    # 2. Test button click on PaginationView (async embed generator without deadlock!)
    btn_inter = MagicMock(spec=discord.Interaction)
    btn_inter.user = inter.user
    btn_inter.response = MagicMock()
    btn_inter.response.edit_message = AsyncMock()

    await tx_view.next_button.callback(btn_inter)
    assert tx_view.current_page == 2
    btn_inter.response.edit_message.assert_called_once()
    p2_embed = btn_inter.response.edit_message.call_args[1]["embed"]
    assert len(p2_embed.fields) == 2
    assert "Page 2 of 2" in p2_embed.footer.text
    assert any("TransferSender" in f.value for f in p2_embed.fields)


@pytest.mark.asyncio
async def test_bulk_role_grant_db(db: DatabaseManager):
    """Test bulk_role_grant in database layer with multiple users and transaction recording."""
    guild_id = 987654321
    admin_id = 112233
    user_ids = [10001, 10002, 10003]

    # Grant 25,000 cash to 3 users
    success, msg, count = await db.bulk_role_grant(
        guild_id=guild_id,
        user_ids=user_ids,
        currency="cash",
        amount=25000,
        reason="Tournament 1st Prize",
        admin_id=admin_id,
        role_name="Champions",
    )
    assert success is True
    assert count == 3

    # Verify each user's balance
    for uid in user_ids:
        u = await db.get_or_create_user(uid, guild_id)
        assert u["cash"] == 25000

        # Verify transaction statement
        txs = await db.get_transactions(uid, guild_id)
        assert len(txs) == 1
        assert txs[0]["tx_type"] == "role_grant"
        assert txs[0]["amount"] == 25000
        assert "Champions" in txs[0]["reason"]


@pytest.mark.asyncio
async def test_rolegrant_slash_and_prefix(db: DatabaseManager):
    """Test /manage rolegrant and bb!rolegrant commands filtering bots and granting funds."""
    from unittest.mock import AsyncMock, MagicMock
    from discord.ext import commands
    from cogs.admin import ManageCurrency, BankerPrefixCommands

    guild_id = 987654322
    admin_id = 990011
    mock_bot = MagicMock()
    mock_bot.db = db

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id

    # Create mock role with 2 humans and 1 bot
    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 555000
    mock_role.name = "GoldVIP"
    mock_role.mention = "<@&555000>"

    member1 = MagicMock(spec=discord.Member)
    member1.id = 20001
    member1.bot = False

    member2 = MagicMock(spec=discord.Member)
    member2.id = 20002
    member2.bot = False

    bot_member = MagicMock(spec=discord.Member)
    bot_member.id = 99999
    bot_member.bot = True

    mock_role.members = [member1, member2, bot_member]

    # 1. Test /manage rolegrant slash command
    manage_cog = ManageCurrency(mock_bot)
    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = admin_id
    inter.user.mention = f"<@{admin_id}>"
    inter.response = MagicMock()
    inter.response.is_done.return_value = False

    async def mock_defer(*args, **kwargs):
        inter.response.is_done.return_value = True

    inter.response.defer = AsyncMock(side_effect=mock_defer)
    inter.response.send_message = AsyncMock()
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()

    await manage_cog.manage_rolegrant.callback(
        manage_cog, inter, role=mock_role, currency="cash", amount="50k", reason="VIP Season Bonus"
    )

    assert inter.followup.send.called is True
    grant_embed = inter.followup.send.call_args[1]["embed"]
    assert "Role Currency Grant Completed" in grant_embed.title
    assert "2 players" in grant_embed.description
    assert "100,000" in grant_embed.description

    u1 = await db.get_or_create_user(member1.id, guild_id)
    u2 = await db.get_or_create_user(member2.id, guild_id)
    assert u1["cash"] == 50000
    assert u2["cash"] == 50000

    # 2. Test bb!rolegrant prefix command
    prefix_cog = BankerPrefixCommands(mock_bot)
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = MagicMock()
    ctx.author.id = admin_id
    ctx.author.mention = f"<@{admin_id}>"
    ctx.message = MagicMock()
    ctx.message.role_mentions = [mock_role]
    ctx.send = AsyncMock()

    # Call bb!rolegrant @GoldVIP tokens 10 "Drills reward"
    await prefix_cog.prefix_rolegrant.callback(
        prefix_cog, ctx, "<@&555000>", "tokens", "10", "Drills reward"
    )
    ctx.send.assert_called_once()
    pref_embed = ctx.send.call_args[1]["embed"]
    assert "Role Currency Grant Completed" in pref_embed.title

    u1 = await db.get_or_create_user(member1.id, guild_id)
    u2 = await db.get_or_create_user(member2.id, guild_id)
    assert u1["tokens"] == 10
    assert u2["tokens"] == 10


@pytest.mark.asyncio
async def test_get_role_members_and_bank_rolegrant(db: DatabaseManager):
    """Test get_role_members fallback mechanisms and /bank rolegrant command."""
    from cogs.admin import get_role_members, BankAdmin
    from unittest.mock import AsyncMock

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = 888777666
    mock_guild.chunked = False

    mock_role = MagicMock(spec=discord.Role)
    mock_role.id = 444333222
    mock_role.mention = "<@&444333222>"
    mock_role.name = "Managers"

    m1 = MagicMock(spec=discord.Member)
    m1.id = 101
    m1.bot = False
    m1.roles = [mock_role]

    m2 = MagicMock(spec=discord.Member)
    m2.id = 102
    m2.bot = True  # Bot should be excluded
    m2.roles = [mock_role]

    m3 = MagicMock(spec=discord.Member)
    m3.id = 103
    m3.bot = False
    m3.roles = [mock_role]

    # Case 1: role.members is empty initially, guild.chunk() populates role.members
    mock_role.members = []

    async def fake_chunk():
        mock_guild.chunked = True
        mock_role.members = [m1, m2, m3]

    mock_guild.chunk = AsyncMock(side_effect=fake_chunk)

    members = await get_role_members(mock_guild, mock_role)
    assert len(members) == 2
    assert [m.id for m in members] == [101, 103]

    # Case 2: guild.chunk fails or returns empty, fetch_members generator yields members
    mock_guild2 = MagicMock(spec=discord.Guild)
    mock_guild2.id = 999111
    mock_guild2.chunked = True
    mock_role2 = MagicMock(spec=discord.Role)
    mock_role2.id = 555666
    mock_role2.members = []

    m4 = MagicMock(spec=discord.Member)
    m4.id = 201
    m4.bot = False
    m4.roles = [mock_role2]

    m5 = MagicMock(spec=discord.Member)
    m5.id = 202
    m5.bot = True
    m5.roles = [mock_role2]

    class AsyncMemberIterator:
        def __init__(self, items):
            self.items = list(items)

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.items:
                raise StopAsyncIteration
            return self.items.pop(0)

    mock_guild2.fetch_members = MagicMock(return_value=AsyncMemberIterator([m4, m5]))

    members2 = await get_role_members(mock_guild2, mock_role2)
    assert len(members2) == 1
    assert members2[0].id == 201

    # Case 3: Test BankAdmin.bank_rolegrant
    mock_bot = MagicMock()
    mock_bot.db = db
    mock_role2.members = [m4]  # cached now
    bank_cog = BankAdmin(mock_bot)

    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = mock_guild2.id
    inter.guild = mock_guild2
    inter.user = MagicMock()
    inter.user.id = 9999
    inter.user.mention = "<@9999>"
    inter.response = MagicMock()
    inter.response.is_done.return_value = False

    async def mock_defer(*args, **kwargs):
        inter.response.is_done.return_value = True

    inter.response.defer = AsyncMock(side_effect=mock_defer)
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()

    await bank_cog.bank_rolegrant.callback(
        bank_cog, inter, role=mock_role2, currency="points", amount="250", reason="Manager Stipend"
    )

    inter.followup.send.assert_called_once()
    embed = inter.followup.send.call_args[1]["embed"]
    assert "Role Currency Grant Completed" in embed.title

    user_data = await db.get_or_create_user(201, mock_guild2.id)
    assert user_data["points"] == 250


@pytest.mark.asyncio
async def test_lineup_image_generation_and_commands(db: DatabaseManager):
    """Verify clean Starting 11 lineup image generation, slash commands, and prefix commands."""
    from unittest.mock import AsyncMock
    from discord.ext import commands
    from utils.lineup_image import generate_lineup_image, compute_formation_coords
    from cogs.squad import SquadCog

    # 1. Test coordinate calculation across all 37 formations
    for form_name in SUPPORTED_FORMATIONS:
        coords = compute_formation_coords(form_name)
        assert len(coords) == 11, f"Formation {form_name} must return 11 coordinates"
        assert coords[0][0] == "GK", "First coordinate must be Goalkeeper"

    # 2. Test Pillow image generation (Full 11 players, partial squad, empty squad)
    squad_11 = [
        {"player_name": "Courtois", "number": 1, "position": "GK", "rating": 90},
        {"player_name": "Mendy", "number": 23, "position": "LB", "rating": 82},
        {"player_name": "Rüdiger", "number": 22, "position": "CB", "rating": 88},
        {"player_name": "Militao", "number": 3, "position": "CB", "rating": 85},
        {"player_name": "Carvajal", "number": 2, "position": "RB", "rating": 86},
        {"player_name": "Tchouameni", "number": 14, "position": "CDM", "rating": 85},
        {"player_name": "Bellingham", "number": 5, "position": "CM", "rating": 90},
        {"player_name": "Valverde", "number": 8, "position": "CM", "rating": 88},
        {"player_name": "Vinicius Jr", "number": 7, "position": "LW", "rating": 90},
        {"player_name": "Mbappe", "number": 9, "position": "ST", "rating": 91},
        {"player_name": "Rodrygo", "number": 11, "position": "RW", "rating": 86},
    ]

    buf1 = generate_lineup_image("Real Madrid CF", "Carlo Ancelotti", "4-3-3 Balanced", squad_11)
    bytes1 = buf1.getvalue()
    assert bytes1.startswith(b"\x89PNG\r\n\x1a\n"), "Buffer must be valid PNG image"
    assert len(bytes1) > 15000, "PNG should be high resolution"

    # Test partial / vacant squad
    buf2 = generate_lineup_image("Arsenal FC", "Mikel Arteta", "3-5-2", squad_11[:5])
    assert buf2.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    # Test empty squad
    buf3 = generate_lineup_image("Empty Squad FC", "Manager", "5-3-2", [])
    assert buf3.getvalue().startswith(b"\x89PNG\r\n\x1a\n")

    # 3. Test slash command /lineup with view="image"
    mock_bot = MagicMock()
    mock_bot.db = db
    squad_cog = SquadCog(mock_bot)

    guild_id = 777666555
    owner_id = 12345
    # Register club and players in test DB
    c_ok, c_msg, club_id = await db.create_club(guild_id, "Galacticos", "GAL", owner_id=owner_id)
    assert c_ok is True
    await db.set_club_formation(guild_id, club_id, "4-3-3 Balanced")
    await db.add_club_player(guild_id, club_id, "Zidane", number=5, position="CM", rating=94, status="starting")
    await db.add_club_player(guild_id, club_id, "Ronaldo", number=9, position="ST", rating=96, status="starting")

    mock_guild = MagicMock(spec=discord.Guild)
    mock_guild.id = guild_id
    mock_member = MagicMock(spec=discord.Member)
    mock_member.display_name = "Zinedine"
    mock_guild.get_member.return_value = mock_member

    inter = MagicMock(spec=discord.Interaction)
    inter.guild_id = guild_id
    inter.guild = mock_guild
    inter.user = MagicMock()
    inter.user.id = owner_id
    inter.response = MagicMock()
    inter.response.defer = AsyncMock()
    inter.response.is_done.return_value = True
    inter.followup = MagicMock()
    inter.followup.send = AsyncMock()

    await squad_cog.slash_lineup.callback(squad_cog, inter, club=None, view="image")
    inter.followup.send.assert_called_once()
    send_kwargs = inter.followup.send.call_args[1]
    assert "file" in send_kwargs
    assert send_kwargs["file"].filename == "lineup.png"

    # 4. Test slash command /customlineup
    inter2 = MagicMock(spec=discord.Interaction)
    inter2.guild_id = guild_id
    inter2.guild = mock_guild
    inter2.response = MagicMock()
    inter2.response.defer = AsyncMock()
    inter2.response.is_done.return_value = True
    inter2.followup = MagicMock()
    inter2.followup.send = AsyncMock()

    await squad_cog.slash_custom_lineup.callback(
        squad_cog,
        inter2,
        team="Manchester City",
        manager="Pep Guardiola",
        formation="4-3-3 Holding",
        players="Ederson, Walker, Dias, Stones, Gvardiol, Rodri, De Bruyne, Silva, Foden, Haaland, Doku",
    )
    inter2.followup.send.assert_called_once()
    assert inter2.followup.send.call_args[1]["file"].filename == "lineup.png"

    # 5. Test prefix command bb!lineupimage
    ctx = MagicMock(spec=commands.Context)
    ctx.guild = mock_guild
    ctx.author = MagicMock()
    ctx.author.id = owner_id
    ctx.message = MagicMock()
    ctx.message.role_mentions = []
    ctx.send = AsyncMock()

    await squad_cog.prefix_lineupimage.callback(squad_cog, ctx, "Galacticos")
    ctx.send.assert_called_once()
    assert ctx.send.call_args[1]["file"].filename == "lineup.png"





