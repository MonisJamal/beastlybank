import os
import tempfile
import pytest
from database.db import DatabaseManager


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
async def test_payroll_rollback_separate_clubs(temp_db):
    """
    Test that wage deductions across multiple matchdays are refunded
    separately to each club based on each club's own wage bills, preserving
    subsequent deposits/transactions with zero data loss.
    """
    guild_id = 112233
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        # 1. Register Club 1
        await cur.execute(
            """
            INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash)
            VALUES (?, 'Alpha FC', 'ALP', 101, 10000000);
            """,
            (guild_id,),
        )
        c1_id = cur.lastrowid

        # 2. Register Club 2
        await cur.execute(
            """
            INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash)
            VALUES (?, 'Beta United', 'BET', 202, 5000000);
            """,
            (guild_id,),
        )
        c2_id = cur.lastrowid

        # Add players to Club 1 (total wage bill = 200,000)
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, position, rating, wage) VALUES (?, ?, 'Striker A', 'ST', 88, 120000);",
            (c1_id, guild_id),
        )
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, position, rating, wage) VALUES (?, ?, 'Midfielder A', 'CM', 85, 80000);",
            (c1_id, guild_id),
        )

        # Add player to Club 2 (total wage bill = 75,000)
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, position, rating, wage) VALUES (?, ?, 'Winger B', 'RW', 82, 75000);",
            (c2_id, guild_id),
        )
        await conn.commit()

    # 3. Simulate bulk matchday wage deductions for 5 matchdays
    for md in range(1, 6):
        ok, msg, rep = await temp_db.deduct_matchday_wages(guild_id, matchday=md)
        assert ok is True

    # Verify balances after 5 matchdays:
    # Club 1 was debited 5 * 200,000 = 1,000,000 -> 9,000,000
    # Club 2 was debited 5 * 75,000 = 375,000 -> 4,625,000
    c1 = await temp_db.get_club_by_name(guild_id, c1_id)
    c2 = await temp_db.get_club_by_name(guild_id, c2_id)
    assert c1["treasury_cash"] == 9_000_000
    assert c2["treasury_cash"] == 4_625_000

    # 4. User activity after wage deduction: Club 1 deposits 500,000
    async with conn.cursor() as cur:
        await cur.execute("UPDATE clubs SET treasury_cash = treasury_cash + 500000 WHERE id = ?;", (c1_id,))
        await cur.execute(
            "INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason) VALUES (?, 101, NULL, 'cash', 500000, 'club_deposit', 'Deposit to club [ALP]');",
            (guild_id,),
        )
        await conn.commit()

    c1_deposited = await temp_db.get_club_by_name(guild_id, c1_id)
    assert c1_deposited["treasury_cash"] == 9_500_000

    # 5. Run rollback
    ok, msg, report = await temp_db.rollback_matchday_wages(guild_id, admin_id=999)
    assert ok is True
    assert report["total_clubs_affected"] == 2
    assert report["total_cash_restored"] == 1_375_000
    assert report["total_matchday_records_cleared"] == 10

    # 6. Verify each club got ONLY their own wages back, deposit preserved!
    # Club 1: 9,500,000 + 1,000,000 refund = 10,500,000 (Original 10M + 500k deposit)
    # Club 2: 4,625,000 + 375,000 refund = 5,000,000 (Original 5M)
    c1_final = await temp_db.get_club_by_name(guild_id, c1_id)
    c2_final = await temp_db.get_club_by_name(guild_id, c2_id)
    assert c1_final["treasury_cash"] == 10_500_000
    assert c2_final["treasury_cash"] == 5_000_000

    # 7. Check matchday_wage_payouts table is completely cleared
    async with conn.cursor() as cur:
        await cur.execute("SELECT COUNT(*) FROM matchday_wage_payouts WHERE guild_id = ?;", (guild_id,))
        assert (await cur.fetchone())[0] == 0

        # Check transactions: matchday_wage spam is removed
        await cur.execute("SELECT COUNT(*) FROM transactions WHERE guild_id = ? AND tx_type = 'matchday_wage';", (guild_id,))
        assert (await cur.fetchone())[0] == 0

        # Check transactions: wage_refund audit entries exist
        await cur.execute("SELECT * FROM transactions WHERE guild_id = ? AND tx_type = 'wage_refund';", (guild_id,))
        refund_txs = await cur.fetchall()
        assert len(refund_txs) == 2


