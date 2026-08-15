"""
state.py — In-memory state with async PostgreSQL persistence.
"""
from __future__ import annotations

import asyncio
import difflib
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
pending_media: dict[str, list[dict]]   = defaultdict(list)  # inlineData parts (ảnh/pdf/audio/video)
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


# ── User directory (username → user_id resolution) ───────────────────────────
# Telegram's Bot API cannot reliably resolve "@username" → user_id for regular
# group members (get_chat only works for channels/bots/users who already have
# a chat with the bot). So instead we passively learn (user_id, username) for
# every user the bot ever sees a message/callback/mention from, and persist it
# via the generic bot_config key/value store (key = "user:{user_id}").
_user_directory: dict[int, dict] = {}   # user_id -> {"username": str|None, "name": str}
_username_to_id: dict[str, int]  = {}   # lowercase username (no @) -> user_id


def remember_user(user_id: Optional[int], username: Optional[str] = None,
                   name: str = "") -> None:
    """Passively record a user's id/username/name so a later @username can be
    resolved back to a numeric id. Cheap no-op if nothing actually changed."""
    if not user_id:
        return
    uname = (username or "").lstrip("@").lower() or None
    prev  = _user_directory.get(user_id)
    if prev and prev.get("username") == uname and (not name or prev.get("name") == name):
        return  # nothing new to persist
    if prev and prev.get("username") and prev.get("username") != uname:
        _username_to_id.pop(prev["username"], None)
    entry = {"username": uname, "name": name or (prev or {}).get("name", "")}
    _user_directory[user_id] = entry
    if uname:
        _username_to_id[uname] = user_id
    _fire(db.config_set(f"user:{user_id}", entry))


def lookup_user_id(handle: str) -> Optional[int]:
    """Resolve '@username' or 'username' (case-insensitive) → user_id using
    the locally learned directory. Returns None if never seen before."""
    h = handle.strip().lstrip("@").lower()
    if not h:
        return None
    return _username_to_id.get(h)


def get_known_user(user_id: int) -> Optional[dict]:
    return _user_directory.get(user_id)


def search_similar_usernames(handle: str, limit: int = 5) -> list[str]:
    """Fuzzy-suggest known usernames close to `handle` (typo tolerance).
    Used to give a helpful hint when exact @username resolution fails."""
    h = handle.strip().lstrip("@").lower()
    if not h or not _username_to_id:
        return []
    known = list(_username_to_id.keys())
    # 1) prefix matches first (most likely what the user meant)
    prefix = [u for u in known if u.startswith(h)]
    # 2) fuzzy matches on the rest
    rest = [u for u in known if u not in prefix]
    fuzzy = difflib.get_close_matches(h, rest, n=limit, cutoff=0.6)
    ordered = prefix + fuzzy
    return ordered[:limit]


def search_users(query: str, limit: int = 8) -> list[dict]:
    """Search the locally-learned user directory by partial USERNAME or
    partial NAME (case-insensitive substring match). O(n) scan over the
    in-memory directory — n is the count of users the bot has ever seen,
    so this stays fast (sub-millisecond) even with thousands of entries.

    Used by the tg_search_user tool so the AI can find a user_id when it
    only has a display name / nickname (not an exact @username) — e.g.
    Owner says "ban thằng Minh" instead of "@minh123".

    Returns a list of {"user_id", "username", "name"} dicts, ranked:
    exact username match > username starts-with > name starts-with >
    substring match anywhere in username or name.
    """
    q = query.strip().lstrip("@").lower()
    if not q or not _user_directory:
        return []

    exact: list[dict] = []
    uname_prefix: list[dict] = []
    name_prefix: list[dict] = []
    contains: list[dict] = []

    for uid, info in _user_directory.items():
        uname    = info.get("username") or ""
        name     = info.get("name") or ""
        uname_lc = uname.lower()
        name_lc  = name.lower()
        if not uname_lc and not name_lc:
            continue
        entry = {"user_id": uid, "username": uname, "name": name}
        if uname_lc == q:
            exact.append(entry)
        elif uname_lc.startswith(q):
            uname_prefix.append(entry)
        elif name_lc.startswith(q):
            name_prefix.append(entry)
        elif q in uname_lc or q in name_lc:
            contains.append(entry)

    ordered = exact + uname_prefix + name_prefix + contains
    return ordered[: max(1, limit)]


def known_user_count() -> int:
    return len(_user_directory)


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
        elif key.startswith("user:"):
            # "user:{user_id}" → {"username": str|None, "name": str}
            try:
                uid = int(key.split(":", 1)[1])
            except (ValueError, IndexError):
                continue
            if isinstance(value, dict):
                _user_directory[uid] = value
                uname = value.get("username")
                if uname:
                    _username_to_id[uname] = uid

    convs = await db.conv_load_all(MAX_HISTORY)
    _conversations.update(convs)

    _log.info(
        "[state] Loaded: %d topic_mode, %d conv_cfg, %d conversations, %d warn entries, %d known users.",
        sum(1 for k in all_cfg if k.startswith("topic_mode:")),
        sum(1 for k in all_cfg if k.startswith("conv_cfg:")),
        len(_conversations),
        len(_warns),
        len(_user_directory),
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


def get_lang(cid: str) -> str:
    # Returns the language code for this conv, falling back to DEFAULT_LANG.
    from config import DEFAULT_LANG as _DL
    return _conv_cfg.get(cid, {}).get("lang", _DL)


def set_cfg(cid: str, **kwargs) -> None:
    _conv_cfg.setdefault(cid, {}).update(kwargs)
    _fire(db.config_set(f"conv_cfg:{cid}", _conv_cfg[cid]))
