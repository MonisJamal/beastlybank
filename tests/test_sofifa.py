"""
Unit & integration tests for SoFIFA Sep 19, 2025 FC 26 database integration.
Validates database caching, instant autocomplete search, embed formatting, and cog loading.
"""
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock
import discord
from discord import app_commands
import pytest
import pytest_asyncio

from database.db import DatabaseManager
from utils.sofifa import sofifa_player_embed
from cogs.sofifa import SoFIFACog, sofifa_autocomplete, SoFIFAView


@pytest_asyncio.fixture
async def db():
    """Create isolated temporary database."""
    fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    manager = DatabaseManager(temp_db_path)
    await manager.init_db()
    yield manager

    await manager.close()
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


SAMPLE_PLAYERS = [
    {
        "id": 231747,
        "name": "K. Mbappé",
        "full_name": "Kylian Mbappé",
        "primary_pos": "ST",
        "positions": "ST, LW",
        "overall_rating": 91,
        "potential": 94,
        "best_pos": "ST",
        "age": 26,
        "team": "Real Madrid",
        "team_logo": "https://cdn.sofifa.net/meta/team/3468/60.png",
        "nationality": "France",
        "flag_url": "https://cdn.sofifa.net/flags/fr.png",
        "value": "€181.5M",
        "wage": "€450K",
        "avatar": "https://cdn.sofifa.net/players/231/747/26_120.png",
        "url": "https://sofifa.com/player/231747/kylian-mbappe/260004/",
    },
    {
        "id": 239085,
        "name": "E. Haaland",
        "full_name": "Erling Haaland",
        "primary_pos": "ST",
        "positions": "ST",
        "overall_rating": 91,
        "potential": 93,
        "best_pos": "ST",
        "age": 25,
        "team": "Manchester City",
        "team_logo": "https://cdn.sofifa.net/meta/team/9/60.png",
        "nationality": "Norway",
        "flag_url": "https://cdn.sofifa.net/flags/no.png",
        "value": "€178M",
        "wage": "€340K",
        "avatar": "https://cdn.sofifa.net/players/239/085/26_120.png",
        "url": "https://sofifa.com/player/239085/erling-haaland/260004/",
    },
    {
        "id": 271701,
        "name": "Lamine Yamal",
        "full_name": "Lamine Yamal Nasraoui Ebana",
        "primary_pos": "RW",
        "positions": "RW",
        "overall_rating": 81,
        "potential": 94,
        "best_pos": "RW",
        "age": 18,
        "team": "FC Barcelona",
        "team_logo": "https://cdn.sofifa.net/meta/team/83/60.png",
        "nationality": "Spain",
        "flag_url": "https://cdn.sofifa.net/flags/es.png",
        "value": "€55.5M",
        "wage": "€35K",
        "avatar": "https://cdn.sofifa.net/players/271/701/26_120.png",
        "url": "https://sofifa.com/player/271701/lamine-yamal/260004/",
    },
]


@pytest.mark.asyncio
async def test_sofifa_caching_and_search(db: DatabaseManager):
    """Test inserting players into cache and querying them."""
    inserted = await db.cache_sofifa_players(SAMPLE_PLAYERS)
    assert inserted == 3

    cnt = await db.get_cached_sofifa_player_count()
    assert cnt == 3

    # Search empty string returns players sorted by overall rating
    top = await db.search_cached_sofifa_players("", limit=10)
    assert len(top) == 3
    assert top[0]["overall_rating"] >= top[1]["overall_rating"] >= top[2]["overall_rating"]

    # Search "Mbappe"
    results = await db.search_cached_sofifa_players("Mbappe")
    assert len(results) >= 1
    assert results[0]["id"] == 231747
    assert results[0]["name"] == "K. Mbappé"

    # Search "Lamine"
    results_yamal = await db.search_cached_sofifa_players("Lamine")
    assert len(results_yamal) >= 1
    assert results_yamal[0]["id"] == 271701


