import pytest
from utils.name_matcher import (
    normalize_text,
    match_player_name,
    match_club_name,
    autocomplete_players_search,
    autocomplete_clubs_search,
)
from database.db import DatabaseManager
import os
import tempfile


def test_normalize_text():
    assert normalize_text("K. Mbappé") == "k mbappe"
    assert normalize_text("Atlético Madrid") == "atletico madrid"
    assert normalize_text("FC Bayern München") == "fc bayern munchen"
    assert normalize_text("Bruno Guimarães") == "bruno guimaraes"
    assert normalize_text("  E.  Haaland  ") == "e haaland"


def test_match_player_name():
    players = [
        "E. Haaland",
        "K. Mbappé",
        "B. Saka",
        "C. Palmer",
        "E. Fernández",
        "Bruno Guimarães",
        "Ronaldo Nazario",
        "Bremer",
        "Blanc",
        "Balde",
    ]

    # Full name to initial-surname
    m, score, _ = match_player_name("Erling Haaland", players)
    assert m == "E. Haaland"
    assert score >= 0.90

    # Surname only
    m, score, _ = match_player_name("haaland", players)
    assert m == "E. Haaland"

    # Fuzzy typo
    m, score, _ = match_player_name("Haland", players)
    assert m == "E. Haaland"

    # Missing accents
    m, score, _ = match_player_name("mbappe", players)
    assert m == "K. Mbappé"

    m, score, _ = match_player_name("Kylian Mbappe", players)
    assert m == "K. Mbappé"

    m, score, _ = match_player_name("Enzo Fernandez", players)
    assert m == "E. Fernández"

    m, score, _ = match_player_name("guimaraes", players)
    assert m == "Bruno Guimarães"

    # Nickname
    m, score, _ = match_player_name("r9", players)
    assert m == "Ronaldo Nazario"

    # Not in roster (Benzema)
    m, score, sugg = match_player_name("benzema", players)
    assert m is None
    assert len(sugg) > 0
    assert "Bremer" in sugg or "Blanc" in sugg or "Balde" in sugg

    m, score, sugg = match_player_name("Karim Benzema", players)
    assert m is None


def test_match_club_name():
    clubs = [
        "Manchester City",
        "Paris Saint-Germain",
        "FC Bayern München",
        "Atlético Madrid",
        "Chelsea",
        "Arsenal",
        "Tottenham Hotspur",
        "Juventus",
    ]

    assert match_club_name("psg", clubs)[0] == "Paris Saint-Germain"
    assert match_club_name("man city", clubs)[0] == "Manchester City"
    assert match_club_name("city", clubs)[0] == "Manchester City"
    assert match_club_name("bayern", clubs)[0] == "FC Bayern München"
    assert match_club_name("atletico", clubs)[0] == "Atlético Madrid"
    assert match_club_name("spurs", clubs)[0] == "Tottenham Hotspur"
    assert match_club_name("juve", clubs)[0] == "Juventus"
    assert match_club_name("chelsea", clubs)[0] == "Chelsea"


def test_autocomplete():
    player_pairs = [
        ("E. Haaland", "Manchester City"),
        ("K. Mbappé", "Real Madrid"),
        ("B. Saka", "Arsenal"),
        ("C. Palmer", "Chelsea"),
    ]

    # Typing "erl" should suggest E. Haaland
    res = autocomplete_players_search("erl", player_pairs)
    assert len(res) >= 1
    assert res[0][0] == "E. Haaland"

    # Typing "mbap" should suggest K. Mbappé
    res = autocomplete_players_search("mbap", player_pairs)
    assert len(res) >= 1
    assert res[0][0] == "K. Mbappé"

    # Typing "sak" should suggest B. Saka
    res = autocomplete_players_search("sak", player_pairs)
    assert len(res) >= 1
    assert res[0][0] == "B. Saka"


@pytest.mark.asyncio
async def test_db_smart_player_profile():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = DatabaseManager(path)
    await db.init_db()

    conn = await db.connect()
    guild_id = 999
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO tournaments (id, guild_id, name, total_matchdays, current_matchday, status, competition_type, season_number)
            VALUES (1, ?, 'TEST TOURNAMENT', 10, 1, 'active', 'league', 1);
            """,
            (guild_id,),
        )
        await cur.execute(
            """
            INSERT INTO tournament_player_stats (
                tournament_id, guild_id, player_name, team_name, goals, assists,
                own_goals, yellow_cards, red_cards, clean_sheets, matches_played,
                minutes_played, rating
            ) VALUES (1, ?, 'E. Haaland', 'Manchester City', 15, 4, 0, 1, 0, 0, 10, 900, 8.2);
            """,
            (guild_id,),
        )
        await cur.execute(
            """
            INSERT INTO tournament_player_stats (
                tournament_id, guild_id, player_name, team_name, goals, assists,
                own_goals, yellow_cards, red_cards, clean_sheets, matches_played,
                minutes_played, rating
            ) VALUES (1, ?, 'K. Mbappé', 'Paris Saint-Germain', 12, 6, 0, 0, 0, 0, 10, 850, 7.9);
            """,
            (guild_id,),
        )
        await conn.commit()

    # Query with full name "Erling Haaland"
    prof = await db.get_player_profile(guild_id, "Erling Haaland")
    assert prof is not None
    assert prof["player_name"] == "E. Haaland"
    assert prof["total_goals"] == 15
    assert prof["total_minutes"] == 900

    # Query with surname only "haaland"
    prof = await db.get_player_profile(guild_id, "haaland")
    assert prof is not None
    assert prof["player_name"] == "E. Haaland"

    # Query with typo "Haland"
    prof = await db.get_player_profile(guild_id, "Haland")
    assert prof is not None
    assert prof["player_name"] == "E. Haaland"

    # Query without accents "mbappe"
    prof = await db.get_player_profile(guild_id, "mbappe")
    assert prof is not None
    assert prof["player_name"] == "K. Mbappé"

    # Query with "Kylian Mbappe"
    prof = await db.get_player_profile(guild_id, "Kylian Mbappe")
    assert prof is not None
    assert prof["player_name"] == "K. Mbappé"

    # Query for absent player "Karim Benzema"
    prof = await db.get_player_profile(guild_id, "Karim Benzema")
    assert prof is None

    # Club query with alias "man city"
    c_players = await db.get_club_player_stats(1, "man city")
    assert len(c_players) == 1
    assert c_players[0]["team_name"] == "Manchester City"

    # Club query with alias "psg"
    c_players = await db.get_club_player_stats(1, "psg")
    assert len(c_players) == 1
    assert c_players[0]["team_name"] == "Paris Saint-Germain"

    await db.close()
    if os.path.exists(path):
        os.remove(path)
