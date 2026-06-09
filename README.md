# Telegram AI Agent

A Telegram chatbot powered by Gemini AI with multi-turn function calling.
The bot can do everything a human admin can do on Telegram — and then some.

---

## Features

| Category | Details |
|---|---|
| **AI** | Gemini 3.x / 2.x models, multi-key rotation, multi-model fallback, multi-turn function calling (up to 12 rounds/message) |
| **Web** | DuckDuckGo & Google search, full-page URL fetch, ArXiv paper search |
| **Code** | Safe Python sandbox — subprocess with 15s timeout, AST security scan, no network/filesystem access |
| **Messaging** | Send text, photos, stickers, GIFs, polls, dice to any chat or channel |
| **Files** | Send any file format (document, audio, video, image) via URL or `file_id`; in-RAM cache up to 256 MB |
| **Moderation** | Ban, unban, mute, unmute users |
| **Admin** | Promote/demote admins, pin/unpin messages, delete messages, forward, copy |
| **Chat mgmt** | Set title/description, get chat info, member count |
| **Edit messages** | Edit bot's own text *and* media messages — auto-detects text vs caption |
| **Group context** | Reads and stores **all** messages from everyone in a group; AI always has full conversation context |
| **Topic isolation** | Per-topic history and config in Supergroups with Topics |
| **Follow-up** | Auto-generates 3 clickable follow-up questions after each response |
| **Persistence** | Full conversation history and config stored in PostgreSQL; survives restarts |

---

## Prerequisites

- Python 3.11+
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
| `ENABLE_FOLLOWUP` | `true` | Generate follow-up question buttons after responses |
| `FOLLOWUP_COUNT` | `3` | Number of follow-up questions to generate |
| `MESSAGE_MERGE_DELAY` | `1.5` | Seconds to wait before processing, to merge rapid consecutive messages |
| `GOOGLE_API_KEY` | `""` | Google Custom Search API key (optional, enhances web search) |
| `GOOGLE_CSE_ID` | `""` | Google Custom Search Engine ID |

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
| `/reset` | Clear conversation history for this chat/topic |
| `/sysreset` | Clear **all** conversation history (every chat) |
| `/model` | Show current model with an inline keyboard to switch |
| `/setmodel` | Alias for `/model` |
| `/plugins on\|off` | Enable or disable all tools for this conversation |
| `/status` | Show current model, history length, plugin state, DB usage |
| `/topic on\|off` | Toggle topic isolation mode (groups only) |

---

## Usage

### Private chat
Message the bot directly — it always responds.

### Group / Supergroup
The bot responds when:
- You **@mention** it: `@YourBot summarize this thread`
- You **reply** to one of its messages
- You are the owner (always triggers a response)

When `GROUP_CONTEXT_ENABLED=true` (the default), the bot silently stores messages from all
other users in a shared conversation history. This gives the AI full context about the ongoing
conversation without responding to everyone.

### Topic Mode (Supergroup with Topics enabled)
Run `/topic on` in the group. Each forum topic gets its own isolated conversation history
and config — `/model` or `/plugins` in topic A do not affect topic B.

---

## Available Models

| Model | Notes |
|---|---|
| `gemini-3.5-flash` | Latest Gemini 3.5 |
| `gemini-3.1-flash-lite` | **Default** — best speed/cost balance |
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
| `web_search` | Search the web via DuckDuckGo (default) or Google |
| `fetch_url` | Fetch and extract readable text from any URL |
| `arxiv_search` | Search ArXiv for scientific papers |

### Code

| Tool | Description |
|---|---|
| `run_python` | Execute Python 3 in a sandboxed subprocess (15s timeout). Allowed stdlib: `math`, `json`, `re`, `datetime`, `random`, `itertools`, `functools`, `collections`, `statistics`, `base64`, `hashlib`, `decimal`. Network and filesystem access are blocked. |

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
| `tg_mute_user` | Restrict a user from sending messages (duration in minutes, 0 = permanent) |
| `tg_unmute_user` | Restore full messaging rights |

### Telegram — Admin & Chat Management

| Tool | Description |
|---|---|
| `tg_promote_admin` | Grant admin rights to a user (configurable permissions) |
| `tg_demote_admin` | Remove all admin rights from a user |
| `tg_set_chat_title` | Change the group or channel title |
| `tg_set_chat_description` | Update the group or channel description |
| `tg_get_chat_info` | Get name, ID, type, username, description of a chat |
| `tg_get_chat_members_count` | Get the member count of a group or channel |

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
agent.py          Gemini API loop — multi-turn function calling
handlers.py       Message accumulation, context storage, response dispatch
commands.py       Slash command handlers
tools_web.py      web_search, fetch_url, arxiv_search
tools_code.py     run_python (sandboxed subprocess + AST security scan)
tools_telegram.py 26 Telegram action tools
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

## Notes

- The bot only responds to the user whose Telegram ID matches `OWNER_ID`. No other user can trigger AI responses.
- Tools that require admin rights (`tg_ban_user`, `tg_pin_message`, `tg_delete_message`, etc.) require the bot to have the corresponding admin permission in the target group.
- The bot must be a member of any group or channel before `tg_send_message` can target it.
- Python code execution has no network or filesystem access. Blocked modules include `os`, `sys`, `subprocess`, `socket`, `requests`, and all database drivers.
- The in-memory file cache is cleared on every Render restart. Telegram `file_id` values remain valid across restarts and can be reused.
- Conversation history is persisted in PostgreSQL and restored on startup, so context survives restarts.
- The `MAX_CONV_ROWS` limit prunes the oldest rows in the `conversations` table to prevent unbounded growth.

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
