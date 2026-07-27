# Telegram AI Agent

A Telegram chatbot powered by Gemini AI with multi-turn function calling.
The bot can do everything a human admin can do on Telegram — and then some.

---

## Features

| Category | Details |
|---|---|
| **AI** | Gemini 3.x / 2.x models, multi-key rotation, multi-model fallback, multi-turn function calling (up to 12 rounds/message) |
| **Web** | Tavily (primary) & DuckDuckGo (fallback) search, full-page URL fetch, ArXiv paper search |
| **Code** | `run_python` — full Python (stdlib + installed packages, incl. network/filesystem, 60s timeout), owner-only, every run mirrored to the owner's chat as an audit log |
| **Messaging** | Send text, photos, stickers, GIFs, polls, dice to any chat or channel |
| **Files** | Send any file format (document, audio, video, image) via URL or `file_id`; in-RAM cache up to 256 MB |
| **Moderation** | Ban, unban, mute, unmute users; warn system with auto-ban at 3 warnings (default); `/feed` buffer (last 100 messages) with inline action buttons — the **Reply** button sends a ForceReply prompt so you can type a response that gets forwarded to the original group message without leaving your private chat |
| **Admin** | Promote/demote admins (with granular permission flags + custom title), pin/unpin messages, delete messages, forward, copy |
| **Chat mgmt** | Set title/description, get chat/user info, member count, create invite links, invite/remove users, leave chats, send media albums |
| **User resolution** | Resolves `@username`, `t.me/username`, and `tg://user?id=...` to a numeric Telegram user ID for moderation actions. Passively learns every user seen (messages, mentions, replies, joins/leaves, pins) plus the current chat's admin list, persisted to PostgreSQL — no `get_chat()` limitation for regular group members. Typo-tolerant suggestions when a username isn't found. |
| **Edit messages** | Edit bot's own text *and* media messages — auto-detects text vs caption |
| **Group context** | Reads and stores **all** messages from everyone in a group; AI always has full conversation context |
| **Topic isolation** | Per-topic history and config in Supergroups with Topics |
| **Language** | Full bilingual support: `en` (English) and `vi` (Vietnamese). Switches UI strings, slash-command replies, and the Gemini system prompt so AI responds in the selected language. Per-conversation setting, stored in DB. |
| **Follow-up** | Auto-generates clickable follow-up questions after each response (count configurable via `FOLLOWUP_COUNT`, default 3) |
| **Persistence** | Full conversation history and config stored in PostgreSQL; survives restarts |

---

## Prerequisites

