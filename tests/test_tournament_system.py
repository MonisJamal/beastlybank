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

    # 4. Verify Leaderboards
    top_scorers = await temp_db.get_tournament_leaderboard(saved["id"], "goals", limit=5)
    assert len(top_scorers) > 0
    assert top_scorers[0]["player_name"] == "E. Haaland"
    assert top_scorers[0]["goals"] == 28

    top_playmakers = await temp_db.get_tournament_leaderboard(saved["id"], "assists", limit=5)
    assert len(top_playmakers) > 0
    assert top_playmakers[0]["player_name"] == "B. Saka"
    assert top_playmakers[0]["assists"] == 19

    top_rated = await temp_db.get_tournament_leaderboard(saved["id"], "rating", limit=5)
    assert len(top_rated) > 0
    assert top_rated[0]["rating"] >= 8.5


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
