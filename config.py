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


# Default club formation (must exist in SUPPORTED_FORMATIONS)
DEFAULT_FORMATION = "4-3-3 Balanced"

# Football Formations Configuration (EA FC-style names as keys)
SUPPORTED_FORMATIONS = {
    # ── 3-Back ──
    "3-1-4-2": {"def": 3, "mid": 5, "fwd": 2, "name": "3-1-4-2", "desc": "CDM shield + flat four midfield behind two (3 DEF, 5 MID, 2 FWD)"},
    "3-2-4-1": {"def": 3, "mid": 6, "fwd": 1, "name": "3-2-4-1", "desc": "Double pivot with four advanced mids (3 DEF, 6 MID, 1 FWD)"},
    "3-4-1-2": {"def": 3, "mid": 5, "fwd": 2, "name": "3-4-1-2", "desc": "CAM playmaker behind dual strikers (3 DEF, 5 MID, 2 FWD)"},
    "3-4-2-1": {"def": 3, "mid": 4, "fwd": 3, "name": "3-4-2-1", "desc": "Dual CAMs supporting a lone striker (3 DEF, 4 MID, 3 FWD)"},
    "3-4-3 Diamond": {"def": 3, "mid": 4, "fwd": 3, "name": "3-4-3 Diamond", "desc": "Diamond midfield with front three (3 DEF, 4 MID, 3 FWD)"},
    "3-4-3 Flat": {"def": 3, "mid": 4, "fwd": 3, "name": "3-4-3 Flat", "desc": "Flat four midfield with front three (3 DEF, 4 MID, 3 FWD)"},
    "3-5-1-1": {"def": 3, "mid": 6, "fwd": 1, "name": "3-5-1-1", "desc": "Packed midfield with second striker (3 DEF, 6 MID, 1 FWD)"},
    "3-5-2": {"def": 3, "mid": 5, "fwd": 2, "name": "3-5-2", "desc": "Wingback midfield dominance (3 DEF, 5 MID, 2 FWD)"},
    # ── 4-Back ──
    "4-1-2-1-2 Narrow": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-2-1-2 Narrow", "desc": "Narrow central diamond (4 DEF, 4 MID, 2 FWD)"},
    "4-1-2-1-2 Wide": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-2-1-2 Wide", "desc": "Wide diamond midfield (4 DEF, 4 MID, 2 FWD)"},
    "4-1-3-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-3-2", "desc": "CDM + three midfielders behind two (4 DEF, 4 MID, 2 FWD)"},
    "4-1-3-2 Attacking": {"def": 4, "mid": 4, "fwd": 2, "name": "4-1-3-2 Attacking", "desc": "Attacking CDM setup behind dual strikers (4 DEF, 4 MID, 2 FWD)"},
    "4-1-4-1": {"def": 4, "mid": 5, "fwd": 1, "name": "4-1-4-1", "desc": "Single CDM anchor with flat four (4 DEF, 5 MID, 1 FWD)"},
    "4-2-2-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-2-2-2", "desc": "Box midfield with dual strikers (4 DEF, 4 MID, 2 FWD)"},
    "4-2-3-1 Attack": {"def": 4, "mid": 5, "fwd": 1, "name": "4-2-3-1 Attack", "desc": "Attacking double pivot with advanced three (4 DEF, 5 MID, 1 FWD)"},
    "4-2-3-1 Narrow": {"def": 4, "mid": 5, "fwd": 1, "name": "4-2-3-1 Narrow", "desc": "Narrow double pivot control (4 DEF, 5 MID, 1 FWD)"},
    "4-2-3-1 Wide": {"def": 4, "mid": 5, "fwd": 1, "name": "4-2-3-1 Wide", "desc": "Wide double pivot control (4 DEF, 5 MID, 1 FWD)"},
    "4-2-4": {"def": 4, "mid": 2, "fwd": 4, "name": "4-2-4", "desc": "Ultra attacking two midfielders and front four (4 DEF, 2 MID, 4 FWD)"},
    "4-3-1-2": {"def": 4, "mid": 4, "fwd": 2, "name": "4-3-1-2", "desc": "CAM behind dual strikers (4 DEF, 4 MID, 2 FWD)"},
    "4-3-2-1": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-2-1", "desc": "Christmas tree with dual number 10s (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 Attack": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Attack", "desc": "Attacking wing-focused front three (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 Balanced": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Balanced", "desc": "Balanced wing attack (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 Defend": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Defend", "desc": "Defensive 4-3-3 shape (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 False 9": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 False 9", "desc": "False nine dropping into midfield (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 Flat": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Flat", "desc": "Flat three midfield with front three (4 DEF, 3 MID, 3 FWD)"},
    "4-3-3 Holding": {"def": 4, "mid": 3, "fwd": 3, "name": "4-3-3 Holding", "desc": "Holding midfielder anchored 4-3-3 (4 DEF, 3 MID, 3 FWD)"},
    "4-4-1-1 Attack": {"def": 4, "mid": 5, "fwd": 1, "name": "4-4-1-1 Attack", "desc": "Attacking second striker behind lone 9 (4 DEF, 5 MID, 1 FWD)"},
    "4-4-1-1 Midfield": {"def": 4, "mid": 5, "fwd": 1, "name": "4-4-1-1 Midfield", "desc": "Midfield-heavy 4-4-1-1 (4 DEF, 5 MID, 1 FWD)"},
    "4-4-2 Flat": {"def": 4, "mid": 4, "fwd": 2, "name": "4-4-2 Flat", "desc": "Traditional flat midfield two up top (4 DEF, 4 MID, 2 FWD)"},
    "4-4-2 Holding": {"def": 4, "mid": 4, "fwd": 2, "name": "4-4-2 Holding", "desc": "Holding double pivot 4-4-2 (4 DEF, 4 MID, 2 FWD)"},
    "4-5-1 Attack": {"def": 4, "mid": 5, "fwd": 1, "name": "4-5-1 Attack", "desc": "Attacking packed midfield (4 DEF, 5 MID, 1 FWD)"},
    "4-5-1 Flat": {"def": 4, "mid": 5, "fwd": 1, "name": "4-5-1 Flat", "desc": "Flat five midfield overload (4 DEF, 5 MID, 1 FWD)"},
    # ── 5-Back ──
    "5-2-1-2": {"def": 5, "mid": 3, "fwd": 2, "name": "5-2-1-2", "desc": "Central CAM behind dual strikers (5 DEF, 3 MID, 2 FWD)"},
    "5-2-3": {"def": 5, "mid": 2, "fwd": 3, "name": "5-2-3", "desc": "Counter-attacking front three (5 DEF, 2 MID, 3 FWD)"},
    "5-3-2": {"def": 5, "mid": 3, "fwd": 2, "name": "5-3-2", "desc": "Solid defensive wall (5 DEF, 3 MID, 2 FWD)"},
    "5-4-1 Diamond": {"def": 5, "mid": 4, "fwd": 1, "name": "5-4-1 Diamond", "desc": "Diamond midfield low block (5 DEF, 4 MID, 1 FWD)"},
    "5-4-1 Flat": {"def": 5, "mid": 4, "fwd": 1, "name": "5-4-1 Flat", "desc": "Flat midfield deep block (5 DEF, 4 MID, 1 FWD)"},
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
