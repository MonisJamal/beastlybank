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
from config import FOOTBALL_JOBS, parse_amount
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
    """Test atomic player-to-player transfers across all currencies."""
    alice_id = 101
    bob_id = 102
    guild_id = 999999999

    # Fund Alice with test currency
    await db.update_balance(alice_id, guild_id, "cash", 1000, "test_grant")
    await db.update_balance(alice_id, guild_id, "tokens", 5, "test_grant")

    # Transfer Cash
    success, msg = await db.transfer(
        sender_id=alice_id,
        receiver_id=bob_id,
        guild_id=guild_id,
        currency="cash",
        amount=300,
        reason="Match wager",
    )
    assert success is True

    alice = await db.get_or_create_user(alice_id, guild_id)
    bob = await db.get_or_create_user(bob_id, guild_id)
    assert alice["cash"] == 700
    assert bob["cash"] == 300

    # Transfer Training Tokens
    tok_success, _ = await db.transfer(
        sender_id=alice_id,
        receiver_id=bob_id,
        guild_id=guild_id,
        currency="tokens",
        amount=2,
        reason="Token trade",
    )
    assert tok_success is True
    alice = await db.get_or_create_user(alice_id, guild_id)
    bob = await db.get_or_create_user(bob_id, guild_id)
    assert alice["tokens"] == 3
    assert bob["tokens"] == 2

    # Verify Insufficient Funds Protection
    fail_success, fail_msg = await db.transfer(
        sender_id=alice_id,
        receiver_id=bob_id,
        guild_id=guild_id,
        currency="cash",
        amount=5000,
    )
    assert fail_success is False
    assert "Insufficient" in fail_msg

    # Verify Self-Transfer Protection
    self_success, self_msg = await db.transfer(
        sender_id=alice_id,
        receiver_id=alice_id,
        guild_id=guild_id,
        currency="cash",
        amount=50,
    )
    assert self_success is False


@pytest.mark.asyncio
async def test_daily_and_cooldown(db: DatabaseManager):
    """Test daily salary claim and 24h cooldown enforcement."""
    user_id = 201
    guild_id = 999999999

    # First claim
    success, msg, data = await db.claim_daily(user_id, guild_id)
    assert success is True
    assert data["cash_earned"] > 0
    assert data["points_earned"] > 0

    # Second claim immediately after should trigger cooldown
    cooldown_success, cooldown_msg, _ = await db.claim_daily(user_id, guild_id)
    assert cooldown_success is False
    assert "already claimed" in cooldown_msg


@pytest.mark.asyncio
async def test_work_drills(db: DatabaseManager):
    """Test football training drills reward cash, points, and tokens."""
    user_id = 301
    guild_id = 999999999
    job = FOOTBALL_JOBS[0]

    success, msg, data = await db.claim_work(user_id, guild_id, job)
    assert success is True
    assert data["cash_earned"] >= job["min_cash"]
    assert data["points_earned"] >= job["min_points"]

    # Immediate second work drill should fail cooldown
    fail_success, fail_msg, _ = await db.claim_work(user_id, guild_id, job)
    assert fail_success is False
    assert "recovering" in fail_msg


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
async def test_shop_and_inventory(db: DatabaseManager):
    """Test purchasing items, stock deduction, and inventory tracking."""
    user_id = 501
    guild_id = 999999999

    items = await db.get_shop_items(guild_id)
    assert len(items) > 0

    vip_item = next(i for i in items if "VIP" in i["name"])
    # Give user enough cash
    await db.update_balance(user_id, guild_id, "cash", 10000, "test_funds")

    buy_success, buy_msg, item = await db.buy_item(
        user_id=user_id,
        guild_id=guild_id,
        item_id=vip_item["id"],
        quantity=1,
    )
    assert buy_success is True

    # Check inventory
    inv = await db.get_inventory(user_id, guild_id)
    assert len(inv) == 1
    assert inv[0]["name"] == vip_item["name"]
    assert inv[0]["quantity"] == 1


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
async def test_redeem_cp(db: DatabaseManager):
    """Verify converting Community Points to Cash."""
    user_id = 801
    guild_id = 999999999

    # Grant user test balance of 1,000 Cash and 250 Points
    await db.update_balance(user_id, guild_id, "cash", 1000, "test_grant")
    await db.update_balance(user_id, guild_id, "points", 250, "test_grant")

    # Redeem 100 Points at 1:2 rate -> 200 Cash
    success, msg, data = await db.redeem_cp(user_id, guild_id, points_amount=100, rate=2)
    assert success is True
    assert data["cash_received"] == 200
    assert data["user"]["cash"] == 1200
    assert data["user"]["points"] == 150

    # Over-redeem fails
    fail_success, fail_msg, _ = await db.redeem_cp(user_id, guild_id, points_amount=500, rate=2)
    assert fail_success is False
    assert "Insufficient" in fail_msg


