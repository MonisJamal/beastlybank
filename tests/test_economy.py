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
    assert any("Normal User Commands" in f.name for f in embed_overview.fields)

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
    - All 12 football formations (set_club_formation, rejection of invalid formations)
    - Adding players to Starting XI (up to 11) and Bench with positions and jersey numbers
    - Starting XI 11-player limit enforcement
    - Editing player details (name, position, status, jersey number)
    - Viewing lineup (get_club_lineup) and specific player info (get_player_info)
    - Swapping players (starter <-> bench substitution, starter <-> starter position swap)
    - Removing players
    - Transfer preserving position and number
    - Lineup and player card embed rendering
    """
    from config import SUPPORTED_FORMATIONS, VALID_POSITIONS
    from utils.embeds import club_lineup_embed, player_card_embed

    guild_id = 123456789
    owner_id = 999111

    # 1. Create a club
    c_ok, c_msg, club = await db.create_club(guild_id, "Real Madrid", "RMA", owner_id, 1001)
    assert c_ok is True
    assert club["formation"] == "4-3-3"

    # 2. Test setting all 12 supported formations
    for form_key in SUPPORTED_FORMATIONS.keys():
        f_ok, f_msg = await db.set_club_formation(guild_id, club["id"], form_key)
        assert f_ok is True
        assert form_key in f_msg

    # Rejection of invalid formation
    bad_ok, bad_msg = await db.set_club_formation(guild_id, club["id"], "2-2-6")
    assert bad_ok is False
    assert "not supported" in bad_msg

    # Set to 4-3-3 for testing
    await db.set_club_formation(guild_id, club["id"], "4-3-3")

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
    assert lineup["formation"] == "4-3-3"

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
        formation="4-3-3",
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









