"""
purge.py — xóa tin hàng loạt (dùng chung cho lệnh /purge, /purgeuser và các tool của AI).

Giới hạn của Telegram: bot chỉ xóa được tin trong nhóm nếu có quyền "Delete messages",
và tin quá cũ (~48 giờ) có thể không xóa được. Vì vậy mọi hàm đều trả (deleted, failed).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

import db
import group_context

logger = logging.getLogger(__name__)

PURGE_CAP = 200          # mặc định tối đa / lần (có thể vượt khi owner gõ `force`)
HARD_CAP  = 1000         # trần tuyệt đối kể cả khi force


async def delete_ids(bot, chat_id: int, ids: Iterable[int]) -> tuple[int, int]:
    """Xóa danh sách msg_id: lô 100 tin bằng delete_messages, lỗi thì thử từng tin."""
    ids = sorted({int(i) for i in ids if i}, reverse=True)
    deleted = failed = 0
    for k in range(0, len(ids), 100):
        batch = ids[k:k + 100]
        try:
            await bot.delete_messages(chat_id=chat_id, message_ids=batch)
            deleted += len(batch)
        except Exception as e:
            logger.info("[purge] batch delete failed (%s) — fallback từng tin", e)
            for mid in batch:
                try:
                    await bot.delete_message(chat_id=chat_id, message_id=mid)
                    deleted += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.05)
        await asyncio.sleep(0.2)
    return deleted, failed


async def _forget(chat_id: int, ids: Iterable[int]) -> None:
    """Dọn các tin đã xóa khỏi RAM + chat_history để AI/tra cứu không còn thấy."""
    idset = {int(i) for i in ids}
    dq = group_context.GROUP_HISTORY.get(chat_id)
    if dq:
        keep = [e for e in dq if e["msg_id"] not in idset]
        dq.clear()
        dq.extend(keep)
    await db.chat_history_delete_ids(chat_id, list(idset))


async def purge_range(bot, chat_id: int, from_id: int, to_id: int,
                      force: bool = False) -> dict:
    """Xóa mọi msg_id trong [from_id, to_id]."""
    if from_id > to_id:
        from_id, to_id = to_id, from_id
    total = to_id - from_id + 1
    cap = HARD_CAP if force else PURGE_CAP
    if total > HARD_CAP:
        return {"ok": False, "error": f"Phạm vi {total} tin vượt trần tuyệt đối {HARD_CAP}."}
    if total > cap:
        return {"ok": False, "needs_force": True, "total": total,
                "error": f"Phạm vi {total} tin vượt giới hạn an toàn {PURGE_CAP}/lần."}
    ids = list(range(from_id, to_id + 1))
    deleted, failed = await delete_ids(bot, chat_id, ids)
    await _forget(chat_id, ids)
    return {"ok": True, "deleted": deleted, "failed": failed,
            "range": f"#{from_id} → #{to_id}"}


async def delete_last_n(bot, chat_id: int, n: int, before_id: int) -> dict:
    """Xóa n tin ngay trước before_id. Ưu tiên danh sách msg_id đã ghi lại;
    nếu chưa ghi gì thì dùng dải số liên tiếp."""
    n = max(1, min(int(n), HARD_CAP))
    ids: list[int] = []
    pool = [e["msg_id"] for e in group_context.GROUP_HISTORY.get(chat_id, []) if e["msg_id"] < before_id]
    if len(pool) >= n:
        ids = sorted(pool)[-n:]
    else:
        ids = await db.chat_history_recent_ids(chat_id, before_id, n)
        if len(ids) < n:
            ids = list(range(max(1, before_id - n), before_id))
    deleted, failed = await delete_ids(bot, chat_id, ids)
    await _forget(chat_id, ids)
    return {"ok": True, "requested": n, "deleted": deleted, "failed": failed}


async def user_message_ids(chat_id: int, user_id: int, limit: int = 500) -> list[int]:
    ram = [e["msg_id"] for e in group_context.GROUP_HISTORY.get(chat_id, [])
           if e.get("user_id") == user_id]
    dbids = await db.chat_history_ids_for_user(chat_id, user_id, limit)
    return sorted(set(ram) | set(dbids), reverse=True)[:limit]


async def purge_user(bot, chat_id: int, user_id: int, limit: int = 500) -> dict:
    """Xóa các tin của 1 người mà bot ĐÃ GHI LẠI (không thể xóa tin bot chưa từng thấy)."""
    ids = await user_message_ids(chat_id, user_id, limit)
    if not ids:
        return {"ok": True, "deleted": 0, "failed": 0,
                "note": "Bot chưa ghi lại tin nào của người này (hoặc đã tắt ghi lịch sử nhóm)."}
    deleted, failed = await delete_ids(bot, chat_id, ids)
    await _forget(chat_id, ids)
    return {"ok": True, "deleted": deleted, "failed": failed, "found": len(ids)}
