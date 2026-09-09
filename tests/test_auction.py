import pytest
import os
import tempfile
from datetime import datetime, timedelta, timezone
from database.db import DatabaseManager
from cogs.auction import (
    calculate_auction_increments,
    format_increment_label,
    parse_bid_amount_or_increment,
    parse_time_duration,
)


def test_increment_calculations():
    """Verify increment calculation rules (especially 5 -> [+1..+5], 10 -> [+2, +4, +6, +8, +10])."""
    # Max increment 5
    inc_5 = calculate_auction_increments(5)
    assert inc_5 == [1, 2, 3, 4, 5]
    assert [format_increment_label(i) for i in inc_5] == ["+1", "+2", "+3", "+4", "+5"]

    # Max increment 10 (skipping one number)
    inc_10 = calculate_auction_increments(10)
    assert inc_10 == [2, 4, 6, 8, 10]
    assert [format_increment_label(i) for i in inc_10] == ["+2", "+4", "+6", "+8", "+10"]

    # Millions: 5M
    inc_5m = calculate_auction_increments(5_000_000)
    assert inc_5m == [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000]
    assert [format_increment_label(i) for i in inc_5m] == ["+1M", "+2M", "+3M", "+4M", "+5M"]

    # Millions: 10M (skipping one number: 2M, 4M, 6M, 8M, 10M)
    inc_10m = calculate_auction_increments(10_000_000)
    assert inc_10m == [2_000_000, 4_000_000, 6_000_000, 8_000_000, 10_000_000]
    assert [format_increment_label(i) for i in inc_10m] == ["+2M", "+4M", "+6M", "+8M", "+10M"]

    # 15M
    inc_15m = calculate_auction_increments(15_000_000)
    assert inc_15m == [3_000_000, 6_000_000, 9_000_000, 12_000_000, 15_000_000]
    assert [format_increment_label(i) for i in inc_15m] == ["+3M", "+6M", "+9M", "+12M", "+15M"]


def test_parsing_helpers():
    """Verify input parsing for amounts, increments, and duration."""
    assert parse_bid_amount_or_increment("5m") == 5_000_000
    assert parse_bid_amount_or_increment("10m") == 10_000_000
    # Shorthand 5 when base amount is 50M -> 5,000,000
    assert parse_bid_amount_or_increment("5", reference_amount=50_000_000) == 5_000_000
    assert parse_bid_amount_or_increment("10", reference_amount=50_000_000) == 10_000_000
    # Low stakes
    assert parse_bid_amount_or_increment("5", reference_amount=500) == 5

    # Duration parsing
    assert parse_time_duration("5m") == 300
    assert parse_time_duration("1h") == 3600
    assert parse_time_duration("24h") == 86400


@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(path)
    await db.init_db()
    yield db
    await db.close()
    if os.path.exists(path):
        os.remove(path)


