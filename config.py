"""
Configuration and constants for BeastlyBank (BeastlyFC Discord Bot).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# Discord Bot Token (sanitize quotes and whitespace from cloud environment)
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip().strip("'\"")

# Server Lock: BeastlyFC Guild ID
# If set, all slash commands and interactions are restricted strictly to this Guild ID.
_guild_id_raw = os.getenv("BEASTLYFC_GUILD_ID", "").strip()
BEASTLYFC_GUILD_ID = int(_guild_id_raw) if _guild_id_raw.isdigit() else 0

# Staff and Banker Roles
_banker_ids_raw = os.getenv("BANKER_ROLE_IDS", "").split(",")
BANKER_ROLE_IDS = [int(r.strip()) for r in _banker_ids_raw if r.strip().isdigit()]

_admin_ids_raw = os.getenv("ADMIN_ROLE_IDS", "").split(",")
ADMIN_ROLE_IDS = [int(r.strip()) for r in _admin_ids_raw if r.strip().isdigit()]

# Database Path
DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "beastlybank.db"))

# Brand Identity
BOT_NAME = "BeastlyBank"
SERVER_NAME = "BeastlyFC"

# Branding Colors (Hex Int)
COLOR_BEASTLY_GOLD = 0xF5A623  # #F5A623 - Official Beastly Gold
COLOR_PITCH_GREEN = 0x0A5C36   # #0A5C36 - BeastlyFC Stadium Pitch
COLOR_SUCCESS = 0x2ECC71       # #2ECC71 - Vibrant Green
COLOR_ERROR = 0xE74C3C         # #E74C3C - Vibrant Red
COLOR_INFO = 0x3498DB          # #3498DB - Light Blue

# Currency Definitions
CURRENCIES = {
    "cash": {
        "name": "Cash",
        "emoji": "💵",
        "description": "Your main server currency for transfers, giveaways, and club fees.",
    },
    "points": {
        "name": "Community Points",
        "emoji": "⭐",
        "description": "Earned through server activities, match events, and rewards.",
    },
    "tokens": {
        "name": "Training Tokens",
        "emoji": "🎟️",
        "description": "Used for player/team training, stat upgrades, and club clinics.",
    },
}


def parse_amount(val_str: str):
    """
    Parses human currency strings including:
    - Scientific notation: 26e6 (26M), 3e7 (30M)
    - Suffix multipliers: 26m, 500k, 1b
    - Plain numbers: 1000000, 26,000,000, 0
    Returns integer amount if >= 0, or None if invalid.
    """
    s = str(val_str).strip().replace(",", "").lower()
    if not s:
        return None
    if "e" in s:
        try:
            num = float(s)
            return int(num) if num >= 0 else None
        except ValueError:
            pass
    if s.endswith("k"):
        try:
            num = float(s[:-1]) * 1_000
            return int(num) if num >= 0 else None
        except ValueError:
            pass
    elif s.endswith("m"):
        try:
            num = float(s[:-1]) * 1_000_000
            return int(num) if num >= 0 else None
        except ValueError:
            pass
    elif s.endswith("b"):
        try:
            num = float(s[:-1]) * 1_000_000_000
            return int(num) if num >= 0 else None
        except ValueError:
            pass
    try:
        val = int(float(s))
        return val if val >= 0 else None
    except ValueError:
        return None


# Football Formations Configuration
SUPPORTED_FORMATIONS = {
    # ── 4-Back Formations ──
    "4-3-3": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Attack", "desc": "Balanced Wing Attack (4 DEF, 3 MID, 3 FWD)"},
    "4-4-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-4-2 Classic", "desc": "Traditional Flat (4 DEF, 4 MID, 2 ST)"},
    "4-2-3-1": {"def": 4, "mid": 5, "fwd": 1, "name": "4-2-3-1 Wide", "desc": "Double Pivot Control (4 DEF, 2 CDM, 3 CAM, 1 ST)"},
    "4-1-4-1": {"def": 4, "mid": 5, "fwd": 1, "name": "4-1-4-1 Anchor", "desc": "Single CDM Shield (4 DEF, 1 CDM, 4 MID, 1 ST)"},
    "4-5-1": {"def": 4, "mid": 5, "fwd": 1, "name": "4-5-1 Overload", "desc": "Packed Midfield (4 DEF, 5 MID, 1 ST)"},
    "4-1-3-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-3-2 Narrow", "desc": "CDM + Three Behind Two (4 DEF, 1 CDM, 3 MID, 2 ST)"},
    "4-3-2-1": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-2-1 Christmas Tree", "desc": "Dual Number 10s (4 DEF, 3 MID, 2 CAM, 1 ST)"},
    "4-2-2-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-2-2-2 Box", "desc": "Dual CDMs & CAMs (4 DEF, 2 CDM, 2 CAM, 2 ST)"},
    "4-1-2-1-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-2-1-2 Diamond", "desc": "Central Diamond (4 DEF, 1 CDM, 2 CM, 1 CAM, 2 ST)"},
    # ── 3-Back Formations ──
    "3-5-2": {"def": 3, "mid": 5, "fwd": 2, "name": "3-5-2 Wingback", "desc": "Midfield Dominance (3 CB, 5 MID, 2 ST)"},
    "3-4-3": {"def": 3, "mid": 4, "fwd": 3, "name": "3-4-3 All-Out Attack", "desc": "High Press Attack (3 CB, 4 MID, 3 FWD)"},
    "3-4-1-2": {"def": 3, "mid": 5, "fwd": 2, "name": "3-4-1-2 Playmaker", "desc": "CAM Playmaker (3 CB, 4 MID, 1 CAM, 2 ST)"},
    "3-4-2-1": {"def": 3, "mid": 4, "fwd": 3, "name": "3-4-2-1 False Nine", "desc": "Dual CAMs Behind Striker (3 CB, 4 MID, 2 CAM, 1 ST)"},
    "3-6-1": {"def": 3, "mid": 6, "fwd": 1, "name": "3-6-1 Ultra Midfield", "desc": "Maximum Midfield Control (3 CB, 6 MID, 1 ST)"},
    # ── 5-Back Formations ──
    "5-3-2": {"def": 5, "mid": 3, "fwd": 2, "name": "5-3-2 Solid Wall", "desc": "Defensive Fortress (5 DEF, 3 MID, 2 ST)"},
    "5-4-1": {"def": 5, "mid": 4, "fwd": 1, "name": "5-4-1 Low Block", "desc": "Deep Defensive Block (5 DEF, 4 MID, 1 ST)"},
    "5-2-1-2": {"def": 5, "mid": 3, "fwd": 2, "name": "5-2-1-2 Narrow Counter", "desc": "Central CAM Behind Two (5 DEF, 2 CM, 1 CAM, 2 ST)"},
    "5-2-3": {"def": 5, "mid": 2, "fwd": 3, "name": "5-2-3 Counter", "desc": "Counter-Attack (5 DEF, 2 MID, 3 FWD)"},
}

# Position Categories
POSITION_CATEGORIES = {
    "GK": "Goalkeeper",
    "CB": "Defense",
    "LB": "Defense",
    "RB": "Defense",
    "LWB": "Defense",
    "RWB": "Defense",
    "CDM": "Midfield",
    "CM": "Midfield",
    "CAM": "Midfield",
    "LM": "Midfield",
    "RM": "Midfield",
    "LW": "Attack",
    "RW": "Attack",
    "ST": "Attack",
    "CF": "Attack",
}
VALID_POSITIONS = list(POSITION_CATEGORIES.keys())
