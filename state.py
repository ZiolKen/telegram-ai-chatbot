"""
state.py — In-memory state with async PostgreSQL persistence.

Thay đổi vs phiên bản cũ:
  • conv_id cho group KHÔNG còn tách theo user_id (g:{chat_id}:u:{uid})
    Thay vào đó dùng shared key g:{chat_id} để tất cả thành viên
    đều dùng chung một lịch sử hội thoại → AI có context đầy đủ.
  • Thêm push_context(): lưu tin nhắn người khác vào shared conv
    mà không trigger AI (chỉ để làm context).
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Optional

import db
from config import GROUP_CONTEXT_ENABLED, MAX_HISTORY, OWNER_ID

_log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Fire-and-forget helper
# ─────────────────────────────────────────────────────────────

def _fire(coro) -> None:
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


# ─────────────────────────────────────────────────────────────
# Auth
# ─────────────────────────────────────────────────────────────

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


# ─────────────────────────────────────────────────────────────
# In-memory stores
# ─────────────────────────────────────────────────────────────

_conversations: dict[str, list[dict]] = {}
_topic_mode:    dict[int,  bool]       = {}
_conv_cfg:      dict[str,  dict]       = {}

pending_texts: dict[str, list[str]]    = defaultdict(list)
pending_tasks: dict[str, asyncio.Task] = {}


# ─────────────────────────────────────────────────────────────
# Startup loader
# ─────────────────────────────────────────────────────────────

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
                _log.warning("[state] Bad topic_mode key: %s", key)
        elif key.startswith("conv_cfg:"):
            cid = key[len("conv_cfg:"):]
            if isinstance(value, dict):
                _conv_cfg[cid] = value

    convs = await db.conv_load_all(MAX_HISTORY)
    _conversations.update(convs)

    _log.info(
        "[state] Loaded: %d topic_mode, %d conv_cfg, %d conversations.",
        sum(1 for k in all_cfg if k.startswith("topic_mode:")),
        sum(1 for k in all_cfg if k.startswith("conv_cfg:")),
        len(_conversations),
    )


# ─────────────────────────────────────────────────────────────
# Conversation key builder
# ─────────────────────────────────────────────────────────────

def conv_id(
    chat_id:         int,
    user_id:         int,
    thread_id:       Optional[int],
    is_private:      bool,
    topic_mode_flag: bool,
) -> str:
    """
    Tính conversation key.

    Private chat           → "u:{user_id}"
    Group + topic mode     → "g:{chat_id}:t:{thread_id}"
    Group + context mode   → "g:{chat_id}"         ← SHARED toàn group
    Group + context off    → "g:{chat_id}:u:{user_id}"  ← per-user (cũ)
    """
    if is_private:
        return f"u:{user_id}"
    if topic_mode_flag and thread_id:
        return f"g:{chat_id}:t:{thread_id}"
    if GROUP_CONTEXT_ENABLED:
        return f"g:{chat_id}"         # Shared — tất cả thành viên dùng chung
    return f"g:{chat_id}:u:{user_id}"  # Fallback per-user (khi tắt context mode)


# ─────────────────────────────────────────────────────────────
# Conversation history
# ─────────────────────────────────────────────────────────────

def get_history(cid: str) -> list[dict]:
    return list(_conversations.get(cid, []))


def _append(cid: str, role: str, text: str) -> None:
    """Thêm vào in-memory và persist vào DB."""
    _conversations.setdefault(cid, []).append(
        {"role": role, "parts": [{"text": text}]}
    )
    if len(_conversations[cid]) > MAX_HISTORY:
        _conversations[cid] = _conversations[cid][-MAX_HISTORY:]
    _fire(db.conv_push(cid, role, text))


def push(cid: str, role: str, text: str) -> None:
    """Lưu một turn vào lịch sử (dùng cho AI response và user prompt)."""
    _append(cid, role, text)


def push_context(cid: str, username: str, text: str) -> None:
    """
    Lưu tin nhắn từ người khác vào shared conv làm context.
    Không trigger AI — chỉ để làm background context cho lần sau.
    Format: "[Username]: text"
    """
    _append(cid, "user", f"[{username}]: {text}")


def clear(cid: str) -> None:
    _conversations.pop(cid, None)
    _fire(db.conv_delete(cid))


def clear_all() -> None:
    _conversations.clear()
    _fire(db.conv_delete_all())


# ─────────────────────────────────────────────────────────────
# Topic mode
# ─────────────────────────────────────────────────────────────

def topic_mode(chat_id: int) -> bool:
    return _topic_mode.get(chat_id, False)


def set_topic_mode(chat_id: int, enabled: bool) -> None:
    _topic_mode[chat_id] = enabled
    _fire(db.config_set(f"topic_mode:{chat_id}", enabled))


# ─────────────────────────────────────────────────────────────
# Per-conversation config
# ─────────────────────────────────────────────────────────────

def get_cfg(cid: str) -> dict:
    return dict(_conv_cfg.get(cid, {}))


def set_cfg(cid: str, **kwargs) -> None:
    _conv_cfg.setdefault(cid, {}).update(kwargs)
    _fire(db.config_set(f"conv_cfg:{cid}", _conv_cfg[cid]))