@pytest.mark.asyncio
async def test_server_settings(db: DatabaseManager):
    """Test getting and toggling server settings."""
    guild_id = 999999999

    settings = await db.get_settings(guild_id)
    assert settings["economy_enabled"] == 1
    assert settings["purchases_enabled"] == 1
    assert settings["shop_enabled"] == 1

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
async def test_shop_admin_features(db: DatabaseManager):
    """Test shop item editing, listing, and toggling."""
    guild_id = 999999999

    items = await db.get_shop_items(guild_id, include_inactive=True)
    assert len(items) > 0
    item = items[0]

    # Edit item
    success, msg = await db.edit_shop_item(
        guild_id=guild_id,
        item_id=item["id"],
        name="Super Boost V2",
        price=999,
    )
    assert success is True

    # Toggle item off
    t_success, t_msg, status = await db.toggle_shop_item(guild_id, item["id"])
    assert t_success is True
    assert status is False  # now disabled

    # Verify not in normal shop items list
    active_items = await db.get_shop_items(guild_id, include_inactive=False)
    assert not any(i["id"] == item["id"] for i in active_items)


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
    """Test full player transfer flow: custom player name, scientific amount, recipient payment, roster relocation."""
    guild_id = 999999999
    seller_owner = 1001
    buyer_owner = 1002
    custom_player = "Erling Haaland"
    recipient_agent = 1004

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

    # Grant cash to buyer owner and fund buying club treasury with 30M cash
    transfer_fee = parse_amount("26e6")  # 26,000,000
    assert transfer_fee == 26_000_000
    await db.update_balance(buyer_owner, guild_id, "cash", 30_000_000, "admin_grant")
    await db.club_deposit(buyer_club["id"], buyer_owner, guild_id, "cash", 30_000_000)

    # Execute transfer with recipient
    success, msg, data = await db.transfer_player(
        guild_id=guild_id,
        player_name=custom_player,
        from_club_query="RST",
        to_club_query="BHW",
        amount=transfer_fee,
        payer_id=buyer_owner,
        recipient_id=recipient_agent,
    )
    assert success is True
    assert data["amount"] == 26_000_000
    assert data["player_name"] == custom_player

    # Verify recipient received 26M cash (started from 0)
    recipient_user = await db.get_or_create_user(recipient_agent, guild_id)
    assert recipient_user["cash"] == 26_000_000

    # Verify buyer club treasury debited by 26M (started from 0 + 30M - 26M = 4M)
    buyer_after = await db.get_club_by_name(guild_id, "BHW")
    assert buyer_after["treasury_cash"] == 4_000_000

    # Verify player moved from seller roster to buyer roster
    seller_members = await db.get_club_members(seller_club["id"])
    buyer_members = await db.get_club_members(buyer_club["id"])
    assert not any(m.get("player_name") == custom_player for m in seller_members)
    assert any(m.get("player_name") == custom_player for m in buyer_members)

    # Verify transaction ledger has record
    txs = await db.get_transactions(recipient_agent, guild_id)
    assert any(t["tx_type"] == "transfer_market" and t["amount"] == 26_000_000 for t in txs)


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


