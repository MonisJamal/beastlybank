# 🏦 BeastlyBank — Official Finance & Economy System for BeastlyFC ⚽

**BeastlyBank** is the premier economy, treasury, and financial ecosystem bot engineered exclusively for the **BeastlyFC** Discord server. It replaces legacy bank systems with an automated, database-backed, multi-currency financial infrastructure featuring Discord slash commands, interactive buttons, club treasuries, an integrated shop, automated giveaways, and forensic audit ledgers.

---

## 📋 Command Reference

> 💡 **Prefix Commands Supported!** You can use standard Discord slash commands (`/command`) or traditional prefix commands using **`bb!`** (e.g. `bb!balance`, `bb!transfer`, `bb!summary`).

### 👤 NORMAL USERS

#### 💰 Balance & Payments
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/balance [user]` | `bb!balance`, `bb!bal` | View your Cash, Community Points & Training Tokens, and club affiliation. |
| `/summary [user]` | `bb!summary`, `bb!profile` | Interactive financial profile and command cheatsheet with dropdown selector. |
| `/pay <user> <curr> <amt>` | `bb!pay <@user> <curr> <amt>` | Send Cash or Training Tokens directly to another BeastlyFC user. |
| `/transfer <player> <@from_role> <@to_role> <amt>` | `bb!transfer <player> <@from_role> <@to_role> <amt>` | Official player transfer! Debits buying club vault and deposits directly into selling club vault (supports `26e6`, `3e7`, `26m`, `500k`, `0`). |
| `/transactions [user]` | `bb!transactions`, `bb!txs` | View your recent transaction history with page navigation. |

#### 🛒 Store & Inventory
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/shop` | `bb!shop`, `bb!store` | Browse the official BeastlyFC store for roles and perks. |
| `/buy <item_id> [quantity]` | `bb!buy <item_id> [quantity]` | Purchase an item or role from the store. |
| `/inventory [user]` | `bb!inventory`, `bb!inv` | Inspect items, roles, and perks in your personal stash. |

#### 🏟️ Club & Treasuries
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/club create <name> <tag> <role: @role>` | `bb!club create <name> <tag> <@role>` | Create your own football club and link an official Discord role (100% Free). |
| `/club info [club: @role]` | `bb!club info [@role]`, `bb!club [@role]` | View club treasury balance, role mention, founder, and squad roster. |
| `/club deposit <currency> <amount> [club: @role]` | `bb!club deposit <curr> <amt> [@role]` | Deposit Cash, Points, or Tokens into your club treasury (Bankers can deposit into any club role). |
| `/club withdraw <currency> <amount> <reason> [club: @role]` | `bb!club withdraw <curr> <amt> [reason] [@role]` | Withdraw cash from your club treasury (Club Owners, Managers & Bankers). |
| `/club transfer <player> <@from_role> <@to_role> <amt>` | `bb!transfer <player> <@from_role> <@to_role> <amt>` | Official player transfer! Debits buying club vault and deposits directly into selling club vault. |
| `/club history [club: @role]` | `bb!club history [@role]` | View recent transactions for a club treasury. |
| `/clubhistory [club: @role]` | `bb!clubhistory [@role]`, `bb!chistory` | View recent club treasury transactions. |
| `/club addmanager <user>` | — | Promote a squad member to Club Manager (Owner only). |
| `/club removemanager <user>` | — | Demote a Club Manager back to squad member (Owner only). |
| `/club list` | `bb!club list` | View the richest BeastlyFC clubs leaderboard. |

#### ⚽ Squad, Lineups & Formations (`/lineup`, `/formation`, `/player`)
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/lineup [club: @role]` | `bb!lineup [@role]` | View tactical pitch lineup (GK, DEF, MID, FWD) with OVR ratings and substitutes bench. |
| `/formation set <formation> [club: @role]` | `bb!setformation <form> [@role]` | Set club tactical formation (all 12 formations supported). |
| `/formation list` | `bb!formations` | Browse all 12 supported football formations with shapes and descriptions. |
| `/player info <player> [club: @role]` | `bb!player <player> [@role]` | Inspect player profile card with position, alternate positions, rating (OVR), potential (POT), jersey number, and club. |
| `/player add <player> <pos> [status] [num] [rating] [potential] [alt_pos] [club: @role]` | `bb!addplayer <player> <pos> [status] [num] [rating] [pot] [alt_pos] [@role]` | Register a player with primary position, overall rating (1-99), potential (1-99), and alternate positions (e.g. `LW, RW`). |
| `/player edit <player> [name] [pos] [status] [num] [rating] [potential] [alt_pos] [club: @role]` | `bb!editplayer <player> <field> <val> [@role]` | Edit player position, status, jersey number, name, rating (`ovr`), potential (`pot`), or alternate positions (`alt`). |
| `/player remove <player> [club: @role]` | `bb!removeplayer <player> [@role]` | Remove a player from the club squad. |
| `/player start <player> [pos] [club: @role]` | `bb!start <player> [pos] [@role]` | Promote a player to Starting XI (enforces max 11 starters). |
| `/player bench <player> [club: @role]` | `bb!bench <player> [@role]` | Move a player to the Substitutes Bench. |
| `/player swap <player1> <player2> [club: @role]` | `bb!swap <p1> <p2> [@role]` | Tactical substitution (starter ⇄ bench) or position switch (starter ⇄ starter). |

---

### 👑 ADMINS & STAFF

#### 💵 Manage Currency (`/manage`) & Banker Vault
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/manage add <user> <currency> <amount> [reason]` | — | Add Cash, CP or Training Tokens to a user. |
| `/manage remove <user> <currency> <amount> [reason]` | — | Remove Cash, CP or Training Tokens from a user. |
| `/manage set <user> <currency> <amount> [reason]` | — | Set a user's Cash, CP or Training Tokens to a specific amount. |
| `/manage vault <@club_role> <currency> <action> <amount> [reason]` | `bb!vault <@club_role> <currency> <action> <amount> [reason]` | Operate club vaults directly: add, remove, or set treasury balances (`26e6`, `3e7`, `500k`). |

#### 🛒 Manage Shop (`/shopadmin`)
| Command | Description |
| :--- | :--- |
| `/shopadmin add <name> <desc> <price> <curr> [stock] [role]` | Add an item or role reward to the store. |
| `/shopadmin edit <item_id> [name] [desc] [price] [curr] [stock]` | Update an existing store item. |
| `/shopadmin list` | View all store items including disabled items. |
| `/shopadmin toggle <item_id>` | Enable or disable a store item. |
| `/shopadmin remove <item_id>` | Permanently delete a store item. |

#### ⚙️ Server Settings (`/settings`)
| Command | Description |
| :--- | :--- |
| `/settings economy <enabled: bool>` | Enable or disable the server economy. |
| `/settings shop <enabled: bool>` | Enable or disable the shop. |
| `/settings purchases <enabled: bool>` | Enable or disable item purchases. |
| `/settings view` | View current server settings. |

#### 🏆 Other & Utility
| Command | Description |
| :--- | :--- |
| `/leaderboard <category: cash\|points\|tokens\|clubs>` | View the richest users or top clubs in the server with medals (🥇🥈🥉). |
| `/giveaway start <duration> <prize> [winners] [curr] [amount]` | Start a new giveaway with interactive button entries & automated payouts. |
| `/giveaway end <message_id>` | Conclude an active giveaway immediately. |
| `/giveaway reroll <message_id>` | Redraw random winners from an existing giveaway. |
| `/bank audit <user>` | Run a full forensic financial audit on any member. |
| `/bank announce [channel]` | Broadcast the official BeastlyBank announcement embed to the server. |
