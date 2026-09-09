"""
MatchSimulator Cup & Tournament Parser
Extracts fixtures, scores, league standings, clean sheets, disciplinary records,
and computes player ratings and awards from matchsimulator.com tournament pages.
"""

import json
import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

logger = logging.getLogger("BeastlyBank.MatchParser")


def parse_matchsimulator_html(html_text: str) -> Dict[str, Any]:
    """Parse complete tournament data from matchsimulator.com HTML page."""
    soup = BeautifulSoup(html_text, "html.parser") if BeautifulSoup else None

    # 1. Title and basic metadata
    if soup:
        title_elem = soup.find("h1", class_="page-header-title")
        tournament_name = title_elem.get_text(strip=True) if title_elem else "Tournament"

        subtitle_elem = soup.find("div", class_="page-header-subtitle")
        season_subtitle = subtitle_elem.get_text(" ", strip=True) if subtitle_elem else ""
    else:
        title_m = re.search(r'<h1[^>]*class=["\'][^"\']*page-header-title[^"\']*["\'][^>]*>(.*?)</h1>', html_text, re.DOTALL)
        raw_t = re.sub(r'<[^>]+>', '', title_m.group(1)) if title_m else "Tournament"
        tournament_name = re.sub(r'<!--.*?-->', '', raw_t).strip()
        sub_m = re.search(r'<div[^>]*class=["\'][^"\']*page-header-subtitle[^"\']*["\'][^>]*>(.*?)</div>', html_text, re.DOTALL)
        raw_s = re.sub(r'<[^>]+>', '', sub_m.group(1)) if sub_m else ""
        season_subtitle = re.sub(r'<!--.*?-->', '', raw_s).strip()

    # 2. Extract fixturesInfo JSON from JavaScript
    fixtures_info = {}
    pattern = r"let\s+fixturesInfo\s*=\s*(\{.*?\});"
    fixtures_match = re.search(pattern, html_text, re.DOTALL)
    if fixtures_match:
        try:
            fixtures_info = json.loads(fixtures_match.group(1))
        except Exception as e:
            logger.warning("Failed parsing fixturesInfo JSON: %s", e)

    raw_fixtures = fixtures_info.get("fixtures", {})
    highest_matchday = fixtures_info.get("highest_matchday") or (len(raw_fixtures) if raw_fixtures else 0)
    winner_data = fixtures_info.get("winner") or {}

    normalized_fixtures: Dict[int, List[Dict[str, Any]]] = {}
    all_fixtures_flat: List[Dict[str, Any]] = []

    for md_str, matches in raw_fixtures.items():
        try:
            md_num = int(md_str)
        except ValueError:
            md_num = 1

        normalized_fixtures[md_num] = []
        for m in matches:
            fixture_entry = {
                "matchday": md_num,
                "match_uid": m.get("match_uid", ""),
                "home_team_id": str(m.get("homeTeamId", "")),
                "away_team_id": str(m.get("awayTeamId", "")),
                "home_team_name": m.get("home_team_name", "Home Team").strip(),
                "away_team_name": m.get("away_team_name", "Away Team").strip(),
                "home_team_short": m.get("home_team_name_short", "").strip(),
                "away_team_short": m.get("away_team_name_short", "").strip(),
                "goals_home": m.get("goals_home_team", 0),
                "goals_away": m.get("goals_away_team", 0),
                "penalties_home": m.get("penalties_home_team", 0),
                "penalties_away": m.get("penalties_away_team", 0),
                "is_finished": bool(m.get("is_finished", False)),
                "replay_exists": bool(m.get("replay_exists", 0)),
            }
            normalized_fixtures[md_num].append(fixture_entry)
            all_fixtures_flat.append(fixture_entry)

    # 3. Calculate League Standings & Clean Sheets from finished fixtures
    table = defaultdict(lambda: {
        "team_id": "",
        "name": "",
        "short": "",
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": 0,
        "goals_against": 0,
        "clean_sheets": 0,
        "points": 0,
    })

    for f in all_fixtures_flat:
        if not f["is_finished"]:
            continue
        h_id = f["home_team_id"]
        a_id = f["away_team_id"]
        h_name = f["home_team_name"]
        a_name = f["away_team_name"]
        h_short = f["home_team_short"]
        a_short = f["away_team_short"]
        h_g = f["goals_home"]
        a_g = f["goals_away"]

        table[h_id]["team_id"] = h_id
        table[h_id]["name"] = h_name
        table[h_id]["short"] = h_short
        table[a_id]["team_id"] = a_id
        table[a_id]["name"] = a_name
        table[a_id]["short"] = a_short

        table[h_id]["played"] += 1
        table[a_id]["played"] += 1
        table[h_id]["goals_for"] += h_g
        table[h_id]["goals_against"] += a_g
        table[a_id]["goals_for"] += a_g
        table[a_id]["goals_against"] += h_g

        if a_g == 0:
            table[h_id]["clean_sheets"] += 1
        if h_g == 0:
            table[a_id]["clean_sheets"] += 1

        if h_g > a_g:
            table[h_id]["won"] += 1
            table[h_id]["points"] += 3
            table[a_id]["lost"] += 1
        elif h_g < a_g:
            table[a_id]["won"] += 1
            table[a_id]["points"] += 3
            table[h_id]["lost"] += 1
        else:
            table[h_id]["drawn"] += 1
            table[h_id]["points"] += 1
            table[a_id]["drawn"] += 1
            table[a_id]["points"] += 1

    standings_list = []
    sorted_teams = sorted(
        table.values(),
        key=lambda t: (t["points"], t["goals_for"] - t["goals_against"], t["goals_for"]),
        reverse=True,
    )
    for rank, t in enumerate(sorted_teams, start=1):
        gd = t["goals_for"] - t["goals_against"]
        standings_list.append({
            "rank": rank,
            "team_id": t["team_id"],
            "name": t["name"],
            "short": t["short"],
            "played": t["played"],
            "won": t["won"],
            "drawn": t["drawn"],
            "lost": t["lost"],
            "goals_for": t["goals_for"],
            "goals_against": t["goals_against"],
            "goal_difference": gd,
            "clean_sheets": t["clean_sheets"],
            "points": t["points"],
        })

    # 4. Extract Player Stats from HTML Tables
    def parse_stat_table(container_id: str) -> List[Dict[str, Any]]:
        results = []
        if soup:
            div = soup.find("div", id=container_id)
            if not div:
                return results
            rows = div.find_all("tr")
            for row in rows:
                cols = row.find_all("td")
                if len(cols) >= 4:
                    try:
                        rank_txt = cols[0].get_text(strip=True)
                        p_name = cols[1].get_text(strip=True)
                        t_name = cols[2].get_text(strip=True)
                        val_txt = cols[3].get_text(strip=True)
                        val = int(re.sub(r"[^0-9]", "", val_txt)) if val_txt else 0
                        results.append({
                            "rank": int(rank_txt) if rank_txt.isdigit() else len(results) + 1,
                            "player_name": p_name,
                            "team_name": t_name,
                            "stat_value": val,
                        })
                    except Exception:
                        continue
        else:
            div_m = re.search(rf'id=["\']{container_id}["\'][^>]*>(.*?)</div>\s*</div>', html_text, re.DOTALL)
            if div_m:
                row_matches = re.findall(r'<tr[^>]*>(.*?)</tr>', div_m.group(1), re.DOTALL)
                for r in row_matches:
                    cols = [re.sub(r'<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', r, re.DOTALL)]
                    if len(cols) >= 4:
                        try:
                            val = int(re.sub(r"[^0-9]", "", cols[3])) if cols[3] else 0
                            results.append({
                                "rank": int(cols[0]) if cols[0].isdigit() else len(results) + 1,
                                "player_name": cols[1],
                                "team_name": cols[2],
                                "stat_value": val,
                            })
                        except Exception:
                            continue
        return results

    top_goals = parse_stat_table("playerStatsGoals")
    top_assists = parse_stat_table("playerStatsAssists")
    top_own_goals = parse_stat_table("playerStatsOwnGoals")
    top_yellow_cards = parse_stat_table("playerStatsYellowCards")
    top_red_cards = parse_stat_table("playerStatsRedCards")

    # 5. Extract Player Availability
    suspensions = []
    injuries = []
    if soup:
        susp_div = soup.find("div", id="availabilityTypeSuspensions")
        if susp_div:
            for r in susp_div.find_all("tr"):
                cols = r.find_all("td")
                if len(cols) >= 3:
                    suspensions.append({
                        "player_name": cols[0].get_text(strip=True),
                        "team_name": cols[1].get_text(strip=True),
                        "until": cols[2].get_text(strip=True),
                    })

        inj_div = soup.find("div", id="availabilityTypeInjuries")
        if inj_div:
            for r in inj_div.find_all("tr"):
                cols = r.find_all("td")
                if len(cols) >= 4:
                    injuries.append({
                        "player_name": cols[0].get_text(strip=True),
                        "team_name": cols[1].get_text(strip=True),
                        "until": cols[2].get_text(strip=True),
                        "injury": cols[3].get_text(strip=True),
                    })

    # 6. Aggregate Comprehensive Player Profiles & Calculate Ratings
    players_map = {}

    def get_or_create_player(name: str, team: str) -> Dict[str, Any]:
        key = f"{name.strip().lower()}::{team.strip().lower()}"
        if key not in players_map:
            players_map[key] = {
                "player_name": name.strip(),
                "team_name": team.strip(),
                "goals": 0,
                "assists": 0,
                "own_goals": 0,
                "yellow_cards": 0,
                "red_cards": 0,
                "clean_sheets": 0,
                "matches_played": 38,
                "minutes_played": 38 * 90,
                "rating": 6.5,
            }
        return players_map[key]

    for g in top_goals:
        p = get_or_create_player(g["player_name"], g["team_name"])
        p["goals"] = g["stat_value"]

    for a in top_assists:
        p = get_or_create_player(a["player_name"], a["team_name"])
        p["assists"] = a["stat_value"]

    for og in top_own_goals:
        p = get_or_create_player(og["player_name"], og["team_name"])
        p["own_goals"] = og["stat_value"]

    for y in top_yellow_cards:
        p = get_or_create_player(y["player_name"], y["team_name"])
        p["yellow_cards"] = y["stat_value"]

    for r in top_red_cards:
        p = get_or_create_player(r["player_name"], r["team_name"])
        p["red_cards"] = r["stat_value"]

    team_cs_map = {t["name"].lower(): t["clean_sheets"] for t in standings_list}
    team_pts_map = {t["name"].lower(): t["points"] for t in standings_list}

    for p in players_map.values():
        t_name = p["team_name"].lower()
        cs = team_cs_map.get(t_name, 0)
        p["clean_sheets"] = cs

        team_pts = team_pts_map.get(t_name, 40)
        team_success = (team_pts / 80.0) * 0.8

        calculated_rating = (
            6.20
            + (p["goals"] * 0.075)
            + (p["assists"] * 0.055)
            + (team_success)
            - (p["yellow_cards"] * 0.015)
            - (p["red_cards"] * 0.06)
            - (p["own_goals"] * 0.05)
        )
        p["rating"] = round(min(9.5, max(6.0, calculated_rating)), 2)

    # 7. Season Awards
    champion = winner_data.get("name") or (standings_list[0]["name"] if standings_list else "Unknown")
    runner_up = standings_list[1]["name"] if len(standings_list) > 1 else "Unknown"

    golden_boot = top_goals[0] if top_goals else None
    playmaker = top_assists[0] if top_assists else None

    sorted_by_cs = sorted(standings_list, key=lambda t: t["clean_sheets"], reverse=True)
    golden_glove = sorted_by_cs[0] if sorted_by_cs else None

    all_players_rated = sorted(players_map.values(), key=lambda p: p["rating"], reverse=True)
    mvp_player = all_players_rated[0] if all_players_rated else None

    return {
        "tournament_name": tournament_name,
        "season_subtitle": season_subtitle,
        "highest_matchday": highest_matchday,
        "champion": champion,
        "runner_up": runner_up,
        "winner_data": winner_data,
        "standings": standings_list,
        "fixtures_by_matchday": normalized_fixtures,
        "total_fixtures": len(all_fixtures_flat),
        "player_stats": {
            "goals": top_goals,
            "assists": top_assists,
            "own_goals": top_own_goals,
            "yellow_cards": top_yellow_cards,
            "red_cards": top_red_cards,
            "all_players": list(players_map.values()),
        },
        "availability": {
            "suspensions": suspensions,
            "injuries": injuries,
        },
        "awards": {
            "champion": champion,
            "runner_up": runner_up,
            "golden_boot": golden_boot,
            "playmaker": playmaker,
            "golden_glove": {
                "team_name": golden_glove["name"] if golden_glove else "None",
                "clean_sheets": golden_glove["clean_sheets"] if golden_glove else 0,
            },
            "mvp": mvp_player,
        },
    }


