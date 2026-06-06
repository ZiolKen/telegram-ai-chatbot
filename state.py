"""
state.py — In-memory state with async PostgreSQL persistence.

All public functions remain *synchronous* so callers don't need to change.
DB writes are fire-and-forget tasks (never block the message handler).
DB reads happen only at startup via load_all_async().

Memory layout
-------------
  _conversations  : { conv_id -> [{"role": ..., "parts": [{"text": ...}]}] }
  _topic_mode     : { chat_id  -> bool }
  _conv_cfg       : { conv_id  -> {model, plugins, system_prompt, ...} }

DB layout
---------
  bot_config    key = "topic_mode:{chat_id}"  value = bool
  bot_config    key = "conv_cfg:{conv_id}"    value = dict
  conversations conv_id, role, content rows
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Optional

import db
from config import MAX_HISTORY, OWNER_ID

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Fire-and-forget helper
# ---------------------------------------------------------------------------

def _fire(coro) -> None:
    """
    Schedule *coro* as a background asyncio task.
    Silently drops if no event loop is running (e.g. during module import).
    Logs (but does not propagate) any exception the coroutine raises.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return

    task = loop.create_task(coro)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            _log.debug("[state] background task error: %s", t.exception())

    task.add_done_callback(_on_done)


# ---------------------------------------------------------------------------
# Auth - owner-only
# ---------------------------------------------------------------------------

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

_conversations: dict[str, list[dict]] = {}
_topic_mode:    dict[int,  bool]       = {}
_conv_cfg:      dict[str,  dict]       = {}

# Message accumulation buffers (never persisted - intentional)
pending_texts: dict[str, list[str]]    = defaultdict(list)
pending_tasks: dict[str, asyncio.Task] = {}


# ---------------------------------------------------------------------------
# Startup - load everything from DB into memory
# ---------------------------------------------------------------------------

async def load_all_async() -> None:
    """
    Called once at bot startup (inside PTB post_init hook).
    Restores all persisted state from PostgreSQL into memory.
    Safe to call even if DB is unreachable - memory stays empty.
    """
    if not db.is_ready():
        _log.info("[state] DB not ready - starting with empty in-memory state.")
        return

    # Load config rows
    all_cfg = await db.config_get_all()

    for key, value in all_cfg.items():
        if key.startswith("topic_mode:"):
            try:
                chat_id = int(key.split(":", 1)[1])
                _topic_mode[chat_id] = bool(value)
            except (ValueError, IndexError):
                _log.warning("[state] Bad topic_mode key in DB: %s", key)

        elif key.startswith("conv_cfg:"):
            cid = key[len("conv_cfg:"):]
            if isinstance(value, dict):
                _conv_cfg[cid] = value
            else:
                _log.warning("[state] Bad conv_cfg value for %s", cid)

    # Load conversation history
    convs = await db.conv_load_all(MAX_HISTORY)
    _conversations.update(convs)

    _log.info(
        "[state] Loaded from DB: %d topic_mode, %d conv_cfg, %d conversations.",
        sum(1 for k in all_cfg if k.startswith("topic_mode:")),
        sum(1 for k in all_cfg if k.startswith("conv_cfg:")),
        len(_conversations),
    )


# ---------------------------------------------------------------------------
# Conversation key builder
# ---------------------------------------------------------------------------

def conv_id(
    chat_id:         int,
    user_id:         int,
    thread_id:       Optional[int],
    is_private:      bool,
    topic_mode_flag: bool,
) -> str:
    if is_private:
        return f"u:{user_id}"
    if topic_mode_flag and thread_id:
        return f"g:{chat_id}:t:{thread_id}"
    return f"g:{chat_id}:u:{user_id}"


# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

def get_history(cid: str) -> list[dict]:
    """Return a copy of the in-memory history for *cid*."""
    return list(_conversations.get(cid, []))


def push(cid: str, role: str, text: str) -> None:
    """
    Append a message to in-memory history and persist it to DB.
    In-memory list is trimmed to MAX_HISTORY.
    DB handles its own row-count trimming (see db._maybe_prune).
    """
    _conversations.setdefault(cid, []).append(
        {"role": role, "parts": [{"text": text}]}
    )
    if len(_conversations[cid]) > MAX_HISTORY:
        _conversations[cid] = _conversations[cid][-MAX_HISTORY:]

    _fire(db.conv_push(cid, role, text))


def clear(cid: str) -> None:
    """Delete history for one conversation (memory + DB)."""
    _conversations.pop(cid, None)
    _fire(db.conv_delete(cid))


def clear_all() -> None:
    """Delete ALL conversation history (memory + DB)."""
    _conversations.clear()
    _fire(db.conv_delete_all())


# ---------------------------------------------------------------------------
# Topic mode (per group chat)
# ---------------------------------------------------------------------------

def topic_mode(chat_id: int) -> bool:
    return _topic_mode.get(chat_id, False)


def set_topic_mode(chat_id: int, enabled: bool) -> None:
    _topic_mode[chat_id] = enabled
    _fire(db.config_set(f"topic_mode:{chat_id}", enabled))


# ---------------------------------------------------------------------------
# Per-conversation config (model, plugins, system_prompt, ...)
# ---------------------------------------------------------------------------

def get_cfg(cid: str) -> dict:
    """Return a copy of the config dict for *cid*."""
    return dict(_conv_cfg.get(cid, {}))


def set_cfg(cid: str, **kwargs) -> None:
    """Update config keys for *cid* and persist to DB."""
    _conv_cfg.setdefault(cid, {}).update(kwargs)
    _fire(db.config_set(f"conv_cfg:{cid}", _conv_cfg[cid]))
