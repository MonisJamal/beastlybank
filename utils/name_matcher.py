"""
BeastlyFC Intelligent Name Matcher & Autocomplete Engine
Provides fuzzy matching, accent stripping, nickname expansion,
initial-to-full-name resolution, and Discord autocomplete suggestions
for tournament players and clubs.
"""

import difflib
import re
import unicodedata
from typing import Dict, List, Optional, Sequence, Tuple

# Known player nicknames & mononyms mapped to canonical forms
KNOWN_NICKNAMES: Dict[str, str] = {
    "cr7": "Cristiano Ronaldo",
    "r9": "Ronaldo Nazario",
    "el fenomeno": "Ronaldo Nazario",
    "kdb": "Kevin De Bruyne",
    "vini": "Vinicius Jr",
    "vini jr": "Vinicius Jr",
    "messi": "Lionel Messi",
    "leo messi": "Lionel Messi",
    "neymar": "Neymar Jr",
    "bellingham": "Jude Bellingham",
    "jude": "Jude Bellingham",
    "haaland": "Erling Haaland",
    "erling": "Erling Haaland",
    "mbappe": "Kylian Mbappe",
    "kylian": "Kylian Mbappe",
    "saka": "Bukayo Saka",
    "bukayo": "Bukayo Saka",
    "palmer": "Cole Palmer",
    "cole": "Cole Palmer",
    "kane": "Harry Kane",
    "harry": "Harry Kane",
    "wirtz": "Florian Wirtz",
    "florian": "Florian Wirtz",
    "salah": "Mohamed Salah",
    "mo salah": "Mohamed Salah",
    "musiala": "Jamal Musiala",
    "jamal": "Jamal Musiala",
    "davies": "Alphonso Davies",
    "alphonso": "Alphonso Davies",
    "pogba": "Paul Pogba",
    "paul": "Paul Pogba",
    "dybala": "Paulo Dybala",
    "paulo": "Paulo Dybala",
    "gyokeres": "Viktor Gyokeres",
    "viktor": "Viktor Gyokeres",
    "calhanoglu": "Hakan Calhanoglu",
    "militao": "Eder Militao",
    "dembele": "Ousmane Dembele",
    "ousmane": "Ousmane Dembele",
    "de jong": "Frenkie de Jong",
    "frenkie": "Frenkie de Jong",
    "cancelo": "Joao Cancelo",
    "joao": "Joao Cancelo",
    "ronaldo": "Cristiano Ronaldo",
    "cristiano": "Cristiano Ronaldo",
    "son": "Son Heung-min",
    "heung min son": "Son Heung-min",
    "son heung min": "Son Heung-min",
    "rodri": "Rodri",
    "pedri": "Pedri",
    "gavi": "Gavi",
    "alisson": "Alisson",
    "ederson": "Ederson",
    "courtois": "Thibaut Courtois",
    "valverde": "Federico Valverde",
    "fede valverde": "Federico Valverde",
    "tchouameni": "Aurelien Tchouameni",
    "camavinga": "Eduardo Camavinga",
    "lewandowski": "Robert Lewandowski",
    "lewa": "Robert Lewandowski",
    "benzema": "Karim Benzema",
    "kante": "NGolo Kante",
    "mane": "Sadio Mane",
    "suarez": "Luis Suarez",
    "bruno": "Bruno Fernandes",
    "bernardo": "Bernardo Silva",
    "van dijk": "Virgil van Dijk",
    "vvd": "Virgil van Dijk",
    "virgil": "Virgil van Dijk",
    "saliba": "William Saliba",
    "rice": "Declan Rice",
    "odegaard": "Martin Odegaard",
}