async def fetch_tournament_html(
    url: str,
    proxy_api_key: Optional[str] = None,
    proxy_service: str = "scraperapi",
) -> Tuple[bool, str, str]:
    """
    Fetch tournament HTML from matchsimulator.com.
    If proxy_api_key is set, routes via ScraperAPI/ZenRows to bypass Cloudflare Turnstile.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    target_url = url
    if proxy_api_key:
        if proxy_service == "scraperapi":
            target_url = f"http://api.scraperapi.com?api_key={proxy_api_key}&url={url}"
        elif proxy_service == "zenrows":
            target_url = f"https://api.zenrows.com/v1/?apikey={proxy_api_key}&url={url}&js_render=true"

    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(target_url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    if "Just a moment..." in text or "challenges.cloudflare.com" in text:
                        return (
                            False,
                            "Cloudflare Turnstile challenge detected. Please configure a scraper proxy key or use `/matches import [file]`.",
                            "",
                        )
                    return True, "Success", text
                elif resp.status == 403:
                    return (
                        False,
                        "Cloudflare 403 Forbidden. Direct server scraping is blocked by Cloudflare. Please use `/matches import` with your saved `.html` file, or set up a scraper proxy key.",
                        "",
                    )
                else:
                    return False, f"Server returned HTTP status {resp.status}.", ""
    except Exception as e:
        logger.error("Error fetching tournament URL: %s", e)
        return False, f"Network error: {str(e)}", ""
