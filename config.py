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
        "description": "Your main server currency for transfers, shop, and club fees.",
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

# Daily Economy Settings
DAILY_REWARD_CASH = 500
DAILY_REWARD_POINTS = 200
DAILY_STREAK_BONUS_CASH = 50  # Additional cash per streak day (up to max 7 days)
DAILY_COOLDOWN_HOURS = 24

# Work / Activity Jobs
WORK_COOLDOWN_MINUTES = 30
FOOTBALL_JOBS = [
    {
        "title": "Striker Finishing Drill",
        "desc": "Completed intensive penalty and volley drills with the first team coach.",
        "min_cash": 120, "max_cash": 300,
        "min_points": 40, "max_points": 100,
        "token_chance": 0.35, "token_reward": 1
    },
    {
        "title": "Midfield Playmaking Clinic",
        "desc": "Orchestrated tactical transitions and through-ball passing lines.",
        "min_cash": 100, "max_cash": 260,
        "min_points": 50, "max_points": 120,
        "token_chance": 0.30, "token_reward": 1
    },
    {
        "title": "Goalkeeper Reflex Training",
        "desc": "Faced 100 high-speed shots and made crucial finger-tip saves.",
        "min_cash": 110, "max_cash": 280,
        "min_points": 45, "max_points": 95,
        "token_chance": 0.25, "token_reward": 1
    },
    {
        "title": "Tactical Video Analysis",
        "desc": "Studied rival formations and prepared tactical scouting dossiers.",
        "min_cash": 150, "max_cash": 320,
        "min_points": 60, "max_points": 140,
        "token_chance": 0.20, "token_reward": 1
    },
    {
        "title": "Matchday Ticket Sales",
        "desc": "Staffed the BeastlyFC stadium box office ahead of the derby.",
        "min_cash": 180, "max_cash": 350,
        "min_points": 30, "max_points": 80,
        "token_chance": 0.10, "token_reward": 1
    },
    {
        "title": "Pitch Turf Maintenance",
        "desc": "Mowed and marked the pitch turf for international competition standards.",
        "min_cash": 130, "max_cash": 270,
        "min_points": 50, "max_points": 110,
        "token_chance": 0.20, "token_reward": 1
    },
    {
        "title": "Youth Academy Scouting",
        "desc": "Traveled to scout emerging wonderkids across competitive grassroots leagues.",
        "min_cash": 200, "max_cash": 400,
        "min_points": 70, "max_points": 150,
        "token_chance": 0.40, "token_reward": 2
    },
    {
        "title": "Club Sponsorship Negotiation",
        "desc": "Closed a lucrative jersey sponsorship deal for the BeastlyFC franchise.",
        "min_cash": 250, "max_cash": 500,
        "min_points": 80, "max_points": 180,
        "token_chance": 0.50, "token_reward": 2
    },
]
