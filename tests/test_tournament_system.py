import os
import tempfile
import pytest
from database.db import DatabaseManager
from utils.match_parser import parse_matchsimulator_html


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
async def test_parse_and_save_tournament(temp_db):
    html_path = "data/beastly_s1_cup.html"
    assert os.path.exists(html_path), "Season 1 HTML file must exist"

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    parsed = parse_matchsimulator_html(html)
    assert parsed["tournament_name"] == "BEASTLY S1 LEAGUE"
    assert parsed["champion"] == "Manchester City"
    assert parsed["total_fixtures"] == 380
    assert len(parsed["standings"]) == 20

    guild_id = 123456
    saved = await temp_db.save_parsed_tournament(
        guild_id=guild_id,
        tournament_data=parsed,
        url="https://matchsimulator.com/cup/2859670/beastly-s1-league",
        season_number=1,
        competition_type="league",
    )
    assert saved["id"] is not None
    assert saved["name"] == "BEASTLY S1 LEAGUE"
    assert saved["total_matchdays"] == 38

    # 1. Verify Active Tournament Query
    active_t = await temp_db.get_active_tournament(guild_id, "league")
    assert active_t is not None
    assert active_t["id"] == saved["id"]

    # 2. Verify Fixtures Query
    m1_fixtures = await temp_db.get_tournament_fixtures(saved["id"], matchday=1)
    assert len(m1_fixtures) == 10
    m38_fixtures = await temp_db.get_tournament_fixtures(saved["id"], matchday=38)
    assert len(m38_fixtures) == 10

    # 3. Verify Standings Query
    standings = await temp_db.get_tournament_standings(saved["id"])
    assert len(standings) == 20
    assert standings[0]["name"] == "Manchester City"
    assert standings[0]["points"] == 74
    assert standings[1]["name"] == "Arsenal"
    assert standings[1]["points"] == 73
    assert standings[2]["name"] == "Liverpool"
    assert standings[2]["points"] == 73

    # Clean sheets: Liverpool should be top with 18
    liv = next(s for s in standings if s["name"] == "Liverpool")
    assert liv["clean_sheets"] == 18

    # 4. Verify Tournament Awards from genuine standings
    awards = parsed["awards"]
    assert awards["champion"] == "Manchester City"
    assert awards["golden_glove"]["team_name"] == "Liverpool"
    assert awards["golden_glove"]["clean_sheets"] == 18
    assert awards["golden_boot"]["player_name"] == "E. Haaland"
    assert awards["golden_boot"]["stat_value"] == 28
    assert awards["playmaker"]["player_name"] == "B. Saka"
    assert awards["playmaker"]["stat_value"] == 19


@pytest.mark.asyncio
async def test_matchday_betting_and_settlement(temp_db):
    guild_id = 999
    user_id = 777
    tourn_id = 1

    # Setup dummy tournament with 1 unplayed fixture
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO tournaments (id, guild_id, name, season_number, competition_type, status)
            VALUES (1, 999, 'Test League', 2, 'league', 'active');
            """
        )
        await cur.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, guild_id, matchday, home_team_id, away_team_id,
                home_team_name, away_team_name, is_finished
            ) VALUES (1, 999, 1, '1', '2', 'Team Alpha', 'Team Beta', 0);
            """
        )
        fixture_id = cur.lastrowid

    # Give user 50M cash
    await temp_db.get_or_create_user(user_id, guild_id)
    async with conn.cursor() as cur:
        await cur.execute("UPDATE users SET cash = 50000000 WHERE user_id = ?;", (user_id,))

    # 1. Place bet on Home Win with 10M at 2.0x odds
    ok, msg, bet = await temp_db.place_matchday_bet(
        guild_id=guild_id,
        tournament_id=tourn_id,
        matchday=1,
        fixture_id=fixture_id,
        user_id=user_id,
        bet_type="home",
        amount=10_000_000,
        odds=2.0,
    )
    assert ok, f"Bet placement failed: {msg}"
    assert bet["status"] == "pending"

    # User cash debited: 50M - 10M = 40M
    u = await temp_db.get_or_create_user(user_id, guild_id)
    assert u["cash"] == 40_000_000

    # 2. Simulate match finishing: Home team wins 3-1
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE tournament_fixtures SET goals_home = 3, goals_away = 1, is_finished = 1 WHERE id = ?;",
            (fixture_id,),
        )

    # 3. Settle matchday bets
    payouts = await temp_db.settle_matchday_bets(tourn_id, matchday=1)
    assert len(payouts) == 1
    assert payouts[0]["status"] == "won"
    assert payouts[0]["payout"] == 20_000_000

    # User cash credited: 40M + 20M = 60M
    u_after = await temp_db.get_or_create_user(user_id, guild_id)
    assert u_after["cash"] == 60_000_000


