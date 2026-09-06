"""
Automated unit and integration test suite for BeastlyBank.
Validates multi-currency ACID ledger, transfers, club treasuries, shop, and giveaways.
"""
import os
import tempfile
from unittest.mock import MagicMock
import pytest
import pytest_asyncio

from database.db import DatabaseManager
from config import parse_amount
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
    mock_member.display_name = "TestCaptain"
    mock_member.mention = "<@12345>"
    mock_member.display_avatar.url = "https://example.com/avatar.png"

    user_data = await db.get_or_create_user(user_id, guild_id)
    club = await db.get_club_by_user(guild_id, user_id)
    txs = await db.get_transactions(user_id, guild_id, limit=4)

    # 4. Generate all summary embeds
    embed_overview = summary_overview_embed(mock_member, user_data, club)
    assert "BeastlyBank" in embed_overview.title
    assert any("Normal User Commands" in f.name for f in embed_overview.fields)

    embed_finance = summary_finance_embed(mock_member, user_data, club, txs)
    assert "Financial Summary" in embed_finance.title
    assert any("Estimated Net Worth" in f.name for f in embed_finance.fields)

    embed_commands = summary_commands_embed()
    assert "Command Cheatsheet" in embed_commands.title

    embed_econ = summary_economy_embed(stats)
    assert "Economy Summary" in embed_econ.title
    assert any("Circulating Cash" in f.name for f in embed_econ.fields)


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




