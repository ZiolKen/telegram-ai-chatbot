"""
bot_identity.py — bot biết mình là ai (id + username lấy từ getMe lúc khởi động),
để phân biệt CHÍNH MÌNH với bot khác. So sánh bằng ID số của Telegram (không đổi),
không dựa vào username.
"""
from __future__ import annotations

SELF_ID: int = 0
SELF_USERNAME: str = ""


def set_self(bot_id: int, username: str = "") -> None:
    global SELF_ID, SELF_USERNAME
    SELF_ID = int(bot_id or 0)
    SELF_USERNAME = (username or "").lstrip("@")


def is_self_id(uid) -> bool:
    return bool(SELF_ID) and uid == SELF_ID


def is_self_user(user) -> bool:
    return user is not None and is_self_id(getattr(user, "id", 0))


def is_other_bot(user) -> bool:
    return (user is not None and bool(getattr(user, "is_bot", False))
            and not is_self_user(user))
