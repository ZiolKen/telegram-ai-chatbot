"""
Centralised in-memory state with JSON persistence.
All runtime data lives here: conversation history, access lists,
topic-mode flags, per-conversation config, and message-accumulation buffers.
"""
import asyncio
import json
import os
from collections import defaultdict
from typing import Optional

from config import DATA_DIR, MAX_HISTORY, OWNER_ID

os.makedirs(DATA_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# Conversation History
# Key formats:
#   Private chat          → "u:{user_id}"
#   Group (per-user)      → "g:{chat_id}:u:{user_id}"
#   Group topic-isolated  → "g:{chat_id}:t:{thread_id}"
# ─────────────────────────────────────────────────────────────
_conversations: dict[str, list[dict]] = {}


def conv_id(
    chat_id: int,
    user_id: int,
    thread_id: Optional[int],
    is_private: bool,
    topic_mode: bool,
) -> str:
    if is_private:
        return f"u:{user_id}"
    if topic_mode and thread_id:
        return f"g:{chat_id}:t:{thread_id}"
    return f"g:{chat_id}:u:{user_id}"


def get_history(cid: str) -> list[dict]:
    return list(_conversations.get(cid, []))


def push(cid: str, role: str, text: str):
    _conversations.setdefault(cid, []).append(
        {"role": role, "parts": [{"text": text}]}
    )
    if len(_conversations[cid]) > MAX_HISTORY:
        _conversations[cid] = _conversations[cid][-MAX_HISTORY:]


def clear(cid: str):
    _conversations.pop(cid, None)


def clear_all():
    _conversations.clear()


# ─────────────────────────────────────────────────────────────
# Topic Mode  (per group)
# ─────────────────────────────────────────────────────────────
_topic_mode: dict[int, bool] = {}


def topic_mode(chat_id: int) -> bool:
    return _topic_mode.get(chat_id, False)


def set_topic_mode(chat_id: int, enabled: bool):
    _topic_mode[chat_id] = enabled
    _save("topic_mode.json", {str(k): v for k, v in _topic_mode.items()})


# ─────────────────────────────────────────────────────────────
# Per-conversation Config
# (model override, plugins on/off, custom system prompt)
# ─────────────────────────────────────────────────────────────
_conv_cfg: dict[str, dict] = {}


def get_cfg(cid: str) -> dict:
    return dict(_conv_cfg.get(cid, {}))


def set_cfg(cid: str, **kwargs):
    _conv_cfg.setdefault(cid, {}).update(kwargs)
    _save("conv_cfg.json", _conv_cfg)


# ─────────────────────────────────────────────────────────────
# Access Control
# ─────────────────────────────────────────────────────────────
_admins: set[int]    = set()
_whitelist: set[int] = set()   # empty = everyone allowed
_blacklist: set[int] = set()


def is_owner(uid: int)  -> bool: return uid == OWNER_ID
def is_admin(uid: int)  -> bool: return is_owner(uid) or uid in _admins


def allowed(uid: int) -> bool:
    if uid in _blacklist:
        return False
    if _whitelist:
        return uid in _whitelist or is_admin(uid)
    return True


def add_admin(uid: int):         _admins.add(uid);        _save("admins.json",     list(_admins))
def rm_admin(uid: int):          _admins.discard(uid);    _save("admins.json",     list(_admins))
def add_whitelist(uid: int):     _whitelist.add(uid);     _save("whitelist.json",  list(_whitelist))
def rm_whitelist(uid: int):      _whitelist.discard(uid); _save("whitelist.json",  list(_whitelist))
def add_blacklist(uid: int):     _blacklist.add(uid);     _save("blacklist.json",  list(_blacklist))
def rm_blacklist(uid: int):      _blacklist.discard(uid); _save("blacklist.json",  list(_blacklist))

def get_admins()    -> list[int]: return sorted(_admins)
def get_whitelist() -> list[int]: return sorted(_whitelist)
def get_blacklist() -> list[int]: return sorted(_blacklist)


# ─────────────────────────────────────────────────────────────
# Message Accumulation Buffers
# ─────────────────────────────────────────────────────────────
pending_texts: dict[str, list[str]]         = defaultdict(list)
pending_tasks: dict[str, asyncio.Task]      = {}


# ─────────────────────────────────────────────────────────────
# Persistence helpers
# ─────────────────────────────────────────────────────────────
def _save(filename: str, data):
    try:
        with open(os.path.join(DATA_DIR, filename), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _load(filename: str, default=None):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default if default is not None else {}


def load_all():
    """Call once at startup to restore persisted state."""
    global _admins, _whitelist, _blacklist

    raw = _load("admins.json", [])
    _admins = {int(x) for x in (raw if isinstance(raw, list) else [])}
    _admins.add(OWNER_ID)

    raw = _load("whitelist.json", [])
    _whitelist = {int(x) for x in (raw if isinstance(raw, list) else [])}

    raw = _load("blacklist.json", [])
    _blacklist = {int(x) for x in (raw if isinstance(raw, list) else [])}

    for k, v in _load("topic_mode.json", {}).items():
        _topic_mode[int(k)] = bool(v)

    _conv_cfg.update(_load("conv_cfg.json", {}))