@pytest.mark.asyncio
async def test_payroll_rollback_single_matchday(temp_db):
    """Test rolling back only a single matchday while leaving others intact."""
    guild_id = 998877
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash) VALUES (?, 'City FC', 'CTY', 555, 2000000);",
            (guild_id,),
        )
        cid = cur.lastrowid
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, position, rating, wage) VALUES (?, ?, 'Ace', 'ST', 90, 100000);",
            (cid, guild_id),
        )
        await conn.commit()

    # Deduct MD 1 and MD 2
    await temp_db.deduct_matchday_wages(guild_id, matchday=1)
    await temp_db.deduct_matchday_wages(guild_id, matchday=2)

    c_deducted = await temp_db.get_club_by_name(guild_id, cid)
    assert c_deducted["treasury_cash"] == 1_800_000  # 2M - 200k

    # Rollback ONLY matchday 2
    ok, msg, report = await temp_db.rollback_matchday_wages(guild_id, matchday=2)
    assert ok is True
    assert report["total_cash_restored"] == 100_000
    assert report["total_matchday_records_cleared"] == 1

    c_restored = await temp_db.get_club_by_name(guild_id, cid)
    assert c_restored["treasury_cash"] == 1_900_000  # 1.8M + 100k (MD 1 still applied)

    # MD 1 is still recorded
    async with conn.cursor() as cur:
        await cur.execute("SELECT matchday FROM matchday_wage_payouts WHERE guild_id = ?;", (guild_id,))
        rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1


@pytest.mark.asyncio
async def test_payroll_rollback_fallback_transactions(temp_db):
    """Test fallback restoration from transactions table if matchday_wage_payouts was emptied."""
    guild_id = 445566
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash) VALUES (?, 'Delta FC', 'DLT', 777, 1000000);",
            (guild_id,),
        )
        cid = cur.lastrowid
        # Manually create matchday_wage transactions
        await cur.execute(
            "INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason) VALUES (?, 777, NULL, 'cash', 150000, 'matchday_wage', 'Matchday 1 Squad Wage Bill for [DLT] Delta FC');",
            (guild_id,),
        )
        await cur.execute(
            "INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason) VALUES (?, 777, NULL, 'cash', 150000, 'matchday_wage', 'Matchday 2 Squad Wage Bill for [DLT] Delta FC');",
            (guild_id,),
        )
        await conn.commit()

    ok, msg, report = await temp_db.rollback_matchday_wages(guild_id)
    assert ok is True
    assert report["total_cash_restored"] == 300_000

    c_after = await temp_db.get_club_by_name(guild_id, cid)
    assert c_after["treasury_cash"] == 1_300_000


@pytest.mark.asyncio
async def test_auto_rollback_in_repair_and_activate_s2(temp_db):
    """Test that repair_and_activate_s2 automatically detects and heals bulk wage cuts on startup."""
    guild_id = 889900
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash) VALUES (?, 'Heal FC', 'HEL', 333, 5000000);",
            (guild_id,),
        )
        cid = cur.lastrowid
        await cur.execute(
            "INSERT INTO club_players (club_id, guild_id, player_name, position, rating, wage) VALUES (?, ?, 'Heal Player', 'CM', 80, 50000);",
            (cid, guild_id),
        )
        await conn.commit()

    # Deduct 3 matchdays (md_count > 1 triggers auto-rollback)
    for md in range(1, 4):
        await temp_db.deduct_matchday_wages(guild_id, matchday=md)

    c_ded = await temp_db.get_club_by_name(guild_id, cid)
    assert c_ded["treasury_cash"] == 4_850_000

    # Run repair_and_activate_s2 (simulating bot restart)
    await temp_db.repair_and_activate_s2(guild_id)

    # Treasury must be healed back to 5,000,000
    c_healed = await temp_db.get_club_by_name(guild_id, cid)
    assert c_healed["treasury_cash"] == 5_000_000

    # Subsequent restart does not repeat or change balance
    await temp_db.repair_and_activate_s2(guild_id)
    c_healed_again = await temp_db.get_club_by_name(guild_id, cid)
    assert c_healed_again["treasury_cash"] == 5_000_000