@pytest.mark.asyncio
async def test_tournament_conclusion_and_hall_of_fame(temp_db):
    guild_id = 888
    # Insert finished tournament
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO tournaments (guild_id, name, season_number, competition_type, status, champion, runner_up)
            VALUES (888, 'Beastly League S1', 1, 'league', 'active', 'Manchester City', 'Arsenal');
            """
        )
        t_id = cur.lastrowid

        # Add standings
        await cur.execute(
            """
            INSERT INTO tournament_standings (tournament_id, team_id, name, rank, clean_sheets, points)
            VALUES (?, '10', 'Manchester City', 1, 12, 74),
                   (?, '1', 'Arsenal', 2, 14, 73);
            """,
            (t_id, t_id),
        )

        # Add player stats
        await cur.execute(
            """
            INSERT INTO tournament_player_stats (tournament_id, guild_id, player_name, team_name, goals, assists, rating)
            VALUES (?, 888, 'E. Haaland', 'Manchester City', 28, 5, 9.04),
                   (?, 888, 'B. Saka', 'Arsenal', 12, 19, 8.45);
            """,
            (t_id, t_id),
        )

    # Conclude tournament
    ok, msg, res = await temp_db.conclude_tournament(t_id)
    assert ok
    assert res["status"] == "completed"

    # Verify Hall of Fame / season_history
    history = await temp_db.get_season_history(guild_id, season_number=1)
    assert len(history) == 1
    record = history[0]
    assert record["champion"] == "Manchester City"
    assert record["runner_up"] == "Arsenal"
    assert record["golden_boot_player"] == "E. Haaland"
    assert record["golden_boot_goals"] == 28
    assert record["playmaker_player"] == "B. Saka"
    assert record["playmaker_assists"] == 19


@pytest.mark.asyncio
async def test_multi_season_stats_retention(temp_db):
    """Test that starting Season 2 preserves Season 1 stats and career profiles aggregate across seasons."""
    guild_id = 999
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        # Create Season 1
        await cur.execute(
            "INSERT INTO tournaments (id, guild_id, name, season_number, competition_type, status) VALUES (10, 999, 'Season 1', 1, 'league', 'completed');"
        )
        # Create Season 2
        await cur.execute(
            "INSERT INTO tournaments (id, guild_id, name, season_number, competition_type, status) VALUES (20, 999, 'Season 2', 2, 'league', 'active');"
        )
        # Add Haaland stats for S1 (28 goals) and S2 (10 goals)
        await cur.execute(
            """
            INSERT INTO tournament_player_stats (tournament_id, guild_id, player_name, team_name, goals, assists, rating, matches_played)
            VALUES (10, 999, 'E. Haaland', 'Man City', 28, 5, 9.04, 38),
                   (20, 999, 'E. Haaland', 'Man City', 10, 2, 8.80, 12);
            """
        )

    # 1. Fetch Season 1 specific profile
    s1_haaland = await temp_db.get_player_profile(guild_id, "E. Haaland", season_number=1)
    assert s1_haaland is not None
    assert s1_haaland["total_goals"] == 28
    assert s1_haaland["season_number"] == 1

    # 2. Fetch Season 2 specific profile
    s2_haaland = await temp_db.get_player_profile(guild_id, "E. Haaland", season_number=2)
    assert s2_haaland is not None
    assert s2_haaland["total_goals"] == 10
    assert s2_haaland["season_number"] == 2

    # 3. Fetch Career all-time profile (sums S1 + S2)
    career_haaland = await temp_db.get_player_profile(guild_id, "E. Haaland")
    assert career_haaland is not None
    assert career_haaland["total_goals"] == 38  # 28 + 10
    assert career_haaland["total_assists"] == 7  # 5 + 2
    assert career_haaland["total_matches"] == 50  # 38 + 12
    assert len(career_haaland["seasons"]) == 2

    # 4. Fetch tournament by season
    t_s1 = await temp_db.get_tournament_by_season(guild_id, "league", 1)
    assert t_s1["name"] == "Season 1"
    t_s2 = await temp_db.get_tournament_by_season(guild_id, "league", 2)
    assert t_s2["name"] == "Season 2"


@pytest.mark.asyncio
async def test_bottom_5_betting_restriction(temp_db):
    """Test that matches involving bottom 5 clubs in standings are blocked from bets."""
    guild_id = 999
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO tournaments (id, guild_id, name, season_number, competition_type, status) VALUES (30, 999, 'Season 2', 2, 'league', 'active');"
        )
        # Create 6 teams with standings: ranks 1 to 6 (so ranks 2, 3, 4, 5, 6 are bottom 5)
        for i in range(1, 7):
            await cur.execute(
                "INSERT INTO tournament_standings (tournament_id, team_id, name, rank, clean_sheets, points) VALUES (30, ?, ?, ?, 0, ?);",
                (str(i), f"Team_{i}", i, 20 - i),
            )
        # Fixture 1: Team_1 (Rank 1, top) vs Team_6 (Rank 6, bottom 5) -> RESTRICTED
        await cur.execute(
            "INSERT INTO tournament_fixtures (id, tournament_id, guild_id, matchday, home_team_id, away_team_id, home_team_name, away_team_name, is_finished) VALUES (301, 30, 999, 1, '1', '6', 'Team_1', 'Team_6', 0);"
        )

    # Fund user
    await temp_db.get_or_create_user(555, guild_id)
    async with conn.cursor() as cur:
        await cur.execute("UPDATE users SET cash = 10000000 WHERE user_id = 555;")
        await conn.commit()

    # Attempt bet on Fixture 301
    ok, msg, bet = await temp_db.place_matchday_bet(
        guild_id=guild_id,
        tournament_id=30,
        matchday=1,
        fixture_id=301,
        user_id=555,
        bet_type="home",
        amount=1_000_000,
    )
    assert not ok
    assert "bottom 5" in msg.lower()
    assert "Team_6" in msg


@pytest.mark.asyncio
async def test_ucl_s1_knockout_tournament(temp_db):
    """Test parsing, knockout stages, penalty shootouts, and dual-seeding for BEASTLY UCL S1."""
    ucl_path = "data/beastly_ucl_s1.html"
    assert os.path.exists(ucl_path), "UCL S1 HTML file must exist"

    with open(ucl_path, "r", encoding="utf-8") as f:
        html = f.read()

    parsed = parse_matchsimulator_html(html)
    assert parsed["tournament_name"] == "BEASTLY UCL S1"
    assert parsed["champion"] == "Paris Saint-Germain"
    assert parsed["runner_up"] == "Chelsea"
    assert parsed["highest_matchday"] == 7
    assert parsed["total_fixtures"] == 29

    # Verify Awards
    awards = parsed["awards"]
    assert awards["golden_boot"]["player_name"] == "Eusebio"
    assert awards["golden_boot"]["stat_value"] == 8
    assert awards["playmaker"]["player_name"] == "A. Hakimi"
    assert awards["champion"] == "Paris Saint-Germain"
    assert awards["runner_up"] == "Chelsea"

    guild_id = 777888
    # Test dual-seeding of League + UCL
    t_league = await temp_db.ensure_tournament_seeded(guild_id)
    assert t_league is not None
    assert t_league["competition_type"] == "league"

    t_ucl = await temp_db.get_active_tournament(guild_id, competition_type="ucl")
    assert t_ucl is not None
    assert t_ucl["name"] == "BEASTLY UCL S1"
    assert t_ucl["champion"] == "Paris Saint-Germain"
    assert t_ucl["runner_up"] == "Chelsea"

    # Verify Matchday 7 (Final) stage name
    final_fixtures = await temp_db.get_tournament_fixtures(t_ucl["id"], matchday=7)
    assert len(final_fixtures) == 1
    final_m = final_fixtures[0]
    assert final_m["stage_name"] == "Final"
    assert final_m["home_team_name"] == "Chelsea"
    assert final_m["away_team_name"] == "Paris Saint-Germain"
    assert final_m["goals_home"] == 1
    assert final_m["goals_away"] == 3

    # Verify Matchday 4 Penalties (Inter vs Bayern)
    m4_fixtures = await temp_db.get_tournament_fixtures(t_ucl["id"], matchday=4)
    pen_match = next((f for f in m4_fixtures if f["home_team_short"] == "INT"), None)
    assert pen_match is not None
    assert pen_match["penalties_home"] == 3
    assert pen_match["penalties_away"] == 4

    # Verify Hall of Fame has both League and UCL
    hof = await temp_db.get_season_history(guild_id)
    assert len(hof) == 2
    comp_names = [h["competition_name"] for h in hof]
    assert "BEASTLY S1 LEAGUE" in comp_names
    assert "BEASTLY UCL S1" in comp_names


@pytest.mark.asyncio
async def test_season_isolation_and_s2_default(temp_db):
    """Test that importing Season 2 creates a distinct tournament, preserves S1, and makes S2 active default."""
    guild_id = 444555
    # 1. Seed Season 1
    t_league = await temp_db.ensure_tournament_seeded(guild_id)
    assert t_league is not None

    s1_t = await temp_db.get_tournament_by_season(guild_id, "league", season_number=1)
    assert s1_t is not None
    s1_fixtures = await temp_db.get_tournament_fixtures(s1_t["id"])
    assert len(s1_fixtures) == 380

    # 2. Simulate importing Season 2 HTML data
    s2_data = {
        "tournament_name": "BEASTLY S2 LEAGUE",
        "highest_matchday": 38,
        "champion": None,
        "runner_up": None,
        "standings": [
            {"team_id": "1", "name": "Arsenal", "short": "ARS", "rank": 1, "played": 0, "won": 0, "drawn": 0, "lost": 0, "goals_for": 0, "goals_against": 0, "goal_difference": 0, "clean_sheets": 0, "points": 0},
            {"team_id": "5", "name": "Chelsea", "short": "CHE", "rank": 2, "played": 0, "won": 0, "drawn": 0, "lost": 0, "goals_for": 0, "goals_against": 0, "goal_difference": 0, "clean_sheets": 0, "points": 0},
        ],
        "fixtures_by_matchday": {
            1: [
                {
                    "matchday": 1,
                    "stage_name": "Matchday 1",
                    "match_uid": "s2_md1_match1",
                    "home_team_id": "1",
                    "away_team_id": "5",
                    "home_team_name": "Arsenal",
                    "away_team_name": "Chelsea",
                    "home_team_short": "ARS",
                    "away_team_short": "CHE",
                    "goals_home": 0,
                    "goals_away": 0,
                    "penalties_home": 0,
                    "penalties_away": 0,
                    "is_finished": False,
                    "replay_exists": False,
                }
            ]
        },
    }

    saved_s2 = await temp_db.save_parsed_tournament(
        guild_id=guild_id,
        tournament_data=s2_data,
        season_number=2,
        competition_type="league",
    )
    assert saved_s2["season_number"] == 2
    assert saved_s2["id"] != s1_t["id"]

    # 3. Verify Active Tournament is now Season 2!
    active_t = await temp_db.get_active_tournament(guild_id, "league")
    assert active_t is not None
    assert active_t["season_number"] == 2
    assert active_t["name"] == "BEASTLY S2 LEAGUE"
    assert active_t["status"] == "active"

    # 4. Verify Season 1 remains completed with all 380 fixtures intact
    s1_after = await temp_db.get_tournament_by_season(guild_id, "league", season_number=1)
    assert s1_after["status"] == "completed"
    s1_fixes_after = await temp_db.get_tournament_fixtures(s1_t["id"])
    assert len(s1_fixes_after) == 380

    # 5. Verify Season 2 Matchday 1 has ONLY Season 2 fixtures (no random S1 results)
    s2_md1 = await temp_db.get_tournament_fixtures(saved_s2["id"], matchday=1)
    assert len(s2_md1) == 1
    assert s2_md1[0]["home_team_name"] == "Arsenal"
    assert s2_md1[0]["away_team_name"] == "Chelsea"
    assert not s2_md1[0]["is_finished"]


@pytest.mark.asyncio
async def test_stale_fixtures_pruned_on_reimport(temp_db):
    """Test that re-importing a tournament prunes stale fixtures so old results never appear above new ones."""
    guild_id = 111222
    t_data_v1 = {
        "tournament_name": "BEASTLY S2 LEAGUE",
        "highest_matchday": 1,
        "fixtures_by_matchday": {
            1: [
                {
                    "matchday": 1,
                    "home_team_id": "100",
                    "away_team_id": "200",
                    "home_team_name": "Old Home",
                    "away_team_name": "Old Away",
                    "goals_home": 3,
                    "goals_away": 0,
                    "is_finished": True,
                }
            ]
        },
        "standings": [],
    }

    t1 = await temp_db.save_parsed_tournament(guild_id, t_data_v1, season_number=2)
    fixes1 = await temp_db.get_tournament_fixtures(t1["id"], matchday=1)
    assert len(fixes1) == 1
    assert fixes1[0]["home_team_name"] == "Old Home"

    # Now re-import with new schedule
    t_data_v2 = {
        "tournament_name": "BEASTLY S2 LEAGUE",
        "highest_matchday": 1,
        "fixtures_by_matchday": {
            1: [
                {
                    "matchday": 1,
                    "home_team_id": "300",
                    "away_team_id": "400",
                    "home_team_name": "New Home",
                    "away_team_name": "New Away",
                    "goals_home": 0,
                    "goals_away": 0,
                    "is_finished": False,
                }
            ]
        },
        "standings": [],
    }

    t2 = await temp_db.save_parsed_tournament(guild_id, t_data_v2, season_number=2)
    assert t2["id"] == t1["id"]
    fixes2 = await temp_db.get_tournament_fixtures(t2["id"], matchday=1)
    assert len(fixes2) == 1
    assert fixes2[0]["home_team_name"] == "New Home"
    assert not fixes2[0]["is_finished"]


@pytest.mark.asyncio
async def test_self_healing_migration_recovers_comingled_fixtures(temp_db):
    """Test that repair_and_activate_s2 detects co-mingled S2 fixtures in S1 and migrates them cleanly."""
    guild_id = 333444
    await temp_db.ensure_tournament_seeded(guild_id)
    s1_t = await temp_db.get_tournament_by_season(guild_id, "league", season_number=1)

    # Intentionally corrupt S1 by injecting an S2 fixture directly into S1's tournament_id
    conn = await temp_db.connect()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO tournament_fixtures (
                tournament_id, guild_id, matchday, home_team_id, away_team_id,
                home_team_name, away_team_name, goals_home, goals_away, is_finished
            ) VALUES (?, ?, 1, '9999', '8888', 'S2 Injected Home', 'S2 Injected Away', 0, 0, 0);
            """,
            (s1_t["id"], guild_id),
        )
        injected_id = cur.lastrowid
        await conn.commit()

    # Verify S1 currently has 381 fixtures (polluted)
    fixes_corrupt = await temp_db.get_tournament_fixtures(s1_t["id"])
    assert len(fixes_corrupt) == 381

    # Run repair
    await temp_db.repair_and_activate_s2(guild_id)

    # Verify S1 is repaired to exactly 380 fixtures
    s1_clean = await temp_db.get_tournament_fixtures(s1_t["id"])
    assert len(s1_clean) == 380

    # Verify S2 exists, is active, and contains the injected fixture
    s2_t = await temp_db.get_tournament_by_season(guild_id, "league", season_number=2)
    assert s2_t is not None
    assert s2_t["status"] == "active"
    s2_fixes = await temp_db.get_tournament_fixtures(s2_t["id"])
    assert len(s2_fixes) >= 1
    injected_found = next((f for f in s2_fixes if f["id"] == injected_id), None)
    assert injected_found is not None
    assert injected_found["home_team_name"] == "S2 Injected Home"

