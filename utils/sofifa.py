"""
SoFIFA Sep 19, 2025 (EA Sports FC 26) Database Integration Client.
Extracts official launch roster update (r=260004) player profiles, photos,
positions, ratings, market values, and wages.
"""
from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
import discord

import unicodedata

logger = logging.getLogger("BeastlyBank.SoFIFA")

SOFIFA_ROSTER_VERSION = "260004"  # Sep 19, 2025 update in FC 26
SOFIFA_BASE_URL = "https://sofifa.com/players"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://sofifa.com/",
}


def normalize_text(text: str) -> str:
    """Strip accents, special characters, and lowercase text for robust fuzzy searching (e.g. Mbappé -> mbappe)."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    stripped = (
        stripped.replace("ø", "o")
        .replace("Ø", "o")
        .replace("æ", "ae")
        .replace("Æ", "ae")
        .replace("ß", "ss")
    )
    return stripped.lower().strip()


def _parse_sofifa_sync(keyword: str = "", offset: int = 0, timeout: int = 10) -> List[Dict[str, Any]]:
    """Synchronous HTTP worker to scrape SoFIFA players for r=260004."""
    cols = ["pi", "ae", "hi", "wi", "pf", "oa", "pt", "bo", "bp", "vl", "wg", "rc", "cp", "cj"]
    query_params = [("r", SOFIFA_ROSTER_VERSION), ("set", "true"), ("offset", str(offset))]
    if keyword:
        query_params.append(("keyword", keyword))
    for c in cols:
        query_params.append(("showCol[]", c))

    url = f"{SOFIFA_BASE_URL}?" + urllib.parse.urlencode(query_params)
    req = urllib.request.Request(url, headers=HEADERS)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning("SoFIFA fetch error for keyword '%s': %s", keyword, e)
        return []

    rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
    players = []
    for r in rows[1:]:  # Skip header row
        try:
            # Player ID
            pid_m = re.search(r'id="(\d+)" class="player-check"', r) or re.search(r'data-col="pi">(\d+)<', r)
            if not pid_m:
                continue
            pid = int(pid_m.group(1))

            # Avatar URL (high-resolution face photo)
            img_m = re.search(r'data-src="([^"]+players/[^"]+)"', r)
            if img_m:
                avatar = img_m.group(1).replace("26_60.png", "26_120.png")
            else:
                pid_str = str(pid).zfill(6)
                avatar = f"https://cdn.sofifa.net/players/{pid_str[:3]}/{pid_str[3:]}/26_120.png"

            # Name and Relative Link
            name_m = re.search(r'<a href="(/player/\d+/[^/]+/260004/)"[^>]*data-tippy-content="([^"]+)">([^<]+)</a>', r)
            if not name_m:
                name_m = re.search(r'<a href="(/player/\d+/[^/]+/[^/]+/)"[^>]*data-tippy-content="([^"]+)">([^<]+)</a>', r)
            if not name_m:
                continue

            link, full_name, short_name = name_m.groups()

            # Clean full name & short name
            full_name = full_name.strip()
            short_name = short_name.strip()

            # Nationalities
            nats = re.findall(r'<img title="([^"]+)"[^>]*data-src="([^"]+flags/[^"]+)"', r)
            main_nat = nats[0][0] if nats else "Unknown"
            flag_url = nats[0][1] if nats else ""

            # Positions
            pos_list = re.findall(r'<span class="pos pos\d+">([A-Z]+)</span>', r)
            primary_pos = pos_list[0] if pos_list else "ST"
            deduped_pos = list(dict.fromkeys(pos_list))
            positions_str = ", ".join(deduped_pos) if deduped_pos else primary_pos

            # Helper for column data
            def get_col(col_name: str) -> Optional[str]:
                m = re.search(rf'data-col="{col_name}"[^>]*>(?:<em[^>]*>)?([^<]+)', r)
                return m.group(1).strip() if m else None

            age = int(get_col("ae") or 25)
            ovr = int(get_col("oa") or 75)
            pot = int(get_col("pt") or ovr)
            best_pos = get_col("bp") or primary_pos
            value = get_col("vl") or "€0"
            wage = get_col("wg") or "€0"

            # Team
            team_m = re.search(r'<a href="/team/\d+/[^"]+">([^<]+)</a>', r)
            team_name = team_m.group(1).strip() if team_m else "Free Agent"
            team_logo_m = re.search(r'class="team"[^>]*data-src="([^"]+)"', r)
            team_logo = team_logo_m.group(1) if team_logo_m else ""

            players.append({
                "id": pid,
                "name": short_name,
                "full_name": full_name,
                "primary_pos": primary_pos,
                "positions": positions_str,
                "overall_rating": ovr,
                "potential": pot,
                "best_pos": best_pos,
                "age": age,
                "team": team_name,
                "team_logo": team_logo,
                "nationality": main_nat,
                "flag_url": flag_url,
                "value": value,
                "wage": wage,
                "avatar": avatar,
                "url": f"https://sofifa.com{link}",
                "search_text": f"{normalize_text(short_name)} {normalize_text(full_name)}",
            })
        except Exception as e:
            logger.debug("Error parsing row: %s", e)

    return players


async def fetch_sofifa_players(keyword: str = "", offset: int = 0, timeout: int = 10) -> List[Dict[str, Any]]:
    """Asynchronously scrape SoFIFA players for r=260004 in a background thread."""
    return await asyncio.to_thread(_parse_sofifa_sync, keyword=keyword, offset=offset, timeout=timeout)


def sofifa_player_embed(player: Dict[str, Any]) -> discord.Embed:
    """
    Generate a clean, focused, broadcast-style player card embed.
    Specifically displays: Photo, OVR & Potential, Positions, Age, Market Value, Wages, Club, and Link.
    """
    ovr = player.get("overall_rating", 75)
    pot = player.get("potential", ovr)
    full_name = player.get("full_name") or player.get("name", "Unknown Player")
    team = player.get("team") or "Free Agent"
    nat = player.get("nationality") or "Unknown"
    positions = player.get("positions") or player.get("primary_pos", "ST")
    age = player.get("age", 25)
    value = player.get("value", "€0")
    wage = player.get("wage", "€0")
    sofifa_url = player.get("url") or f"https://sofifa.com/player/{player.get('id', '')}"
    avatar = player.get("avatar") or ""

    # Dynamic Card Color by OVR
    if ovr >= 90:
        color = 0xF59E0B  # Elite Gold
    elif ovr >= 85:
        color = 0x10B981  # Master Emerald
    elif ovr >= 80:
        color = 0x06B6D4  # Star Cyan
    elif ovr >= 75:
        color = 0x94A3B8  # Silver
    else:
        color = 0xB45309  # Bronze

    embed = discord.Embed(
        title=f"⭐ [{ovr}] {full_name}",
        url=sofifa_url,
        description=f"🏛️ **{team}**  •  🌍 **{nat}**",
        color=color,
    )

    # Player Face Photo
    if avatar:
        embed.set_thumbnail(url=avatar)

    embed.add_field(
        name="📊 Rating & Potential",
        value=f"**{ovr} OVR** (Potential: **{pot}**)",
        inline=True,
    )
    embed.add_field(
        name="🎯 Positions",
        value=f"**{positions}**",
        inline=True,
    )
    embed.add_field(
        name="🎂 Age",
        value=f"**{age}** years old",
        inline=True,
    )
    embed.add_field(
        name="💰 Market Value",
        value=f"**{value}**",
        inline=True,
    )
    embed.add_field(
        name="💵 Weekly Wage",
        value=f"**{wage}** / week",
        inline=True,
    )
    embed.add_field(
        name="🔗 SoFIFA Profile",
        value=f"[View on SoFIFA]({sofifa_url})",
        inline=True,
    )

    embed.set_footer(
        text="EA Sports FC 26 Database • Sep 19, 2025 Update (r=260004)",
        icon_url="https://cdn.sofifa.net/favicon.ico",
    )
    return embed