# Full name expansions for initial-style names commonly in tournament data
PLAYER_EXPANSIONS: Dict[str, List[str]] = {
    "E. Haaland": ["Erling Haaland", "Erling Braut Haaland", "Haaland"],
    "K. Mbappé": ["Kylian Mbappe", "Kylian Mbappé", "Mbappe", "Mbappé"],
    "B. Saka": ["Bukayo Saka", "Saka"],
    "C. Palmer": ["Cole Palmer", "Palmer", "Cold Palmer"],
    "H. Kane": ["Harry Kane", "Kane"],
    "F. Wirtz": ["Florian Wirtz", "Wirtz"],
    "M. Salah": ["Mohamed Salah", "Mo Salah", "Salah"],
    "J. Musiala": ["Jamal Musiala", "Musiala"],
    "A. Davies": ["Alphonso Davies", "Davies"],
    "A. Bastoni": ["Alessandro Bastoni", "Bastoni"],
    "A. Hakimi": ["Achraf Hakimi", "Hakimi"],
    "A. Laporte": ["Aymeric Laporte", "Laporte"],
    "B. Mbeumo": ["Bryan Mbeumo", "Mbeumo"],
    "D. Alaba": ["David Alaba", "Alaba"],
    "D. Burn": ["Dan Burn", "Burn"],
    "D. Muñoz": ["Daniel Munoz", "Daniel Muñoz", "Munoz", "Muñoz"],
    "E. Anderson": ["Elliot Anderson", "Anderson"],
    "E. Fernández": ["Enzo Fernandez", "Enzo Fernández", "Fernandez", "Fernández"],
    "F. Dimarco": ["Federico Dimarco", "Dimarco"],
    "F. de Jong": ["Frenkie de Jong", "De Jong"],
    "H. Maguire": ["Harry Maguire", "Maguire"],
    "H. Çalhanoğlu": ["Hakan Calhanoglu", "Hakan Çalhanoğlu", "Calhanoglu", "Çalhanoğlu"],
    "J. Kimmich": ["Joshua Kimmich", "Kimmich"],
    "L. Díaz": ["Luis Diaz", "Luis Díaz", "Diaz", "Díaz"],
    "M. Greenwood": ["Mason Greenwood", "Greenwood"],
    "M. Olise": ["Michael Olise", "Olise"],
    "M. de Ligt": ["Matthijs de Ligt", "De Ligt"],
    "O. Dembélé": ["Ousmane Dembele", "Ousmane Dembélé", "Dembele", "Dembélé"],
    "P. Dybala": ["Paulo Dybala", "Dybala"],
    "P. Pogba": ["Paul Pogba", "Pogba"],
    "V. Gyökeres": ["Viktor Gyokeres", "Viktor Gyökeres", "Gyokeres", "Gyökeres"],
    "X. Simons": ["Xavi Simons", "Simons"],
    "Éder Militão": ["Eder Militao", "Éder Militão", "Militao", "Militão"],
    "Ronaldo Nazario": ["Ronaldo", "R9", "Fenomeno", "Ronaldo Nazário", "Nazario"],
    "Bruno Fernandes": ["Bruno", "Fernandes"],
    "Bruno Guimarães": ["Bruno Guimaraes", "Guimaraes", "Guimarães"],
    "Lamine Yamal": ["Yamal", "Lamine"],
}

# Club aliases & abbreviations
CLUB_ALIASES: Dict[str, str] = {
    "psg": "Paris Saint-Germain",
    "paris": "Paris Saint-Germain",
    "man city": "Manchester City",
    "mancity": "Manchester City",
    "mcfc": "Manchester City",
    "city": "Manchester City",
    "man utd": "Manchester United",
    "manutd": "Manchester United",
    "mufc": "Manchester United",
    "united": "Manchester United",
    "spurs": "Tottenham Hotspur",
    "tottenham": "Tottenham Hotspur",
    "atleti": "Atlético Madrid",
    "atletico": "Atlético Madrid",
    "atm": "Atlético Madrid",
    "bayern": "FC Bayern München",
    "munich": "FC Bayern München",
    "bayern munich": "FC Bayern München",
    "fc bayern": "FC Bayern München",
    "barca": "FC Barcelona",
    "barcelona": "FC Barcelona",
    "bvb": "Borussia Dortmund",
    "dortmund": "Borussia Dortmund",
    "real": "Real Madrid",
    "madrid": "Real Madrid",
    "inter": "Inter",
    "inter milan": "Inter",
    "juve": "Juventus",
    "juventus": "Juventus",
    "newcastle": "Newcastle United",
    "toon": "Newcastle United",
    "galatasaray": "Galatasaray SK",
    "gala": "Galatasaray SK",
    "arsenal": "Arsenal",
    "gunners": "Arsenal",
    "chelsea": "Chelsea",
    "blues": "Chelsea",
    "liverpool": "Liverpool",
    "reds": "Liverpool",
    "milan": "Milan",
    "ac milan": "Milan",
    "everton": "Everton",
    "como": "Como",
}