- Python 3.12+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- One or more [Gemini API keys](https://aistudio.google.com/app/apikey)
- A PostgreSQL database (Aiven, Neon, Supabase, Render Postgres, or any standard instance)

---

## Environment Variables

### Required

| Variable | Description |
|---|---|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `OWNER_ID` | Your Telegram user ID — the **only** user who can interact with the bot |
| `GEMINI_KEYS` | Comma-separated Gemini API keys: `key1,key2,key3` |
| `DATABASE_URL` | PostgreSQL connection string, e.g. `postgresql://user:pass@host:5432/db?sslmode=require` |
| `WEBHOOK_URL` | Public HTTPS URL of your server, e.g. `https://mybot.onrender.com` (webhook mode only) |

### Optional

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8080` | HTTP server port |
| `WEBHOOK_SECRET` | `""` | Secret token for webhook request validation |
| `DEFAULT_MODEL` | `gemini-3.1-flash-lite` | Gemini model used for new conversations |
| `MAX_HISTORY` | `40` | Max conversation turns kept in memory per conversation |
| `MAX_CONV_ROWS` | `10000` | Max rows in the PostgreSQL `conversations` table before LRU pruning |
| `GROUP_CONTEXT_ENABLED` | `true` | Store all group messages (from everyone) as shared context |
| `FILE_CACHE_MAX_MB` | `256` | RAM limit for the in-memory file cache (MB) |
| `ENABLE_PLUGINS` | `true` | Enable all tools/plugins globally |
| `DEFAULT_LANG` | `en` | Default bot language (`en` = English, `vi` = Vietnamese). Override per-conversation with `/lang` |
| `ENABLE_FOLLOWUP` | `true` | Generate follow-up question buttons after responses |
| `FOLLOWUP_COUNT` | `3` | Number of follow-up questions to generate |
| `MESSAGE_MERGE_DELAY` | `1.5` | Seconds to wait before processing, to merge rapid consecutive messages |
| `TAVILY_API_KEY` | `""` | Tavily API key (optional, primary web_search engine; falls back to DuckDuckGo if unset). Uses `search_depth=advanced` (2 credits/call, deeper & more relevant snippets) — free tier gives 1,000 credits/month = ~500 searches |
| `DB_READONLY_URL` | `""` | Optional read-only PostgreSQL connection string, exposed **only** to the `run_python` sandbox (env var) so the AI can query the DB via `asyncpg` without ever touching the writable `DATABASE_URL`. See [Security notes](#security-notes) for how to get one on Aiven. |

---

## Running Locally (Polling)

```bash
git clone <repo>
cd telegram-ai-chatbot
pip install -r requirements.txt

export BOT_TOKEN="your_token"
export OWNER_ID="123456789"
export GEMINI_KEYS="key1,key2"
export DATABASE_URL="postgresql://..."

python db.py && python main.py
```

`db.py` runs first: connects to the database, creates tables/indexes if they don't exist, then exits.
`main.py` starts the bot in long-polling mode when `WEBHOOK_URL` is not set.

---

## Deploying to Render

1. Create a **Web Service** on [render.com](https://render.com)
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `python db.py && python main.py`
4. Add all required environment variables in the Render dashboard
5. Set `WEBHOOK_URL` to the URL Render assigns (e.g. `https://mybot.onrender.com`)
6. Link a Render Postgres instance or paste any external `DATABASE_URL`

> **Why `python db.py && python main.py`?**
> `db.py` validates the DB connection and ensures the schema exists before the bot starts.
> If the DB is unreachable, `db.py` exits with code 1 and `main.py` never runs — preventing the bot
> from silently starting without persistence.

---

## Commands

All commands are **owner-only**.

| Command | Description |
|---|---|
| `/start` | Introduction message |
| `/help` | Show all commands |
| `/lang en\|vi` | Switch bot language (UI + AI prompt). Default: `en` |
| `/reset` | Clear conversation history for this chat/topic |
| `/sysreset` | Clear **all** conversation history (every chat) |
| `/model` | Show current model with an inline keyboard to switch |
| `/setmodel` | Alias for `/model` |
| `/plugins on\|off` | Enable or disable all tools for this conversation |
| `/status` | Show current model, history length, plugin state, DB usage |
| `/topic on\|off` | Toggle topic isolation mode (groups only) |
| `/del [id]` | Delete a message — reply to it or pass a message ID |
| `/pin [silent]` | Pin the replied-to message; add `silent` to skip notification |
| `/ban [@user] [reason]` | Permanently ban a user |
| `/unban @user` | Unban a user |
| `/mute [@user] <duration>` | Mute a user (`30s`, `5m`, `2h`, `1d`, `1w`, `3mo`, `1y`; omit = permanent. Note: `m`=minutes, `mo`=months) |
| `/unmute @user` | Restore full messaging rights |
| `/addadmin [@user] [flags]` | Promote a user to admin. Flags: `del pin inv restrict topics promote info video post title:Name` |
| `/rmadmin @user` | Remove all admin rights from a user |
| `/warn [@user] [reason]` | Warn a user. Automatically bans when max warns is reached (default: **3**) |
| `/warns [@user]` | Show warn count for a user (or all warned users) |
| `/resetwarns @user` | Reset all warns for a user |
| `/feed [group_id] [n]` | Show last *n* messages from a group's context buffer (default 5, max 100). In private chat, pass the group's `chat_id` (auto-selected if only one group is buffered). Action buttons: **Reply** → ForceReply prompt (type to send a reply into the group), **Del**, **Pin**, **Warn**, **Mute**, **Ban** |
| `/cancel` | Cancel a pending ForceReply prompt started by the `/feed` Reply button |

---

## Usage

### Private chat
Message the bot directly — it always responds.

### Group / Supergroup
The bot only responds to the **owner** (`OWNER_ID`), and only when:
- You **@mention** it: `@YourBot summarize this thread`
- You **reply** to one of its messages

Messages from other users never trigger a response, but with `GROUP_CONTEXT_ENABLED=true`
(the default) they are silently stored as shared context, giving the AI full visibility into
the ongoing conversation without responding to everyone. Slash commands (e.g. `/ban`, `/del`)
still work regardless of mention/reply.

### Topic Mode (Supergroup with Topics enabled)
Run `/topic on` in the group. Each forum topic gets its own isolated conversation history
and config — `/model` or `/plugins` in topic A do not affect topic B.

---

## Available Models

| Model | Notes |
|---|---|
| `gemini-3.1-flash-lite` | **Default** — fastest, lowest cost |
| `gemini-3.5-flash` | Latest Gemini 3.5 |
| `gemini-3-flash-preview` | Gemini 3.0 preview |
| `gemini-2.5-flash` | Gemini 2.5 stable |
| `gemini-2.5-flash-lite-preview-06-17` | Lightweight 2.5 |
| `gemini-2.0-flash` | Gemini 2.0 |
| `gemini-2.0-flash-lite` | Fast 2.0 |
| `gemini-1.5-pro` | Higher reasoning |
| `gemini-1.5-flash` | Gemini 1.5 |
| `gemini-1.5-flash-8b` | Smallest 1.5 |

The agent automatically falls back to the next model/key if a request fails or hits a rate limit.

---

## Tool Reference

### Web

| Tool | Description |
|---|---|
| `web_search` | Search the web via Tavily (default, if configured) or DuckDuckGo (fallback) |
| `fetch_url` | Fetch and extract readable text from any URL |
| `arxiv_search` | Search ArXiv for scientific papers |

### Code

| Tool | Description |
|---|---|
| `run_python` | Execute Python 3 in a subprocess (60s timeout). Full stdlib plus everything installed in the bot's venv (`os`, `socket`, `urllib`, `requests`/`aiohttp`, `asyncpg`, `beautifulsoup4`, ...) — network and filesystem access are **allowed**. Gets `DB_READONLY_URL` as an env var for read-only DB queries via `asyncpg`. **Only reachable by the Owner** (see [Security notes](#security-notes)); every call is mirrored in full (code + output) to the owner's chat regardless of what the AI says in its reply. |

### Telegram — Messaging

| Tool | Description |
|---|---|
| `tg_send_message` | Send a text message; supports HTML formatting and clickable links |
| `tg_send_photo` | Send a photo via URL or `file_id`, with optional HTML caption |
| `tg_send_document` | Send any file (document, audio, video, image) via URL or `file_id`; auto-detects type; uses in-RAM cache to avoid re-uploading the same file |
| `tg_send_sticker` | Send a sticker via `file_id` or `.webp`/`.tgs` URL |
| `tg_send_animation` | Send a GIF or animation via `file_id` or `.gif`/`.mp4` URL |
| `tg_send_poll` | Create an interactive poll |
| `tg_send_dice` | Send an animated emoji game (🎲 🎯 🏀 ⚽ 🎳 🎰) |
| `tg_send_media_group` | Send an album of up to 10 photos/videos in one message (via URL or `file_id`) |
| `tg_forward_message` | Forward a message to another chat |
| `tg_copy_message` | Copy a message without the "Forwarded from" label |

### Telegram — Editing & Reactions

| Tool | Description |
|---|---|
| `tg_edit_message` | Edit a message the bot sent. Automatically uses `editMessageText` for text messages and `editMessageCaption` for messages that contain media (photo, video, document, etc.) |
| `tg_react` | Set an emoji reaction on any message |

### Telegram — Moderation

| Tool | Description |
|---|---|
| `tg_delete_message` | Delete a message (requires Delete Messages admin permission) |
| `tg_pin_message` | Pin a message |
| `tg_unpin_message` | Unpin a specific message or all messages |
| `tg_ban_user` | Permanently ban a user |
| `tg_unban_user` | Unban a user |
| `tg_mute_user` | Restrict a user from sending messages for `duration_minutes` (0 = permanent) |
| `tg_unmute_user` | Restore full messaging rights |
| `tg_resolve_user` | Resolve `@username` / `t.me/username` / `tg://user?id=...` to a numeric user ID before acting on it (or to get a clear error + suggestions if the bot doesn't know that user) |

### Telegram — Admin & Chat Management

| Tool | Description |
|---|---|
| `tg_promote_admin` | Grant admin rights to a user (configurable permissions + custom title) |
| `tg_demote_admin` | Remove all admin rights from a user |
| `tg_set_user_title` | Set a custom admin title for a user |
| `tg_set_chat_title` | Change the group or channel title |
| `tg_set_chat_description` | Update the group or channel description |
| `tg_get_chat_info` | Get name, ID, type, username, description of a chat |
| `tg_get_chat_members_count` | Get the member count of a group or channel |
| `tg_get_user_info` | Get a user's name, ID, username, and membership status in a chat |
| `tg_create_invite_link` | Create an invite link (optional name, expiry, member limit, join-request mode) |
| `tg_invite_user` | Add a user directly to a group/channel (requires Invite Users permission) |
| `tg_leave_chat` | Make the bot leave a group or channel |

---

## Example Prompts

```
# Web search
What are the latest AI news from this week?

# Fetch a page
Summarize the article at https://example.com/article

# Run Python
Find all prime numbers below 1000 using a sieve

# Send a message to another group
Send "Meeting at 3pm today!" to @mygroup

# React to a message
React 🔥 to the message above

# Create a poll
Create a poll "Lunch options?" with: Pizza, Sushi, Burgers, Salad

# Send a file
Send the PDF at https://example.com/report.pdf to this chat with caption "Q3 Report"

# Edit a photo caption
Edit message 12345 to say "Updated: Q3 revenue results (revised)"

# Scientific search
Find the 3 most recent papers on retrieval-augmented generation on ArXiv

# Admin action
Mute user 987654321 for 30 minutes
```

---

## Architecture

```
main.py           Entry point — webhook server (aiohttp) + PTB bot
db.py             Standalone DB setup script + asyncpg connection pool
config.py         All configuration from environment variables
state.py          In-memory state with fire-and-forget PostgreSQL writes
i18n.py           Bilingual (en/vi) UI string tables
agent.py          Gemini API loop — multi-turn function calling
handlers.py       Message accumulation, context storage, response dispatch, passive user-directory learning (messages, joins/leaves, chat_member updates)
commands.py       Slash command handlers
tools_web.py      web_search, fetch_url, arxiv_search
tools_code.py     run_python (unrestricted subprocess, 60s timeout, mirrors code+output to owner)
tools_telegram.py 31 Telegram action tools
file_cache.py     In-RAM file cache (LRU eviction, no disk/DB writes)
utils.py          md_to_html, split_message, merge
```

### Startup sequence

```
python db.py          → connect PostgreSQL, create schema, exit 0
python main.py
  ├─ db.init()        → reconnect (fast, DB already confirmed healthy)
  ├─ state.load()     → restore conversations + config from DB into RAM
  ├─ aiohttp server   → Render health check passes
  ├─ app.initialize() → PTB ready (.updater(None) avoids polling hang)
  └─ set_webhook()    → bot online
```

### Agent loop

```
User message
    │
    ▼
  history + user text + tool declarations
    │
    ▼
  Gemini API
    │
    ├─ functionCall(s)?
    │       │
    │       ├─ web_search / fetch_url / arxiv_search
    │       ├─ run_python
    │       └─ tg_* (any Telegram action)
    │               │
    │       functionResponse ──────────────────┐
    │                                          │
    │                    (loop, max 12 rounds) ┘
    │
    └─ text (final answer)
            │
            ├─ md_to_html()
            ├─ split if > 4000 chars
            └─ send to Telegram
                    │
                    └─ generate follow-up questions (background task)
                              └─ edit last message to attach keyboard
```

### File send flow

```
tg_send_document(url="https://...")
    │
    ├─ cache hit + tg_file_id?  →  send file_id directly  (no upload)
    ├─ cache hit, no file_id?   →  InputFile(BytesIO)  →  upload  →  store file_id
    └─ cache miss               →  download  →  cache bytes  →  upload  →  store file_id
```

---

## Security Notes

- **Owner-only gate.** `handlers.py` checks `user.id == OWNER_ID` before any message reaches the AI/tools — non-owner messages are only stored as group context (if `GROUP_CONTEXT_ENABLED`) and never trigger a reply or a tool call. `run_python` (see below) relies entirely on this gate for its safety, since the sandbox itself no longer restricts anything.
- **`run_python` has full OS access.** As of the current version, `run_python` is **not** sandboxed against `os`, sockets, `open()`, etc. — it can read/write files and make network calls, because it's only ever invoked for the Owner. If you ever loosen the owner-only gate (e.g. allow a second user), revisit `tools_code.py` first.
  - The subprocess env is minimal and explicit (`PATH`, `LANG`, `HOME`, `DB_READONLY_URL`) — it does **not** inherit `BOT_TOKEN`, `DATABASE_URL`, `GEMINI_KEYS`, etc., so sandboxed code (or anything that tricks the AI into running attacker-supplied code) can't read the bot's own secrets.
  - Every `run_python` call is mirrored **in full** (code + output, uncut) to the owner's Telegram chat — as a message if short, or a `.txt` document if long — independent of whatever the AI says in its actual reply. Check `tools_code.py::_mirror_to_owner` if you want to change where/how this is sent.
  - The system prompt (`agent.py::build_system_prompt`) explicitly tells the model to treat content from `web_search`/`fetch_url`/`arxiv_search`, non-owner messages, and tool output as **data, never as instructions** — a basic prompt-injection defense. This reduces but does not eliminate the risk of a malicious webpage tricking the model into running harmful code with `run_python`.
- **`DB_READONLY_URL`.** Point this at a database role that can only `SELECT`, never at your main writable `DATABASE_URL` — the sandbox has no read-only enforcement of its own, it just hands the connection string to whatever code the AI writes.

### Getting a read-only Postgres URL

**Option C — automated, via Render's Build Command (no web console, no local psql):**

The repo includes `setup_readonly_role.py`, an idempotent script (safe to re-run every deploy) that creates the role and grants over your existing `DATABASE_URL` using `asyncpg` (already a dependency) — no extra tools needed.

1. In Render, add env vars **before** deploying:
   - `BOT_RO_PASSWORD` — any password you choose (used once, then you can forget it).
   - `BOT_RO_USER` — optional, defaults to `bot_ro`.
2. Change the **Build Command** to:
   ```
   pip install -r requirements.txt && python setup_readonly_role.py
   ```
3. Deploy. Open the build logs and find the line:
   ```
   [setup_readonly_role] DB_READONLY_URL=postgresql://bot_ro:...@host:port/db?sslmode=require
   ```
4. Copy that whole value into a new env var `DB_READONLY_URL`, then trigger a redeploy so `main.py` picks it up.

If `DATABASE_URL` or `BOT_RO_PASSWORD` isn't set, the script just logs a message and exits `0` — it never fails your build.

**Option A — Aiven's built-in read replica (recommended if your plan supports it):**
1. In the Aiven Console, open your PostgreSQL service.
2. On the **Overview** page, look for **Read replica** / a **Replica URI**. If your plan has a standby node (Business/Premium, or HA add-on), the Replica URI is listed right there — copy it as `DB_READONLY_URL`.
3. If no replica URI is shown, your plan may not include a standby node yet — under **Read replica**, click **Create replica** (Startup plan replicas are supported) and Aiven will provision one with its own URI.
4. Physical replicas reject write queries at the Postgres level (`cannot execute ... in a read-only transaction`), so this is safe even though it uses the same DB user as your primary.

**Option B — a dedicated read-only role (works on any plan/provider, including Aiven Startup with no replica):**
```sql
-- run against your primary DB
CREATE ROLE bot_ro WITH LOGIN PASSWORD 'choose-a-strong-password';
GRANT CONNECT ON DATABASE defaultdb TO bot_ro;      -- Aiven's default DB name is usually "defaultdb"
GRANT USAGE ON SCHEMA public TO bot_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO bot_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO bot_ro;
```
Then build the DSN using your service's host/port from the Aiven Overview page (same host/port as `DATABASE_URL`, just swap in the new user/password):
```
postgresql://bot_ro:choose-a-strong-password@<your-service>.aivencloud.com:<port>/defaultdb?sslmode=require
```
Set that as `DB_READONLY_URL`. This role can `SELECT` but literally cannot `INSERT`/`UPDATE`/`DELETE`/`DROP`, regardless of what code runs against it — the strongest guarantee here since it doesn't depend on the sandbox behaving.

---

## Notes

- The bot only responds to the user whose Telegram ID matches `OWNER_ID`. No other user can trigger AI responses.
- Tools that require admin rights (`tg_ban_user`, `tg_pin_message`, `tg_delete_message`, etc.) require the bot to have the corresponding admin permission in the target group.
- The bot must be a member of any group or channel before `tg_send_message` can target it.
- `run_python` has full network/filesystem access and no import restrictions — see [Security notes](#security-notes) for why this is safe here and how to configure `DB_READONLY_URL`.
- The in-memory file cache is cleared on every Render restart. Telegram `file_id` values remain valid across restarts and can be reused.
- Conversation history is persisted in PostgreSQL and restored on startup, so context survives restarts.
- The `MAX_CONV_ROWS` limit prunes the oldest rows in the `conversations` table to prevent unbounded growth.
- The `/feed` buffer holds the last **100 messages** per group (in-memory, cleared on restart). `GROUP_CONTEXT_ENABLED=true` is required to populate it.
- The warn system auto-bans a user when they accumulate **3 warnings** (default). The `/feed` Reply button works by sending a ForceReply prompt to the owner; use `/cancel` to abort it.

---

## License

This project is licensed under the [MIT](LICENSE).

---

## Credits

Created and maintained by **[ZiolKen](https://github.com/ZiolKen)**.

---

## Support

If you find this helpful:

[![BuyMeACoffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/_zkn)
[![PayPal](https://img.shields.io/badge/PayPal-00457C?style=for-the-badge&logo=paypal&logoColor=white)](https://paypal.me/zkn0461)
[![Patreon](https://img.shields.io/badge/Patreon-F96854?style=for-the-badge&logo=patreon&logoColor=white)](https://patreon.com/ZiolKen)

<div>
  <img style="width: 100%;" src="https://capsule-render.vercel.app/api?type=waving&height=110&section=footer&fontSize=60&fontColor=FFFFFF&fontAlign=50&fontAlignY=40&descSize=18&descAlign=50&descAlignY=70&theme=cobalt" />
</div>
