"""
Database manager and ACID repository for BeastlyBank.
Supports Cash, Community Points, Training Tokens, Clubs, Shop, Inventory, Giveaways, and Auditing.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import aiosqlite

logger = logging.getLogger("BeastlyBank.DB")


class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[aiosqlite.Connection] = None

    async def connect(self) -> aiosqlite.Connection:
        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode=WAL;")
            await self._conn.execute("PRAGMA foreign_keys=ON;")
            await self._conn.execute("PRAGMA synchronous=NORMAL;")
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

            # Club Custom Players Table (for custom written player transfers)
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS club_players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    club_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    player_name TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'Player',
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

            # Ensure role_id column exists on clubs
            try:
                await cur.execute("ALTER TABLE clubs ADD COLUMN role_id INTEGER;")
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
        self, guild_id: int, name: str, tag: str, owner_id: int
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

            # Creation fee: 100% Free!
            # Insert Club with 0 starter treasury
            await cur.execute(
                """
                INSERT INTO clubs (guild_id, name, tag, owner_id, treasury_cash, treasury_points, treasury_tokens)
                VALUES (?, ?, ?, ?, 0, 0, 0);
                """,
                (guild_id, name, tag, owner_id),
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

            # Update custom players roster
            await cur.execute(
                "DELETE FROM club_players WHERE guild_id = ? AND LOWER(player_name) = LOWER(?);",
                (guild_id, p_name),
            )
            await cur.execute(
                """
                INSERT INTO club_players (club_id, guild_id, player_name, role)
                VALUES (?, ?, ?, 'Player');
                """,
                (to_club["id"], guild_id, p_name),
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
        elif isinstance(query, str):
            clean = query.strip()
            if clean.startswith("<@&") and clean.endswith(">"):
                raw = clean.strip("<@&>")
                if raw.isdigit():
                    role_id = int(raw)
            elif clean.isdigit() and len(clean) >= 15:
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
        Search club by Discord role object, role ID, exact name/tag, or case-insensitive partial match.
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
            if q.startswith("<@&") and q.endswith(">"):
                raw_id = q.strip("<@&>")
                if raw_id.isdigit():
                    role_id = int(raw_id)
            elif q.isdigit() and len(q) >= 15:
                role_id = int(q)

        conn = await self.connect()
        async with conn.cursor() as cur:
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
                       NULL as player_name
                FROM club_members cm
                LEFT JOIN users u ON cm.user_id = u.user_id AND cm.guild_id = u.guild_id
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
                SELECT club_id, NULL as user_id, guild_id, role, transferred_at as joined_at,
                       0 as cash, 0 as points, 0 as tokens,
                       player_name
                FROM club_players
                WHERE club_id = ?
                ORDER BY id ASC;
                """,
                (club_id,),
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
            club = await self.get_club_by_name(guild_id, club_query)
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

            updated_club = await self.get_club_by_name(guild_id, club_query)
            return True, f"Successfully updated [{club['tag']}] {club['name']} vault!", {
                "club": updated_club,
                "currency": currency,
                "action": action,
                "amount": amount,
                "previous": current_val,
                "new_balance": new_val,
            }

    async def set_club_manager(
        self, club_id: int, owner_id: int, target_user_id: int, is_manager: bool
    ) -> Tuple[bool, str]:
        """Promote or demote a club member to/from Manager role (Owner only)."""
        conn = await self.connect()
        async with conn.cursor() as cur:
            await cur.execute("SELECT owner_id, tag, name FROM clubs WHERE id = ?;", (club_id,))
            club = await cur.fetchone()
            if not club:
                return False, "Club not found."
            if club["owner_id"] != owner_id:
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
