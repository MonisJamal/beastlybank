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

#### ⭐ Community Points
| Command | Prefix (`bb!`) | Description |
| :--- | :--- | :--- |
| `/redeemcp <points>` | `bb!redeemcp`, `bb!rcp` | Convert your Community Points into Cash (Exchange rate: 1 CP = 2 Cash). |

#### 🏟️ Club & Treasuries
| Command | Description |
| :--- | :--- |
| `/club create <name> <tag>` | Create your own football club and activate its treasury (100% Free). |
| `/club info [club]` | View club treasury balance, founder, and squad roster. |
| `/club deposit <currency> <amount>` | Deposit personal Cash, Points, or Tokens into your club treasury. |
| `/club withdraw <currency> <amount> <reason>` | Withdraw cash from your club treasury (Club Owners, Managers & Bankers). |
| `/club transfer <player> <@from_role> <@to_role> <amt>` | Execute official player transfer under club group. |
| `/club history` | View recent transactions for your club treasury. |
| `/clubhistory [club]` | View recent club treasury transactions. |
| `/club addmanager <user>` | Promote a squad member to Club Manager (Owner only). |
| `/club removemanager <user>` | Demote a Club Manager back to squad member (Owner only). |
| `/club list` | View the richest BeastlyFC clubs leaderboard. |

---

### 👑 ADMINS & STAFF

#### 💵 Manage Currency (`/manage`)
| Command | Description |
| :--- | :--- |
| `/manage add <user> <currency> <amount> [reason]` | Add Cash, CP or Training Tokens to a user. |
| `/manage remove <user> <currency> <amount> [reason]` | Remove Cash, CP or Training Tokens from a user. |
| `/manage set <user> <currency> <amount> [reason]` | Set a user's Cash, CP or Training Tokens to a specific amount. |
| `/manage vault <club> <currency> <action> <amount>` | Add, remove, or set club vault treasury balances directly. |

#### ⚙️ Server Settings (`/settings`)
| Command | Description |
| :--- | :--- |
| `/settings economy <enabled: bool>` | Enable or disable the server economy. |
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
