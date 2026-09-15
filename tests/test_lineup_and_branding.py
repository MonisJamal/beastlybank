import os
import tempfile
from unittest.mock import MagicMock
import pytest
import pytest_asyncio
from database.db import DatabaseManager
from utils.lineup_image import (
    resolve_club_preset,
    get_preset_choices,
    generate_lineup_image,
    CLUB_PRESETS,
    CLUB_ALIASES,
)
from utils.embeds import club_lineup_embed, club_ratings_embed


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
async def test_club_presets_coverage():
    """Verify that all 20 requested world clubs are properly registered with aliases."""
    expected_clubs = [
        "Aston Villa",
        "Arsenal",
        "Inter Milan",
        "AC Milan",
        "Bayern Munich",
        "Barcelona",
        "Real Madrid",
        "Manchester United",
        "Manchester City",
        "Atlético Madrid",
        "Nottingham Forest",
        "Liverpool",
        "Juventus",
        "Napoli",
        "Newcastle",
        "Borussia Dortmund",
        "Chelsea",
        "Tottenham Hotspur",
        "Paris Saint-Germain (PSG)",
        "Galatasaray",
    ]

    choices = get_preset_choices()
    for club_name in expected_clubs:
        assert club_name in choices, f"Missing preset choice: {club_name}"

    test_queries = {
        "Aston villa": "aston villa",
        "Arsenal": "arsenal",
        "Inter Millan": "inter milan",
        "inter": "inter milan",
        "AC Millan": "ac milan",
        "milan": "ac milan",
        "Bayern": "bayern",
        "bayern munich": "bayern",
        "Barcelona": "barcelona",
        "barca": "barcelona",
        "Real Madrid": "real madrid",
        "real": "real madrid",
        "Man united": "manchester united",
        "man utd": "manchester united",
        "Manchester city": "manchester city",
        "man city": "manchester city",
        "Athletico Madrid": "atletico madrid",
        "atleti": "atletico madrid",
        "Nottingham Forrest": "nottingham forest",
        "forest": "nottingham forest",
        "Liverpool": "liverpool",
        "Juventus": "juventus",
        "juve": "juventus",
        "Napoli": "napoli",
        "Newcastle": "newcastle",
        "newcastle united": "newcastle",
        "Dortmund": "borussia dortmund",
        "bvb": "borussia dortmund",
        "Chelsea": "chelsea",
        "Tottenham": "tottenham",
        "spurs": "tottenham",
        "psg": "psg",
        "paris": "psg",
        "galatasaray": "galatasaray",
        "cimbom": "galatasaray",
    }

    for query, expected_key in test_queries.items():
        preset = resolve_club_preset(query)
        assert preset is not None, f"Failed to resolve query: '{query}'"
        assert preset["primary"].startswith("#")
        assert preset["secondary"].startswith("#")
        assert "slogan_1" in preset
        assert "chant" in preset


