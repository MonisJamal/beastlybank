"""
Database manager and ACID repository for BeastlyBank.
Supports Cash, Community Points, Training Tokens, Clubs, Shop, Inventory, Giveaways, and Auditing.
"""
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite


def _normalize_search_text(text: str) -> str:
    """Normalize text by stripping accents, ligatures, and converting to lowercase."""
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

from config import (
    DEFAULT_FORMATION,
    SUPPORTED_FORMATIONS,
    VALID_POSITIONS,
    POSITION_CATEGORIES,
    get_formation_positions,
)
from utils.name_matcher import match_player_name, match_club_name

logger = logging.getLogger("BeastlyBank.DB")


def normalize_alt_positions(alt_positions: Optional[str], primary_pos: Optional[str] = None) -> Optional[str]:
    """
    Normalizes alternate positions separated by commas, spaces, slashes, or semicolons
    (e.g. 'pos1, pos2, pos3, .....') into a clean, uppercase, deduplicated, comma-separated string
    excluding the primary position and any invalid positions.
    Returns format: 'POS1, POS2, POS3, ...' or None if empty.
    """
    if not alt_positions:
        return None
    raw = str(alt_positions).strip()
    if raw.lower() in ("none", "clear", "remove", "null", "no", "empty", "-"):
        return None

    # Replace common delimiters with commas
    standardized = raw.replace("/", ",").replace(";", ",").replace("|", ",")

    if "," in standardized:
        tokens = standardized.split(",")
    else:
        tokens = standardized.split()

    prim = primary_pos.upper().strip() if primary_pos else None
    seen = set()
    deduped = []

    for tok in tokens:
        sub_tokens = tok.split() if tok.strip().upper() not in VALID_POSITIONS else [tok]
        for sub in sub_tokens:
            cleaned = sub.strip(" \t\n\r\"'[](),.").upper()
            if cleaned in VALID_POSITIONS and cleaned != prim:
                if cleaned not in seen:
                    seen.add(cleaned)
                    deduped.append(cleaned)

    return ", ".join(deduped) if deduped else None


def parse_wage_to_int(wage_val: Any) -> int:
    """
    Parses wage strings or numbers into an integer Cash amount.
    Handles '€150K', '€1.2M', '50k', '150,000', None, etc.
    """
    if wage_val is None:
        return 0
    if isinstance(wage_val, (int, float)):
        return max(0, int(wage_val))
    s = str(wage_val).strip()
    if not s:
        return 0
    s = re.sub(r'[€$£¥,\s]', '', s).lower()
    s = s.replace("/wk", "").replace("/md", "").replace("/week", "")
    if s.endswith("k"):
        try:
            return max(0, int(float(s[:-1]) * 1_000))
        except ValueError:
            return 0
    elif s.endswith("m"):
        try:
            return max(0, int(float(s[:-1]) * 1_000_000))
        except ValueError:
            return 0
    elif s.endswith("b"):
        try:
            return max(0, int(float(s[:-1]) * 1_000_000_000))
        except ValueError:
            return 0
    try:
        return max(0, int(float(s)))
    except ValueError:
        return 0


