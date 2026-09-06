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
from config import FOOTBALL_JOBS
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
async def test_user_starter_pack(db: DatabaseManager):
    """Verify new users receive starter kit (1,000 Cash, 250 Points, 5 Tokens)."""
    user_id = 111111111
    guild_id = 999999999

    user = await db.get_or_create_user(user_id, guild_id)
    assert user["cash"] == 1000
    assert user["points"] == 250
    assert user["tokens"] == 5
    assert user["daily_streak"] == 0

    # Verify starter bonus was logged in transaction ledger
    txs = await db.get_transactions(user_id, guild_id)
    assert len(txs) == 1
    assert txs[0]["tx_type"] == "starter_bonus"
    assert txs[0]["amount"] == 1000


@pytest.mark.asyncio
async def test_player_to_player_transfer(db: DatabaseManager):
    """Test atomic player-to-player transfers across all currencies."""
    alice_id = 101
    bob_id = 102
    guild_id = 999999999

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
    assert bob["cash"] == 1300

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
    assert bob["tokens"] == 7

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
async def test_daily_streak_and_cooldown(db: DatabaseManager):
    """Test daily salary claim and 24h cooldown enforcement."""
    user_id = 201
    guild_id = 999999999

    # First claim
    success, msg, data = await db.claim_daily(user_id, guild_id)
    assert success is True
    assert data["streak"] == 1
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
    assert club["treasury_cash"] == 500  # starter club treasury

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
    assert updated_club["treasury_cash"] == 1500

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
    assert final_club["treasury_cash"] == 1100

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

    # Verify winner was credited with 2500 Cash prize
    winner_acc = await db.get_or_create_user(winners[0], guild_id)
    assert winner_acc["cash"] == 1000 + 2500  # Starter 1000 + 2500 prize


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
