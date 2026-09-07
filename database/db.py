"""
Database manager and ACID repository for BeastlyBank.
Supports Cash, Community Points, Training Tokens, Clubs, Shop, Inventory, Giveaways, and Auditing.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite

from config import (
    DEFAULT_FORMATION,
    SUPPORTED_FORMATIONS,
    VALID_POSITIONS,
    POSITION_CATEGORIES,
    get_formation_positions,
)

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
            ]:
                try:
                    await cur.execute(col_stmt)
                except Exception:
                    pass

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

    async def get_club_leaderboard(self, guild_id: int, limit: int = 10) -> List[Dict[str, Any]]:
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
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Add a player to a club squad (Starting XI or Bench).
        Accepts custom player name or Discord user mention/ID.
        """
        p_name = str(player_name).strip()
        if not p_name:
            return False, "Player name cannot be empty.", {}

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
                INSERT INTO club_players (club_id, guild_id, player_name, role, position, status, number, rating, potential, alt_positions, user_id)
                VALUES (?, ?, ?, 'Player', ?, ?, ?, ?, ?, ?, ?);
                """,
                (club["id"], guild_id, p_name, pos, st, number, r_val, pot_val, clean_alt, uid),
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
            return True, f"Added **{p_name}**{num_str} ({r_val} OVR / {pot_val} POT) as **{pos}**{alt_desc} ({status_desc}) to **[{club['tag']}] {club['name']}**!", dict(new_p)

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
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Edit an existing player's details (name, position, lineup status, jersey number, rating, potential, alt positions).
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

    async def set_club_formation(
        self,
        guild_id: int,
        club_query: Any,
        formation: str,
        default_owner_id: int = 0,
    ) -> Tuple[bool, str]:
        """Set tactical formation for a club and adapt starting XI positions to match new formation slots."""
        form = formation.strip().lower()
        matched = None
        for k in SUPPORTED_FORMATIONS:
            if k.lower() == form:
                matched = k
                break

        if not matched:
            return False, f"Formation '{formation}' is not supported. Supported formations: {', '.join(SUPPORTED_FORMATIONS.keys())}."

        club = await self.get_or_create_club_from_role(guild_id, club_query, default_owner_id=default_owner_id)
        if not club:
            club_label = club_query.mention if hasattr(club_query, "mention") else str(club_query)
            return False, f"Club {club_label} not found."

        conn = await self.connect()
        reassigned = []
        async with conn.cursor() as cur:
            await cur.execute(
                "UPDATE clubs SET formation = ? WHERE id = ?;",
                (matched, club["id"]),
            )

            # Fetch starting players to align with the new formation's tactical slots
            await cur.execute(
                "SELECT * FROM club_players WHERE club_id = ? AND status = 'starting' ORDER BY id ASC;",
                (club["id"],),
            )
            starters = [dict(r) for r in await cur.fetchall()]

            if starters:
                target_slots = get_formation_positions(matched)
                available_slots = list(target_slots)
                assigned_players = {}  # player_id -> new_pos
                unassigned_players = []

                # Phase 1: Keep players whose current position is directly in available slots
                for p in starters:
                    pos = (p.get("position") or "").upper()
                    if pos in available_slots:
                        assigned_players[p["id"]] = pos
                        available_slots.remove(pos)
                    else:
                        unassigned_players.append(p)

                # Phase 2: Match unassigned players using their alternate positions
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

                # Phase 3: Match remaining players by tactical category (Defense, Midfield, Attack, GK)
                final_unassigned = []
                for p in still_unassigned:
                    current_cat = POSITION_CATEGORIES.get((p.get("position") or "").upper())
                    cat_match = None
                    for slot in available_slots:
                        if POSITION_CATEGORIES.get(slot) == current_cat:
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
                for p in starters:
                    new_pos = assigned_players.get(p["id"])
                    if new_pos and new_pos != p.get("position"):
                        # Clean new position from alt_positions if present
                        alt_clean = normalize_alt_positions(p.get("alt_positions"), primary_pos=new_pos)
                        await cur.execute(
                            "UPDATE club_players SET position = ?, alt_positions = ? WHERE id = ?;",
                            (new_pos, alt_clean, p["id"]),
                        )
                        reassigned.append(f"• **{p['player_name']}**: `{p.get('position', '??')}` ➔ **`{new_pos}`**")

            await conn.commit()

        form_meta = SUPPORTED_FORMATIONS[matched]
        msg = f"Formation for **[{club['tag']}] {club['name']}** set to **{matched}** — {form_meta['desc']}."
        if reassigned:
            msg += f"\n\n📋 **Tactical Realignment Applied ({len(reassigned)} players updated):**\n" + "\n".join(reassigned[:11])
        elif starters:
            msg += f"\n\n✅ Starting XI positions already match **{matched}** requirements."
        return True, msg

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
            p1 = await self._resolve_club_player(cur, club["id"], p1_name)
            if not p1:
                return False, f"Player **{p1_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            p2 = await self._resolve_club_player(cur, club["id"], p2_name)
            if not p2:
                return False, f"Player **{p2_name}** was not found in **[{club['tag']}] {club['name']}** squad."

            if p1["id"] == p2["id"]:
                return False, "Cannot swap a player with themselves."

            if p1["status"] != p2["status"]:
                # Tactical substitution: swap both status and position
                await cur.execute(
                    "UPDATE club_players SET status = ?, position = ? WHERE id = ?;",
                    (p2["status"], p2["position"], p1["id"]),
                )
                await cur.execute(
                    "UPDATE club_players SET status = ?, position = ? WHERE id = ?;",
                    (p1["status"], p1["position"], p2["id"]),
                )
                await conn.commit()
                return True, (
                    f"🔁 **Substitution Complete!**\n"
                    f"• **{p1['player_name']}**: Now **{p2['status'].capitalize()}** ({p2['position']})\n"
                    f"• **{p2['player_name']}**: Now **{p1['status'].capitalize()}** ({p1['position']})\n"
                    f"Club: **[{club['tag']}] {club['name']}**"
                )
            else:
                # Both same status: swap positions
                await cur.execute(
                    "UPDATE club_players SET position = ? WHERE id = ?;",
                    (p2["position"], p1["id"]),
                )
                await cur.execute(
                    "UPDATE club_players SET position = ? WHERE id = ?;",
                    (p1["position"], p2["id"]),
                )
                await conn.commit()
                return True, (
                    f"🔁 **Position Swap Complete!**\n"
                    f"• **{p1['player_name']}**: Now **{p2['position']}**\n"
                    f"• **{p2['player_name']}**: Now **{p1['position']}**\n"
                    f"Club: **[{club['tag']}] {club['name']}**"
                )