def format_wage(amount: Any) -> str:
    """
    Formats integer wage into clean display e.g. €150K, €1.5M, €500.
    """
    amt = parse_wage_to_int(amount)
    if amt <= 0:
        return "€0"
    if amt >= 1_000_000:
        val = amt / 1_000_000
        return f"€{val:.2f}".rstrip("0").rstrip(".") + "M"
    elif amt >= 1_000:
        val = amt / 1_000
        return f"€{val:.1f}".rstrip("0").rstrip(".") + "K"
    return f"€{amt:,}"


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            from config import TURSO_DATABASE_URL, TURSO_AUTH_TOKEN
            if TURSO_DATABASE_URL and TURSO_AUTH_TOKEN:
                try:
                    import libsql
                    sync_url = TURSO_DATABASE_URL
                    if sync_url.startswith("http://"):
                        sync_url = sync_url.replace("http://", "libsql://")
                    elif sync_url.startswith("https://"):
                        sync_url = sync_url.replace("https://", "libsql://")

                    def _turso_connector():
                        con = libsql.connect(
                            self.db_path,
                            sync_url=sync_url,
                            auth_token=TURSO_AUTH_TOKEN,
                            sync_interval=30,
                        )
                        try:
                            con.sync()
                        except Exception as sync_err:
                            logger.warning("Turso initial sync: %s", sync_err)
                        return con

                    self._conn = aiosqlite.Connection(connector=_turso_connector, iter_chunk_size=64)
                    await self._conn
                    self._conn.row_factory = aiosqlite.Row
                    logger.info("⚡ Connected to Turso Cloud SQLite database! Replication active.")
                    return self._conn
                except Exception as e:
                    logger.warning("Could not initialize Turso cloud replication: %s. Using local SQLite.", e)

            self._conn = await aiosqlite.connect(self.db_path, timeout=30.0)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.execute("PRAGMA synchronous=NORMAL;")
            await self._conn.execute("PRAGMA busy_timeout=15000;")
        return self._conn

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def init_db(self) -> None:
        """Create all required tables and indices for BeastlyBank."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            # Users Table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    cash INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    tokens INTEGER NOT NULL DEFAULT 0,
                    daily_streak INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT,
                    last_work TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, guild_id)
                );
                """
            )

            # Transactions Table (Double-entry transaction audit log)
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    sender_id INTEGER,
                    receiver_id INTEGER,
                    currency TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    tx_type TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Clubs (BeastlyFC Club Treasuries)
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS clubs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    tag TEXT NOT NULL,
                    owner_id INTEGER NOT NULL,
                    role_id INTEGER,
                    formation TEXT NOT NULL DEFAULT '4-3-3 Balanced',
                    treasury_cash INTEGER NOT NULL DEFAULT 0,
                    treasury_points INTEGER NOT NULL DEFAULT 0,
                    treasury_tokens INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, name),
                    UNIQUE(guild_id, tag)
                );
                """
            )

            # Club Members Table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS club_members (
                    club_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'Member',
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (club_id, user_id),
                    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE
                );
                """
            )

            # Club Custom Players Table (for custom written player transfers and squad lineups)
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS club_players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    club_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'Player',
                    position TEXT NOT NULL DEFAULT 'ST',
                    status TEXT NOT NULL DEFAULT 'starting',
                    number INTEGER DEFAULT NULL,
                    user_id INTEGER DEFAULT NULL,
                    rating INTEGER DEFAULT 75,
                    potential INTEGER DEFAULT 80,
                    alt_positions TEXT DEFAULT NULL,
                    wage INTEGER NOT NULL DEFAULT 0,
                    transferred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (club_id) REFERENCES clubs(id) ON DELETE CASCADE
                );
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_club_players_lookup ON club_players (guild_id, LOWER(player_name));"
            )

            # Shop Items
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS shop_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    currency TEXT NOT NULL DEFAULT 'cash',
                    role_reward_id INTEGER DEFAULT NULL,
                    stock INTEGER DEFAULT -1,
                    category TEXT DEFAULT 'Perk',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            # Safe migration for existing tables without is_active column
            try:
                await cur.execute("ALTER TABLE shop_items ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1;")
            except Exception:
                pass

            # SoFIFA Sep 19 2025 FC 26 Players Cache & Autocomplete Index
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS sofifa_players (
                    id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    full_name TEXT NOT NULL,
                    primary_pos TEXT NOT NULL,
                    positions TEXT,
                    overall_rating INTEGER NOT NULL,
                    potential INTEGER NOT NULL,
                    age INTEGER NOT NULL,
                    team TEXT,
                    nationality TEXT,
                    value TEXT,
                    wage TEXT,
                    avatar_url TEXT,
                    sofifa_url TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    search_text TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sofifa_lookup ON sofifa_players (LOWER(name), LOWER(full_name));"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sofifa_search ON sofifa_players (search_text);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_sofifa_ovr ON sofifa_players (overall_rating DESC);"
            )

            # Server Settings (Economy, Purchases, Shop toggles)
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS server_settings (
                    guild_id INTEGER PRIMARY KEY,
                    economy_enabled INTEGER NOT NULL DEFAULT 1,
                    purchases_enabled INTEGER NOT NULL DEFAULT 1,
                    shop_enabled INTEGER NOT NULL DEFAULT 1
                );
                """
            )

            # User Inventory
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    item_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    acquired_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (item_id) REFERENCES shop_items(id) ON DELETE CASCADE,
                    UNIQUE(user_id, guild_id, item_id)
                );
                """
            )

            # Giveaways
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS giveaways (
                    message_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    host_id INTEGER NOT NULL,
                    prize_name TEXT NOT NULL,
                    prize_currency TEXT,
                    prize_amount INTEGER DEFAULT 0,
                    winner_count INTEGER NOT NULL DEFAULT 1,
                    end_time TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    entries TEXT NOT NULL DEFAULT '[]',
                    winners TEXT DEFAULT '[]',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Market Auctions Table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS market_auctions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER DEFAULT NULL,
                    seller_id INTEGER NOT NULL,
                    seller_club_id INTEGER DEFAULT NULL,
                    player_name TEXT NOT NULL,
                    ovr INTEGER NOT NULL,
                    potential INTEGER NOT NULL,
                    position TEXT NOT NULL DEFAULT 'ST',
                    starting_bid INTEGER NOT NULL,
                    max_increment INTEGER NOT NULL,
                    current_bid INTEGER NOT NULL DEFAULT 0,
                    highest_bidder_id INTEGER DEFAULT NULL,
                    highest_bidder_club_id INTEGER DEFAULT NULL,
                    escrow_source TEXT DEFAULT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    photo_url TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    expires_at TEXT NOT NULL,
                    idle_timeout_seconds INTEGER DEFAULT NULL,
                    last_bid_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Auction Bids Audit Table
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS auction_bids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    auction_id INTEGER NOT NULL,
                    bidder_id INTEGER NOT NULL,
                    bidder_club_id INTEGER DEFAULT NULL,
                    bid_amount INTEGER NOT NULL,
                    increment INTEGER NOT NULL,
                    escrow_source TEXT NOT NULL DEFAULT 'treasury',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (auction_id) REFERENCES market_auctions(id) ON DELETE CASCADE
                );
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_auction_guild_status ON market_auctions (guild_id, status);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_auction_expires ON market_auctions (status, expires_at);"
            )

            # Tournament & Match Simulator Tables
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    season_number INTEGER NOT NULL DEFAULT 1,
                    competition_type TEXT NOT NULL DEFAULT 'league',
                    url TEXT DEFAULT NULL,
                    current_matchday INTEGER NOT NULL DEFAULT 1,
                    total_matchdays INTEGER NOT NULL DEFAULT 38,
                    status TEXT NOT NULL DEFAULT 'active',
                    champion TEXT DEFAULT NULL,
                    runner_up TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tournament_fixtures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    matchday INTEGER NOT NULL,
                    stage_name TEXT DEFAULT NULL,
                    match_uid TEXT DEFAULT NULL,
                    home_team_id TEXT NOT NULL,
                    away_team_id TEXT NOT NULL,
                    home_team_name TEXT NOT NULL,
                    away_team_name TEXT NOT NULL,
                    home_team_short TEXT DEFAULT NULL,
                    away_team_short TEXT DEFAULT NULL,
                    goals_home INTEGER DEFAULT NULL,
                    goals_away INTEGER DEFAULT NULL,
                    penalties_home INTEGER DEFAULT 0,
                    penalties_away INTEGER DEFAULT 0,
                    is_finished INTEGER NOT NULL DEFAULT 0,
                    replay_exists INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )

            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tournament_player_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    team_name TEXT NOT NULL,
                    club_id INTEGER DEFAULT NULL,
                    goals INTEGER NOT NULL DEFAULT 0,
                    assists INTEGER NOT NULL DEFAULT 0,
                    own_goals INTEGER NOT NULL DEFAULT 0,
                    yellow_cards INTEGER NOT NULL DEFAULT 0,
                    red_cards INTEGER NOT NULL DEFAULT 0,
                    clean_sheets INTEGER NOT NULL DEFAULT 0,
                    matches_played INTEGER NOT NULL DEFAULT 0,
                    minutes_played INTEGER NOT NULL DEFAULT 0,
                    rating REAL NOT NULL DEFAULT 6.5,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )

            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS tournament_standings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tournament_id INTEGER NOT NULL,
                    team_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    short TEXT DEFAULT NULL,
                    rank INTEGER NOT NULL,
                    played INTEGER NOT NULL DEFAULT 0,
                    won INTEGER NOT NULL DEFAULT 0,
                    drawn INTEGER NOT NULL DEFAULT 0,
                    lost INTEGER NOT NULL DEFAULT 0,
                    goals_for INTEGER NOT NULL DEFAULT 0,
                    goals_against INTEGER NOT NULL DEFAULT 0,
                    goal_difference INTEGER NOT NULL DEFAULT 0,
                    clean_sheets INTEGER NOT NULL DEFAULT 0,
                    points INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )

            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS matchday_bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    tournament_id INTEGER NOT NULL,
                    matchday INTEGER NOT NULL,
                    fixture_id INTEGER DEFAULT NULL,
                    match_uid TEXT DEFAULT NULL,
                    user_id INTEGER NOT NULL,
                    bet_type TEXT NOT NULL,
                    amount INTEGER NOT NULL,
                    odds REAL NOT NULL DEFAULT 2.0,
                    escrow_source TEXT NOT NULL DEFAULT 'personal',
                    status TEXT NOT NULL DEFAULT 'pending',
                    payout_amount INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    settled_at TEXT DEFAULT NULL,
                    FOREIGN KEY (tournament_id) REFERENCES tournaments(id) ON DELETE CASCADE
                );
                """
            )

            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS season_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    season_number INTEGER NOT NULL,
                    competition_name TEXT NOT NULL,
                    champion TEXT NOT NULL,
                    runner_up TEXT DEFAULT NULL,
                    golden_boot_player TEXT DEFAULT NULL,
                    golden_boot_goals INTEGER DEFAULT NULL,
                    playmaker_player TEXT DEFAULT NULL,
                    playmaker_assists INTEGER DEFAULT NULL,
                    golden_glove_team TEXT DEFAULT NULL,
                    golden_glove_clean_sheets INTEGER DEFAULT NULL,
                    mvp_player TEXT DEFAULT NULL,
                    mvp_rating REAL DEFAULT NULL,
                    archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tournament_guild_status ON tournaments (guild_id, status);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_fixture_tourn_md ON tournament_fixtures (tournament_id, matchday);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_player_stats_tourn ON tournament_player_stats (tournament_id, player_name);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_bets_tourn_md ON matchday_bets (tournament_id, matchday, status);"
            )

            try:
                await cur.execute("ALTER TABLE tournament_fixtures ADD COLUMN stage_name TEXT DEFAULT NULL;")
            except Exception:
                pass

            # Matchday Wage Payouts Ledger
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS matchday_wage_payouts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    club_id INTEGER NOT NULL,
                    matchday INTEGER NOT NULL,
                    tournament_id INTEGER DEFAULT NULL,
                    total_wages INTEGER NOT NULL,
                    treasury_before INTEGER NOT NULL,
                    treasury_after INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'paid',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(guild_id, club_id, matchday)
                );
                """
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_wage_payouts_lookup ON matchday_wage_payouts (guild_id, matchday, club_id);"
            )

            # Performance Indices
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions (guild_id, sender_id, receiver_id);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_tx_time ON transactions (created_at DESC);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_club_owner ON clubs (guild_id, owner_id);"
            )
            await cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_club_members_user ON club_members (guild_id, user_id);"
            )

            # Seed Default Shop Items if empty
            await cur.execute("SELECT COUNT(*) as count FROM shop_items;")
            row = await cur.fetchone()
            if row and row["count"] == 0:
                default_items = [
                    (
                        0,
                        "⭐ Beastly VIP Role",
                        "Exclusive gold VIP badge and VIP matchday channel access.",
                        2500,
                        "cash",
                        None,
                        -1,
                        "Perk",
                    ),
                    (
                        0,
                        "⚡ 2x Training Drill Pass",
                        "Doubles training token earnings for 24 hours.",
                        500,
                        "points",
                        None,
                        -1,
                        "Boost",
                    ),
                    (
                        0,
                        "🛡️ Club Stadium Upgrade",
                        "Unlocks advanced tier for your BeastlyFC club treasury.",
                        25,
                        "tokens",
                        None,
                        -1,
                        "Club",
                    ),
                    (
                        0,
                        "🏆 Beastly Legend Title",
                        "Highest honor awarded in BeastlyFC server profile.",
                        10000,
                        "cash",
                        None,
                        5,
                        "Exclusive",
                    ),
                ]
                await cur.executemany(
                    """
                    INSERT INTO shop_items (guild_id, name, description, price, currency, role_reward_id, stock, category)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    default_items,
                )

            # Reset any users that had the legacy starter pack to 0
            await cur.execute(
                """
                UPDATE users
                SET cash = 0, points = 0, tokens = 0
                WHERE cash = 1000 AND points = 250 AND tokens = 5;
                """
            )
            await cur.execute("DELETE FROM transactions WHERE tx_type = 'starter_bonus';")

            # Reset any legacy club vaults to 0
            await cur.execute(
                """
                UPDATE clubs
                SET treasury_cash = 0, treasury_points = 0, treasury_tokens = 0
                WHERE treasury_cash != 0 OR treasury_points != 0 OR treasury_tokens != 0;
                """
            )

            # Ensure role_id, formation, and squad player columns exist
            for col_stmt in [
                "ALTER TABLE clubs ADD COLUMN role_id INTEGER;",
                "ALTER TABLE clubs ADD COLUMN formation TEXT NOT NULL DEFAULT '4-3-3 Balanced';",
                "ALTER TABLE club_players ADD COLUMN position TEXT NOT NULL DEFAULT 'ST';",
                "ALTER TABLE club_players ADD COLUMN status TEXT NOT NULL DEFAULT 'starting';",
                "ALTER TABLE club_players ADD COLUMN number INTEGER DEFAULT NULL;",
                "ALTER TABLE club_players ADD COLUMN user_id INTEGER DEFAULT NULL;",
                "ALTER TABLE club_players ADD COLUMN rating INTEGER DEFAULT 75;",
                "ALTER TABLE club_players ADD COLUMN potential INTEGER DEFAULT 80;",
                "ALTER TABLE club_players ADD COLUMN alt_positions TEXT DEFAULT NULL;",
                "ALTER TABLE club_players ADD COLUMN wage INTEGER NOT NULL DEFAULT 0;",
                "ALTER TABLE clubs ADD COLUMN logo_url TEXT DEFAULT NULL;",
                "ALTER TABLE clubs ADD COLUMN kit_primary TEXT DEFAULT NULL;",
                "ALTER TABLE clubs ADD COLUMN kit_secondary TEXT DEFAULT NULL;",
                "ALTER TABLE clubs ADD COLUMN slogan_1 TEXT DEFAULT NULL;",
                "ALTER TABLE clubs ADD COLUMN slogan_2 TEXT DEFAULT NULL;",
                "ALTER TABLE clubs ADD COLUMN chant TEXT DEFAULT NULL;",
                "ALTER TABLE sofifa_players ADD COLUMN search_text TEXT;",
            ]:
                try:
                    await cur.execute(col_stmt)
                except Exception:
                    pass

            # Migrate any legacy 4-2-3-1 Attack clubs to 4-2-1-3
            try:
                await cur.execute(
                    "UPDATE clubs SET formation = '4-2-1-3' WHERE LOWER(formation) IN ('4-2-3-1 attack', '4231 attack', '4-2-3-1attack', '4231');"
                )
                await cur.execute(
                    "SELECT id, formation FROM clubs WHERE LOWER(formation) IN ('4-2-1-3', '4213', '4-2-1-3 attack', '4213 attack');"
                )
                f4213_clubs = [dict(r) for r in await cur.fetchall()]
                for fc in f4213_clubs:
                    await self._realign_club_starters(cur, fc["id"], "4-2-1-3")
            except Exception as mig_err:
                logger.debug("Migration 4-2-1-3 notice: %s", mig_err)

        await conn.commit()
        logger.info("Database schema initialized successfully.")

    # ------------------ User Account & Balances ------------------ #

    async def get_or_create_user(self, user_id: int, guild_id: int) -> Dict[str, Any]:
        """Fetch or initialize a user's BeastlyBank account."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM users WHERE user_id = ? AND guild_id = ?;",
                (user_id, guild_id),
            )
            row = await cur.fetchone()
            if row:
                return dict(row)

            # Create new account with 0 default balances
            await cur.execute(
                """
                INSERT INTO users (user_id, guild_id, cash, points, tokens, daily_streak)
                VALUES (?, ?, 0, 0, 0, 0);
                """,
                (user_id, guild_id),
            )
            await conn.commit()

            await cur.execute(
                "SELECT * FROM users WHERE user_id = ? AND guild_id = ?;",
                (user_id, guild_id),
            )
            new_row = await cur.fetchone()
            return dict(new_row)

    async def update_balance(
        self,
        user_id: int,
        guild_id: int,
        currency: str,
        delta: int,
        tx_type: str,
        reason: Optional[str] = None,
        related_user_id: Optional[int] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Atomically modify a user's balance.
        delta > 0 credits funds; delta < 0 debits funds.
        Prevents balance from dropping below 0.
        """
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'. Must be 'cash', 'points', or 'tokens'.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Ensure user exists
            await self.get_or_create_user(user_id, guild_id)

            await cur.execute(
                f"SELECT {currency} FROM users WHERE user_id = ? AND guild_id = ?;",
                (user_id, guild_id),
            )
            row = await cur.fetchone()
            current_val = row[currency]

            new_val = current_val + delta
            if new_val < 0:
                return False, f"Insufficient {currency}! Available: {current_val:,}, Required: {abs(delta):,}.", {}

            await cur.execute(
                f"UPDATE users SET {currency} = {currency} + ? WHERE user_id = ? AND guild_id = ?;",
                (delta, user_id, guild_id),
            )

            # Record in transactions ledger
            sender_id = related_user_id if delta > 0 else user_id
            receiver_id = user_id if delta > 0 else related_user_id

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (guild_id, sender_id, receiver_id, currency, abs(delta), tx_type, reason),
            )

            await conn.commit()

            # Return updated account
            await cur.execute(
                "SELECT * FROM users WHERE user_id = ? AND guild_id = ?;",
                (user_id, guild_id),
            )
            updated = await cur.fetchone()
            return True, "Success", dict(updated)

    async def transfer(
        self,
        sender_id: int,
        receiver_id: int,
        guild_id: int,
        currency: str,
        amount: int,
        reason: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Atomic player-to-player payment.
        Guarantees sender has funds and debits/credits in a single transaction.
        """
        if sender_id == receiver_id:
            return False, "You cannot send money to yourself!"
        if amount <= 0:
            return False, "Transfer amount must be greater than 0."
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'."

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Ensure both accounts exist
            await self.get_or_create_user(sender_id, guild_id)
            await self.get_or_create_user(receiver_id, guild_id)

            await cur.execute(
                f"SELECT {currency} FROM users WHERE user_id = ? AND guild_id = ?;",
                (sender_id, guild_id),
            )
            sender_row = await cur.fetchone()
            sender_balance = sender_row[currency]

            if sender_balance < amount:
                return False, f"Insufficient {currency}. You have {sender_balance:,}, need {amount:,}."

            # Perform atomic transfer
            await cur.execute(
                f"UPDATE users SET {currency} = {currency} - ? WHERE user_id = ? AND guild_id = ?;",
                (amount, sender_id, guild_id),
            )
            await cur.execute(
                f"UPDATE users SET {currency} = {currency} + ? WHERE user_id = ? AND guild_id = ?;",
                (amount, receiver_id, guild_id),
            )

            # Record in ledger
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, ?, ?, 'transfer', ?);
                """,
                (guild_id, sender_id, receiver_id, currency, amount, reason or "Direct Player Payment"),
            )

            await conn.commit()
            return True, "Transfer completed successfully."

    async def redeem_cp(
        self, user_id: int, guild_id: int, points_amount: int, rate: int = 2
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Convert Community Points into Cash.
        rate: 1 Point = rate Cash (default: 1 CP = 2 Cash).
        """
        if points_amount <= 0:
            return False, "Amount of Community Points to convert must be greater than 0.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            user = await self.get_or_create_user(user_id, guild_id)
            if user["points"] < points_amount:
                return False, f"Insufficient Community Points! You have ⭐ {user['points']:,}, requested {points_amount:,}.", {}

            cash_received = points_amount * rate

            await cur.execute(
                """
                UPDATE users
                SET points = points - ?,
                    cash = cash + ?
                WHERE user_id = ? AND guild_id = ?;
                """,
                (points_amount, cash_received, user_id, guild_id),
            )

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, 'points', ?, 'cp_redeem', ?);
                """,
                (guild_id, user_id, points_amount, f"Converted {points_amount:,} CP to Cash"),
            )
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, NULL, ?, 'cash', ?, 'cp_redeem', ?);
                """,
                (guild_id, user_id, cash_received, f"Received Cash from {points_amount:,} CP conversion"),
            )
            await conn.commit()

        updated_user = await self.get_or_create_user(user_id, guild_id)
        return True, f"Successfully converted ⭐ **{points_amount:,} CP** into 💵 **{cash_received:,} Cash**!", {
            "points_redeemed": points_amount,
            "cash_received": cash_received,
            "user": updated_user,
        }

    # ------------------ Transactions & Ledger ------------------ #

    async def get_transactions(
        self, user_id: int, guild_id: int, limit: int = 10, offset: int = 0
    ) -> List[Dict[str, Any]]:
        """Get paginated transaction history for a user."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM transactions
                WHERE guild_id = ? AND (sender_id = ? OR receiver_id = ?)
                ORDER BY id DESC
                LIMIT ? OFFSET ?;
                """,
                (guild_id, user_id, user_id, limit, offset),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_total_transactions_count(self, user_id: int, guild_id: int) -> int:
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT COUNT(*) as cnt FROM transactions
                WHERE guild_id = ? AND (sender_id = ? OR receiver_id = ?);
                """,
                (guild_id, user_id, user_id),
            )
            row = await cur.fetchone()
            return row["cnt"] if row else 0

    # ------------------ Leaderboards ------------------ #

    async def get_leaderboard(
        self, guild_id: int, currency: str = "cash", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get the richest players in BeastlyFC by specified currency."""
        if currency not in ("cash", "points", "tokens"):
            currency = "cash"

        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT user_id, {currency} as balance, cash, points, tokens
                FROM users
                WHERE guild_id = ?
                ORDER BY {currency} DESC
                LIMIT ?;
                """,
                (guild_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------ Club Treasuries ------------------ #

    async def create_club(
        self, guild_id: int, name: str, tag: str, owner_id: int, role_id: Optional[int] = None
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Form a new BeastlyFC football club with its own treasury."""
        name = name.strip()
        tag = tag.strip().upper()
        if len(tag) > 5:
            return False, "Club tag must be 5 characters or fewer (e.g. BFC, STK).", None
        if len(name) > 32:
            return False, "Club name must be 32 characters or fewer.", None

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Check if user already owns or is in a club
            await cur.execute(
                "SELECT * FROM club_members WHERE guild_id = ? AND user_id = ?;",
                (guild_id, owner_id),
            )
            if await cur.fetchone():
                return False, "You are already a member/owner of a club! Leave your club first.", None

            # Check if name or tag exists
            await cur.execute(
                "SELECT * FROM clubs WHERE guild_id = ? AND (LOWER(name) = LOWER(?) OR UPPER(tag) = UPPER(?));",
                (guild_id, name, tag),
            )
            if await cur.fetchone():
                return False, "A club with this name or tag already exists in BeastlyFC!", None

            # Check if role_id is already linked to another club
            if role_id:
                await cur.execute(
                    "SELECT name, tag FROM clubs WHERE guild_id = ? AND role_id = ?;",
                    (guild_id, role_id),
                )
                existing_role = await cur.fetchone()
                if existing_role:
                    return False, f"The role <@&{role_id}> is already linked to **[{existing_role['tag']}] {existing_role['name']}**!", None

            # Creation fee: 100% Free!
            # Insert Club with 0 starter treasury and optional linked role_id
            await cur.execute(
                """
                INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash, treasury_points, treasury_tokens, role_id)
                VALUES (?, ?, ?, ?, 0, 0, 0, ?);
                """,
                (guild_id, name, tag, owner_id, role_id),
            )
            club_id = cur.lastrowid

            # Insert Owner into club_members
            await cur.execute(
                """
                INSERT INTO club_members (club_id, user_id, guild_id, role)
                VALUES (?, ?, ?, 'Owner');
                """,
                (club_id, owner_id, guild_id),
            )

            await conn.commit()

            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club = await cur.fetchone()
            return True, f"Club **[{tag}] {name}** has been officially registered with BeastlyBank!", dict(club)

    async def transfer_player(
        self,
        guild_id: int,
        player_name: str,
        from_club_query: str,
        to_club_query: str,
        amount: int,
        payer_id: int,
        recipient_id: Optional[int] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Execute official transfer of a player (custom written name) between clubs with transfer fee disbursement.
        """
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty.", {}

        if amount < 0:
            return False, "Transfer fee cannot be negative.", {}

        from_club = await self.get_or_create_club_from_role(guild_id, from_club_query, default_owner_id=payer_id)
        to_club = await self.get_or_create_club_from_role(guild_id, to_club_query, default_owner_id=payer_id)

        from_label = from_club_query.mention if hasattr(from_club_query, "mention") else f"'{from_club_query}'"
        to_label = to_club_query.mention if hasattr(to_club_query, "mention") else f"'{to_club_query}'"

        if not from_club:
            return False, f"Selling club {from_label} not found in BeastlyBank.", {}
        if not to_club:
            return False, f"Buying club {to_label} not found in BeastlyBank.", {}
        if from_club["id"] == to_club["id"]:
            return False, "Selling club and buying club cannot be the same.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:

            if amount > 0:
                # Debit the buying club's vault treasury directly
                await cur.execute(
                    "UPDATE clubs SET treasury_cash = treasury_cash - ? WHERE id = ?;",
                    (amount, to_club["id"]),
                )

                if recipient_id:
                    await self.get_or_create_user(recipient_id, guild_id)
                    await cur.execute(
                        "UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;",
                        (amount, recipient_id, guild_id),
                    )
                    payee_desc = f"<@{recipient_id}>"
                else:
                    await cur.execute(
                        "UPDATE clubs SET treasury_cash = treasury_cash + ? WHERE id = ?;",
                        (amount, from_club["id"]),
                    )
                    role_tag = f"<@&{from_club['role_id']}>" if from_club.get("role_id") else f"**[{from_club['tag']}]**"
                    payee_desc = f"{role_tag} Treasury"

                await cur.execute(
                    """
                    INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                    VALUES (?, ?, ?, 'cash', ?, 'transfer_market', ?);
                    """,
                    (
                        guild_id,
                        payer_id,
                        recipient_id if recipient_id else None,
                        amount,
                        f"Transfer Fee: {p_name} from [{from_club['tag']}] to [{to_club['tag']}] (Paid to {payee_desc})",
                    ),
                )
            else:
                payee_desc = "Free Transfer"

            # Fetch existing custom player details to preserve position, number, rating, potential, alt_positions
            await cur.execute(
                "SELECT position, number, rating, potential, alt_positions FROM club_players WHERE guild_id = ? AND LOWER(player_name) = LOWER(?);",
                (guild_id, p_name),
            )
            old_p = await cur.fetchone()
            p_pos = old_p["position"] if old_p and old_p["position"] else "ST"
            p_num = old_p["number"] if old_p and old_p["number"] else None
            p_rating = old_p["rating"] if old_p and old_p["rating"] is not None else 75
            p_pot = old_p["potential"] if old_p and old_p["potential"] is not None else 80
            p_alt = normalize_alt_positions(old_p["alt_positions"], primary_pos=p_pos) if old_p and old_p["alt_positions"] else None

            # Update custom players roster
            await cur.execute(
                "DELETE FROM club_players WHERE guild_id = ? AND LOWER(player_name) = LOWER(?);",
                (guild_id, p_name),
            )
            await cur.execute(
                """
                INSERT INTO club_players (club_id, guild_id, player_name, role, position, status, number, rating, potential, alt_positions)
                VALUES (?, ?, ?, 'Player', ?, 'starting', ?, ?, ?, ?);
                """,
                (to_club["id"], guild_id, p_name, p_pos, p_num, p_rating, p_pot, p_alt),
            )

            # If p_name happens to be a mention or numeric user id, also move in club_members
            mention_id = None
            if p_name.startswith("<@") and p_name.endswith(">"):
                raw_id = p_name.strip("<@!>")
                if raw_id.isdigit():
                    mention_id = int(raw_id)
            elif p_name.isdigit():
                mention_id = int(p_name)

            if mention_id:
                await cur.execute(
                    "DELETE FROM club_members WHERE guild_id = ? AND user_id = ?;",
                    (guild_id, mention_id),
                )
                await self.get_or_create_user(mention_id, guild_id)
                await cur.execute(
                    """
                    INSERT INTO club_members (club_id, user_id, guild_id, role)
                    VALUES (?, ?, ?, 'Member')
                    ON CONFLICT(club_id, user_id) DO UPDATE SET role = 'Member';
                    """,
                    (to_club["id"], mention_id, guild_id),
                )

            await conn.commit()

            return True, "Player transfer completed successfully!", {
                "player_name": p_name,
                "from_club": from_club,
                "to_club": to_club,
                "amount": amount,
                "payee_desc": payee_desc,
                "recipient_id": recipient_id,
            }

    async def get_club_by_user(self, guild_id: int, user_id: int) -> Optional[Dict[str, Any]]:
        """Get the club that a user belongs to."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT c.*, cm.role as user_role, cm.joined_at as member_since
                FROM clubs c
                JOIN club_members cm ON c.id = cm.club_id
                WHERE cm.guild_id = ? AND cm.user_id = ?;
                """,
                (guild_id, user_id),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_or_create_club_from_role(
        self,
        guild_id: int,
        query: Any,
        default_owner_id: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve a club by Role or query; if not found, automatically register
        the club using the Discord Role details so transfers succeed without manual club creation.
        """
        if not query:
            return None

        # First attempt standard lookup
        club = await self.get_club_by_name(guild_id, query)
        if club:
            return club

        role_id = None
        role_name = None
        if hasattr(query, "id") and hasattr(query, "name"):
            role_id = query.id
            role_name = str(query.name).strip()
        elif isinstance(query, (int, str)):
            clean = str(query).strip()
            if clean.startswith("<@&") and clean.endswith(">"):
                raw = clean.strip("<@&>")
                if raw.isdigit():
                    role_id = int(raw)
            elif clean.isdigit():
                role_id = int(clean)

        if not role_name and not role_id and isinstance(query, str):
            role_name = query.strip()

        if not role_name and not role_id:
            return None

        import re
        display_name = role_name or f"Club-{str(role_id)[-4:]}"
        tag_match = re.search(r"\[(.*?)\]", display_name)
        if tag_match:
            tag = tag_match.group(1).strip()[:5].upper()
            display_name = re.sub(r"\[.*?\]", "", display_name).strip()
        else:
            words = [w for w in display_name.split() if w.isalnum()]
            if len(words) >= 2:
                tag = "".join(w[0] for w in words[:4]).upper()
            else:
                tag = display_name[:4].upper()

        if not tag:
            tag = "FC"
        if not display_name:
            display_name = tag

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Check if name or tag collision in this guild
            await cur.execute(
                "SELECT * FROM clubs WHERE guild_id = ? AND (LOWER(name) = LOWER(?) OR UPPER(tag) = UPPER(?));",
                (guild_id, display_name, tag),
            )
            row = await cur.fetchone()
            if row:
                res = dict(row)
                if role_id and not res.get("role_id"):
                    await cur.execute("UPDATE clubs SET role_id = ? WHERE id = ?;", (role_id, res["id"]))
                    await conn.commit()
                    res["role_id"] = role_id
                return res

            # Auto-register club in database
            await cur.execute(
                """
                INSERT INTO clubs (guild_id, name, tag, owner_id, role_id, treasury_cash, treasury_points, treasury_tokens)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0);
                """,
                (guild_id, display_name, tag, default_owner_id, role_id),
            )
            new_id = cur.lastrowid
            await conn.commit()

            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (new_id,))
            new_row = await cur.fetchone()
            logger.info("Auto-registered club '%s' [%s] for role %s in guild %d", display_name, tag, role_id, guild_id)
            return dict(new_row) if new_row else None

    async def get_club_by_name(self, guild_id: int, query: Any) -> Optional[Dict[str, Any]]:
        """
        Search club by Discord role object, role mention, role ID, database ID, exact name/tag, or case-insensitive partial match.
        """
        if not query:
            return None

        role_id = None
        role_name = None

        if hasattr(query, "id") and hasattr(query, "name"):
            role_id = query.id
            role_name = str(query.name).strip()
            q = role_name
        else:
            q = str(query).strip()
            import re
            m = re.search(r"<@&(\d+)>", q)
            if m:
                role_id = int(m.group(1))
            elif q.isdigit():
                role_id = int(q)

        conn = await self.connect()
        async with conn.cursor() as cur:
            # 0. If integer ID, match by database primary key or role_id
            if isinstance(query, int):
                await cur.execute(
                    "SELECT * FROM clubs WHERE guild_id = ? AND id = ?;",
                    (guild_id, query),
                )
                row = await cur.fetchone()
                if row:
                    return dict(row)
                await cur.execute(
                    "SELECT * FROM clubs WHERE guild_id = ? AND role_id = ?;",
                    (guild_id, query),
                )
                row = await cur.fetchone()
                if row:
                    return dict(row)

            # 1. Match by role_id if set on club
            if role_id:
                await cur.execute(
                    "SELECT * FROM clubs WHERE guild_id = ? AND role_id = ?;",
                    (guild_id, role_id),
                )
                row = await cur.fetchone()
                if row:
                    return dict(row)

            # 2. Exact match by name or tag (case-insensitive)
            await cur.execute(
                """
                SELECT * FROM clubs
                WHERE guild_id = ? AND (LOWER(name) = LOWER(?) OR UPPER(tag) = UPPER(?));
                """,
                (guild_id, q, q),
            )
            row = await cur.fetchone()
            if row:
                res = dict(row)
                if role_id and not res.get("role_id"):
                    await cur.execute("UPDATE clubs SET role_id = ? WHERE id = ?;", (role_id, res["id"]))
                    await conn.commit()
                    res["role_id"] = role_id
                return res

            # 3. If query had brackets like "[RDF] Red Dragons", try stripping them
            import re
            bracket_match = re.search(r"\[(.*?)\]", q)
            if bracket_match:
                extracted_tag = bracket_match.group(1).strip()
                cleaned_name = re.sub(r"\[.*?\]", "", q).strip()
                await cur.execute(
                    """
                    SELECT * FROM clubs
                    WHERE guild_id = ? AND (UPPER(tag) = UPPER(?) OR LOWER(name) = LOWER(?));
                    """,
                    (guild_id, extracted_tag, cleaned_name),
                )
                row = await cur.fetchone()
                if row:
                    res = dict(row)
                    if role_id and not res.get("role_id"):
                        await cur.execute("UPDATE clubs SET role_id = ? WHERE id = ?;", (role_id, res["id"]))
                        await conn.commit()
                        res["role_id"] = role_id
                    return res

            # 4. Partial match
            await cur.execute(
                """
                SELECT * FROM clubs
                WHERE guild_id = ? AND (LOWER(name) LIKE LOWER(?) OR UPPER(tag) LIKE UPPER(?))
                LIMIT 1;
                """,
                (guild_id, f"%{q}%", f"%{q}%"),
            )
            row = await cur.fetchone()
            if row:
                res = dict(row)
                if role_id and not res.get("role_id"):
                    await cur.execute("UPDATE clubs SET role_id = ? WHERE id = ?;", (role_id, res["id"]))
                    await conn.commit()
                    res["role_id"] = role_id
                return res

            # 5. Role name fuzzy match
            if role_name:
                cleaned = re.sub(r"\[.*?\]", "", role_name).strip()
                await cur.execute(
                    """
                    SELECT * FROM clubs
                    WHERE guild_id = ? AND (LOWER(?) LIKE '%' || LOWER(name) || '%' OR LOWER(?) LIKE '%' || LOWER(tag) || '%')
                    LIMIT 1;
                    """,
                    (guild_id, cleaned, cleaned),
                )
                row = await cur.fetchone()
                if row:
                    res = dict(row)
                    if role_id and not res.get("role_id"):
                        await cur.execute("UPDATE clubs SET role_id = ? WHERE id = ?;", (role_id, res["id"]))
                        await conn.commit()
                        res["role_id"] = role_id
                    return res

            return None

    async def get_club_members(self, club_id: int) -> List[Dict[str, Any]]:
        """Get roster for a club including linked Discord members and custom written players."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT cm.club_id, cm.user_id, cm.guild_id, cm.role, cm.joined_at,
                       COALESCE(u.cash, 0) as cash, COALESCE(u.points, 0) as points, COALESCE(u.tokens, 0) as tokens,
                       NULL as player_name,
                       COALESCE(cp.position, 'CM') as position,
                       COALESCE(cp.status, 'starting') as status,
                       cp.number as number
                FROM club_members cm
                LEFT JOIN users u ON cm.user_id = u.user_id AND cm.guild_id = u.guild_id
                LEFT JOIN club_players cp ON cp.club_id = cm.club_id AND cp.user_id = cm.user_id
                WHERE cm.club_id = ?
                ORDER BY CASE cm.role
                    WHEN 'Owner' THEN 1
                    WHEN 'Captain' THEN 2
                    WHEN 'Vice-Captain' THEN 3
                    WHEN 'Manager' THEN 4
                    ELSE 5
                END;
                """,
                (club_id,),
            )
            discord_members = [dict(r) for r in await cur.fetchall()]

            # Also fetch custom players registered to this club
            await cur.execute(
                """
                SELECT club_id, user_id, guild_id, role, transferred_at as joined_at,
                       0 as cash, 0 as points, 0 as tokens,
                       player_name, position, status, number
                FROM club_players
                WHERE club_id = ? AND (user_id IS NULL OR user_id NOT IN (SELECT user_id FROM club_members WHERE club_id = ?))
                ORDER BY id ASC;
                """,
                (club_id, club_id),
            )
            custom_players = [dict(r) for r in await cur.fetchall()]

            return discord_members + custom_players

    async def club_deposit(
        self, club_id: int, user_id: int, guild_id: int, currency: str, amount: int, is_banker: bool = False
    ) -> Tuple[bool, str]:
        """Deposit user funds into the club treasury."""
        if amount <= 0:
            return False, "Deposit amount must be greater than 0."
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'."

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Verify user is in this club unless authorized as Banker
            if not is_banker:
                await cur.execute(
                    "SELECT * FROM club_members WHERE club_id = ? AND user_id = ?;",
                    (club_id, user_id),
                )
                if not await cur.fetchone():
                    return False, "You are not a member of this club!"

            # Check user balance
            user = await self.get_or_create_user(user_id, guild_id)
            if user[currency] < amount:
                return False, f"Insufficient {currency}! You have {user[currency]:,}, need {amount:,}."

            treasury_col = f"treasury_{currency}"

            # Deduct from user
            await cur.execute(
                f"UPDATE users SET {currency} = {currency} - ? WHERE user_id = ? AND guild_id = ?;",
                (amount, user_id, guild_id),
            )
            # Add to club treasury
            await cur.execute(
                f"UPDATE clubs SET {treasury_col} = {treasury_col} + ? WHERE id = ?;",
                (amount, club_id),
            )
            # Record ledger
            auth_tag = " [Banker Op]" if is_banker else ""
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, ?, ?, 'club_deposit', ?);
                """,
                (guild_id, user_id, currency, amount, f"Treasury Deposit into Club #{club_id}{auth_tag}"),
            )
            await conn.commit()
            return True, f"Successfully deposited {amount:,} {currency} into Club Treasury!"

    async def club_withdraw(
        self, club_id: int, user_id: int, guild_id: int, currency: str, amount: int, reason: str, is_banker: bool = False
    ) -> Tuple[bool, str]:
        """Withdraw funds from the club treasury (Owner, Captain, Manager, or BeastlyBank Banker)."""
        if amount <= 0:
            return False, "Withdrawal amount must be greater than 0."
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'."

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Check permissions
            if not is_banker:
                await cur.execute(
                    "SELECT role FROM club_members WHERE club_id = ? AND user_id = ?;",
                    (club_id, user_id),
                )
                member = await cur.fetchone()
                if not member or member["role"] not in ("Owner", "Captain", "Manager"):
                    return False, "Only Club Owners, Captains, Managers, and BeastlyBank Bankers can withdraw from the Treasury."

            # Check club treasury
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club = await cur.fetchone()
            if not club:
                return False, "Club not found."

            treasury_col = f"treasury_{currency}"
            current_treasury = club[treasury_col]

            if current_treasury < amount:
                return False, f"Club Treasury has insufficient {currency}! Available: {current_treasury:,}, Requested: {amount:,}."

            # Deduct from club treasury
            await cur.execute(
                f"UPDATE clubs SET {treasury_col} = {treasury_col} - ? WHERE id = ?;",
                (amount, club_id),
            )
            # Ensure user exists and credit to user
            await self.get_or_create_user(user_id, guild_id)
            await cur.execute(
                f"UPDATE users SET {currency} = {currency} + ? WHERE user_id = ? AND guild_id = ?;",
                (amount, user_id, guild_id),
            )
            # Record ledger
            auth_tag = " [Banker Op]" if is_banker else ""
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, NULL, ?, ?, ?, 'club_withdraw', ?);
                """,
                (guild_id, user_id, currency, amount, f"Club Withdrawal [{club['tag']}]{auth_tag}: {reason}"),
            )
            await conn.commit()
            return True, f"Withdrew {amount:,} {currency} from the Club Treasury."

    async def update_club_treasury(
        self,
        guild_id: int,
        club_query: str,
        currency: str,
        action: str,
        amount: int,
        admin_id: int,
        reason: str = "Banker Vault Operation",
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Directly add, remove, or set club vault balances (Banker / Admin operation)."""
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'.", {}

        if action in ("add", "remove") and amount <= 0:
            return False, "Amount must be greater than 0.", {}
        if action == "set" and amount < 0:
            return False, "Balance cannot be set to a negative number.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=admin_id)
            if not club:
                return False, f"Club '{club_query}' not found in BeastlyFC.", {}

            treasury_col = f"treasury_{currency}"
            current_val = club[treasury_col]

            if action == "add":
                new_val = current_val + amount
            elif action == "remove":
                if current_val < amount:
                    return False, f"Club vault has insufficient {currency}! Available: {current_val:,}, requested deduction: {amount:,}.", {}
                new_val = current_val - amount
            elif action == "set":
                new_val = amount
            else:
                return False, f"Invalid action '{action}'. Must be 'add', 'remove', or 'set'.", {}

            await cur.execute(
                f"UPDATE clubs SET {treasury_col} = ? WHERE id = ?;",
                (new_val, club["id"]),
            )

            tx_type = f"banker_vault_{action}"
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, ?, ?, ?, ?);
                """,
                (guild_id, admin_id, currency, amount, tx_type, f"Banker Vault {action.upper()} [{club['tag']}]: {reason}"),
            )
            await conn.commit()

            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club["id"],))
            updated_club = dict(await cur.fetchone())
            return True, f"Successfully updated [{club['tag']}] {club['name']} vault!", {
                "club": updated_club,
                "currency": currency,
                "action": action,
                "amount": amount,
                "previous": current_val,
                "new_balance": new_val,
            }

    async def set_club_manager(
        self, club_id: int, owner_id: int, target_user_id: int, is_manager: bool, is_admin: bool = False
    ) -> Tuple[bool, str]:
        """Promote or demote a club member to/from Manager role (Owner or Admin)."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT owner_id, tag, name FROM clubs WHERE id = ?;", (club_id,))
            club = await cur.fetchone()
            if not club:
                return False, "Club not found."
            if not is_admin and club["owner_id"] != owner_id:
                return False, "Only the Club Owner can assign or remove Club Managers."

            if target_user_id == owner_id:
                return False, "The Club Owner already has full management privileges."

            await cur.execute(
                "SELECT * FROM club_members WHERE club_id = ? AND user_id = ?;",
                (club_id, target_user_id),
            )
            target = await cur.fetchone()
            if not target:
                return False, "That player is not a member of your club!"

            new_role = "Manager" if is_manager else "Member"
            await cur.execute(
                "UPDATE club_members SET role = ? WHERE club_id = ? AND user_id = ?;",
                (new_role, club_id, target_user_id),
            )
            await conn.commit()
            action = "promoted to **Club Manager**" if is_manager else "returned to **Squad Member**"
            return True, f"<@{target_user_id}> has been {action} for **[{club['tag']}] {club['name']}**."

    async def admin_set_club_manager(
        self,
        guild_id: int,
        club_query: Any,
        target_user_id: int,
        is_manager: bool,
        admin_id: int,
        reason: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Staff/Banker command to assign or remove Club Managers with zero data loss.
        Guarantees that user currency balances, club treasuries, squad players,
        and transaction history remain 100% intact.
        """
        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=admin_id)
        if not club:
            return False, "Club not found. Please provide a valid club role mention, tag, or name.", None

        club_id = club["id"]
        # Ensure target user account exists in DB (balances untouched)
        await self.get_or_create_user(target_user_id, guild_id)

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Re-fetch latest club record
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club_data = await cur.fetchone()
            if not club_data:
                return False, "Club record could not be found in database.", None

            owner_id = club_data["owner_id"]
            tag = club_data["tag"]
            name = club_data["name"]

            # Owner check
            if target_user_id == owner_id:
                if is_manager:
                    return False, f"<@{target_user_id}> is already the **Club Owner** of **[{tag}] {name}** (Owners already possess full managerial authority).", dict(club_data)
                else:
                    return False, f"Cannot remove management permissions from the **Club Owner** (<@{target_user_id}>)! Club ownership must be transferred, not demoted.", dict(club_data)

            # Check target's membership in THIS club
            await cur.execute(
                "SELECT * FROM club_members WHERE club_id = ? AND user_id = ?;",
                (club_id, target_user_id),
            )
            member = await cur.fetchone()

            if is_manager:
                # ADDING / APPOINTING MANAGER
                if member:
                    current_role = member["role"]
                    if current_role == "Manager":
                        return False, f"<@{target_user_id}> is already a **Club Manager** for **[{tag}] {name}**.", dict(club_data)
                    # Promote existing member to Manager (keeps join date, player attributes, etc.)
                    await cur.execute(
                        "UPDATE club_members SET role = 'Manager' WHERE club_id = ? AND user_id = ?;",
                        (club_id, target_user_id),
                    )
                else:
                    # Target is not currently in this club. Check if they belong to another club in this guild.
                    await cur.execute(
                        """
                        SELECT c.id, c.tag, c.name, cm.role
                        FROM club_members cm
                        JOIN clubs c ON cm.club_id = c.id
                        WHERE cm.guild_id = ? AND cm.user_id = ?;
                        """,
                        (guild_id, target_user_id),
                    )
                    other_club = await cur.fetchone()
                    if other_club:
                        return (
                            False,
                            f"<@{target_user_id}> is currently enrolled in another club: **[{other_club['tag']}] {other_club['name']}** (Role: `{other_club['role']}`). "
                            f"To prevent data conflicts or accidental loss, they must leave or be transferred from their current club before being appointed as Manager here.",
                            dict(club_data),
                        )
                    # Free agent: enroll into this club directly as Manager
                    await cur.execute(
                        """
                        INSERT INTO club_members (club_id, user_id, guild_id, role)
                        VALUES (?, ?, ?, 'Manager');
                        """,
                        (club_id, target_user_id, guild_id),
                    )

                action_str = "promoted to **Club Manager**"
            else:
                # REMOVING / DEMOTING MANAGER
                if not member:
                    return False, f"<@{target_user_id}> is not a member of **[{tag}] {name}**.", dict(club_data)

                current_role = member["role"]
                if current_role != "Manager":
                    return False, f"<@{target_user_id}> is not currently a Club Manager for **[{tag}] {name}** (Current role: `{current_role}`).", dict(club_data)

                # Demote back to Member without touching anything else
                await cur.execute(
                    "UPDATE club_members SET role = 'Member' WHERE club_id = ? AND user_id = ?;",
                    (club_id, target_user_id),
                )
                action_str = "demoted from Club Manager to **Squad Member**"

            # Log administrative action to transaction audit log
            memo = f"Admin Manager Update: {action_str} in [{tag}] {name} by Admin #{admin_id}"
            if reason:
                memo += f" ({reason})"
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', 0, 'admin_manager_change', ?);
                """,
                (guild_id, admin_id, target_user_id, memo),
            )
            await conn.commit()

            club_dict = dict(club_data)
            role_mention = f"<@&{club_dict['role_id']}>" if club_dict.get("role_id") else f"**[{tag}] {name}**"
            msg = f"<@{target_user_id}> has been successfully {action_str} for {role_mention} (Zero data loss: balances, squad, and treasury 100% preserved)."
            return True, msg, club_dict

    async def admin_set_club_owner(
        self,
        guild_id: int,
        club_query: Any,
        new_owner_id: int,
        admin_id: int,
        reason: Optional[str] = None,
        is_add_action: bool = False,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Staff/Banker command to assign (add) or transfer (change) Club Owner with zero data loss.
        Guarantees that former and new owner's personal balances, club treasuries,
        squad players, and transaction history remain 100% intact.
        """
        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=0)
        if not club:
            return False, "Club not found. Please provide a valid club role mention, tag, or name.", None

        club_id = club["id"]
        # Ensure target new owner account exists in DB (balances untouched)
        await self.get_or_create_user(new_owner_id, guild_id)

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Re-fetch latest club record
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club_data = await cur.fetchone()
            if not club_data:
                return False, "Club record could not be found in database.", None

            old_owner_id = club_data["owner_id"]
            tag = club_data["tag"]
            name = club_data["name"]

            # If user is already the owner of this club
            if new_owner_id == old_owner_id and old_owner_id != 0:
                return False, f"<@{new_owner_id}> is already the **Club Owner** of **[{tag}] {name}**.", dict(club_data)

            # Check if target user is already the owner of another club in this guild
            await cur.execute(
                "SELECT id, tag, name FROM clubs WHERE guild_id = ? AND owner_id = ? AND id != ?;",
                (guild_id, new_owner_id, club_id),
            )
            other_owned_club = await cur.fetchone()
            if other_owned_club:
                return (
                    False,
                    f"<@{new_owner_id}> is already the owner of another club: **[{other_owned_club['tag']}] {other_owned_club['name']}**. "
                    f"A user cannot own multiple clubs simultaneously.",
                    dict(club_data),
                )

            # Check if target user belongs to another club in this guild
            await cur.execute(
                """
                SELECT c.id, c.tag, c.name, cm.role
                FROM club_members cm
                JOIN clubs c ON cm.club_id = c.id
                WHERE cm.guild_id = ? AND cm.user_id = ? AND cm.club_id != ?;
                """,
                (guild_id, new_owner_id, club_id),
            )
            other_club = await cur.fetchone()
            if other_club:
                return (
                    False,
                    f"<@{new_owner_id}> is currently enrolled in another club: **[{other_club['tag']}] {other_club['name']}** (Role: `{other_club['role']}`). "
                    f"To prevent data conflicts or accidental squad disruption, they must leave or be transferred from their current club before becoming Club Owner here.",
                    dict(club_data),
                )

            # Check if target user is already in THIS club
            await cur.execute(
                "SELECT * FROM club_members WHERE club_id = ? AND user_id = ?;",
                (club_id, new_owner_id),
            )
            existing_member = await cur.fetchone()

            # Demote former owner to Member in club_members if valid
            if old_owner_id != 0 and old_owner_id != new_owner_id:
                await cur.execute(
                    "UPDATE club_members SET role = 'Member' WHERE club_id = ? AND user_id = ?;",
                    (club_id, old_owner_id),
                )

            # Promote or insert new owner in club_members
            if existing_member:
                await cur.execute(
                    "UPDATE club_members SET role = 'Owner' WHERE club_id = ? AND user_id = ?;",
                    (club_id, new_owner_id),
                )
            else:
                await cur.execute(
                    """
                    INSERT INTO club_members (club_id, user_id, guild_id, role)
                    VALUES (?, ?, ?, 'Owner');
                    """,
                    (club_id, new_owner_id, guild_id),
                )

            # Update owner_id on club
            await cur.execute(
                "UPDATE clubs SET owner_id = ? WHERE id = ?;",
                (new_owner_id, club_id),
            )

            # Determine action text and audit tx_type
            if old_owner_id == 0:
                action_str = "appointed as **Club Owner**"
                tx_type = "admin_owner_add"
                memo = f"Admin Owner Assignment: Appointed <@{new_owner_id}> as Owner of [{tag}] {name} by Admin #{admin_id}"
            else:
                action_str = f"transferred ownership from <@{old_owner_id}> to <@{new_owner_id}>"
                tx_type = "admin_owner_change"
                memo = f"Admin Owner Transfer: Changed Owner of [{tag}] {name} from #{old_owner_id} to #{new_owner_id} by Admin #{admin_id}"

            if reason:
                memo += f" ({reason})"

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', 0, ?, ?);
                """,
                (guild_id, admin_id, new_owner_id, tx_type, memo),
            )
            await conn.commit()

            club_dict = dict(club_data)
            club_dict["owner_id"] = new_owner_id
            club_dict["former_owner_id"] = old_owner_id

            role_mention = f"<@&{club_dict['role_id']}>" if club_dict.get("role_id") else f"**[{tag}] {name}**"
            msg = f"Successfully {action_str} for {role_mention} (Zero data loss: balances, squad, and treasury 100% preserved)."
            return True, msg, club_dict

    async def admin_remove_club_owner(
        self,
        guild_id: int,
        club_query: Any,
        admin_id: int,
        reason: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Staff/Banker command to vacate/remove a club owner with zero data loss.
        Former owner's balances, club treasury, and squad remain 100% preserved.
        """
        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=0)
        if not club:
            return False, "Club not found. Please provide a valid club role mention, tag, or name.", None

        club_id = club["id"]
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club_data = await cur.fetchone()
            if not club_data:
                return False, "Club record could not be found in database.", None

            old_owner_id = club_data["owner_id"]
            tag = club_data["tag"]
            name = club_data["name"]

            if old_owner_id == 0:
                return False, f"**[{tag}] {name}** currently has no assigned owner.", dict(club_data)

            # Demote former owner to Member in club_members so they keep their membership and player card
            await cur.execute(
                "UPDATE club_members SET role = 'Member' WHERE club_id = ? AND user_id = ?;",
                (club_id, old_owner_id),
            )

            # Vacate ownership
            await cur.execute(
                "UPDATE clubs SET owner_id = 0 WHERE id = ?;",
                (club_id,),
            )

            memo = f"Admin Owner Vacate: Removed <@{old_owner_id}> as Owner of [{tag}] {name} by Admin #{admin_id}"
            if reason:
                memo += f" ({reason})"

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', 0, 'admin_owner_remove', ?);
                """,
                (guild_id, admin_id, old_owner_id, memo),
            )
            await conn.commit()

            club_dict = dict(club_data)
            club_dict["former_owner_id"] = old_owner_id
            club_dict["owner_id"] = 0

            role_mention = f"<@&{club_dict['role_id']}>" if club_dict.get("role_id") else f"**[{tag}] {name}**"
            msg = f"<@{old_owner_id}> has been removed as owner of {role_mention} (Ownership is now vacant; treasury and squad 100% preserved)."
            return True, msg, club_dict

    async def admin_delete_club(
        self,
        guild_id: int,
        club_query: Any,
        admin_id: int,
        reason: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        Staff/Banker command to delete/disband a club completely.
        Ensures members' personal balances are untouched, and squad/club records are cleanly cleaned up.
        """
        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=0)
        if not club:
            return False, "Club not found. Please provide a valid club role mention, tag, or name.", None

        club_id = club["id"]
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club_id,))
            club_data = await cur.fetchone()
            if not club_data:
                return False, "Club record could not be found in database.", None

            tag = club_data["tag"]
            name = club_data["name"]
            owner_id = club_data["owner_id"]

            # Count members and players for reporting
            await cur.execute("SELECT COUNT(*) as cnt FROM club_members WHERE club_id = ?;", (club_id,))
            member_count = (await cur.fetchone())["cnt"]
            await cur.execute("SELECT COUNT(*) as cnt FROM club_players WHERE club_id = ?;", (club_id,))
            player_count = (await cur.fetchone())["cnt"]

            # Delete players, members, and the club
            await cur.execute("DELETE FROM club_players WHERE club_id = ?;", (club_id,))
            await cur.execute("DELETE FROM club_members WHERE club_id = ?;", (club_id,))
            await cur.execute("DELETE FROM clubs WHERE id = ?;", (club_id,))

            memo = f"Admin Club Delete: Deleted [{tag}] {name} by Admin #{admin_id} ({member_count} members, {player_count} players removed)"
            if reason:
                memo += f" ({reason})"

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', 0, 'admin_club_delete', ?);
                """,
                (guild_id, admin_id, owner_id or admin_id, memo),
            )
            await conn.commit()

            club_dict = dict(club_data)
            msg = f"Club **[{tag}] {name}** has been successfully disbanded by staff ({member_count} members, {player_count} squad registrations removed. Personal balances remain 100% intact)."
            return True, msg, club_dict

    async def get_club_transactions(
        self, club_id: int, guild_id: int, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent transaction history for a club treasury."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT tag, name FROM clubs WHERE id = ?;", (club_id,))
            club = await cur.fetchone()
            tag = club["tag"] if club else ""

            await cur.execute(
                """
                SELECT * FROM transactions
                WHERE guild_id = ? AND (reason LIKE ? OR reason LIKE ? OR tx_type LIKE 'club_%')
                ORDER BY id DESC
                LIMIT ?;
                """,
                (guild_id, f"%#{club_id}%", f"%[{tag}]%", limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_club_leaderboard(self, guild_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get clubs ranked by total treasury wealth."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT c.*, COUNT(cm.user_id) as member_count
                FROM clubs c
                LEFT JOIN club_members cm ON c.id = cm.club_id
                WHERE c.guild_id = ?
                GROUP BY c.id
                ORDER BY (c.treasury_cash + (c.treasury_points * 2) + (c.treasury_tokens * 100)) DESC
                LIMIT ?;
                """,
                (guild_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------ Shop & Inventory ------------------ #

    async def get_shop_items(self, guild_id: int, include_inactive: bool = False) -> List[Dict[str, Any]]:
        """Get items in the BeastlyBank server shop."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            if include_inactive:
                await cur.execute(
                    """
                    SELECT * FROM shop_items
                    WHERE guild_id = ? OR guild_id = 0
                    ORDER BY id ASC;
                    """,
                    (guild_id,),
                )
            else:
                await cur.execute(
                    """
                    SELECT * FROM shop_items
                    WHERE (guild_id = ? OR guild_id = 0) AND (is_active = 1 OR is_active IS NULL)
                    ORDER BY id ASC;
                    """,
                    (guild_id,),
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def edit_shop_item(
        self,
        guild_id: int,
        item_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        price: Optional[int] = None,
        currency: Optional[str] = None,
        stock: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """Edit an existing shop item."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM shop_items WHERE id = ? AND (guild_id = ? OR guild_id = 0);",
                (item_id, guild_id),
            )
            item = await cur.fetchone()
            if not item:
                return False, f"Shop item #{item_id} not found."

            new_name = name if name is not None else item["name"]
            new_desc = description if description is not None else item["description"]
            new_price = price if price is not None else item["price"]
            new_currency = currency if currency is not None else item["currency"]
            new_stock = stock if stock is not None else item["stock"]

            await cur.execute(
                """
                UPDATE shop_items
                SET name = ?, description = ?, price = ?, currency = ?, stock = ?
                WHERE id = ?;
                """,
                (new_name, new_desc, new_price, new_currency, new_stock, item_id),
            )
            await conn.commit()
            return True, f"Successfully updated item #{item_id} (**{new_name}**)."

    async def toggle_shop_item(self, guild_id: int, item_id: int) -> Tuple[bool, str, bool]:
        """Toggle active status of a shop item."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM shop_items WHERE id = ? AND (guild_id = ? OR guild_id = 0);",
                (item_id, guild_id),
            )
            item = await cur.fetchone()
            if not item:
                return False, f"Shop item #{item_id} not found.", False

            curr_status = item["is_active"] if "is_active" in item.keys() and item["is_active"] is not None else 1
            new_status = 0 if curr_status == 1 else 1

            await cur.execute(
                "UPDATE shop_items SET is_active = ? WHERE id = ?;",
                (new_status, item_id),
            )
            await conn.commit()
            status_text = "enabled" if new_status == 1 else "disabled"
            return True, f"Shop item #{item_id} (**{item['name']}**) is now **{status_text}**.", bool(new_status)

    async def buy_item(
        self, user_id: int, guild_id: int, item_id: int, quantity: int = 1
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Purchase an item from the BeastlyBank Shop."""
        if quantity <= 0:
            return False, "Quantity must be at least 1.", None

        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM shop_items WHERE id = ?;", (item_id,))
            item = await cur.fetchone()
            if not item:
                return False, f"Shop item #{item_id} not found.", None

            # Check stock
            if item["stock"] != -1 and item["stock"] < quantity:
                return False, f"Only {item['stock']} in stock.", None

            total_cost = item["price"] * quantity
            currency = item["currency"]

            # Check user balance
            user = await self.get_or_create_user(user_id, guild_id)
            if user[currency] < total_cost:
                return False, f"Insufficient {currency}! Cost: {total_cost:,}, Available: {user[currency]:,}.", None

            # Deduct cost
            await cur.execute(
                f"UPDATE users SET {currency} = {currency} - ? WHERE user_id = ? AND guild_id = ?;",
                (total_cost, user_id, guild_id),
            )

            # Reduce stock if limited
            if item["stock"] != -1:
                await cur.execute(
                    "UPDATE shop_items SET stock = stock - ? WHERE id = ?;",
                    (quantity, item_id),
                )

            # Add to inventory
            await cur.execute(
                """
                INSERT INTO inventory (user_id, guild_id, item_id, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, guild_id, item_id)
                DO UPDATE SET quantity = quantity + excluded.quantity;
                """,
                (user_id, guild_id, item_id, quantity),
            )

            # Record transaction
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, ?, ?, 'shop_purchase', ?);
                """,
                (guild_id, user_id, currency, total_cost, f"Shop Purchase: {quantity}x {item['name']}"),
            )

            await conn.commit()
            return True, f"Purchased **{quantity}x {item['name']}** for {total_cost:,} {currency}!", dict(item)

    async def get_inventory(self, user_id: int, guild_id: int) -> List[Dict[str, Any]]:
        """Fetch items in a user's BeastlyBank inventory."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT inv.*, si.name, si.description, si.category, si.role_reward_id
                FROM inventory inv
                JOIN shop_items si ON inv.item_id = si.id
                WHERE inv.user_id = ? AND inv.guild_id = ? AND inv.quantity > 0
                ORDER BY inv.acquired_at DESC;
                """,
                (user_id, guild_id),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------ Giveaways ------------------ #

    async def create_giveaway(
        self,
        message_id: int,
        channel_id: int,
        guild_id: int,
        host_id: int,
        prize_name: str,
        prize_currency: Optional[str],
        prize_amount: int,
        winner_count: int,
        end_time: str,
    ) -> None:
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO giveaways (
                    message_id, channel_id, guild_id, host_id, prize_name,
                    prize_currency, prize_amount, winner_count, end_time, status, entries
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', '[]');
                """,
                (
                    message_id,
                    channel_id,
                    guild_id,
                    host_id,
                    prize_name,
                    prize_currency,
                    prize_amount,
                    winner_count,
                    end_time,
                ),
            )
            await conn.commit()

    async def toggle_giveaway_entry(
        self, message_id: int, user_id: int
    ) -> Tuple[bool, str, int]:
        """Add or remove a user's entry for a giveaway."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM giveaways WHERE message_id = ? AND status = 'active';",
                (message_id,),
            )
            gw = await cur.fetchone()
            if not gw:
                return False, "This giveaway is no longer active.", 0

            entries: List[int] = json.loads(gw["entries"])
            if user_id in entries:
                entries.remove(user_id)
                entered = False
                msg = "You have left the giveaway."
            else:
                entries.append(user_id)
                entered = True
                msg = "You have entered the BeastlyBank giveaway! Good luck!"

            await cur.execute(
                "UPDATE giveaways SET entries = ? WHERE message_id = ?;",
                (json.dumps(entries), message_id),
            )
            await conn.commit()
            return True, msg, len(entries)

    async def end_giveaway(
        self, message_id: int
    ) -> Tuple[bool, str, List[int], Dict[str, Any]]:
        """End a giveaway, pick winners, and credit accounts if currency prize."""
        import random

        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM giveaways WHERE message_id = ?;",
                (message_id,),
            )
            gw = await cur.fetchone()
            if not gw:
                return False, "Giveaway not found.", [], {}

            gw_dict = dict(gw)
            if gw_dict["status"] != "active":
                return False, "Giveaway has already concluded.", [], gw_dict

            entries: List[int] = json.loads(gw_dict["entries"])
            winner_count = min(gw_dict["winner_count"], len(entries))

            winners = []
            if entries:
                winners = random.sample(entries, winner_count)

            await cur.execute(
                "UPDATE giveaways SET status = 'ended', winners = ? WHERE message_id = ?;",
                (json.dumps(winners), message_id),
            )

            # If currency prize, automatically disburse into winners' BeastlyBank accounts!
            if gw_dict.get("prize_currency") and gw_dict.get("prize_amount", 0) > 0 and winners:
                currency = gw_dict["prize_currency"]
                amount_each = gw_dict["prize_amount"]
                guild_id = gw_dict["guild_id"]

                for w_id in winners:
                    await self.get_or_create_user(w_id, guild_id)
                    await cur.execute(
                        f"UPDATE users SET {currency} = {currency} + ? WHERE user_id = ? AND guild_id = ?;",
                        (amount_each, w_id, guild_id),
                    )
                    await cur.execute(
                        """
                        INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                        VALUES (?, NULL, ?, ?, ?, 'giveaway_win', ?);
                        """,
                        (guild_id, w_id, currency, amount_each, f"Won Giveaway: {gw_dict['prize_name']}"),
                    )

            await conn.commit()
            return True, "Giveaway concluded.", winners, gw_dict

    async def get_active_giveaways(self) -> List[Dict[str, Any]]:
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM giveaways WHERE status = 'active';")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------ Admin & Auditing ------------------ #

    async def admin_set_balance(
        self,
        user_id: int,
        guild_id: int,
        currency: str,
        amount: int,
        reason: str,
        admin_id: int,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Admin override of user balance."""
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'.", {}
        if amount < 0:
            return False, "Balance cannot be set to a negative number.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            await self.get_or_create_user(user_id, guild_id)
            await cur.execute(
                f"UPDATE users SET {currency} = ? WHERE user_id = ? AND guild_id = ?;",
                (amount, user_id, guild_id),
            )
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, ?, ?, 'admin_set', ?);
                """,
                (guild_id, admin_id, user_id, currency, amount, f"Admin Adjustment by <@{admin_id}>: {reason}"),
            )
            await conn.commit()

        updated = await self.get_or_create_user(user_id, guild_id)
        return True, f"Updated <@{user_id}>'s {currency} balance to {amount:,}.", updated

    async def bulk_role_grant(
        self,
        guild_id: int,
        user_ids: List[int],
        currency: str,
        amount: int,
        reason: str,
        admin_id: int,
        role_name: str = "Role",
    ) -> Tuple[bool, str, int]:
        """Batch credit currency to all specified user IDs atomically in a single database transaction."""
        if currency not in ("cash", "points", "tokens"):
            return False, f"Invalid currency '{currency}'.", 0
        if amount <= 0:
            return False, "Grant amount must be greater than 0.", 0
        if not user_ids:
            return False, "No eligible user IDs provided for role grant.", 0

        conn = await self.connect()
        async with conn.cursor() as cur:
            for uid in user_ids:
                await cur.execute(
                    """
                    INSERT OR IGNORE INTO users (user_id, guild_id, cash, points, tokens, daily_streak)
                    VALUES (?, ?, 0, 0, 0, 0);
                    """,
                    (uid, guild_id),
                )
                await cur.execute(
                    f"""
                    UPDATE users
                    SET {currency} = {currency} + ?
                    WHERE user_id = ? AND guild_id = ?;
                    """,
                    (amount, uid, guild_id),
                )
                memo = f"Role Grant [{role_name}] by <@{admin_id}>: {reason}"
                await cur.execute(
                    """
                    INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                    VALUES (?, NULL, ?, ?, ?, 'role_grant', ?);
                    """,
                    (guild_id, uid, currency, amount, memo),
                )
            await conn.commit()

        return True, f"Successfully granted {amount:,} {currency} to {len(user_ids)} members!", len(user_ids)

    # ------------------ Server Settings ------------------ #

    async def get_settings(self, guild_id: int) -> Dict[str, Any]:
        """Fetch server settings for economy, purchases, and shop."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM server_settings WHERE guild_id = ?;", (guild_id,)
            )
            row = await cur.fetchone()
            if row:
                return dict(row)

            # Initialize defaults
            await cur.execute(
                """
                INSERT INTO server_settings (guild_id, economy_enabled, purchases_enabled, shop_enabled)
                VALUES (?, 1, 1, 1);
                """,
                (guild_id,),
            )
            await conn.commit()
            return {
                "guild_id": guild_id,
                "economy_enabled": 1,
                "purchases_enabled": 1,
                "shop_enabled": 1,
            }

    async def update_setting(
        self, guild_id: int, setting_key: str, enabled: bool
    ) -> Tuple[bool, str]:
        """Toggle an economy/shop setting on or off."""
        valid_keys = {
            "economy": "economy_enabled",
            "economy_enabled": "economy_enabled",
            "purchases": "purchases_enabled",
            "purchases_enabled": "purchases_enabled",
            "shop": "shop_enabled",
            "shop_enabled": "shop_enabled",
        }
        actual_col = valid_keys.get(setting_key)
        if not actual_col:
            return False, f"Invalid setting '{setting_key}'. Must be 'economy', 'purchases', or 'shop'."

        conn = await self.connect()
        async with conn.cursor() as cur:
            await self.get_settings(guild_id)
            int_val = 1 if enabled else 0
            await cur.execute(
                f"UPDATE server_settings SET {actual_col} = ? WHERE guild_id = ?;",
                (int_val, guild_id),
            )
            await conn.commit()
            label = actual_col.replace("_enabled", "").title()
            state = "ENABLED ✅" if enabled else "DISABLED ❌"
            return True, f"**{label}** is now **{state}** in BeastlyFC."

    async def get_economy_stats(self, guild_id: int) -> Dict[str, Any]:
        """Fetch overall server economy metrics for BeastlyFC."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            # Total users & circulating cash
            await cur.execute(
                """
                SELECT COUNT(*) as total_users,
                       COALESCE(SUM(cash), 0) as total_cash,
                       COALESCE(SUM(points), 0) as total_points,
                       COALESCE(SUM(tokens), 0) as total_tokens
                FROM users WHERE guild_id = ?;
                """,
                (guild_id,),
            )
            u_row = await cur.fetchone()

            # Total clubs & vault cash
            await cur.execute(
                """
                SELECT COUNT(*) as total_clubs,
                       COALESCE(SUM(treasury_cash), 0) as total_vault_cash
                FROM clubs WHERE guild_id = ?;
                """,
                (guild_id,),
            )
            c_row = await cur.fetchone()

            # Total transactions
            await cur.execute(
                "SELECT COUNT(*) as total_txs FROM transactions WHERE guild_id = ?;",
                (guild_id,),
            )
            tx_row = await cur.fetchone()

            # Total custom players registered
            await cur.execute(
                "SELECT COUNT(*) as total_players FROM club_players WHERE guild_id = ?;",
                (guild_id,),
            )
            p_row = await cur.fetchone()

            user_cash = u_row["total_cash"] if u_row else 0
            vault_cash = c_row["total_vault_cash"] if c_row else 0

            return {
                "total_users": u_row["total_users"] if u_row else 0,
                "total_cash": user_cash + vault_cash,
                "user_cash": user_cash,
                "vault_cash": vault_cash,
                "total_points": u_row["total_points"] if u_row else 0,
                "total_tokens": u_row["total_tokens"] if u_row else 0,
                "total_clubs": c_row["total_clubs"] if c_row else 0,
                "total_txs": tx_row["total_txs"] if tx_row else 0,
                "total_players": p_row["total_players"] if p_row else 0,
            }

    # ==========================================
    # SQUAD & LINEUP MANAGEMENT
    # ==========================================

    async def add_club_player(
        self,
        guild_id: int,
        club_query: Any,
        player_name: str,
        position: str = "ST",
        status: str = "starting",
        number: Optional[int] = None,
        rating: Optional[int] = 75,
        potential: Optional[int] = 80,
        alt_positions: Optional[str] = None,
        user_id: Optional[int] = None,
        default_owner_id: int = 0,
        wage: Optional[Union[int, str]] = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Add a player to a club squad (Starting XI or Bench).
        Accepts custom player name or Discord user mention/ID.
        """
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty.", {}

        w_val = parse_wage_to_int(wage)

        uid = user_id
        if not uid:
            if p_name.startswith("<@") and p_name.endswith(">"):
                raw_id = p_name.strip("<@!>")
                if raw_id.isdigit():
                    uid = int(raw_id)
            elif p_name.isdigit() and len(p_name) >= 15:
                uid = int(p_name)

        pos = position.upper().strip()
        if pos not in VALID_POSITIONS:
            return False, f"Invalid position '{position}'. Valid positions are: {', '.join(VALID_POSITIONS)}.", {}

        st = status.lower().strip()
        if st not in ("starting", "bench"):
            return False, "Invalid status. Must be either 'starting' (Starting XI) or 'bench' (Substitutes).", {}

        if number is not None and (number < 0 or number > 99):
            return False, "Jersey number must be between 0 and 99.", {}

        # Rating and Potential validation (1-99)
        r_val = rating if rating is not None else 75
        if r_val < 1 or r_val > 99:
            return False, "Player rating must be between 1 and 99.", {}

        pot_val = potential if potential is not None else max(r_val, 80)
        if pot_val < 1 or pot_val > 99:
            return False, "Player potential must be between 1 and 99.", {}

        # Clean alternate positions (e.g. 'pos1, pos2, pos3, .....')
        clean_alt = normalize_alt_positions(alt_positions, primary_pos=pos)

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            if st == "starting":
                await cur.execute(
                    "SELECT COUNT(*) as cnt FROM club_players WHERE club_id = ? AND status = 'starting';",
                    (club["id"],),
                )
                start_cnt = (await cur.fetchone())["cnt"]
                if start_cnt >= 11:
                    return False, f"Starting XI for **[{club['tag']}] {club['name']}** already has 11 players! Add as `bench` or move a player to the bench first.", {}

            if uid:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND (user_id = ? OR LOWER(player_name) = LOWER(?));",
                    (club["id"], uid, p_name),
                )
            else:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                    (club["id"], p_name),
                )
            existing = await cur.fetchone()
            if existing:
                return False, f"Player **{p_name}** is already in **[{club['tag']}] {club['name']}** squad! Use `/player edit` to change their position or lineup status.", {}

            if uid:
                await cur.execute(
                    """
                    SELECT cp.*, c.name as club_name, c.tag as club_tag
                    FROM club_players cp
                    JOIN clubs c ON cp.club_id = c.id
                    WHERE cp.guild_id = ? AND (cp.user_id = ? OR LOWER(cp.player_name) = LOWER(?));
                    """,
                    (guild_id, uid, p_name),
                )
            else:
                await cur.execute(
                    """
                    SELECT cp.*, c.name as club_name, c.tag as club_tag
                    FROM club_players cp
                    JOIN clubs c ON cp.club_id = c.id
                    WHERE cp.guild_id = ? AND LOWER(cp.player_name) = LOWER(?);
                    """,
                    (guild_id, p_name),
                )
            other_club = await cur.fetchone()
            if other_club:
                return False, f"Player **{p_name}** is currently registered with **[{other_club['club_tag']}] {other_club['club_name']}**! Transfer them using `/transfer` or remove them first.", {}

            await cur.execute(
                """
                INSERT INTO club_players (club_id, guild_id, player_name, role, position, status, number, rating, potential, alt_positions, user_id, wage)
                VALUES (?, ?, ?, 'Player', ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (club["id"], guild_id, p_name, pos, st, number, r_val, pot_val, clean_alt, uid, w_val),
            )
            player_id = cur.lastrowid

            if uid:
                await cur.execute(
                    """
                    INSERT OR IGNORE INTO club_members (club_id, user_id, guild_id, role)
                    VALUES (?, ?, ?, 'Member');
                    """,
                    (club["id"], uid, guild_id),
                )

            await conn.commit()

            await cur.execute("SELECT * FROM club_players WHERE id = ?;", (player_id,))
            new_p = await cur.fetchone()
            num_str = f" #{number}" if number is not None else ""
            status_desc = "Starting XI 🟢" if st == "starting" else "Bench 🟡"
            alt_desc = f" | Alt: {clean_alt}" if clean_alt else ""
            wage_desc = f" | Wage: {format_wage(w_val)}/MD" if w_val > 0 else ""
            return True, f"Added **{p_name}**{num_str} ({r_val} OVR / {pot_val} POT) as **{pos}**{alt_desc}{wage_desc} ({status_desc}) to **[{club['tag']}] {club['name']}**!", dict(new_p)

    async def edit_club_player(
        self,
        guild_id: int,
        club_query: Any,
        player_name: str,
        new_name: Optional[str] = None,
        position: Optional[str] = None,
        status: Optional[str] = None,
        number: Optional[int] = None,
        rating: Optional[int] = None,
        potential: Optional[int] = None,
        alt_positions: Optional[str] = None,
        default_owner_id: int = 0,
        wage: Optional[Union[int, str]] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Edit an existing player's details (name, position, lineup status, jersey number, rating, potential, alt positions, wage).
        """
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty.", {}

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found.", {}

        uid = None
        if p_name.startswith("<@") and p_name.endswith(">"):
            raw_id = p_name.strip("<@!>")
            if raw_id.isdigit():
                uid = int(raw_id)
        elif p_name.isdigit() and len(p_name) >= 15:
            uid = int(p_name)

        conn = await self.connect()
        async with conn.cursor() as cur:
            if uid:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND (user_id = ? OR LOWER(player_name) = LOWER(?));",
                    (club["id"], uid, p_name),
                )
            else:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                    (club["id"], p_name),
                )
            player = await cur.fetchone()
            if not player:
                return False, f"Player **{p_name}** was not found in **[{club['tag']}] {club['name']}** squad.", {}

            updates = []
            params = []
            changes = []

            if new_name is not None and new_name.strip():
                clean_new_name = new_name.strip()
                updates.append("player_name = ?")
                params.append(clean_new_name)
                changes.append(f"Name: **{clean_new_name}**")

            curr_pos = player["position"]
            if position is not None and position.strip():
                pos = position.upper().strip()
                if pos not in VALID_POSITIONS:
                    return False, f"Invalid position '{position}'. Valid positions: {', '.join(VALID_POSITIONS)}.", {}
                updates.append("position = ?")
                params.append(pos)
                changes.append(f"Position: **{pos}**")
                curr_pos = pos

            if status is not None and status.strip():
                st = status.lower().strip()
                if st not in ("starting", "bench"):
                    return False, "Invalid status. Must be either 'starting' (Starting XI) or 'bench' (Substitutes).", {}
                if st == "starting" and player["status"] != "starting":
                    await cur.execute(
                        "SELECT COUNT(*) as cnt FROM club_players WHERE club_id = ? AND status = 'starting';",
                        (club["id"],),
                    )
                    start_cnt = (await cur.fetchone())["cnt"]
                    if start_cnt >= 11:
                        return False, f"Starting XI for **[{club['tag']}] {club['name']}** already has 11 players! Bench another player before moving this player to starting.", {}
                updates.append("status = ?")
                params.append(st)
                changes.append(f"Status: **{'Starting XI 🟢' if st == 'starting' else 'Bench 🟡'}**")

            if number is not None:
                if number < 0 or number > 99:
                    return False, "Jersey number must be between 0 and 99.", {}
                updates.append("number = ?")
                params.append(number)
                changes.append(f"Jersey: **#{number}**")

            if rating is not None:
                if rating < 1 or rating > 99:
                    return False, "Player rating must be between 1 and 99.", {}
                updates.append("rating = ?")
                params.append(rating)
                changes.append(f"Rating: **{rating} OVR**")

            if potential is not None:
                if potential < 1 or potential > 99:
                    return False, "Player potential must be between 1 and 99.", {}
                updates.append("potential = ?")
                params.append(potential)
                changes.append(f"Potential: **{potential} POT**")

            if alt_positions is not None:
                clean_alt = normalize_alt_positions(alt_positions, primary_pos=curr_pos)
                updates.append("alt_positions = ?")
                params.append(clean_alt)
                changes.append(f"Alt Positions: **{clean_alt or 'None'}**")
            elif position is not None and ("alt_positions" in player.keys() and player["alt_positions"]):
                cleaned_existing = normalize_alt_positions(player["alt_positions"], primary_pos=curr_pos)
                if cleaned_existing != player["alt_positions"]:
                    updates.append("alt_positions = ?")
                    params.append(cleaned_existing)

            if wage is not None:
                clean_wage = parse_wage_to_int(wage)
                updates.append("wage = ?")
                params.append(clean_wage)
                changes.append(f"Wage: **{format_wage(clean_wage)}/MD**")

            if not updates:
                return False, "No modifications provided. Specify at least one attribute to edit.", {}

            params.append(player["id"])
            await cur.execute(
                f"UPDATE club_players SET {', '.join(updates)} WHERE id = ?;",
                params,
            )
            await conn.commit()

            await cur.execute("SELECT * FROM club_players WHERE id = ?;", (player["id"],))
            updated = await cur.fetchone()
            return True, f"Updated **{player['player_name']}** ({', '.join(changes)}) in **[{club['tag']}] {club['name']}**!", dict(updated)

    async def remove_club_player(
        self,
        guild_id: int,
        club_query: Any,
        player_name: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str]:
        """Remove a player from a club squad."""
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty."

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found."

        uid = None
        if p_name.startswith("<@") and p_name.endswith(">"):
            raw_id = p_name.strip("<@!>")
            if raw_id.isdigit():
                uid = int(raw_id)
        elif p_name.isdigit() and len(p_name) >= 15:
            uid = int(p_name)

        conn = await self.connect()
        async with conn.cursor() as cur:
            if uid:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND (user_id = ? OR LOWER(player_name) = LOWER(?));",
                    (club["id"], uid, p_name),
                )
            else:
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                    (club["id"], p_name),
                )
            player = await cur.fetchone()
            if not player:
                return False, f"Player **{p_name}** not found in **[{club['tag']}] {club['name']}** squad."

            await cur.execute("DELETE FROM club_players WHERE id = ?;", (player["id"],))
            await conn.commit()
            return True, f"Player **{player['player_name']}** has been removed from **[{club['tag']}] {club['name']}** squad."

    async def _realign_club_starters(self, cur, club_id: int, formation: str) -> List[str]:
        """
        Intelligently align club starting XI players to the tactical slots of the given formation.
        Resolves duplicate positions (e.g. multiple CAMs in 4-2-1-3) into their required slots (LW, CAM, RW).
        """
        from collections import Counter
        clean_form = str(formation).lower().replace("-", "").replace(" ", "")
        matched = None
        for k in SUPPORTED_FORMATIONS:
            if k.lower() == str(formation).lower() or k.lower().replace("-", "").replace(" ", "") == clean_form:
                matched = k
                break
        if not matched:
            if clean_form in ("4213", "4213attack", "4231attack"):
                matched = "4-2-1-3"
            else:
                matched = DEFAULT_FORMATION

        target_slots = get_formation_positions(matched)
        if not target_slots:
            return []

        await cur.execute(
            "SELECT * FROM club_players WHERE club_id = ? AND status = 'starting' ORDER BY id ASC;",
            (club_id,),
        )
        starters = [dict(r) for r in await cur.fetchall()]
        if not starters:
            return []

        target_counts = Counter(target_slots)
        current_counts = Counter((p.get("position") or "").upper() for p in starters)

        if current_counts == target_counts:
            return []

        available_slots = list(target_slots)
        assigned_players: Dict[int, str] = {}
        unassigned_players: List[Dict[str, Any]] = []

        # Special tactical handling for 4-2-1-3 with multiple CAMs:
        # In 4-2-1-3, exactly 1 CAM, 1 LW, 1 RW are needed.
        # Intelligently map multiple CAMs into wings (LW/RW) and central CAM.
        if matched == "4-2-1-3":
            cams = [p for p in starters if (p.get("position") or "").upper() == "CAM"]
            if len(cams) > 1 and ("LW" in available_slots or "RW" in available_slots):
                for p in cams:
                    alts = [a.strip().upper() for a in (p.get("alt_positions") or "").replace("/", ",").replace(";", ",").split(",") if a.strip()]
                    if "LW" in alts and "LW" in available_slots and p["id"] not in assigned_players:
                        assigned_players[p["id"]] = "LW"
                        available_slots.remove("LW")
                    elif "RW" in alts and "RW" in available_slots and p["id"] not in assigned_players:
                        assigned_players[p["id"]] = "RW"
                        available_slots.remove("RW")

                remaining_cams = [p for p in cams if p["id"] not in assigned_players]
                for p in remaining_cams:
                    if "LW" in available_slots:
                        assigned_players[p["id"]] = "LW"
                        available_slots.remove("LW")
                    elif "CAM" in available_slots:
                        assigned_players[p["id"]] = "CAM"
                        available_slots.remove("CAM")
                    elif "RW" in available_slots:
                        assigned_players[p["id"]] = "RW"
                        available_slots.remove("RW")

        # Phase 1: Keep players whose current position is directly in available slots
        for p in starters:
            if p["id"] in assigned_players:
                continue
            pos = (p.get("position") or "").upper()
            if pos in available_slots:
                assigned_players[p["id"]] = pos
                available_slots.remove(pos)
            else:
                unassigned_players.append(p)

        # Phase 2: Match unassigned players using alternate positions
        still_unassigned = []
        for p in unassigned_players:
            alts_str = p.get("alt_positions") or ""
            alts = [a.strip().upper() for a in alts_str.replace(";", ",").replace("/", ",").split(",") if a.strip()]
            matched_alt = None
            for alt in alts:
                if alt in available_slots:
                    matched_alt = alt
                    break
            if matched_alt:
                assigned_players[p["id"]] = matched_alt
                available_slots.remove(matched_alt)
            else:
                still_unassigned.append(p)

        # Phase 3: Tactical role & category match
        final_unassigned = []
        for p in still_unassigned:
            cur_pos = (p.get("position") or "").upper()
            cur_cat = POSITION_CATEGORIES.get(cur_pos)
            cat_match = None
            for slot in available_slots:
                if POSITION_CATEGORIES.get(slot) == cur_cat:
                    cat_match = slot
                    break
            if cat_match:
                assigned_players[p["id"]] = cat_match
                available_slots.remove(cat_match)
            else:
                final_unassigned.append(p)

        # Phase 4: Assign any remaining available slots
        for p in final_unassigned:
            if available_slots:
                slot = available_slots.pop(0)
                assigned_players[p["id"]] = slot

        # Apply updates to database for players whose position changed
        reassigned = []
        for p in starters:
            new_pos = assigned_players.get(p["id"])
            if new_pos and new_pos != p.get("position"):
                alt_clean = normalize_alt_positions(p.get("alt_positions"), primary_pos=new_pos)
                await cur.execute(
                    "UPDATE club_players SET position = ?, alt_positions = ? WHERE id = ?;",
                    (new_pos, alt_clean, p["id"]),
                )
                reassigned.append(f"• **{p['player_name']}**: `{p.get('position', '??')}` ➔ **`{new_pos}`**")

        return reassigned

    async def set_club_formation(
        self,
        guild_id: int,
        club_query: Any,
        formation: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str]:
        """Set tactical formation for a club and adapt starting XI positions to match new formation slots."""
        form = formation.strip().lower()
        form_clean = form.replace("-", "").replace(" ", "")
        matched = None
        for k in SUPPORTED_FORMATIONS:
            if k.lower() == form:
                matched = k
                break
        if not matched:
            for k in SUPPORTED_FORMATIONS:
                if k.lower().replace("-", "").replace(" ", "") == form_clean:
                    matched = k
                    break
        if not matched:
            aliases = {
                "4213": "4-2-1-3",
                "4213attack": "4-2-1-3",
                "4231attack": "4-2-1-3",
            }
            matched = aliases.get(form_clean)

        if not matched:
            return False, f"Formation '{formation}' is not supported. Supported formations: {', '.join(SUPPORTED_FORMATIONS.keys())}."

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found."

        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE clubs SET formation = ? WHERE id = ?;",
                (matched, club["id"]),
            )

            reassigned = await self._realign_club_starters(cur, club["id"], matched)
            await conn.commit()

        form_meta = SUPPORTED_FORMATIONS[matched]
        msg = f"Formation for **[{club['tag']}] {club['name']}** set to **{matched}** — {form_meta['desc']}."
        if reassigned:
            msg += f"\n\n📋 **Tactical Realignment Applied ({len(reassigned)} players updated):**\n" + "\n".join(reassigned[:11])
        else:
            msg += f"\n\n✅ Starting XI positions already match **{matched}** requirements."
        return True, msg

    async def set_club_branding(
        self,
        guild_id: int,
        club_query: Any,
        kit_primary: Optional[str] = None,
        kit_secondary: Optional[str] = None,
        logo_url: Optional[str] = None,
        slogan_1: Optional[str] = None,
        slogan_2: Optional[str] = None,
        chant: Optional[str] = None,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Update branding settings (kit colors, slogans, logo, chant) for a club."""
        if isinstance(club_query, dict) and "id" in club_query:
            club = club_query
        else:
            club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found.", {}

        updates = []
        params = []
        if kit_primary is not None:
            updates.append("kit_primary = ?")
            params.append(kit_primary)
        if kit_secondary is not None:
            updates.append("kit_secondary = ?")
            params.append(kit_secondary)
        if logo_url is not None:
            updates.append("logo_url = ?")
            params.append(logo_url)
        if slogan_1 is not None:
            updates.append("slogan_1 = ?")
            params.append(slogan_1)
        if slogan_2 is not None:
            updates.append("slogan_2 = ?")
            params.append(slogan_2)
        if chant is not None:
            updates.append("chant = ?")
            params.append(chant)

        if not updates:
            return False, "No branding fields provided to update.", club

        params.append(club["id"])
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE clubs SET {', '.join(updates)} WHERE id = ?;", tuple(params))
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club["id"],))
            updated = await cur.fetchone()
            await conn.commit()
            return True, f"Branding updated for **[{club['tag']}] {club['name']}**.", dict(updated) if updated else club

    async def _resolve_club_player(self, cur, club_id: int, query: str) -> Optional[Dict[str, Any]]:
        """
        Fuzzy and exact resolver for a player in a club.
        Matches by:
        1. Discord mention / user_id
        2. Exact case-insensitive player_name
        3. Word match (e.g. 'Mbappe' matches 'Kylian Mbappe')
        4. Substring / prefix match
        """
        p_name = str(query).strip().strip("'\"")
        if not p_name:
            return None

        # 1. Check mention or raw numeric id
        uid = None
        if p_name.startswith("<@") and p_name.endswith(">"):
            r = p_name.strip("<@!>")
            if r.isdigit():
                uid = int(r)
        elif p_name.isdigit() and len(p_name) >= 15:
            uid = int(p_name)

        if uid:
            await cur.execute(
                "SELECT * FROM club_players WHERE club_id = ? AND (user_id = ? OR LOWER(player_name) = LOWER(?));",
                (club_id, uid, p_name),
            )
            row = await cur.fetchone()
            if row:
                return dict(row)

        # 2. Exact case-insensitive match
        await cur.execute(
            "SELECT * FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
            (club_id, p_name),
        )
        row = await cur.fetchone()
        if row:
            return dict(row)

        # 3. Word match / substring in club squad
        await cur.execute(
            "SELECT * FROM club_players WHERE club_id = ?;",
            (club_id,),
        )
        all_players = [dict(r) for r in await cur.fetchall()]
        q_low = p_name.lower()

        # Check if q_low is one of the individual words in player_name (e.g. 'mbappe' in ['kylian', 'mbappe'])
        word_matches = [
            p for p in all_players
            if q_low in [w.lower() for w in p["player_name"].split()]
        ]
        if len(word_matches) == 1:
            return word_matches[0]

        # Check substring match
        sub_matches = [
            p for p in all_players
            if q_low in p["player_name"].lower()
        ]
        if len(sub_matches) == 1:
            return sub_matches[0]
        elif len(sub_matches) > 1:
            # Prefer prefix match if unique
            pref_matches = [p for p in sub_matches if p["player_name"].lower().startswith(q_low)]
            if len(pref_matches) == 1:
                return pref_matches[0]

        return None

    async def switch_lineup_position(
        self,
        guild_id: int,
        club_query: Any,
        player_query: str,
        new_position: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Switch or change a player's position in a club lineup without losing any user data.
        All stats, rating, potential, number, and attributes remain strictly untouched.
        If another starting player currently occupies the target position, their positions
        are automatically swapped tactically so the XI remains balanced.
        """
        p_name = str(player_query).strip()
        pos = str(new_position).strip().upper()
        if not p_name:
            return False, "Player name or mention must be specified.", {}
        if pos not in VALID_POSITIONS:
            return False, f"Invalid position '{new_position}'. Supported positions: {', '.join(VALID_POSITIONS)}.", {}

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            player = await self._resolve_club_player(cur, club["id"], p_name)
            if not player:
                return False, f"Player **{p_name}** not found in **[{club['tag']}] {club['name']}** squad.", {}

            old_pos = player.get("position", "??")
            if old_pos == pos:
                return True, f"Player **{player['player_name']}** is already positioned as **{pos}**.", player

            # If the player is a starter, check if another starter already holds this position to swap them
            if player.get("status") == "starting":
                await cur.execute(
                    "SELECT * FROM club_players WHERE club_id = ? AND status = 'starting' AND position = ? AND id != ?;",
                    (club["id"], pos, player["id"]),
                )
                occupant = await cur.fetchone()
                if occupant:
                    occupant = dict(occupant)
                    # Swap positions between the two starters
                    await cur.execute(
                        "UPDATE club_players SET position = ? WHERE id = ?;",
                        (old_pos, occupant["id"]),
                    )
                    await cur.execute(
                        "UPDATE club_players SET position = ? WHERE id = ?;",
                        (pos, player["id"]),
                    )
                    await conn.commit()
                    player["position"] = pos
                    return True, (
                        f"🔁 **Lineup Positions Swapped!**\n"
                        f"• **{player['player_name']}**: `{old_pos}` ➔ **`{pos}`**\n"
                        f"• **{occupant['player_name']}**: `{pos}` ➔ **`{old_pos}`**\n"
                        f"• Club: **[{club['tag']}] {club['name']}**\n"
                        f"*(Lineup tactical positions updated, all user data & stats preserved)*"
                    ), player

            # Clean new primary position from alternate positions if it was listed there
            alt_pos = normalize_alt_positions(player.get("alt_positions"), primary_pos=pos)

            await cur.execute(
                "UPDATE club_players SET position = ?, alt_positions = ? WHERE id = ?;",
                (pos, alt_pos, player["id"]),
            )
            await conn.commit()

            player["position"] = pos
            player["alt_positions"] = alt_pos
            return True, (
                f"🔁 **Position Switched!**\n"
                f"• Player: **{player['player_name']}**\n"
                f"• Position: `{old_pos}` ➔ **`{pos}`**\n"
                f"• Status: `{player['status'].capitalize()}`\n"
                f"• Club: **[{club['tag']}] {club['name']}**\n"
                f"*(Attributes rating [{player.get('rating', 75)} OVR], potential [{player.get('potential', 80)} POT] preserved)*"
            ), player


    async def get_club_lineup(
        self,
        guild_id: int,
        club_query: Any,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Fetch current starting XI and bench for a club."""
        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM clubs WHERE id = ?;", (club["id"],))
            c_row = await cur.fetchone()
            if c_row:
                club = dict(c_row)

            # Automatically align starters to club formation (e.g. converting duplicate CAMs to LW/RW in 4-2-1-3)
            await self._realign_club_starters(cur, club["id"], club.get("formation", DEFAULT_FORMATION))
            await conn.commit()

            # Automatically populate wages from SoFIFA cache for squad players with 0 or NULL wage
            try:
                await cur.execute(
                    """
                    SELECT p.id, s.wage FROM club_players p
                    JOIN sofifa_players s ON (
                        LOWER(p.player_name) = LOWER(s.name)
                        OR LOWER(p.player_name) = LOWER(s.full_name)
                    )
                    WHERE p.club_id = ? AND (p.wage IS NULL OR p.wage = 0);
                    """,
                    (club["id"],),
                )
                sofifa_matches = await cur.fetchall()
                for sm in sofifa_matches:
                    w_int = parse_wage_to_int(sm["wage"])
                    if w_int > 0:
                        await cur.execute("UPDATE club_players SET wage = ? WHERE id = ?;", (w_int, sm["id"]))
                if sofifa_matches:
                    await conn.commit()
            except Exception as w_err:
                logger.debug("Auto SoFIFA wage sync notice: %s", w_err)

            await cur.execute(
                """
                SELECT * FROM club_players
                WHERE club_id = ?
                ORDER BY
                    CASE status WHEN 'starting' THEN 1 ELSE 2 END,
                    CASE position
                        WHEN 'GK' THEN 1
                        WHEN 'CB' THEN 2
                        WHEN 'LB' THEN 3
                        WHEN 'RB' THEN 4
                        WHEN 'LWB' THEN 5
                        WHEN 'RWB' THEN 6
                        WHEN 'CDM' THEN 7
                        WHEN 'CM' THEN 8
                        WHEN 'CAM' THEN 9
                        WHEN 'LM' THEN 10
                        WHEN 'RM' THEN 11
                        WHEN 'LW' THEN 12
                        WHEN 'RW' THEN 13
                        WHEN 'CF' THEN 14
                        WHEN 'ST' THEN 15
                        ELSE 16
                    END,
                    id ASC;
                """,
                (club["id"],),
            )
            rows = await cur.fetchall()
            starting = [dict(r) for r in rows if r["status"] == "starting"]
            bench = [dict(r) for r in rows if r["status"] == "bench"]

            return True, "", {
                "club": club,
                "formation": club.get("formation", DEFAULT_FORMATION),
                "starting": starting,
                "bench": bench,
            }

    async def get_player_info(
        self,
        guild_id: int,
        player_name: str,
        club_query: Optional[Any] = None,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Fetch full details and club affiliation for a specific player."""
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty.", {}

        uid = None
        if p_name.startswith("<@") and p_name.endswith(">"):
            raw_id = p_name.strip("<@!>")
            if raw_id.isdigit():
                uid = int(raw_id)
        elif p_name.isdigit() and len(p_name) >= 15:
            uid = int(p_name)

        conn = await self.connect()
        async with conn.cursor() as cur:
            if club_query:
                club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
                if not club:
                    return False, "Specified club not found.", {}
                if uid:
                    await cur.execute(
                        """
                        SELECT cp.*, c.name as club_name, c.tag as club_tag, c.role_id as club_role_id, c.formation
                        FROM club_players cp
                        JOIN clubs c ON cp.club_id = c.id
                        WHERE cp.club_id = ? AND (cp.user_id = ? OR LOWER(cp.player_name) = LOWER(?));
                        """,
                        (club["id"], uid, p_name),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT cp.*, c.name as club_name, c.tag as club_tag, c.role_id as club_role_id, c.formation
                        FROM club_players cp
                        JOIN clubs c ON cp.club_id = c.id
                        WHERE cp.club_id = ? AND LOWER(cp.player_name) = LOWER(?);
                        """,
                        (club["id"], p_name),
                    )
            else:
                if uid:
                    await cur.execute(
                        """
                        SELECT cp.*, c.name as club_name, c.tag as club_tag, c.role_id as club_role_id, c.formation
                        FROM club_players cp
                        JOIN clubs c ON cp.club_id = c.id
                        WHERE cp.guild_id = ? AND (cp.user_id = ? OR LOWER(cp.player_name) = LOWER(?));
                        """,
                        (guild_id, uid, p_name),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT cp.*, c.name as club_name, c.tag as club_tag, c.role_id as club_role_id, c.formation
                        FROM club_players cp
                        JOIN clubs c ON cp.club_id = c.id
                        WHERE cp.guild_id = ? AND LOWER(cp.player_name) = LOWER(?);
                        """,
                        (guild_id, p_name),
                    )

            row = await cur.fetchone()
            if not row:
                return False, f"Player **{p_name}** was not found in any registered club squad.", {}

            data = dict(row)
            if not data.get("wage"):
                try:
                    await cur.execute(
                        """
                        SELECT wage FROM sofifa_players
                        WHERE LOWER(name) = LOWER(?) OR LOWER(full_name) = LOWER(?)
                        ORDER BY overall_rating DESC LIMIT 1;
                        """,
                        (data["player_name"], data["player_name"]),
                    )
                    sm = await cur.fetchone()
                    if sm:
                        w_int = parse_wage_to_int(sm["wage"])
                        if w_int > 0:
                            await cur.execute("UPDATE club_players SET wage = ? WHERE id = ?;", (w_int, data["id"]))
                            await conn.commit()
                            data["wage"] = w_int
                except Exception as w_err:
                    logger.debug("SoFIFA wage sync notice for player: %s", w_err)

            return True, "", {
                "player": data,
                "club": {
                    "id": data["club_id"],
                    "name": data["club_name"],
                    "tag": data["club_tag"],
                    "role_id": data["club_role_id"],
                    "formation": data["formation"],
                },
            }

    async def swap_club_players(
        self,
        guild_id: int,
        club_query: Any,
        player1_name: str,
        player2_name: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str]:
        """
        Swap two players in a club squad.
        - If one is Starting and one is Bench: swaps status & position (Tactical Substitution).
        - If both are Starting or both are Bench: swaps positions (Tactical Realignment).
        """
        p1_name = str(player1_name).strip()
        p2_name = str(player2_name).strip()
        if not p1_name or not p2_name:
            return False, "Both player names must be specified."

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found."

        conn = await self.connect()
        async with conn.cursor() as cur:
            # 1. Ensure starters are aligned to club formation (realigns legacy CAMs in 4-2-1-3 to LW/RW)
            await self._realign_club_starters(cur, club["id"], club.get("formation", DEFAULT_FORMATION))

            p1 = await self._resolve_club_player(cur, club["id"], p1_name)
            if not p1:
                return False, f"Player **{p1_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            p2 = await self._resolve_club_player(cur, club["id"], p2_name)
            if not p2:
                return False, f"Player **{p2_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            if p1["id"] == p2["id"]:
                return False, "Cannot swap a player with themselves."

            if p1["status"] != p2["status"]:
                starter = p1 if p1["status"] == "starting" else p2
                bencher = p2 if p1["status"] == "starting" else p1

                # Target slot for bencher entering the starting lineup:
                target_slots = get_formation_positions(club.get("formation", DEFAULT_FORMATION))
                target_pos = starter["position"]
                if bencher["position"] in target_slots:
                    if starter["position"] not in target_slots or (starter["position"] == "CAM" and bencher["position"] in ("LW", "RW")):
                        target_pos = bencher["position"]

                # Starter moves to bench keeping their natural position
                bench_pos = starter["position"]

                await cur.execute(
                    "UPDATE club_players SET status = 'starting', position = ? WHERE id = ?;",
                    (target_pos, bencher["id"]),
                )
                await cur.execute(
                    "UPDATE club_players SET status = 'bench', position = ? WHERE id = ?;",
                    (bench_pos, starter["id"]),
                )
                await conn.commit()
                return True, (
                    f"🔁 **Substitution Complete!**\n"
                    f"• **{bencher['player_name']}**: Now **Starting** (`{target_pos}`)\n"
                    f"• **{starter['player_name']}**: Now **Bench** (`{bench_pos}`)\n"
                    f"Club: **[{club['tag']}] {club['name']}**"
                )
            else:
                # Both same status (e.g. both starting)
                p1_pos = p2["position"]
                p2_pos = p1["position"]
                # If both are starting and both currently hold the same position (e.g. CAM and CAM),
                # resolve to missing wing slots in the formation!
                if p1["position"] == p2["position"] and p1["status"] == "starting":
                    target_slots = get_formation_positions(club.get("formation", DEFAULT_FORMATION))
                    await cur.execute(
                        "SELECT position FROM club_players WHERE club_id = ? AND status = 'starting';",
                        (club["id"],),
                    )
                    active_positions = [r["position"] for r in await cur.fetchall()]
                    missing_wings = [w for w in ("LW", "RW") if w in target_slots and w not in active_positions]
                    if missing_wings and p1["position"] == "CAM":
                        p2_pos = missing_wings[0]
                        p1_pos = "CAM"

                await cur.execute(
                    "UPDATE club_players SET position = ? WHERE id = ?;",
                    (p1_pos, p1["id"]),
                )
                await cur.execute(
                    "UPDATE club_players SET position = ? WHERE id = ?;",
                    (p2_pos, p2["id"]),
                )
                await conn.commit()
                return True, (
                    f"🔁 **Position Swap Complete!**\n"
                    f"• **{p1['player_name']}**: Now **`{p1_pos}`**\n"
                    f"• **{p2['player_name']}**: Now **`{p2_pos}`**\n"
                    f"Club: **[{club['tag']}] {club['name']}**"
                )

    async def substitute_club_player(
        self,
        guild_id: int,
        club_query: Any,
        player_off_name: str,
        player_on_name: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str]:
        """
        Execute a tactical substitution: sub out player_off (from Starting XI) and bring in player_on (from Bench).
        Smart auto-detection reverses the arguments if player_off is bench and player_on is starting.
        """
        p_off_name = str(player_off_name).strip()
        p_on_name = str(player_on_name).strip()
        if not p_off_name or not p_on_name:
            return False, "Both player names must be specified (player coming OFF and player coming ON)."

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found."

        conn = await self.connect()
        async with conn.cursor() as cur:
            # 1. Align current starters if needed
            await self._realign_club_starters(cur, club["id"], club.get("formation", DEFAULT_FORMATION))

            p_off = await self._resolve_club_player(cur, club["id"], p_off_name)
            if not p_off:
                return False, f"Player **{p_off_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            p_on = await self._resolve_club_player(cur, club["id"], p_on_name)
            if not p_on:
                return False, f"Player **{p_on_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            if p_off["id"] == p_on["id"]:
                return False, "Cannot substitute a player with themselves."

            # Smart detection if user inverted off/on
            if p_off["status"] == "bench" and p_on["status"] == "starting":
                p_off, p_on = p_on, p_off

            if p_off["status"] == "starting" and p_on["status"] == "starting":
                return False, (
                    f"Both **{p_off['player_name']}** and **{p_on['player_name']}** are already in the **Starting XI**!\n"
                    f"💡 Use `/player swap` or `bb!swap {p_off['player_name']} {p_on['player_name']}` to switch their positions."
                )

            if p_off["status"] == "bench" and p_on["status"] == "bench":
                return False, (
                    f"Both **{p_off['player_name']}** and **{p_on['player_name']}** are currently on the **Bench**!\n"
                    f"💡 Specify a starting player to sub off, or use `bb!lineup add` to promote them."
                )

            # At this point: p_off is 'starting' and p_on is 'bench'
            starter = p_off
            bencher = p_on

            target_slots = get_formation_positions(club.get("formation", DEFAULT_FORMATION))
            target_pos = starter["position"]
            if bencher["position"] in target_slots:
                if starter["position"] not in target_slots or (starter["position"] == "CAM" and bencher["position"] in ("LW", "RW")):
                    target_pos = bencher["position"]

            bench_pos = starter["position"]

            await cur.execute(
                "UPDATE club_players SET status = 'starting', position = ? WHERE id = ?;",
                (target_pos, bencher["id"]),
            )
            await cur.execute(
                "UPDATE club_players SET status = 'bench', position = ? WHERE id = ?;",
                (bench_pos, starter["id"]),
            )
            await conn.commit()

            # Re-align formation starters in case slots need balance
            await self._realign_club_starters(cur, club["id"], club.get("formation", DEFAULT_FORMATION))
            await conn.commit()

            # Re-fetch updated position of bencher after realignment
            await cur.execute("SELECT position FROM club_players WHERE id = ?;", (bencher["id"],))
            row_on = await cur.fetchone()
            actual_on_pos = row_on["position"] if row_on else target_pos

            return True, (
                f"🔄 **Tactical Substitution Executed!**\n"
                f"🔻 **[OFF]** **{starter['player_name']}** (`{bench_pos}`)\n"
                f"🔺 **[ON]** **{bencher['player_name']}** (`{actual_on_pos}`)\n"
                f"Club: **[{club['tag']}] {club['name']}**"
            )

    async def deduct_matchday_wages(
        self,
        guild_id: int,
        matchday: int,
        tournament_id: Optional[int] = None,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Deducts matchday wages for all clubs registered in the guild.
        Prevents duplicate deduction for the same matchday via matchday_wage_payouts table.
        Logs each club transaction in the audit ledger and returns a detailed payroll report.
        """
        if matchday < 1:
            return False, "Matchday must be greater than or equal to 1.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Fetch all clubs in guild
            await cur.execute(
                "SELECT * FROM clubs WHERE guild_id = ? ORDER BY id ASC;",
                (guild_id,),
            )
            clubs = [dict(r) for r in await cur.fetchall()]
            if not clubs:
                return False, "No clubs registered in this server.", {}

            # Check for already processed clubs for this matchday
            await cur.execute(
                "SELECT club_id FROM matchday_wage_payouts WHERE guild_id = ? AND matchday = ?;",
                (guild_id, matchday),
            )
            already_paid_ids = {r["club_id"] for r in await cur.fetchall()}

            processed_clubs = []
            skipped_clubs = []
            total_payroll_disbursed = 0

            for club in clubs:
                cid = club["id"]
                if cid in already_paid_ids:
                    skipped_clubs.append(club)
                    continue

                # Auto-sync any unassigned wages from SoFIFA before computing
                try:
                    await cur.execute(
                        """
                        SELECT p.id, s.wage FROM club_players p
                        JOIN sofifa_players s ON (
                            LOWER(p.player_name) = LOWER(s.name)
                            OR LOWER(p.player_name) = LOWER(s.full_name)
                        )
                        WHERE p.club_id = ? AND (p.wage IS NULL OR p.wage = 0);
                        """,
                        (cid,),
                    )
                    for sm in await cur.fetchall():
                        w_int = parse_wage_to_int(sm["wage"])
                        if w_int > 0:
                            await cur.execute("UPDATE club_players SET wage = ? WHERE id = ?;", (w_int, sm["id"]))
                except Exception as w_err:
                    logger.debug("Auto SoFIFA wage sync notice for club %s: %s", cid, w_err)

                # Calculate total wage bill for all squad players
                await cur.execute(
                    "SELECT COALESCE(SUM(wage), 0) as total_wage, COUNT(*) as p_cnt FROM club_players WHERE club_id = ?;",
                    (cid,),
                )
                wage_row = await cur.fetchone()
                club_wage = int(wage_row["total_wage"] if wage_row else 0)
                p_cnt = int(wage_row["p_cnt"] if wage_row else 0)

                old_treasury = int(club.get("treasury_cash") or 0)
                new_treasury = old_treasury - club_wage
                status = "paid" if new_treasury >= 0 else "deficit"

                # Deduct from treasury_cash
                await cur.execute(
                    "UPDATE clubs SET treasury_cash = ? WHERE id = ?;",
                    (new_treasury, cid),
                )

                # Record in matchday_wage_payouts
                await cur.execute(
                    """
                    INSERT INTO matchday_wage_payouts (guild_id, club_id, matchday, tournament_id, total_wages, treasury_before, treasury_after, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (guild_id, cid, matchday, tournament_id, club_wage, old_treasury, new_treasury, status),
                )

                # Record in transactions audit log
                if club_wage > 0:
                    await cur.execute(
                        """
                        INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                        VALUES (?, ?, NULL, 'cash', ?, 'matchday_wage', ?);
                        """,
                        (guild_id, club.get("owner_id"), club_wage, f"Matchday {matchday} Squad Wage Bill for [{club['tag']}] {club['name']}"),
                    )

                total_payroll_disbursed += club_wage
                processed_clubs.append({
                    "club": club,
                    "total_wage": club_wage,
                    "player_count": p_cnt,
                    "old_treasury": old_treasury,
                    "new_treasury": new_treasury,
                    "status": status,
                })

            await conn.commit()

            report = {
                "matchday": matchday,
                "processed_count": len(processed_clubs),
                "skipped_count": len(skipped_clubs),
                "total_disbursed": total_payroll_disbursed,
                "clubs": processed_clubs,
                "skipped": skipped_clubs,
            }
            msg = f"Matchday {matchday} payroll successfully processed for {len(processed_clubs)} clubs ({format_wage(total_payroll_disbursed)} total deducted)."
            if skipped_clubs:
                msg += f" ({len(skipped_clubs)} clubs were already settled for MD {matchday})."
            return True, msg, report

    async def get_club_payroll(self, guild_id: int, club_query: Any) -> Tuple[bool, str, Dict[str, Any]]:
        """Fetch full payroll summary for a club: starters wage, bench wage, total wage, treasury, and runway."""
        success, msg, lineup = await self.get_club_lineup(guild_id, club_query)
        if not success:
            return False, msg, {}

        club = lineup["club"]
        starting = lineup["starting"]
        bench = lineup["bench"]

        starting_wages = sum(int(p.get("wage") or 0) for p in starting)
        bench_wages = sum(int(p.get("wage") or 0) for p in bench)
        total_wage = starting_wages + bench_wages
        treasury = int(club.get("treasury_cash") or 0)
        runway = (treasury / total_wage) if total_wage > 0 else float("inf")

        top_earner = max(starting + bench, key=lambda p: int(p.get("wage") or 0)) if (starting + bench) else None

        return True, "Payroll retrieved successfully.", {
            "club": club,
            "starting_wages": starting_wages,
            "bench_wages": bench_wages,
            "total_wage": total_wage,
            "treasury_cash": treasury,
            "runway": runway,
            "top_earner": top_earner,
            "starters_count": len(starting),
            "bench_count": len(bench),
        }

    # ------------------ SoFIFA Sep 19 2025 FC 26 Players Cache ------------------ #

    async def cache_sofifa_players(self, players: List[Dict[str, Any]]) -> int:
        """Upsert a list of parsed SoFIFA FC 26 players into SQLite cache."""
        if not players:
            return 0
        conn = await self.connect()
        inserted = 0
        async with conn.cursor() as cur:
            for p in players:
                try:
                    search_text = p.get("search_text") or f"{_normalize_search_text(p.get('name', ''))} {_normalize_search_text(p.get('full_name', ''))}"
                    await cur.execute(
                        """
                        INSERT INTO sofifa_players (
                            id, name, full_name, primary_pos, positions,
                            overall_rating, potential, age, team, nationality,
                            value, wage, avatar_url, sofifa_url, data_json, search_text
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            name = excluded.name,
                            full_name = excluded.full_name,
                            primary_pos = excluded.primary_pos,
                            positions = excluded.positions,
                            overall_rating = excluded.overall_rating,
                            potential = excluded.potential,
                            age = excluded.age,
                            team = excluded.team,
                            nationality = excluded.nationality,
                            value = excluded.value,
                            wage = excluded.wage,
                            avatar_url = excluded.avatar_url,
                            sofifa_url = excluded.sofifa_url,
                            data_json = excluded.data_json,
                            search_text = excluded.search_text;
                        """,
                        (
                            p["id"],
                            p["name"],
                            p.get("full_name") or p["name"],
                            p.get("primary_pos", "ST"),
                            p.get("positions", p.get("primary_pos", "ST")),
                            int(p.get("overall_rating", 75)),
                            int(p.get("potential", 75)),
                            int(p.get("age", 25)),
                            p.get("team", "Free Agent"),
                            p.get("nationality", "Unknown"),
                            p.get("value", "€0"),
                            p.get("wage", "€0"),
                            p.get("avatar", ""),
                            p.get("url", f"https://sofifa.com/player/{p['id']}"),
                            json.dumps(p),
                            search_text,
                        ),
                    )
                    inserted += 1
                except Exception as e:
                    logger.warning("Error caching player %s: %s", p.get("name"), e)
            await conn.commit()
        return inserted

    async def search_cached_sofifa_players(self, query: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Fast instant search for Discord autocomplete matching player name or full name."""
        clean = query.strip()
        conn = await self.connect()
        async with conn.cursor() as cur:
            if not clean:
                await cur.execute(
                    """
                    SELECT id, name, full_name, primary_pos, overall_rating, potential, team, avatar_url, sofifa_url
                    FROM sofifa_players
                    ORDER BY overall_rating DESC, potential DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
            else:
                norm = _normalize_search_text(clean)
                pattern = f"%{norm}%"
                prefix_pattern = f"{norm}%"
                word_pattern = f"% {norm}%"
                raw_pattern = f"%{clean.lower()}%"
                await cur.execute(
                    """
                    SELECT id, name, full_name, primary_pos, overall_rating, potential, team, avatar_url, sofifa_url
                    FROM sofifa_players
                    WHERE search_text LIKE ? OR LOWER(name) LIKE ? OR LOWER(full_name) LIKE ?
                    ORDER BY
                        CASE
                            WHEN search_text LIKE ? THEN 1
                            WHEN search_text LIKE ? THEN 2
                            WHEN search_text LIKE ? THEN 3
                            ELSE 4
                        END,
                        overall_rating DESC
                    LIMIT ?;
                    """,
                    (pattern, raw_pattern, raw_pattern, prefix_pattern, word_pattern, pattern, limit),
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_cached_sofifa_player(self, query: str) -> Optional[Dict[str, Any]]:
        """Retrieve full player details from local SQLite cache by ID or exact/fuzzy name."""
        clean = query.strip()
        conn = await self.connect()
        async with conn.cursor() as cur:
            if clean.isdigit():
                await cur.execute("SELECT data_json FROM sofifa_players WHERE id = ?;", (int(clean),))
                row = await cur.fetchone()
                if row:
                    return json.loads(row["data_json"])

            norm = _normalize_search_text(clean)

            # 1. Match exact name, full name, or search text
            await cur.execute(
                """
                SELECT data_json FROM sofifa_players
                WHERE LOWER(name) = LOWER(?) OR LOWER(full_name) = LOWER(?) OR search_text = ?
                ORDER BY overall_rating DESC LIMIT 1;
                """,
                (clean, clean, norm),
            )
            row = await cur.fetchone()
            if row:
                return json.loads(row["data_json"])

            # 2. Prefix or word-boundary match (e.g. "Mbappe" matches "Kylian Mbappe", "Kimmich" matches "Joshua Kimmich")
            # Avoid mid-word substring matches so custom names like "immi" never accidentally hijack "Joshua Kimmich"
            prefix_pattern = f"{norm}%"
            word_pattern = f"% {norm}%"
            await cur.execute(
                """
                SELECT data_json FROM sofifa_players
                WHERE search_text LIKE ? OR search_text LIKE ? OR LOWER(name) LIKE ? OR LOWER(full_name) LIKE ?
                ORDER BY
                    CASE
                        WHEN LOWER(name) LIKE ? THEN 1
                        WHEN search_text LIKE ? THEN 2
                        ELSE 3
                    END,
                    overall_rating DESC
                LIMIT 1;
                """,
                (prefix_pattern, word_pattern, prefix_pattern, prefix_pattern, prefix_pattern, prefix_pattern),
            )
            row = await cur.fetchone()
            if row:
                return json.loads(row["data_json"])
        return None

    async def get_cached_sofifa_player_count(self) -> int:
        """Count total cached SoFIFA players."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT COUNT(*) as cnt FROM sofifa_players;")
            row = await cur.fetchone()
            return row["cnt"] if row else 0

    get_cached_sofifa_player_by_name = get_cached_sofifa_player

    # ── Market Auction System ──

    async def create_market_auction(
        self,
        guild_id: int,
        channel_id: int,
        seller_id: int,
        player_name: str,
        ovr: int,
        potential: int,
        starting_bid: int,
        max_increment: int,
        expires_at: str,
        idle_timeout_seconds: Optional[int] = None,
        position: str = "ST",
        seller_club_id: Optional[int] = None,
        photo_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a new player auction in the market."""
        now_str = datetime.now(timezone.utc).isoformat()
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO market_auctions (
                    guild_id, channel_id, seller_id, seller_club_id,
                    player_name, ovr, potential, position,
                    starting_bid, max_increment, current_bid,
                    status, photo_url, created_at, expires_at,
                    idle_timeout_seconds, last_bid_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 'active', ?, ?, ?, ?, ?);
                """,
                (
                    guild_id,
                    channel_id,
                    seller_id,
                    seller_club_id,
                    player_name.strip(),
                    ovr,
                    potential,
                    position.upper() if position else "ST",
                    starting_bid,
                    max_increment,
                    photo_url,
                    now_str,
                    expires_at,
                    idle_timeout_seconds,
                    now_str,
                ),
            )
            auction_id = cur.lastrowid
            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            row = await cur.fetchone()
            return dict(row)

    async def set_auction_message_id(self, auction_id: int, message_id: int) -> None:
        """Link the Discord message ID to the auction."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE market_auctions SET message_id = ? WHERE id = ?;",
                (message_id, auction_id),
            )

    async def get_auction(self, auction_id: int) -> Optional[Dict[str, Any]]:
        """Fetch an auction by ID."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_active_market_auctions(self, guild_id: int) -> List[Dict[str, Any]]:
        """Fetch all active auctions for a guild."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM market_auctions WHERE guild_id = ? AND status = 'active' ORDER BY expires_at ASC;",
                (guild_id,),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_all_active_auctions(self) -> List[Dict[str, Any]]:
        """Fetch all active auctions across all guilds for the background task."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM market_auctions WHERE status = 'active';",
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_auction_bids(self, auction_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent bids for an auction."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM auction_bids WHERE auction_id = ? ORDER BY id DESC LIMIT ?;",
                (auction_id, limit),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def place_auction_bid(
        self,
        auction_id: int,
        bidder_id: int,
        increment: int,
        guild_id: int,
    ) -> Tuple[bool, str, Dict[str, Any], Optional[Dict[str, Any]]]:
        """
        Place a bid on an active auction with escrow balance debit and outbid refund.
        Priority:
        1. Try bidder's club treasury cash (if in club and sufficient).
        2. If not enough in treasury or not in club, try bidder's personal cash.
        3. If neither has enough, reject.
        """
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            auction_row = await cur.fetchone()
            if not auction_row:
                return False, "Auction not found.", {}, None
            auction = dict(auction_row)

            if auction["status"] != "active":
                return False, f"This auction is {auction['status']} and no longer accepts bids.", auction, None

            now = datetime.now(timezone.utc)
            # Check absolute expiration
            exp_dt = datetime.fromisoformat(auction["expires_at"])
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            if now >= exp_dt:
                return False, "This auction has already expired.", auction, None

            # Check idle inactivity timeout
            if auction.get("idle_timeout_seconds"):
                last_dt = datetime.fromisoformat(auction["last_bid_at"])
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if (now - last_dt).total_seconds() >= auction["idle_timeout_seconds"]:
                    return False, "This auction has closed due to bidding inactivity.", auction, None

            # Prevent bidding against oneself if already the highest bidder
            if bidder_id == auction["highest_bidder_id"]:
                return False, "You already hold the highest bid on this player!", auction, None

            # Validate increment
            if increment <= 0 or increment > auction["max_increment"]:
                return False, f"Bid increment must be between 1 and {auction['max_increment']:,} Cash.", auction, None

            # Compute new bid
            current_bid = auction["current_bid"]
            base_price = current_bid if current_bid > 0 else auction["starting_bid"]
            new_bid = base_price + increment

            # Check funding: Club Treasury first, then Personal Balance
            bidder_club = await self.get_club_by_user(guild_id, bidder_id)
            bidder_club_id = bidder_club["id"] if bidder_club else None
            funding_source = None

            await self.get_or_create_user(bidder_id, guild_id)
            await cur.execute("SELECT cash FROM users WHERE user_id = ? AND guild_id = ?;", (bidder_id, guild_id))
            user_row = await cur.fetchone()
            personal_cash = user_row["cash"] if user_row else 0

            if bidder_club and bidder_club.get("treasury_cash", 0) >= new_bid:
                funding_source = "treasury"
                await cur.execute(
                    "UPDATE clubs SET treasury_cash = treasury_cash - ? WHERE id = ?;",
                    (new_bid, bidder_club_id),
                )
            elif personal_cash >= new_bid:
                funding_source = "personal"
                await cur.execute(
                    "UPDATE users SET cash = cash - ? WHERE user_id = ? AND guild_id = ?;",
                    (new_bid, bidder_id, guild_id),
                )
            else:
                club_bal_str = f"{bidder_club.get('treasury_cash', 0):,}" if bidder_club else "N/A (No club)"
                return False, (
                    f"Insufficient funds to place bid of **{new_bid:,} Cash**!\n"
                    f"• **Club Treasury**: {club_bal_str} Cash\n"
                    f"• **Personal Balance**: {personal_cash:,} Cash"
                ), auction, None

            # Record escrow transaction
            payer_desc = f"Club [{bidder_club['tag']}] Treasury" if funding_source == "treasury" else f"<@{bidder_id}> Personal Cash"
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, 'cash', ?, 'auction_escrow', ?);
                """,
                (guild_id, bidder_id, new_bid, f"Auction Bid Escrow: {auction['player_name']} (Funded via {payer_desc})"),
            )

            # Refund previous highest bidder
            outbid_info = None
            if auction["highest_bidder_id"] and current_bid > 0:
                prev_id = auction["highest_bidder_id"]
                prev_club_id = auction["highest_bidder_club_id"]
                prev_src = auction.get("escrow_source") or "treasury"
                prev_amount = current_bid

                if prev_src == "treasury" and prev_club_id:
                    await cur.execute(
                        "UPDATE clubs SET treasury_cash = treasury_cash + ? WHERE id = ?;",
                        (prev_amount, prev_club_id),
                    )
                else:
                    await cur.execute(
                        "UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;",
                        (prev_amount, prev_id, guild_id),
                    )

                await cur.execute(
                    """
                    INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                    VALUES (?, NULL, ?, 'cash', ?, 'auction_refund', ?);
                    """,
                    (guild_id, prev_id, prev_amount, f"Auction Outbid Refund: {auction['player_name']} (Refunded to {prev_src})"),
                )

                outbid_info = {
                    "user_id": prev_id,
                    "club_id": prev_club_id,
                    "amount": prev_amount,
                    "source": prev_src,
                }

            # Anti-sniping: If less than 120s remaining on expires_at, extend by 120s
            new_expires = exp_dt
            if (exp_dt - now).total_seconds() < 120:
                new_expires = now + timedelta(seconds=120)

            now_iso = now.isoformat()
            new_exp_iso = new_expires.isoformat()

            # Record bid in auction_bids
            await cur.execute(
                """
                INSERT INTO auction_bids (auction_id, bidder_id, bidder_club_id, bid_amount, increment, escrow_source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (auction_id, bidder_id, bidder_club_id, new_bid, increment, funding_source, now_iso),
            )

            # Update market_auctions
            await cur.execute(
                """
                UPDATE market_auctions
                SET current_bid = ?,
                    highest_bidder_id = ?,
                    highest_bidder_club_id = ?,
                    escrow_source = ?,
                    last_bid_at = ?,
                    expires_at = ?
                WHERE id = ?;
                """,
                (new_bid, bidder_id, bidder_club_id, funding_source, now_iso, new_exp_iso, auction_id),
            )

            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            updated_row = await cur.fetchone()
            return True, f"Bid placed successfully! New bid is **{new_bid:,} Cash**.", dict(updated_row), outbid_info

    async def settle_auction(self, auction_id: int) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Settle an auction upon timer expiration or idle timeout.
        If bids were placed:
        - Transfers player to winner's club (or registers under user's club).
        - Pays seller (club treasury or personal cash).
        - Sets status to 'completed'.
        If no bids were placed:
        - Sets status to 'expired'.
        """
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            row = await cur.fetchone()
            if not row:
                return False, "Auction not found.", {}
            auction = dict(row)

            if auction["status"] != "active":
                return False, f"Auction is already {auction['status']}.", auction

            winner_id = auction["highest_bidder_id"]
            winning_bid = auction["current_bid"]
            guild_id = auction["guild_id"]
            p_name = auction["player_name"]

            # Case 1: Expired without any bids
            if not winner_id or winning_bid == 0:
                await cur.execute(
                    "UPDATE market_auctions SET status = 'expired' WHERE id = ?;",
                    (auction_id,),
                )
                auction["status"] = "expired"
                return True, f"Auction for **{p_name}** expired with no bids.", auction

            # Case 2: Winning bid placed
            winner_club_id = auction["highest_bidder_club_id"]
            if not winner_club_id:
                w_club = await self.get_club_by_user(guild_id, winner_id)
                winner_club_id = w_club["id"] if w_club else None

            # Disburse winning bid to seller
            seller_club_id = auction["seller_club_id"]
            if seller_club_id:
                await cur.execute(
                    "UPDATE clubs SET treasury_cash = treasury_cash + ? WHERE id = ?;",
                    (winning_bid, seller_club_id),
                )
                payee_desc = f"Club {seller_club_id} Treasury"
            else:
                seller_id = auction["seller_id"]
                await self.get_or_create_user(seller_id, guild_id)
                await cur.execute(
                    "UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;",
                    (winning_bid, seller_id, guild_id),
                )
                payee_desc = f"<@{seller_id}> Personal Balance"

            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, ?, 'cash', ?, 'auction_payout', ?);
                """,
                (
                    guild_id,
                    winner_id,
                    auction["seller_id"],
                    winning_bid,
                    f"Auction Settlement: {p_name} (Paid to {payee_desc})",
                ),
            )

            # Transfer player to winning club
            if winner_club_id:
                # If seller had player in their club, delete old row
                if seller_club_id:
                    await cur.execute(
                        "DELETE FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                        (seller_club_id, p_name),
                    )
                # Remove if already exists in winning club (prevent duplicate)
                await cur.execute(
                    "DELETE FROM club_players WHERE club_id = ? AND LOWER(player_name) = LOWER(?);",
                    (winner_club_id, p_name),
                )
                # Insert into winning club
                await cur.execute(
                    """
                    INSERT INTO club_players (club_id, guild_id, player_name, role, position, status, rating, potential)
                    VALUES (?, ?, ?, 'Player', ?, 'starting', ?, ?);
                    """,
                    (winner_club_id, guild_id, p_name, auction.get("position", "ST"), auction["ovr"], auction["potential"]),
                )

            # Mark completed
            await cur.execute(
                "UPDATE market_auctions SET status = 'completed' WHERE id = ?;",
                (auction_id,),
            )
            auction["status"] = "completed"
            return True, f"Auction won by <@{winner_id}> for **{winning_bid:,} Cash**!", auction

    async def cancel_market_auction(
        self,
        auction_id: int,
        caller_id: int,
        is_admin: bool = False,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Cancel an active auction and refund any active high bidder."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM market_auctions WHERE id = ?;", (auction_id,))
            row = await cur.fetchone()
            if not row:
                return False, "Auction not found.", {}
            auction = dict(row)

            if auction["status"] != "active":
                return False, f"Auction is already {auction['status']}.", auction

            if not is_admin and caller_id != auction["seller_id"]:
                return False, "Only the auction seller or an administrator can cancel this auction.", auction

            # Refund high bidder if any
            if auction["highest_bidder_id"] and auction["current_bid"] > 0:
                bidder_id = auction["highest_bidder_id"]
                club_id = auction["highest_bidder_club_id"]
                amt = auction["current_bid"]
                src = auction.get("escrow_source") or "treasury"
                guild_id = auction["guild_id"]

                if src == "treasury" and club_id:
                    await cur.execute("UPDATE clubs SET treasury_cash = treasury_cash + ? WHERE id = ?;", (amt, club_id))
                else:
                    await cur.execute("UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;", (amt, bidder_id, guild_id))

                await cur.execute(
                    """
                    INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                    VALUES (?, NULL, ?, 'cash', ?, 'auction_cancel_refund', ?);
                    """,
                    (guild_id, bidder_id, amt, f"Auction Cancellation Refund: {auction['player_name']}"),
                )

            await cur.execute("UPDATE market_auctions SET status = 'cancelled' WHERE id = ?;", (auction_id,))
            auction["status"] = "cancelled"
            return True, "Auction successfully cancelled and funds refunded.", auction


    # =========================================================================
    # TOURNAMENTS, MATCHES & MATCHDAY BETTING
    # =========================================================================

    async def save_parsed_tournament(
        self,
        guild_id: int,
        tournament_data: Dict[str, Any],
        url: Optional[str] = None,
        season_number: int = 1,
        competition_type: str = "league",
    ) -> Dict[str, Any]:
        """Insert or update parsed tournament, fixtures, standings, and player stats."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            name = tournament_data.get("tournament_name", "Tournament")
            tot_md = tournament_data.get("highest_matchday", 38)
            champion = tournament_data.get("champion")
            runner_up = tournament_data.get("runner_up")

            # Check if active tournament exists for this guild and competition_type
            await cur.execute(
                "SELECT * FROM tournaments WHERE guild_id = ? AND competition_type = ? AND status = 'active';",
                (guild_id, competition_type),
            )
            existing = await cur.fetchone()
            if existing:
                tournament_id = existing["id"]
                await cur.execute(
                    """
                    UPDATE tournaments
                    SET name = ?, season_number = ?, url = COALESCE(?, url),
                        total_matchdays = ?, champion = ?, runner_up = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?;
                    """,
                    (name, season_number, url, tot_md, champion, runner_up, tournament_id),
                )
            else:
                await cur.execute(
                    """
                    INSERT INTO tournaments (
                        guild_id, name, season_number, competition_type,
                        url, current_matchday, total_matchdays, status, champion, runner_up
                    ) VALUES (?, ?, ?, ?, ?, 1, ?, 'active', ?, ?);
                    """,
                    (guild_id, name, season_number, competition_type, url, tot_md, champion, runner_up),
                )
                tournament_id = cur.lastrowid

            # Save Fixtures
            fixtures_by_md = tournament_data.get("fixtures_by_matchday", {})
            for md, match_list in fixtures_by_md.items():
                for m in match_list:
                    await cur.execute(
                        """
                        SELECT id FROM tournament_fixtures
                        WHERE tournament_id = ? AND matchday = ? AND home_team_id = ? AND away_team_id = ?;
                        """,
                        (tournament_id, md, m["home_team_id"], m["away_team_id"]),
                    )
                    fix_row = await cur.fetchone()
                    if fix_row:
                        await cur.execute(
                            """
                            UPDATE tournament_fixtures
                            SET goals_home = ?, goals_away = ?, penalties_home = ?, penalties_away = ?,
                                is_finished = ?, replay_exists = ?, match_uid = COALESCE(?, match_uid),
                                stage_name = COALESCE(?, stage_name)
                            WHERE id = ?;
                            """,
                            (
                                m["goals_home"], m["goals_away"], m["penalties_home"], m["penalties_away"],
                                1 if m["is_finished"] else 0, 1 if m["replay_exists"] else 0,
                                m.get("match_uid"), m.get("stage_name"), fix_row["id"],
                            ),
                        )
                    else:
                        await cur.execute(
                            """
                            INSERT INTO tournament_fixtures (
                                tournament_id, guild_id, matchday, stage_name, match_uid,
                                home_team_id, away_team_id, home_team_name, away_team_name,
                                home_team_short, away_team_short, goals_home, goals_away,
                                penalties_home, penalties_away, is_finished, replay_exists
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                            """,
                            (
                                tournament_id, guild_id, md, m.get("stage_name"), m.get("match_uid"),
                                m["home_team_id"], m["away_team_id"], m["home_team_name"], m["away_team_name"],
                                m["home_team_short"], m["away_team_short"], m["goals_home"], m["goals_away"],
                                m["penalties_home"], m["penalties_away"], 1 if m["is_finished"] else 0,
                                1 if m["replay_exists"] else 0,
                            ),
                        )

            # Save Standings
            standings = tournament_data.get("standings", [])
            for s in standings:
                await cur.execute(
                    "SELECT id FROM tournament_standings WHERE tournament_id = ? AND team_id = ?;",
                    (tournament_id, s["team_id"]),
                )
                st_row = await cur.fetchone()
                if st_row:
                    await cur.execute(
                        """
                        UPDATE tournament_standings
                        SET rank = ?, played = ?, won = ?, drawn = ?, lost = ?,
                            goals_for = ?, goals_against = ?, goal_difference = ?,
                            clean_sheets = ?, points = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?;
                        """,
                        (
                            s["rank"], s["played"], s["won"], s["drawn"], s["lost"],
                            s["goals_for"], s["goals_against"], s["goal_difference"],
                            s["clean_sheets"], s["points"], st_row["id"],
                        ),
                    )
                else:
                    await cur.execute(
                        """
                        INSERT INTO tournament_standings (
                            tournament_id, team_id, name, short, rank,
                            played, won, drawn, lost, goals_for, goals_against,
                            goal_difference, clean_sheets, points
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            tournament_id, s["team_id"], s["name"], s["short"], s["rank"],
                            s["played"], s["won"], s["drawn"], s["lost"], s["goals_for"],
                            s["goals_against"], s["goal_difference"], s["clean_sheets"], s["points"],
                        ),
                    )

            # Save Player Stats
            all_players = tournament_data.get("player_stats", {}).get("all_players", [])
            for p in all_players:
                # Link club if exists
                await cur.execute(
                    "SELECT id FROM clubs WHERE guild_id = ? AND LOWER(name) LIKE ?;",
                    (guild_id, f"%{p['team_name'].lower()}%"),
                )
                c_row = await cur.fetchone()
                linked_club_id = c_row["id"] if c_row else None

                await cur.execute(
                    """
                    SELECT id FROM tournament_player_stats
                    WHERE tournament_id = ? AND LOWER(player_name) = LOWER(?) AND LOWER(team_name) = LOWER(?);
                    """,
                    (tournament_id, p["player_name"], p["team_name"]),
                )
                ps_row = await cur.fetchone()
                if ps_row:
                    await cur.execute(
                        """
                        UPDATE tournament_player_stats
                        SET goals = ?, assists = ?, own_goals = ?, yellow_cards = ?,
                            red_cards = ?, clean_sheets = ?, matches_played = ?,
                            minutes_played = ?, rating = ?, club_id = COALESCE(?, club_id)
                        WHERE id = ?;
                        """,
                        (
                            p["goals"], p["assists"], p["own_goals"], p["yellow_cards"],
                            p["red_cards"], p["clean_sheets"], p["matches_played"],
                            p["minutes_played"], p["rating"], linked_club_id, ps_row["id"],
                        ),
                    )
                else:
                    await cur.execute(
                        """
                        INSERT INTO tournament_player_stats (
                            tournament_id, guild_id, player_name, team_name, club_id,
                            goals, assists, own_goals, yellow_cards, red_cards,
                            clean_sheets, matches_played, minutes_played, rating
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        (
                            tournament_id, guild_id, p["player_name"], p["team_name"], linked_club_id,
                            p["goals"], p["assists"], p["own_goals"], p["yellow_cards"], p["red_cards"],
                            p["clean_sheets"], p["matches_played"], p["minutes_played"], p["rating"],
                        ),
                    )

            await conn.commit()
            await cur.execute("SELECT * FROM tournaments WHERE id = ?;", (tournament_id,))
            t_row = await cur.fetchone()
            return dict(t_row)

    async def ensure_tournament_seeded(self, guild_id: int) -> Optional[Dict[str, Any]]:
        """Ensure Season 1 tournaments (League and UCL) exist for this guild; if not, seed immediately from data/."""
        from pathlib import Path
        from utils.match_parser import parse_matchsimulator_html

        # 1. League Season 1
        existing_league = await self.get_tournament_by_season(guild_id, "league", 1)
        if not existing_league:
            s1_file = Path("data/beastly_s1_cup.html")
            if s1_file.exists():
                try:
                    with open(s1_file, "r", encoding="utf-8") as f:
                        html_text = f.read()
                    parsed = parse_matchsimulator_html(html_text)
                    saved = await self.save_parsed_tournament(
                        guild_id=guild_id,
                        tournament_data=parsed,
                        url="https://matchsimulator.com/cup/2859670/beastly-s1-league",
                        season_number=1,
                        competition_type="league",
                    )
                    hist = await self.get_season_history(guild_id, season_number=1, competition_name="league")
                    if not hist:
                        await self.conclude_tournament(saved["id"])
                        conn = await self.connect()
                        async with conn.cursor() as cur:
                            await cur.execute("UPDATE tournaments SET status = 'active' WHERE id = ?;", (saved["id"],))
                            await conn.commit()
                except Exception as e:
                    logger.warning("ensure_tournament_seeded league error: %s", e)

        # 2. UCL Season 1
        existing_ucl = await self.get_tournament_by_season(guild_id, "ucl", 1)
        if not existing_ucl:
            ucl_file = Path("data/beastly_ucl_s1.html")
            if ucl_file.exists():
                try:
                    with open(ucl_file, "r", encoding="utf-8") as f:
                        ucl_text = f.read()
                    parsed_ucl = parse_matchsimulator_html(ucl_text)
                    saved_ucl = await self.save_parsed_tournament(
                        guild_id=guild_id,
                        tournament_data=parsed_ucl,
                        url="https://matchsimulator.com/cup/2894790/beastly-ucl-s1",
                        season_number=1,
                        competition_type="ucl",
                    )
                    hist_ucl = await self.get_season_history(guild_id, season_number=1, competition_name="ucl")
                    if not hist_ucl:
                        await self.conclude_tournament(saved_ucl["id"])
                        conn = await self.connect()
                        async with conn.cursor() as cur:
                            await cur.execute("UPDATE tournaments SET status = 'active' WHERE id = ?;", (saved_ucl["id"],))
                            await conn.commit()
                except Exception as e:
                    logger.warning("ensure_tournament_seeded ucl error: %s", e)

        return await self.get_tournament_by_season(guild_id, "league", 1)

    async def get_active_tournament(self, guild_id: int, competition_type: str = "league") -> Optional[Dict[str, Any]]:
        """Fetch the currently active tournament for a given competition type in a guild."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM tournaments WHERE (guild_id = ? OR guild_id = 0) AND competition_type = ? AND status = 'active' ORDER BY id DESC LIMIT 1;",
                (guild_id, competition_type),
            )
            row = await cur.fetchone()
            if not row:
                # Fallback: if no active tournament, get latest completed tournament so standings/stats are accessible
                await cur.execute(
                    "SELECT * FROM tournaments WHERE (guild_id = ? OR guild_id = 0) AND competition_type = ? ORDER BY id DESC LIMIT 1;",
                    (guild_id, competition_type),
                )
                row = await cur.fetchone()
            return dict(row) if row else None

    async def get_tournament_by_id(self, tournament_id: int) -> Optional[Dict[str, Any]]:
        """Fetch tournament record by its ID."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM tournaments WHERE id = ?;", (tournament_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_tournament_by_season(
        self, guild_id: int, competition_type: str = "league", season_number: int = 1
    ) -> Optional[Dict[str, Any]]:
        """Fetch tournament record by guild, competition type, and season number."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM tournaments WHERE (guild_id = ? OR guild_id = 0) AND competition_type = ? AND season_number = ? ORDER BY id DESC LIMIT 1;",
                (guild_id, competition_type, season_number),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_tournament_fixtures(self, tournament_id: int, matchday: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetch fixtures for a tournament, optionally filtered by matchday."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            if matchday is not None:
                await cur.execute(
                    "SELECT * FROM tournament_fixtures WHERE tournament_id = ? AND matchday = ? ORDER BY id ASC;",
                    (tournament_id, matchday),
                )
            else:
                await cur.execute(
                    "SELECT * FROM tournament_fixtures WHERE tournament_id = ? ORDER BY matchday ASC, id ASC;",
                    (tournament_id,),
                )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_tournament_standings(self, tournament_id: int) -> List[Dict[str, Any]]:
        """Fetch sorted league standings for a tournament."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT * FROM tournament_standings WHERE tournament_id = ? ORDER BY rank ASC;",
                (tournament_id,),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_tournament_leaderboard(
        self, tournament_id: int, category: str = "goals", limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Fetch player stat leaderboard (goals, assists, rating, clean_sheets, yellow_cards, red_cards)."""
        valid_cats = {
            "goals": "goals DESC, rating DESC",
            "assists": "assists DESC, rating DESC",
            "rating": "rating DESC, goals DESC",
            "clean_sheets": "clean_sheets DESC, rating DESC",
            "yellow_cards": "yellow_cards DESC",
            "red_cards": "red_cards DESC",
        }
        order_clause = valid_cats.get(category, "goals DESC")
        conn = await self.connect()
        async with conn.cursor() as cur:
            query = f"""
                SELECT * FROM tournament_player_stats
                WHERE tournament_id = ?
                ORDER BY {order_clause}
                LIMIT ?;
            """
            await cur.execute(query, (tournament_id, limit))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def get_distinct_tournament_players(
        self, guild_id: int, season_number: Optional[int] = None
    ) -> List[Dict[str, str]]:
        """Fetch distinct player names and their teams from tournament match stats."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT id FROM tournaments WHERE guild_id = ? LIMIT 1;", (guild_id,))
            has_gid = await cur.fetchone()
            target_gid = guild_id if has_gid else 0

            if season_number is not None:
                await cur.execute(
                    """
                    SELECT DISTINCT s.player_name, s.team_name
                    FROM tournament_player_stats s
                    JOIN tournaments t ON s.tournament_id = t.id
                    WHERE s.guild_id = ? AND t.season_number = ?
                    ORDER BY s.player_name ASC;
                    """,
                    (target_gid, season_number),
                )
            else:
                await cur.execute(
                    """
                    SELECT DISTINCT player_name, team_name
                    FROM tournament_player_stats
                    WHERE guild_id = ?
                    ORDER BY player_name ASC;
                    """,
                    (target_gid,),
                )
            rows = await cur.fetchall()
            return [{"player_name": r[0], "team_name": r[1]} for r in rows]

    async def get_distinct_tournament_clubs(
        self, tournament_id: Optional[int] = None, guild_id: Optional[int] = None
    ) -> List[str]:
        """Fetch distinct club/team names from tournament match stats."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            if tournament_id is not None:
                await cur.execute(
                    "SELECT DISTINCT team_name FROM tournament_player_stats WHERE tournament_id = ? ORDER BY team_name ASC;",
                    (tournament_id,),
                )
            elif guild_id is not None:
                await cur.execute("SELECT id FROM tournaments WHERE guild_id = ? LIMIT 1;", (guild_id,))
                has_gid = await cur.fetchone()
                target_gid = guild_id if has_gid else 0
                await cur.execute(
                    "SELECT DISTINCT team_name FROM tournament_player_stats WHERE guild_id = ? ORDER BY team_name ASC;",
                    (target_gid,),
                )
            else:
                await cur.execute("SELECT DISTINCT team_name FROM tournament_player_stats ORDER BY team_name ASC;")
            rows = await cur.fetchall()
            return [r[0] for r in rows if r[0]]

    async def get_player_name_suggestions(
        self, guild_id: int, query: str, season_number: Optional[int] = None
    ) -> List[str]:
        """Return closest candidate player names when a player search fails."""
        avail = await self.get_distinct_tournament_players(guild_id, season_number)
        avail_names = [p["player_name"] for p in avail]
        _, _, suggestions = match_player_name(query, avail_names)
        return suggestions

    async def get_player_profile(
        self, guild_id: int, player_name: str, season_number: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """Fetch cumulative player stats across active/past tournaments, with smart name resolution and optional season filter."""
        target_name = player_name.strip()
        if not target_name:
            return None

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Determine effective guild_id to avoid blending duplicate guild=0 records
            await cur.execute("SELECT id FROM tournaments WHERE guild_id = ? LIMIT 1;", (guild_id,))
            has_gid = await cur.fetchone()
            target_gid = guild_id if has_gid else 0

            # 1. Resolve canonical player name
            matched_name = target_name
            await cur.execute(
                "SELECT player_name FROM tournament_player_stats WHERE guild_id = ? AND LOWER(player_name) = LOWER(?) LIMIT 1;",
                (target_gid, target_name),
            )
            direct_row = await cur.fetchone()
            if direct_row:
                matched_name = direct_row[0]
            else:
                avail = await self.get_distinct_tournament_players(target_gid, season_number)
                avail_names = [p["player_name"] for p in avail]
                resolved_name, score, _ = match_player_name(target_name, avail_names)
                if not resolved_name or score < 0.70:
                    return None
                matched_name = resolved_name

            # 2. Query cumulative stats and competition breakdowns
            if season_number is not None:
                await cur.execute(
                    """
                    SELECT
                        player_name,
                        team_name,
                        SUM(goals) as total_goals,
                        SUM(assists) as total_assists,
                        SUM(own_goals) as total_own_goals,
                        SUM(yellow_cards) as total_yellow_cards,
                        SUM(red_cards) as total_red_cards,
                        SUM(clean_sheets) as total_clean_sheets,
                        SUM(matches_played) as total_matches,
                        SUM(minutes_played) as total_minutes,
                        AVG(rating) as avg_rating
                    FROM tournament_player_stats s
                    JOIN tournaments t ON s.tournament_id = t.id
                    WHERE s.guild_id = ? AND s.player_name = ? AND t.season_number = ?
                    GROUP BY s.player_name;
                    """,
                    (target_gid, matched_name, season_number),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                res = dict(row)
                res["season_number"] = season_number
                await cur.execute(
                    """
                    SELECT
                        s.team_name,
                        s.goals,
                        s.assists,
                        s.rating,
                        s.matches_played,
                        s.minutes_played,
                        s.clean_sheets,
                        t.season_number,
                        t.name as tournament_name
                    FROM tournament_player_stats s
                    JOIN tournaments t ON s.tournament_id = t.id
                    WHERE s.guild_id = ? AND s.player_name = ? AND t.season_number = ?
                    ORDER BY t.id ASC;
                    """,
                    (target_gid, matched_name, season_number),
                )
                res["seasons"] = [dict(r) for r in await cur.fetchall()]
                return res
            else:
                await cur.execute(
                    """
                    SELECT
                        player_name,
                        team_name,
                        SUM(goals) as total_goals,
                        SUM(assists) as total_assists,
                        SUM(own_goals) as total_own_goals,
                        SUM(yellow_cards) as total_yellow_cards,
                        SUM(red_cards) as total_red_cards,
                        SUM(clean_sheets) as total_clean_sheets,
                        SUM(matches_played) as total_matches,
                        SUM(minutes_played) as total_minutes,
                        AVG(rating) as avg_rating
                    FROM tournament_player_stats
                    WHERE guild_id = ? AND player_name = ?
                    GROUP BY player_name;
                    """,
                    (target_gid, matched_name),
                )
                row = await cur.fetchone()
                if not row:
                    return None
                res = dict(row)
                await cur.execute(
                    """
                    SELECT
                        s.team_name,
                        s.goals,
                        s.assists,
                        s.rating,
                        s.matches_played,
                        s.minutes_played,
                        s.clean_sheets,
                        t.season_number,
                        t.name as tournament_name
                    FROM tournament_player_stats s
                    JOIN tournaments t ON s.tournament_id = t.id
                    WHERE s.guild_id = ? AND s.player_name = ?
                    ORDER BY t.season_number ASC, t.id ASC;
                    """,
                    (target_gid, matched_name),
                )
                res["seasons"] = [dict(r) for r in await cur.fetchall()]
                return res

    async def get_club_player_stats(self, tournament_id: int, team_name: str) -> List[Dict[str, Any]]:
        """Fetch all tournament player records for a specific club/team with smart name and alias matching."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT
                    player_name, team_name, goals, assists, own_goals,
                    yellow_cards, red_cards, clean_sheets, matches_played,
                    minutes_played, rating
                FROM tournament_player_stats
                WHERE tournament_id = ? AND LOWER(team_name) LIKE ?
                ORDER BY rating DESC, goals DESC, assists DESC;
                """,
                (tournament_id, f"%{team_name.strip().lower()}%"),
            )
            rows = await cur.fetchall()
            if rows:
                return [dict(r) for r in rows]

            # Try smart club matching
            clubs = await self.get_distinct_tournament_clubs(tournament_id=tournament_id)
            matched_club, _ = match_club_name(team_name, clubs)
            if not matched_club:
                return []

            await cur.execute(
                """
                SELECT
                    player_name, team_name, goals, assists, own_goals,
                    yellow_cards, red_cards, clean_sheets, matches_played,
                    minutes_played, rating
                FROM tournament_player_stats
                WHERE tournament_id = ? AND team_name = ?
                ORDER BY rating DESC, goals DESC, assists DESC;
                """,
                (tournament_id, matched_club),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def conclude_tournament(self, tournament_id: int) -> Tuple[bool, str, Dict[str, Any]]:
        """Conclude and archive an active tournament, immortalizing awards in season_history."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT * FROM tournaments WHERE id = ?;", (tournament_id,))
            row = await cur.fetchone()
            if not row:
                return False, "Tournament not found.", {}
            t = dict(row)

            # Get Standings & Awards
            await cur.execute("SELECT * FROM tournament_standings WHERE tournament_id = ? ORDER BY rank ASC;", (tournament_id,))
            standings = [dict(r) for r in await cur.fetchall()]
            champ = t.get("champion") or (standings[0]["name"] if standings else "Unknown")
            runner = t.get("runner_up") or (standings[1]["name"] if len(standings) > 1 else "Unknown")

            # Golden Boot
            await cur.execute("SELECT * FROM tournament_player_stats WHERE tournament_id = ? ORDER BY goals DESC LIMIT 1;", (tournament_id,))
            gb_row = await cur.fetchone()
            gb_p = gb_row["player_name"] if gb_row else None
            gb_g = gb_row["goals"] if gb_row else 0

            # Playmaker
            await cur.execute("SELECT * FROM tournament_player_stats WHERE tournament_id = ? ORDER BY assists DESC LIMIT 1;", (tournament_id,))
            pm_row = await cur.fetchone()
            pm_p = pm_row["player_name"] if pm_row else None
            pm_a = pm_row["assists"] if pm_row else 0

            # Golden Glove
            await cur.execute("SELECT * FROM tournament_standings WHERE tournament_id = ? ORDER BY clean_sheets DESC LIMIT 1;", (tournament_id,))
            gg_row = await cur.fetchone()
            gg_t = gg_row["name"] if gg_row else None
            gg_cs = gg_row["clean_sheets"] if gg_row else 0

            # MVP
            await cur.execute("SELECT * FROM tournament_player_stats WHERE tournament_id = ? ORDER BY rating DESC LIMIT 1;", (tournament_id,))
            mvp_row = await cur.fetchone()
            mvp_p = mvp_row["player_name"] if mvp_row else None
            mvp_r = mvp_row["rating"] if mvp_row else 6.5

            # Save in season_history
            await cur.execute(
                """
                INSERT INTO season_history (
                    guild_id, season_number, competition_name, champion, runner_up,
                    golden_boot_player, golden_boot_goals, playmaker_player, playmaker_assists,
                    golden_glove_team, golden_glove_clean_sheets, mvp_player, mvp_rating
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    t["guild_id"], t["season_number"], t["name"], champ, runner,
                    gb_p, gb_g, pm_p, pm_a, gg_t, gg_cs, mvp_p, mvp_r,
                ),
            )

            # Mark completed
            await cur.execute(
                "UPDATE tournaments SET status = 'completed', champion = ?, runner_up = ? WHERE id = ?;",
                (champ, runner, tournament_id),
            )
            await conn.commit()
            t["status"] = "completed"
            t["champion"] = champ
            t["runner_up"] = runner
            return True, f"Season {t['season_number']} concluded! {champ} crowned Champions!", t

    async def get_season_history(
        self,
        guild_id: int,
        season_number: Optional[int] = None,
        competition_name: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch archived season history for the Hall of Fame."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            query = "SELECT * FROM season_history WHERE (guild_id = ? OR guild_id = 0)"
            params: List[Any] = [guild_id]
            if season_number is not None:
                query += " AND season_number = ?"
                params.append(season_number)
            if competition_name:
                query += " AND LOWER(competition_name) LIKE ?"
                params.append(f"%{competition_name.lower()}%")
            query += " ORDER BY season_number DESC, id DESC;"
            await cur.execute(query, tuple(params))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def place_matchday_bet(
        self,
        guild_id: int,
        tournament_id: int,
        matchday: int,
        fixture_id: int,
        user_id: int,
        bet_type: str,
        amount: int,
        odds: float = 2.0,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Place a bet on a match fixture with escrow funding from Club Treasury or Personal Cash."""
        if amount <= 0:
            return False, "Bet amount must be positive.", {}

        bet_type = bet_type.lower()
        if bet_type not in ("home", "draw", "away"):
            return False, "Bet choice must be 'home', 'draw', or 'away'.", {}

        conn = await self.connect()
        async with conn.cursor() as cur:
            # Check fixture exists and is unfinished
            await cur.execute("SELECT * FROM tournament_fixtures WHERE id = ?;", (fixture_id,))
            f_row = await cur.fetchone()
            if not f_row:
                return False, "Fixture not found.", {}
            fixture = dict(f_row)

            if fixture["is_finished"]:
                return False, "This match has already concluded. Bets can only be placed on unplayed fixtures.", {}

            # Prohibit betting on matches involving bottom 5 clubs
            await cur.execute(
                "SELECT name, rank FROM tournament_standings WHERE tournament_id = ? ORDER BY rank DESC LIMIT 5;",
                (tournament_id,),
            )
            b5_rows = await cur.fetchall()
            if b5_rows:
                bottom_5_map = {r["name"].strip().lower(): r["rank"] for r in b5_rows}
                h_name = fixture["home_team_name"].strip().lower()
                a_name = fixture["away_team_name"].strip().lower()
                if h_name in bottom_5_map:
                    r_num = bottom_5_map[h_name]
                    return False, f"❌ Betting is prohibited on matches involving bottom 5 clubs. **{fixture['home_team_name']}** is currently ranked #{r_num}.", {}
                if a_name in bottom_5_map:
                    r_num = bottom_5_map[a_name]
                    return False, f"❌ Betting is prohibited on matches involving bottom 5 clubs. **{fixture['away_team_name']}** is currently ranked #{r_num}.", {}

            # Check funding: Club Treasury first, then Personal Cash
            user_club = await self.get_club_by_user(guild_id, user_id)
            user_club_id = user_club["id"] if user_club else None
            funding_source = None

            await self.get_or_create_user(user_id, guild_id)
            await cur.execute("SELECT cash FROM users WHERE user_id = ? AND guild_id = ?;", (user_id, guild_id))
            u_row = await cur.fetchone()
            p_cash = u_row["cash"] if u_row else 0

            if user_club and user_club.get("treasury_cash", 0) >= amount:
                funding_source = "treasury"
                await cur.execute("UPDATE clubs SET treasury_cash = treasury_cash - ? WHERE id = ?;", (amount, user_club_id))
            elif p_cash >= amount:
                funding_source = "personal"
                await cur.execute("UPDATE users SET cash = cash - ? WHERE user_id = ? AND guild_id = ?;", (amount, user_id, guild_id))
            else:
                return False, f"Insufficient funds. You need **{amount:,} Cash** to place this bet.", {}

            # Insert transaction
            await cur.execute(
                """
                INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                VALUES (?, ?, NULL, 'cash', ?, 'match_bet_escrow', ?);
                """,
                (guild_id, user_id, amount, f"Bet Escrow: {fixture['home_team_name']} vs {fixture['away_team_name']} ({bet_type.upper()})"),
            )

            # Insert bet
            await cur.execute(
                """
                INSERT INTO matchday_bets (
                    guild_id, tournament_id, matchday, fixture_id, match_uid,
                    user_id, bet_type, amount, odds, escrow_source, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending');
                """,
                (
                    guild_id, tournament_id, matchday, fixture_id, fixture.get("match_uid"),
                    user_id, bet_type, amount, odds, funding_source,
                ),
            )
            bet_id = cur.lastrowid
            await conn.commit()
            await cur.execute("SELECT * FROM matchday_bets WHERE id = ?;", (bet_id,))
            bet_data = dict(await cur.fetchone())
            return True, f"Bet placed! Choice: **{bet_type.upper()}**, Amount: **{amount:,} Cash** ({funding_source.capitalize()}).", bet_data

    async def settle_matchday_bets(self, tournament_id: int, matchday: int) -> List[Dict[str, Any]]:
        """Evaluate and disburse winning payouts for finished matchday fixtures."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT * FROM tournament_fixtures
                WHERE tournament_id = ? AND matchday = ? AND is_finished = 1;
                """,
                (tournament_id, matchday),
            )
            finished_fixtures = [dict(r) for r in await cur.fetchall()]
            if not finished_fixtures:
                return []

            fix_outcomes = {}
            for f in finished_fixtures:
                if f["goals_home"] > f["goals_away"]:
                    outcome = "home"
                elif f["goals_home"] < f["goals_away"]:
                    outcome = "away"
                else:
                    outcome = "draw"
                fix_outcomes[f["id"]] = outcome

            await cur.execute(
                """
                SELECT * FROM matchday_bets
                WHERE tournament_id = ? AND matchday = ? AND status = 'pending';
                """,
                (tournament_id, matchday),
            )
            pending_bets = [dict(r) for r in await cur.fetchall()]
            payouts = []

            for bet in pending_bets:
                f_id = bet["fixture_id"]
                if f_id not in fix_outcomes:
                    continue

                actual = fix_outcomes[f_id]
                bet_id = bet["id"]
                u_id = bet["user_id"]
                g_id = bet["guild_id"]
                src = bet["escrow_source"]
                amt = bet["amount"]
                odds = bet["odds"]

                if bet["bet_type"] == actual:
                    # Won!
                    winnings = int(amt * odds)
                    if src == "treasury":
                        # Credit user's club treasury
                        u_club = await self.get_club_by_user(g_id, u_id)
                        if u_club:
                            await cur.execute("UPDATE clubs SET treasury_cash = treasury_cash + ? WHERE id = ?;", (winnings, u_club["id"]))
                        else:
                            await cur.execute("UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;", (winnings, u_id, g_id))
                    else:
                        await cur.execute("UPDATE users SET cash = cash + ? WHERE user_id = ? AND guild_id = ?;", (winnings, u_id, g_id))

                    await cur.execute(
                        """
                        UPDATE matchday_bets
                        SET status = 'won', payout_amount = ?, settled_at = CURRENT_TIMESTAMP
                        WHERE id = ?;
                        """,
                        (winnings, bet_id),
                    )
                    await cur.execute(
                        """
                        INSERT INTO transactions (guild_id, sender_id, receiver_id, currency, amount, tx_type, reason)
                        VALUES (?, NULL, ?, 'cash', ?, 'match_bet_win', ?);
                        """,
                        (g_id, u_id, winnings, f"Matchday {matchday} Bet Win! ({winnings:,} Cash paid to {src})"),
                    )
                    payouts.append({
                        "bet_id": bet_id,
                        "user_id": u_id,
                        "status": "won",
                        "payout": winnings,
                        "source": src,
                    })
                else:
                    # Lost
                    await cur.execute(
                        "UPDATE matchday_bets SET status = 'lost', settled_at = CURRENT_TIMESTAMP WHERE id = ?;",
                        (bet_id,),
                    )
                    payouts.append({
                        "bet_id": bet_id,
                        "user_id": u_id,
                        "status": "lost",
                        "payout": 0,
                        "source": src,
                    })

            await conn.commit()
            return payouts

    async def get_user_matchday_bets(
        self,
        guild_id: int,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """Retrieve bets placed by a user with fixture and tournament details."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            query = """
                SELECT b.*, f.home_team_name, f.away_team_name, f.goals_home, f.goals_away, f.is_finished, t.name as tournament_name
                FROM matchday_bets b
                LEFT JOIN tournament_fixtures f ON b.fixture_id = f.id
                LEFT JOIN tournaments t ON b.tournament_id = t.id
                WHERE (b.guild_id = ? OR b.guild_id = 0) AND b.user_id = ?
            """
            params: List[Any] = [guild_id, user_id]
            if status:
                query += " AND b.status = ?"
                params.append(status)
            query += " ORDER BY b.created_at DESC LIMIT ?;"
            params.append(limit)
            await cur.execute(query, tuple(params))
            rows = await cur.fetchall()
            return [dict(r) for r in rows]