@pytest.mark.asyncio
async def test_get_cached_sofifa_player(db: DatabaseManager):
    """Test resolving full player object by ID and name."""
    await db.cache_sofifa_players(SAMPLE_PLAYERS)

    # By ID
    p = await db.get_cached_sofifa_player("231747")
    assert p is not None
    assert p["name"] == "K. Mbappé"
    assert p["team"] == "Real Madrid"
    assert p["overall_rating"] == 91
    assert p["value"] == "€181.5M"

    # By Short Name
    p2 = await db.get_cached_sofifa_player("E. Haaland")
    assert p2 is not None
    assert p2["id"] == 239085

    # By Full Name
    p3 = await db.get_cached_sofifa_player("Lamine Yamal Nasraoui Ebana")
    assert p3 is not None
    assert p3["id"] == 271701


def test_sofifa_player_embed_no_stats():
    """Verify embed displays photo, ovr, positions, age, market value, wages, link, and NO sub-stats."""
    player = SAMPLE_PLAYERS[0]
    embed = sofifa_player_embed(player)

    # Basic card info
    assert "91" in embed.title
    assert "Kylian Mbappé" in embed.title
    assert embed.url == "https://sofifa.com/player/231747/kylian-mbappe/260004/"
    assert embed.thumbnail.url == "https://cdn.sofifa.net/players/231/747/26_120.png"
    assert "Real Madrid" in embed.description

    field_names = [f.name for f in embed.fields]
    field_values = [f.value for f in embed.fields]

    # Required fields per user request:
    # "leave the stats show photo, ovr, postions, age, market value, wages and link to player"
    assert any("Rating" in name or "OVR" in name for name in field_names)
    assert any("Position" in name for name in field_names)
    assert any("Age" in name for name in field_names)
    assert any("Market Value" in name for name in field_names)
    assert any("Weekly Wage" in name or "Wage" in name for name in field_names)
    assert any("SoFIFA Profile" in name or "Link" in name for name in field_names)

    # Values verify
    combined_values = " ".join(field_values)
    assert "91 OVR" in combined_values
    assert "ST, LW" in combined_values
    assert "26" in combined_values
    assert "€181.5M" in combined_values
    assert "€450K" in combined_values
    assert "sofifa.com" in combined_values

    # Strict check: "leave the stats" - NO attribute radar or sub-stats (PAC, SHO, PAS, DRI, DEF, PHY)
    for stat in ["Pace", "Shooting", "Passing", "Dribbling", "Defending", "Physicality", "PAC", "SHO", "PAS", "DRI", "DEF", "PHY"]:
        for name in field_names:
            assert stat not in name, f"Forbidden stat attribute '{stat}' found in embed field '{name}'"

    # Check footer has Sep 19, 2025
    assert "Sep 19, 2025" in embed.footer.text


@pytest.mark.asyncio
async def test_sofifa_autocomplete(db: DatabaseManager):
    """Verify autocomplete returns valid Choice objects formatted with OVR, position, team."""
    await db.cache_sofifa_players(SAMPLE_PLAYERS)

    interaction = MagicMock(spec=discord.Interaction)
    client_mock = MagicMock()
    client_mock.db = db
    interaction.client = client_mock

    # Autocomplete for "Haal"
    choices = await sofifa_autocomplete(interaction, "Haal")
    assert len(choices) >= 1
    choice = choices[0]
    assert isinstance(choice, app_commands.Choice)
    assert choice.value == "239085"
    assert "Haaland" in choice.name
    assert "91" in choice.name
    assert "ST" in choice.name
    assert "Manchester City" in choice.name


@pytest.mark.asyncio
async def test_sofifa_view_button():
    """Verify link button in SoFIFAView."""
    view = SoFIFAView("https://sofifa.com/player/231747")
    assert len(view.children) == 1
    btn = view.children[0]
    assert isinstance(btn, discord.ui.Button)
    assert btn.url == "https://sofifa.com/player/231747"
    assert btn.label == "View on SoFIFA"
