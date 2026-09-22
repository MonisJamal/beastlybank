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
async def test_get_all_clubs_and_lookup(temp_db):
    """
    Test that get_all_clubs returns all clubs and get_club_by_name can resolve
    numeric ID, username-based club names, and user mentions.
    """
    guild_id = 998877
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        # Create normal club with role
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, role_id, owner_id) VALUES (?, 'Real Madrid', 'RMA', 555666, 1001);",
            (guild_id,),
        )
        c1_id = cur.lastrowid

        # Create accidental club created with user mention as name
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, role_id, owner_id) VALUES (?, '<@123456789>', 'FC', 0, 1002);",
            (guild_id,),
        )
        c2_id = cur.lastrowid
        await conn.commit()

    all_clubs = await temp_db.get_all_clubs(guild_id)
    assert len(all_clubs) == 2
    club_ids = {c["id"] for c in all_clubs}
    assert c1_id in club_ids
    assert c2_id in club_ids

    # 1. Resolve by numeric string ID
    found_by_id = await temp_db.get_club_by_name(guild_id, str(c2_id))
    assert found_by_id is not None
    assert found_by_id["id"] == c2_id

    # 2. Resolve by user mention
    found_by_mention = await temp_db.get_club_by_name(guild_id, "<@123456789>")
    assert found_by_mention is not None
    assert found_by_mention["id"] == c2_id

    # 3. Resolve by user ID matching name
    found_by_uid = await temp_db.get_club_by_name(guild_id, "123456789")
    assert found_by_uid is not None
    assert found_by_uid["id"] == c2_id

    # 4. Resolve normal club by role ID
    found_by_role = await temp_db.get_club_by_name(guild_id, 555666)
    assert found_by_role is not None
    assert found_by_role["id"] == c1_id


@pytest.mark.asyncio
async def test_get_or_create_club_rejects_user_mentions(temp_db):
    """
    Test that get_or_create_club_from_role refuses to auto-create clubs when
    given user mentions or user strings, preventing accidental club creation.
    """
    guild_id = 998877
    res = await temp_db.get_or_create_club_from_role(guild_id, "<@123456789>")
    assert res is None

    res2 = await temp_db.get_or_create_club_from_role(guild_id, "<@!987654321>")
    assert res2 is None

    all_clubs = await temp_db.get_all_clubs(guild_id)
    assert len(all_clubs) == 0


@pytest.mark.asyncio
async def test_admin_manage_owner_on_username_club(temp_db):
    """
    Test that admin_set_club_owner, admin_remove_club_owner, and admin_delete_club
    work seamlessly on clubs created with usernames/IDs without roles.
    """
    guild_id = 998877
    admin_id = 777
    new_owner_id = 888

    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        # Create username-named club with no role (role_id = 0)
        await cur.execute(
            "INSERT INTO clubs (guild_id, name, tag, role_id, owner_id, treasury_cash) VALUES (?, '<@123456789>', 'FC', 0, 1002, 5000000);",
            (guild_id,),
        )
        c_id = cur.lastrowid
        await conn.commit()

    # 1. Appoint new owner using string ID
    ok, msg, c_data = await temp_db.admin_set_club_owner(
        guild_id=guild_id,
        club_query=str(c_id),
        new_owner_id=new_owner_id,
        admin_id=admin_id,
        reason="Owner assignment for username club",
    )
    assert ok is True
    assert c_data["owner_id"] == new_owner_id

    # 2. Verify treasury and data intact
    club_check = await temp_db.get_club_by_name(guild_id, str(c_id))
    assert club_check["treasury_cash"] == 5000000
    assert club_check["owner_id"] == new_owner_id

    # 3. Vacate owner using user mention query
    ok, msg, c_data = await temp_db.admin_remove_club_owner(
        guild_id=guild_id,
        club_query="<@123456789>",
        admin_id=admin_id,
        reason="Vacating owner",
    )
    assert ok is True
    assert c_data["owner_id"] == 0

    # 4. Delete club completely
    ok, msg, c_data = await temp_db.admin_delete_club(
        guild_id=guild_id,
        club_query=str(c_id),
        admin_id=admin_id,
        reason="Disbanding accidental club",
    )
    assert ok is True
    remaining = await temp_db.get_all_clubs(guild_id)
    assert len(remaining) == 0


@pytest.mark.asyncio
async def test_repair_and_activate_s2_fixture_separation(temp_db):
    """
    Test that repair_and_activate_s2 cleans up Season 1 fixtures co-mingled
    inside Season 2 tournament, leaving only genuine Season 2 fixtures in S2.
    """
    guild_id = 998877
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        # Create S1 League Tournament
        await cur.execute(
            """
            INSERT INTO tournaments (guild_id, name, season_number, competition_type, current_matchday, total_matchdays, status)
            VALUES (?, 'BEASTLY S1 LEAGUE', 1, 'league', 38, 38, 'completed');
            """,
            (guild_id,),
        )
        s1_id = cur.lastrowid

        # Insert canonical S1 matchday 1 fixture in S1
        await cur.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, guild_id, matchday, match_uid, home_team_id, away_team_id,
                home_team_name, away_team_name, goals_home, goals_away, is_finished
            ) VALUES (?, ?, 1, '01acb2eaae62d866', '325', '21', 'Galatasaray SK', 'FC Bayern München', 2, 1, 1);
            """,
            (s1_id, guild_id),
        )

        # Create S2 League Tournament
        await cur.execute(
            """
            INSERT INTO tournaments (guild_id, name, season_number, competition_type, current_matchday, total_matchdays, status)
            VALUES (?, 'BEASTLY S2 LEAGUE', 2, 'league', 1, 38, 'active');
            """,
            (guild_id,),
        )
        s2_id = cur.lastrowid

        # Co-mingled/duplicated S1 fixture inside S2 (the "fake fixture" showing score 2-1)
        await cur.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, guild_id, matchday, match_uid, home_team_id, away_team_id,
                home_team_name, away_team_name, goals_home, goals_away, is_finished
            ) VALUES (?, ?, 1, '01acb2eaae62d866', '325', '21', 'Galatasaray SK', 'FC Bayern München', 2, 1, 1);
            """,
            (s2_id, guild_id),
        )

        # Genuine unplayed S2 fixture in S2
        await cur.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, guild_id, matchday, match_uid, home_team_id, away_team_id,
                home_team_name, away_team_name, goals_home, goals_away, is_finished
            ) VALUES (?, ?, 1, 's2_game_1_unique', '999', '888', 'Inter Miami', 'Al Nassr', 0, 0, 0);
            """,
            (s2_id, guild_id),
        )
        await conn.commit()

    # Before repair: S2 has 2 fixtures (1 fake finished S1, 1 genuine unplayed S2)
    s2_before = await temp_db.get_tournament_fixtures(s2_id)
    assert len(s2_before) == 2

    # Run repair routine
    await temp_db.repair_and_activate_s2(guild_id)

    # After repair: S2 only has the 1 genuine unplayed fixture
    s2_after = await temp_db.get_tournament_fixtures(s2_id)
    assert len(s2_after) == 1
    assert s2_after[0]["match_uid"] == "s2_game_1_unique"
    assert s2_after[0]["is_finished"] == 0

    # S1 still has its finished fixture
    s1_after = await temp_db.get_tournament_fixtures(s1_id)
    assert len(s1_after) == 1
    assert s1_after[0]["match_uid"] == "01acb2eaae62d866"
    assert s1_after[0]["goals_home"] == 2
    assert s1_after[0]["goals_away"] == 1
