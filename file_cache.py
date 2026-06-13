"""
file_cache.py — In-RAM file cache (NO disk, NO DB).

Lý do dùng RAM:
  • Tốc độ: lần 2 gửi cùng file dùng Telegram file_id → không upload lại
  • Sạch: không cần clean-up, restart Render = cache empty
  • Giới hạn: 200 MB (cấu hình qua FILE_CACHE_MAX_MB)

Luồng:
  1. AI gọi tg_send_document(url="https://...")
  2. Kiểm tra cache → nếu đã có tg_file_id → gửi ngay (0 bandwidth)
  3. Nếu chỉ có bytes → dùng InputFile(BytesIO) → Telegram upload → lưu file_id
  4. Nếu chưa có → download → cache bytes → upload → lưu file_id

Eviction: LRU — xóa entry cũ nhất khi sắp vượt giới hạn.
"""
from __future__ import annotations

import io
import logging
import mimetypes
import os
import time
from dataclasses import dataclass, field
from typing import Optional

import aiohttp

from tools_web import _is_safe_url

logger = logging.getLogger(__name__)

_DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=120, connect=15)


@dataclass
class CacheEntry:
    data:       bytes
    mime:       str
    filename:   str
    tg_file_id: Optional[str] = None   # Đặt sau lần upload đầu lên Telegram
    accessed:   float          = field(default_factory=time.monotonic)

    @property
    def size(self) -> int:
        return len(self.data)


_cache:      dict[str, CacheEntry] = {}
_cache_size: int = 0
_max_bytes:  int = 200 * 1024 * 1024   # 200 MB


def configure(max_mb: int) -> None:
    global _max_bytes
    _max_bytes = max_mb * 1024 * 1024
    logger.info("[file_cache] Limit set to %d MB", max_mb)


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _evict_for(needed: int) -> None:
    """Xóa LRU entries cho đến khi đủ chỗ cho `needed` bytes."""
    global _cache_size
    if _cache_size + needed <= _max_bytes:
        return
    for key in sorted(_cache, key=lambda k: _cache[k].accessed):
        if _cache_size + needed <= _max_bytes:
            break
        entry = _cache.pop(key)
        _cache_size -= entry.size
        logger.debug("[file_cache] Evicted '%s' (%.1f KB)", entry.filename, entry.size / 1024)


def _put(key: str, entry: CacheEntry) -> None:
    global _cache_size
    if entry.size > _max_bytes:
        logger.warning(
            "[file_cache] '%s' (%.1f MB) vượt quá giới hạn cache %d MB — bỏ qua.",
            entry.filename, entry.size / 1024 / 1024, _max_bytes // 1024 // 1024,
        )
        return
    if key in _cache:
        _cache_size -= _cache[key].size
    _evict_for(entry.size)
    _cache[key] = entry
    _cache_size += entry.size
    logger.info(
        "[file_cache] Đã lưu '%s' (%.1f KB) | tổng %.1f / %d MB",
        entry.filename, entry.size / 1024,
        _cache_size / 1024 / 1024, _max_bytes // 1024 // 1024,
    )


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def get(key: str) -> Optional[CacheEntry]:
    """Lấy entry từ cache (cập nhật thời gian truy cập)."""
    entry = _cache.get(key)
    if entry:
        entry.accessed = time.monotonic()
    return entry


def set_tg_file_id(key: str, file_id: str) -> None:
    """Lưu Telegram file_id sau lần upload đầu tiên — dùng lại cho lần sau."""
    if key in _cache:
        _cache[key].tg_file_id = file_id
        logger.debug("[file_cache] Lưu file_id cho '%s'", _cache[key].filename)


def store_bytes(key: str, data: bytes, mime: str, filename: str) -> CacheEntry:
    """Lưu trực tiếp bytes vào cache (khi đã có data sẵn)."""
    entry = CacheEntry(data=data, mime=mime, filename=filename)
    _put(key, entry)
    return entry


async def download(url: str) -> Optional[CacheEntry]:
    """
    Tải file từ URL về RAM.
    Trả về CacheEntry đã cache, hoặc None nếu thất bại.
    """
    # Trả về cache hit nếu đã có
    cached = get(url)
    if cached:
        logger.debug("[file_cache] Cache hit: %s", url)
        return cached

    # SSRF check (#2) — bot server fetches this URL directly, unlike
    # tg_send_photo/sticker/etc. where Telegram's servers do the fetch.
    safe, reason = _is_safe_url(url)
    if not safe:
        logger.warning("[file_cache] Blocked unsafe URL %s: %s", url, reason)
        return None

    try:
        async with aiohttp.ClientSession(timeout=_DOWNLOAD_TIMEOUT) as sess:
            async with sess.get(url, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.error("[file_cache] HTTP %d cho %s", resp.status, url)
                    return None

                # Kiểm tra kích thước trước khi tải
                cl = resp.headers.get("Content-Length")
                if cl and int(cl) > _max_bytes:
                    logger.warning(
                        "[file_cache] File tại %s quá lớn (%s bytes > %d MB)",
                        url, cl, _max_bytes // 1024 // 1024,
                    )
                    return None

                data = await resp.read()

                if len(data) > _max_bytes:
                    logger.warning(
                        "[file_cache] File đã tải quá lớn (%.1f MB), bỏ qua.",
                        len(data) / 1024 / 1024,
                    )
                    return None

                mime = (resp.content_type or "application/octet-stream").split(";")[0].strip()
    except aiohttp.ClientError as e:
        logger.error("[file_cache] Tải thất bại %s: %s", url, e)
        return None
    except Exception as e:
        logger.error("[file_cache] Lỗi không xác định khi tải %s: %s", url, e)
        return None

    # Đoán tên file từ URL
    filename = os.path.basename(url.split("?")[0].rstrip("/")) or "file"
    if "." not in filename:
        ext = mimetypes.guess_extension(mime) or ""
        filename += ext

    entry = CacheEntry(data=data, mime=mime, filename=filename)
    _put(url, entry)
    return entry


def to_bytesio(entry: CacheEntry) -> io.BytesIO:
    """Tạo BytesIO với tên file đúng để truyền vào InputFile."""
    buf = io.BytesIO(entry.data)
    buf.name = entry.filename
    return buf


def stats() -> dict:
    return {
        "files":    len(_cache),
        "size_mb":  round(_cache_size / 1024 / 1024, 2),
        "limit_mb": _max_bytes // 1024 // 1024,
    }


def clear() -> None:
    global _cache_size
    _cache.clear()
    _cache_size = 0
    logger.info("[file_cache] Đã xóa toàn bộ cache.")
