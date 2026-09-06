# 🏦 BeastlyBank — Official Finance & Economy System for BeastlyFC ⚽

**BeastlyBank** is the premier economy, treasury, and financial ecosystem bot engineered exclusively for the **BeastlyFC** Discord server. It replaces legacy bank systems with an automated, database-backed, multi-currency financial infrastructure featuring Discord slash commands, interactive buttons, club treasuries, an integrated shop, automated giveaways, and forensic audit ledgers.

---

## 🌟 Core Features

- 💵 **Cash** — Primary server currency for player-to-player transfers, shop purchases, and club investments.
- ⭐ **Community Points** — Secondary currency earned via daily streaks, match events, and community activities.
- 🎟️ **Training Tokens** — Specialized currency earned from drills, used for player stat upgrades and club upgrades.
- 🔒 **Server-Exclusive Lock** — Hardened guild-level verification that guarantees BeastlyBank only operates within the **BeastlyFC** server.
- 🏟️ **Club Treasuries** — Dedicated team vaults for BeastlyFC squads with deposit, withdrawal, roster permissions, and inter-club treasury rankings.
- 🛒 **Interactive Shop & Inventory** — Browse perks, roles, and upgrades with automated Discord role assignment upon checkout.
- 🎉 **Automated Giveaways** — Persistent interactive buttons for instant entry, timer monitoring, crypto-random winner selection, and automatic direct bank prize payouts.
- 📜 **Automated Ledger** — Complete double-entry transaction history tracking all deposits, debits, transfers, and staff grants.
- 🏆 **Leaderboards** — Dynamic wealth rankings for Cash, Points, Tokens, and Club Treasuries.

---

## 📋 Slash Command Reference

### 💰 Economy Commands (All Members)
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/balance` | `[user]` | View your official BeastlyBank passbook, balances (Cash, Points, Tokens), daily streak, and club affiliation. |
| `/pay` | `<user> <currency> <amount> [reason]` | Instantly transfer funds to another BeastlyFC player with an automated receipt. |
| `/daily` | *None* | Claim your daily salary and build your consecutive day streak for higher bonuses. |
| `/work` | *None* | Participate in a football training drill (Scouting, Striker Drills, Video Analysis) for rewards. |
| `/transactions` | `[user]` | Browse your official BeastlyBank statement and transaction history with pagination. |

### 🏟️ Club Treasuries (`/club`)
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/club create` | `<name> <tag>` | Register a new BeastlyFC club and activate its dedicated treasury vault (2,000 Cash fee). |
| `/club info` | `[club_query]` | Inspect club treasury balances, founder, and squad roster. |
| `/club deposit` | `<currency> <amount>` | Contribute personal Cash, Points, or Tokens directly into your club's treasury. |
| `/club withdraw`| `<currency> <amount> <reason>` | Withdraw funds from the club treasury into your personal account (*Owners & Captains only*). |
| `/club list` | *None* | View the leaderboard of BeastlyFC clubs ranked by total treasury assets. |

### 🛒 Shop & Inventory
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/shop` | *None* | Browse items, perks, role rewards, and boosts in the BeastlyBank catalogue. |
| `/buy` | `<item_id> [quantity]` | Purchase an item with instant balance deduction and inventory delivery. |
| `/inventory` | `[user]` | View owned perks, upgrades, and items in your personal stash. |
| `/shop-admin add` | `<name> <desc> <price> <curr> [stock] [role]` | Staff command to add new perks or roles to the store. |
| `/shop-admin remove` | `<item_id>` | Staff command to retire an item from the shop catalogue. |

### 🎉 Giveaways (`/giveaway`)
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/giveaway start` | `<duration> <prize> [winners] [curr] [amount]` | Host a giveaway with interactive button entries and optional automated bank payout. |
| `/giveaway end` | `<message_id>` | Conclude an active giveaway immediately. |
| `/giveaway reroll` | `<message_id>` | Redraw random winners from the existing entry pool. |

### 🏆 Leaderboards
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/leaderboard` | `<category: cash \| points \| tokens \| clubs>` | Top 10 high-roller rankings with gold, silver, and bronze podium medals. |

### 👮 Banker & Staff Controls (`/bank`)
| Command | Arguments | Description |
| :--- | :--- | :--- |
| `/bank add` | `<user> <currency> <amount> [reason]` | Credit funds to a player's account. |
| `/bank remove` | `<user> <currency> <amount> [reason]` | Deduct funds from a player's account. |
| `/bank set` | `<user> <currency> <amount> [reason]` | Manually set an account's balance to an exact amount. |
| `/bank audit` | `<user>` | Generate a full financial forensic audit report on any member. |
| `/bank announce`| `[channel]` | Broadcast the official BeastlyBank launch announcement embed into the server. |

---

## 🚀 Setup & Installation

### 1. Prerequisites
- Python 3.10 or higher (Python 3.14 recommended)
- A Discord Bot Application created on the [Discord Developer Portal](https://discord.com/developers/applications)

### 2. Discord Developer Portal Configuration
1. Go to **Discord Developer Portal** ➡️ **Applications** ➡️ **New Application**.
2. Name your bot `BeastlyBank`.
3. Go to the **Bot** tab:
   - Click **Reset Token** and copy your token.
   - Under **Privileged Gateway Intents**, enable **Server Members Intent** (required for user lookups and role rewards).
4. Go to the **Installation** / **OAuth2** tab:
   - Select `bot` and `applications.commands` scopes.
   - Under permissions, select:
     - `Send Messages`, `Embed Links`, `Attach Files`, `Read Message History`, `Manage Roles` (if shop grants roles), `Use External Emojis`.
   - Copy the Generated URL and invite the bot to the **BeastlyFC** server.

### 3. Server Lock Configuration
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your values:
```ini
# Discord Bot Token
DISCORD_TOKEN=MTE...your_token_here...

# BeastlyFC Server Guild ID (STRICT SERVER LOCK)
# Right-click the BeastlyFC server icon in Discord -> Copy Server ID
BEASTLYFC_GUILD_ID=123456789012345678

# Optional: Banker / Admin Role IDs (comma-separated)
BANKER_ROLE_IDS=987654321098765432
ADMIN_ROLE_IDS=123456789012345678

# Database Path
DATABASE_PATH=beastlybank.db
```

### 4. Running the Bot

Using the project's virtual environment:
```bash
# Run the bot
.venv/bin/python3 bot.py
```

Upon boot, BeastlyBank will:
1. Initialize the SQLite database with WAL mode and indices.
2. Synchronize all slash commands instantly to the BeastlyFC guild.
3. Announce ready status in the console:
   ```text
   🏦 BeastlyBank is online and guarding BeastlyFC finances!
   🔒 SERVER LOCK: ACTIVE (Locked to Guild: 123456789012345678)
   ```

### 5. Running the Automated Test Suite
To verify database integrity and test business logic anytime:
```bash
.venv/bin/pytest -v
```
All 9 test cases will run against an in-memory/temp database and validate all economy features in under a second.