def normalize_text(text: str) -> str:
    """
    Normalize text: strip accents/diacritics, lowercase, remove punctuation, collapse spaces.
    e.g. 'K. Mbappé' -> 'k mbappe'
    e.g. 'Atlético Madrid' -> 'atletico madrid'
    """
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    ascii_text = "".join(c for c in norm if not unicodedata.combining(c))
    cleaned = re.sub(r"[^\w\s]", " ", ascii_text).lower()
    return re.sub(r"\s+", " ", cleaned).strip()


def match_player_name(
    query: str,
    available_players: Sequence[str],
) -> Tuple[Optional[str], float, List[str]]:
    """
    Intelligently match a user-input player name against a list of available players.
    Handles:
    - Exact match & case insensitivity
    - Accents & diacritics (Mbappé -> mbappe)
    - Full name to initial-style matching ('Erling Haaland' -> 'E. Haaland')
    - Surname-only / mononym matching ('Haaland' -> 'E. Haaland')
    - Known nicknames & expansions ('r9' -> 'Ronaldo Nazario')
    - Typos / fuzzy matching ('Haland' -> 'E. Haaland')

    Returns:
        (best_match, best_score, suggestions)
        best_match is None if confidence < 0.70.
        suggestions contains up to 3 close candidate names.
    """
    if not query or not query.strip():
        return None, 0.0, []

    q_raw = query.strip()
    q_norm = normalize_text(q_raw)
    if not q_norm:
        return None, 0.0, []

    # Check known nicknames
    if q_norm in KNOWN_NICKNAMES:
        target_name = KNOWN_NICKNAMES[q_norm]
        q_norm = normalize_text(target_name)

    q_words = q_norm.split()
    scored_candidates: List[Tuple[float, str]] = []

    for player in available_players:
        if not player:
            continue
        p_norm = normalize_text(player)
        p_words = p_norm.split()

        # 1. Exact raw or exact normalized match
        if q_raw.lower() == player.lower() or q_norm == p_norm:
            return player, 1.0, []

        score = 0.0

        # Check pre-mapped expansions (e.g. "E. Haaland" expansions include "Erling Haaland")
        expansions = PLAYER_EXPANSIONS.get(player, [])
        for exp in expansions:
            exp_norm = normalize_text(exp)
            if q_norm == exp_norm:
                return player, 1.0, []
            if q_norm in exp_norm or exp_norm in q_norm:
                score = max(score, 0.95)

        # 2. Substring matching
        if q_norm in p_norm:
            score = max(score, 0.92)
        elif p_norm in q_norm:
            score = max(score, 0.90)

        # 3. Token / Surname / Initial matching
        # Scenario A: User input has 2+ words (e.g. "Erling Haaland"), DB has "E. Haaland"
        if len(q_words) >= 2 and len(p_words) >= 2:
            # Match surname
            if q_words[-1] == p_words[-1]:
                # Check if first initial matches
                if q_words[0][0] == p_words[0][0]:
                    score = max(score, 0.98)
                else:
                    score = max(score, 0.85)

        # Scenario B: User entered single word (e.g. "Haaland", "Saka", "Wirtz")
        if len(q_words) == 1 and len(p_words) >= 2:
            if q_words[0] == p_words[-1]:  # Matches surname
                score = max(score, 0.95)
            elif q_words[0] == p_words[0]:  # Matches first word
                score = max(score, 0.80)

        # Scenario C: User entered initial style "E Haaland" or "E. Haaland", DB has full or partial
        if len(q_words) >= 2 and len(p_words) >= 2:
            if len(q_words[0]) == 1 and q_words[0] == p_words[0][0] and q_words[-1] == p_words[-1]:
                score = max(score, 0.98)

        # 4. Fuzzy string similarity via difflib
        sim_full = difflib.SequenceMatcher(None, q_norm, p_norm).ratio()
        sim_surname = 0.0
        if q_words and p_words and len(q_words[-1]) >= 4 and len(p_words[-1]) >= 4:
            sim_surname = difflib.SequenceMatcher(None, q_words[-1], p_words[-1]).ratio()

        fuzzy_score = max(sim_full, sim_surname * 0.92)
        score = max(score, fuzzy_score)

        if score >= 0.40:
            scored_candidates.append((score, player))

    # Sort descending by score
    scored_candidates.sort(key=lambda x: x[0], reverse=True)

    if scored_candidates:
        best_score, best_player = scored_candidates[0]
        # High-confidence threshold
        if best_score >= 0.70:
            suggestions = [c[1] for c in scored_candidates[1:4] if c[1] != best_player]
            return best_player, best_score, suggestions
        else:
            suggestions = [c[1] for c in scored_candidates[:3]]
            return None, best_score, suggestions

    return None, 0.0, []