@pytest.mark.asyncio
async def test_bench_limit_and_reserves_squad_lifecycle(db: DatabaseManager):
    """Verify max 9 bench players limit, overflow handling, and reserve status."""
    guild_id = 123456789
    role_mock = MagicMock()
    role_mock.id = 987654321
    role_mock.name = "Aston Villa"
    role_mock.color = MagicMock(value=0x95BFE5)

    club = await db.get_or_create_club_from_role(guild_id, role_mock, default_owner_id=55555)

    # 1. Add 11 starting players
    starters = [
        ("Martinez", "GK", 87),
        ("Cash", "RB", 80),
        ("Konsa", "CB", 82),
        ("Pau Torres", "CB", 83),
        ("Digne", "LB", 80),
        ("Kamara", "CDM", 82),
        ("Douglas Luiz", "CM", 85),
        ("McGinn", "CAM", 83),
        ("Bailey", "RW", 82),
        ("Watkins", "ST", 85),
        ("Rogers", "LW", 79),
    ]
    for name, pos, rat in starters:
        ok, msg, _ = await db.add_club_player(guild_id, club["id"], name, pos, "starting", rating=rat)
        assert ok is True, f"Failed to add starter {name}: {msg}"

    # Adding 12th starter should fail
    ok, msg, _ = await db.add_club_player(guild_id, club["id"], "Extra Starter", "CB", "starting")
    assert ok is False
    assert "already has 11 players" in msg

    # 2. Add 9 bench players
    bench_names = [f"BenchPlayer_{i}" for i in range(1, 10)]
    for name in bench_names:
        ok, msg, _ = await db.add_club_player(guild_id, club["id"], name, "CM", "bench", rating=78)
        assert ok is True, f"Failed to add bench player {name}: {msg}"

    # Adding 10th bench player should fail with guidance to use reserve
    ok, msg, _ = await db.add_club_player(guild_id, club["id"], "BenchPlayer_10", "ST", "bench", rating=75)
    assert ok is False
    assert "is full (9/9 players)" in msg
    assert "reserve" in msg

    # Adding as reserve should succeed
    ok, msg, _ = await db.add_club_player(guild_id, club["id"], "ReservePlayer_1", "ST", "reserve", rating=75)
    assert ok is True
    assert "Reserves" in msg

    # Add another reserve
    ok, msg, _ = await db.add_club_player(guild_id, club["id"], "ReservePlayer_2", "CB", "reserve", rating=74)
    assert ok is True

    # 3. Retrieve lineup and verify split
    ok, msg, lineup = await db.get_club_lineup(guild_id, club["id"])
    assert ok is True
    assert len(lineup["starting"]) == 11
    assert len(lineup["bench"]) == 9
    assert len(lineup["reserves"]) == 2

    # 4. Verify Lineup Embed formatting
    embed = club_lineup_embed(
        club=lineup["club"],
        formation=lineup["formation"],
        starting_players=lineup["starting"],
        bench_players=lineup["bench"],
        reserves=lineup["reserves"],
    )
    bench_field = next((f for f in embed.fields if "Substitutes Bench" in f.name), None)
    assert bench_field is not None
    assert "9/9" in bench_field.name

    reserve_field = next((f for f in embed.fields if "Reserves" in f.name), None)
    assert reserve_field is not None
    assert "ReservePlayer_1" in reserve_field.value
    assert "ReservePlayer_2" in reserve_field.value

    # 5. Edit a player from reserve to bench (should fail if bench is 9/9)
    res_player = lineup["reserves"][0]
    ok, msg, _ = await db.edit_club_player(guild_id, club["id"], res_player["player_name"], status="bench")
    assert ok is False
    assert "is full (9/9 players)" in msg

    # Edit a bench player to reserve (opens a bench slot)
    bench_p1 = lineup["bench"][0]
    ok, msg, _ = await db.edit_club_player(guild_id, club["id"], bench_p1["player_name"], status="reserve")
    assert ok is True

    # Now editing res_player to bench should succeed!
    ok, msg, _ = await db.edit_club_player(guild_id, club["id"], res_player["player_name"], status="bench")
    assert ok is True

    # 6. Test swap between bench and reserve
    _, _, fresh_lineup = await db.get_club_lineup(guild_id, club["id"])
    assert len(fresh_lineup["bench"]) == 9
    assert len(fresh_lineup["reserves"]) == 2

    cur_bench = fresh_lineup["bench"][0]["player_name"]
    cur_res = fresh_lineup["reserves"][0]["player_name"]
    swap_ok, swap_msg = await db.swap_club_players(guild_id, club["id"], cur_bench, cur_res)
    assert swap_ok is True
    assert "Swapped" in swap_msg

    # 7. Generate Lineup Image with full 11 + 9 bench + reserves
    buffer = generate_lineup_image(
        team_name="Aston Villa",
        manager_name="Unai Emery",
        formation_name=fresh_lineup["formation"],
        starting_players=fresh_lineup["starting"],
        bench_players=fresh_lineup["bench"],
        reserves=fresh_lineup["reserves"],
        custom_branding={
            "kit_primary": "#670E36",
            "kit_secondary": "#95BFE5",
            "slogan_1": "PREPARED.",
            "slogan_2": "VILLANS FOR LIFE.",
            "chant": "UP THE VILLA!",
        },
    )
    assert buffer is not None
    image_bytes = buffer.getvalue()
    assert len(image_bytes) > 50000


@pytest.mark.asyncio
async def test_set_branding_preset_and_custom(db: DatabaseManager):
    """Test applying a world club preset and custom overrides via DB."""
    guild_id = 123456789
    role_mock = MagicMock()
    role_mock.id = 987654322
    role_mock.name = "Real Madrid CF"
    role_mock.color = MagicMock(value=0xFEBE10)

    club = await db.get_or_create_club_from_role(guild_id, role_mock, default_owner_id=55555)

    # 1. Apply Real Madrid preset
    preset_data = resolve_club_preset("Real Madrid")
    assert preset_data is not None
    ok, msg, updated = await db.set_club_branding(
        guild_id=guild_id,
        club_query=club["id"],
        kit_primary=preset_data.get("primary"),
        kit_secondary=preset_data.get("secondary"),
        slogan_1=preset_data.get("slogan_1"),
        slogan_2=preset_data.get("slogan_2"),
        chant=preset_data.get("chant"),
    )
    assert ok is True
    assert updated["kit_primary"] == "#FFFFFF"
    assert "HISTORIA" in updated["chant"]
    assert "HALA MADRID" in updated["slogan_2"]

    # 2. Apply Galatasaray preset
    gala_preset = resolve_club_preset("Galatasaray")
    assert gala_preset is not None
    ok, msg, updated = await db.set_club_branding(
        guild_id=guild_id,
        club_query=club["id"],
        kit_primary=gala_preset.get("primary"),
        kit_secondary=gala_preset.get("secondary"),
        slogan_1=gala_preset.get("slogan_1"),
        slogan_2=gala_preset.get("slogan_2"),
        chant=gala_preset.get("chant"),
    )
    assert ok is True
    assert updated["kit_primary"] == "#A90432"
    assert updated["kit_secondary"] == "#FDB913"
    assert "GALATASARAY" in updated["chant"]