@pytest.mark.asyncio
async def test_market_auction_lifecycle(temp_db):
    guild_id = 999
    seller_id = 101
    bidder_a = 201
    bidder_b = 301
    poor_bidder = 401

    # 1. Setup clubs & balances
    # Seller club
    await temp_db.create_club(
        guild_id=guild_id,
        name="Seller FC",
        tag="SFC",
        owner_id=seller_id,
        role_id=1111,
    )
    s_club = await temp_db.get_club_by_user(guild_id, seller_id)
    # Add player to seller club
    await temp_db.add_club_player(
        guild_id=guild_id,
        club_query=s_club["id"],
        player_name="Lamine Yamal",
        position="RW",
        status="starting",
        rating=82,
        potential=90,
    )

    # Bidder A club with 100M treasury
    await temp_db.create_club(
        guild_id=guild_id,
        name="Alpha FC",
        tag="AFC",
        owner_id=bidder_a,
        role_id=2222,
    )
    a_club = await temp_db.get_club_by_user(guild_id, bidder_a)
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute("UPDATE clubs SET treasury_cash = 100000000 WHERE id = ?;", (a_club["id"],))

    # Bidder B has no club, but 80M personal cash
    await temp_db.get_or_create_user(bidder_b, guild_id)
    async with conn.cursor() as cur:
        await cur.execute("UPDATE users SET cash = 80000000 WHERE user_id = ? AND guild_id = ?;", (bidder_b, guild_id))

    # Poor bidder has 0 in treasury and 500 in personal cash
    await temp_db.get_or_create_user(poor_bidder, guild_id)
    async with conn.cursor() as cur:
        await cur.execute("UPDATE users SET cash = 500 WHERE user_id = ? AND guild_id = ?;", (poor_bidder, guild_id))

    # 2. Create Auction: Lamine Yamal, starting bid 50M, max increment 5M (so +1M..+5M)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=1)).isoformat()
    auction = await temp_db.create_market_auction(
        guild_id=guild_id,
        channel_id=12345,
        seller_id=seller_id,
        seller_club_id=s_club["id"],
        player_name="Lamine Yamal",
        ovr=82,
        potential=90,
        starting_bid=50_000_000,
        max_increment=5_000_000,
        expires_at=expires_at,
        position="RW",
    )
    assert auction["id"] is not None
    assert auction["status"] == "active"
    assert auction["current_bid"] == 0

    # 3. Seller cannot bid on own auction
    ok, err, _, _ = await temp_db.place_auction_bid(auction["id"], seller_id, 1_000_000, guild_id)
    assert not ok
    assert "own player auction" in err

    # 4. Bidder A places bid of +2M (50M + 2M = 52M)
    ok, msg, updated, outbid = await temp_db.place_auction_bid(auction["id"], bidder_a, 2_000_000, guild_id)
    assert ok
    assert updated["current_bid"] == 52_000_000
    assert updated["highest_bidder_id"] == bidder_a
    assert updated["escrow_source"] == "treasury"
    assert outbid is None

    # Check Bidder A club treasury was debited: 100M - 52M = 48M
    a_club_after = await temp_db.get_club_by_user(guild_id, bidder_a)
    assert a_club_after["treasury_cash"] == 48_000_000

    # 5. Bidder A cannot bid against themselves
    ok, err, _, _ = await temp_db.place_auction_bid(auction["id"], bidder_a, 1_000_000, guild_id)
    assert not ok
    assert "already hold the highest bid" in err

    # 6. Poor bidder tries to bid: should be rejected
    ok, err, _, _ = await temp_db.place_auction_bid(auction["id"], poor_bidder, 1_000_000, guild_id)
    assert not ok
    assert "Insufficient funds" in err

    # 7. Bidder B (personal cash) places bid of +5M (52M + 5M = 57M)
    ok, msg, updated, outbid = await temp_db.place_auction_bid(auction["id"], bidder_b, 5_000_000, guild_id)
    assert ok
    assert updated["current_bid"] == 57_000_000
    assert updated["highest_bidder_id"] == bidder_b
    assert updated["escrow_source"] == "personal"

    # Verify Bidder A was refunded 100% back to club treasury (48M + 52M = 100M)
    a_club_refunded = await temp_db.get_club_by_user(guild_id, bidder_a)
    assert a_club_refunded["treasury_cash"] == 100_000_000
    assert outbid["user_id"] == bidder_a
    assert outbid["amount"] == 52_000_000
    assert outbid["source"] == "treasury"

    # Verify Bidder B was debited from personal cash: 80M - 57M = 23M
    b_user = await temp_db.get_or_create_user(bidder_b, guild_id)
    assert b_user["cash"] == 23_000_000

    # 8. Check bid history
    bids = await temp_db.get_auction_bids(auction["id"])
    assert len(bids) == 2
    assert bids[0]["bid_amount"] == 57_000_000
    assert bids[1]["bid_amount"] == 52_000_000

    # 9. Settle auction
    # Create a club for Bidder B so the player transfers there
    await temp_db.create_club(
        guild_id=guild_id,
        name="Beta FC",
        tag="BFC",
        owner_id=bidder_b,
        role_id=3333,
    )
    b_club = await temp_db.get_club_by_user(guild_id, bidder_b)

    ok, msg, settled = await temp_db.settle_auction(auction["id"])
    assert ok
    assert settled["status"] == "completed"

    # Verify seller club received 57M in treasury
    s_club_after = await temp_db.get_club_by_user(guild_id, seller_id)
    assert s_club_after["treasury_cash"] == 57_000_000

    # Verify player moved from Seller FC to Beta FC
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM club_players WHERE club_id = ? AND player_name = 'Lamine Yamal';", (s_club["id"],))
        assert await cur.fetchone() is None
        await cur.execute("SELECT * FROM club_players WHERE club_id = ? AND player_name = 'Lamine Yamal';", (b_club["id"],))
        new_p = await cur.fetchone()
        assert new_p is not None
        assert new_p["rating"] == 82
        assert new_p["potential"] == 90
        assert new_p["position"] == "RW"


@pytest.mark.asyncio
async def test_auction_cancellation(temp_db):
    guild_id = 888
    seller_id = 102
    bidder_id = 202

    # Setup bidder with 20M cash
    await temp_db.get_or_create_user(bidder_id, guild_id)
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute("UPDATE users SET cash = 20000000 WHERE user_id = ? AND guild_id = ?;", (bidder_id, guild_id))

    # Create auction
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=1)).isoformat()
    auction = await temp_db.create_market_auction(
        guild_id=guild_id,
        channel_id=123,
        seller_id=seller_id,
        player_name="Rodri",
        ovr=91,
        potential=91,
        starting_bid=10_000_000,
        max_increment=2_000_000,
        expires_at=expires_at,
        position="CDM",
    )

    # Place bid: 10M + 2M = 12M
    ok, _, _, _ = await temp_db.place_auction_bid(auction["id"], bidder_id, 2_000_000, guild_id)
    assert ok
    b_user = await temp_db.get_or_create_user(bidder_id, guild_id)
    assert b_user["cash"] == 8_000_000

    # Unauthorized cancel
    ok, err, _ = await temp_db.cancel_market_auction(auction["id"], caller_id=9999, is_admin=False)
    assert not ok
    assert "Only the auction seller or an administrator" in err

    # Authorized cancel by seller
    ok, msg, cancelled = await temp_db.cancel_market_auction(auction["id"], caller_id=seller_id, is_admin=False)
    assert ok
    assert cancelled["status"] == "cancelled"

    # Bidder refunded: 8M + 12M = 20M
    b_user_after = await temp_db.get_or_create_user(bidder_id, guild_id)
    assert b_user_after["cash"] == 20_000_000
