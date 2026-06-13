"""
state.py — In-memory state with async PostgreSQL persistence.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

import db
from config import GROUP_CONTEXT_ENABLED, MAX_HISTORY, OWNER_ID

_log = logging.getLogger(__name__)

# ── Fire-and-forget helper ────────────────────────────────────────────────────
def _fire(coro) -> None:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        coro.close()
        return
    task = loop.create_task(coro)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled():
            exc = t.exception()
            if exc:
                _log.warning("[state] background DB write failed: %s", exc)

    task.add_done_callback(_on_done)

# ── Auth ──────────────────────────────────────────────────────────────────────
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

# ── In-memory stores ──────────────────────────────────────────────────────────
_conversations: dict[str, list[dict]]  = {}
_topic_mode:    dict[int,  bool]        = {}
_conv_cfg:      dict[str,  dict]        = {}

pending_texts: dict[str, list[str]]    = defaultdict(list)
pending_tasks: dict[str, asyncio.Task] = {}

# Pending manual feed replies triggered by the ↩️ Reply button.
# key   : (private_chat_id, prompt_msg_id)  — the ForceReply prompt bot sent
# value : {"group_chat_id": int, "target_msg_id": int, "expires": float}
pending_feed_replies: dict[tuple[int, int], dict] = {}
_FEED_REPLY_TTL = 300  # seconds — expire after 5 min of no response


def feed_reply_set(chat_id: int, msg_id: int, group_chat_id: int, target_msg_id: int) -> None:
    import time as _t
    # Evict expired entries first
    now = _t.monotonic()
    expired = [k for k, v in pending_feed_replies.items() if now > v["expires"]]
    for k in expired:
        pending_feed_replies.pop(k, None)
    pending_feed_replies[(chat_id, msg_id)] = {
        "group_chat_id": group_chat_id,
        "target_msg_id": target_msg_id,
        "expires":       now + _FEED_REPLY_TTL,
    }


def feed_reply_pop(chat_id: int, msg_id: int) -> dict | None:
    import time as _t
    entry = pending_feed_replies.pop((chat_id, msg_id), None)
    if entry and _t.monotonic() > entry["expires"]:
        return None  # Expired — discard
    return entry

# ── Feed buffer  (per group) ─────────────────────────────────────────────────
MAX_FEED_BUFFER = 100

_feed: dict[int, deque] = {}   # chat_id → deque[FeedEntry]


class FeedEntry:
    __slots__ = ("msg_id", "date", "user_id", "user_name", "username", "text", "chat_id")

    def __init__(self, chat_id: int, msg_id: int, date: datetime,
                 user_id: int, user_name: str, username: str, text: str):
        self.chat_id   = chat_id
        self.msg_id    = msg_id
        self.date      = date
        self.user_id   = user_id
        self.user_name = user_name
        self.username  = username       # "@handle" or ""
        self.text      = text[:400]


def feed_push(entry: FeedEntry) -> None:
    q = _feed.setdefault(entry.chat_id, deque(maxlen=MAX_FEED_BUFFER))
    q.appendleft(entry)   # newest first


def feed_get(chat_id: int, n: int = 10) -> list[FeedEntry]:
    q = _feed.get(chat_id)
    if not q:
        return []
    return list(q)[:max(1, min(n, MAX_FEED_BUFFER))]


def feed_size(chat_id: int) -> int:
    q = _feed.get(chat_id)
    return len(q) if q else 0


def feed_list_chats() -> list[int]:
    """Return all chat_ids that have at least one buffered message."""
    return [cid for cid, q in _feed.items() if q]


# ── Warn system  (in-memory, persisted via bot_config) ───────────────────────
_warns: dict[tuple[int, int], int] = {}   # (chat_id, user_id) → count
MAX_WARNS = 3   # configurable via /setwarnlimit


def warn_get(chat_id: int, user_id: int) -> int:
    return _warns.get((chat_id, user_id), 0)


def warn_add(chat_id: int, user_id: int) -> int:
    key = (chat_id, user_id)
    _warns[key] = _warns.get(key, 0) + 1
    _fire(db.config_set(f"warns:{chat_id}:{user_id}", _warns[key]))
    return _warns[key]


def warn_reset(chat_id: int, user_id: int) -> None:
    _warns.pop((chat_id, user_id), None)
    _fire(db.config_delete(f"warns:{chat_id}:{user_id}"))


def warn_get_all(chat_id: int) -> dict[int, int]:
    return {uid: cnt for (cid, uid), cnt in _warns.items() if cid == chat_id}


def get_max_warns() -> int:
    return MAX_WARNS


# ── Startup loader ────────────────────────────────────────────────────────────
async def load_all_async() -> None:
    if not db.is_ready():
        _log.info("[state] DB not ready — empty in-memory state.")
        return

    all_cfg = await db.config_get_all()

    for key, value in all_cfg.items():
        if key.startswith("topic_mode:"):
            try:
                _topic_mode[int(key.split(":", 1)[1])] = bool(value)
            except (ValueError, IndexError):
                pass
        elif key.startswith("conv_cfg:"):
            cid = key[len("conv_cfg:"):]
            if isinstance(value, dict):
                _conv_cfg[cid] = value
        elif key.startswith("warns:"):
            # "warns:{chat_id}:{user_id}"
            parts = key.split(":")
            if len(parts) == 3:
                try:
                    _warns[(int(parts[1]), int(parts[2]))] = int(value)
                except (ValueError, IndexError):
                    pass

    convs = await db.conv_load_all(MAX_HISTORY)
    _conversations.update(convs)

    _log.info(
        "[state] Loaded: %d topic_mode, %d conv_cfg, %d conversations, %d warn entries.",
        sum(1 for k in all_cfg if k.startswith("topic_mode:")),
        sum(1 for k in all_cfg if k.startswith("conv_cfg:")),
        len(_conversations),
        len(_warns),
    )


# ── Conversation key builder ──────────────────────────────────────────────────
def conv_id(chat_id: int, user_id: int, thread_id: Optional[int],
            is_private: bool, topic_mode_flag: bool) -> str:
    if is_private:
        return f"u:{user_id}"
    if topic_mode_flag and thread_id:
        return f"g:{chat_id}:t:{thread_id}"
    if GROUP_CONTEXT_ENABLED:
        return f"g:{chat_id}"
    return f"g:{chat_id}:u:{user_id}"


# ── Conversation history ──────────────────────────────────────────────────────
def get_history(cid: str) -> list[dict]:
    return list(_conversations.get(cid, []))


def _append(cid: str, role: str, text: str) -> None:
    _conversations.setdefault(cid, []).append(
        {"role": role, "parts": [{"text": text}]}
    )
    if len(_conversations[cid]) > MAX_HISTORY:
        _conversations[cid] = _conversations[cid][-MAX_HISTORY:]
    _fire(db.conv_push(cid, role, text))


def push(cid: str, role: str, text: str) -> None:
    _append(cid, role, text)


def push_context(cid: str, username: str, text: str) -> None:
    _append(cid, "user", f"[{username}]: {text}")


def clear(cid: str) -> None:
    _conversations.pop(cid, None)
    _fire(db.conv_delete(cid))


def clear_all() -> None:
    _conversations.clear()
    _fire(db.conv_delete_all())


# ── Topic mode ────────────────────────────────────────────────────────────────
def topic_mode(chat_id: int) -> bool:
    return _topic_mode.get(chat_id, False)


def set_topic_mode(chat_id: int, enabled: bool) -> None:
    _topic_mode[chat_id] = enabled
    _fire(db.config_set(f"topic_mode:{chat_id}", enabled))


# ── Per-conversation config ───────────────────────────────────────────────────
def get_cfg(cid: str) -> dict:
    return dict(_conv_cfg.get(cid, {}))


def set_cfg(cid: str, **kwargs) -> None:
    _conv_cfg.setdefault(cid, {}).update(kwargs)
    _fire(db.config_set(f"conv_cfg:{cid}", _conv_cfg[cid]))