def match_club_name(query: str, available_clubs: Sequence[str]) -> Tuple[Optional[str], List[str]]:
    """
    Intelligently match a club name against available tournament clubs.
    Handles aliases (psg, man city, atleti, bayern, etc.), accent stripping, and fuzzy matches.
    """
    if not query or not query.strip():
        return None, []

    q_raw = query.strip()
    q_norm = normalize_text(q_raw)
    if not q_norm:
        return None, []

    # 1. Check known aliases
    if q_norm in CLUB_ALIASES:
        target_name = CLUB_ALIASES[q_norm]
        for c in available_clubs:
            if normalize_text(c) == normalize_text(target_name):
                return c, []

    # 2. Exact match
    for c in available_clubs:
        if q_raw.lower() == c.lower() or q_norm == normalize_text(c):
            return c, []

    # 3. Substring match
    for c in available_clubs:
        c_norm = normalize_text(c)
        if q_norm in c_norm or c_norm in q_norm:
            return c, []

    # 4. Fuzzy match
    club_map = {normalize_text(c): c for c in available_clubs}
    close_matches = difflib.get_close_matches(q_norm, list(club_map.keys()), n=3, cutoff=0.55)
    if close_matches:
        best_club = club_map[close_matches[0]]
        suggestions = [club_map[m] for m in close_matches[1:]]
        return best_club, suggestions

    return None, []


def autocomplete_players_search(
    query: str,
    available_players_with_teams: Sequence[Tuple[str, str]],
    limit: int = 25,
) -> List[Tuple[str, str]]:
    """
    Autocomplete search for Discord slash command choices.
    Returns list of (player_name, team_name) sorted by match relevance.
    """
    clean = normalize_text(query)
    if not clean:
        return list(available_players_with_teams)[:limit]

    # Check known nicknames
    alias_target = KNOWN_NICKNAMES.get(clean)
    if alias_target:
        clean = normalize_text(alias_target)

    scored: List[Tuple[int, str, str]] = []
    for p_name, team in available_players_with_teams:
        p_norm = normalize_text(p_name)
        p_words = p_norm.split()

        all_variants = [p_name] + PLAYER_EXPANSIONS.get(p_name, [])
        priority = 999

        for var in all_variants:
            v_norm = normalize_text(var)
            v_words = v_norm.split()
            if v_norm.startswith(clean):
                priority = min(priority, 1)
            elif any(w.startswith(clean) for w in v_words):
                priority = min(priority, 2)
            elif clean in v_norm:
                priority = min(priority, 3)

        if priority > 3 and len(clean) >= 3:
            # Fuzzy match on surname
            q_words = clean.split()
            if any(w in p_norm for w in q_words):
                priority = min(priority, 4)

        if priority <= 4:
            scored.append((priority, p_name, team))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [(r[1], r[2]) for r in scored[:limit]]


def autocomplete_clubs_search(
    query: str,
    available_clubs: Sequence[str],
    limit: int = 25,
) -> List[str]:
    """
    Autocomplete search for Discord club parameter.
    Returns list of club names.
    """
    clean = normalize_text(query)
    if not clean:
        return list(available_clubs)[:limit]

    # Check alias
    if clean in CLUB_ALIASES:
        target = CLUB_ALIASES[clean]
        for c in available_clubs:
            if normalize_text(c) == normalize_text(target):
                return [c] + [x for x in available_clubs if x != c][: limit - 1]

    results: List[Tuple[int, str]] = []
    for c in available_clubs:
        c_norm = normalize_text(c)
        c_words = c_norm.split()
        priority = 999
        if c_norm.startswith(clean):
            priority = 1
        elif any(w.startswith(clean) for w in c_words):
            priority = 2
        elif clean in c_norm:
            priority = 3

        if priority <= 3:
            results.append((priority, c))

    results.sort(key=lambda x: (x[0], x[1]))
    return [r[1] for r in results[:limit]]
