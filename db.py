"""
db.py — Async PostgreSQL persistence layer (asyncpg).

Supports Aiven, Render, Supabase, Neon, and any standard Postgres provider.

Hai cách dùng:
  1. Import bình thường trong main.py  → dùng init(), close(), các CRUD functions
  2. Chạy trực tiếp: python db.py      → kết nối, tạo schema, in kết quả, exit 0/1
     Dùng làm bước đầu tiên trong Start Command:
       python db.py && python main.py

Key fixes vs original:
  • asyncpg silently ignores ?sslmode= in the DSN — we strip it and pass a
    proper ssl.SSLContext instead.
  • Auto-detects Aiven hostnames and forces sslmode=require even when the
    caller forgets to include it in the URL.
  • Stores _last_error so the health endpoint / /status can surface it.
  • Retries the pool creation up to 3 times with 5 s backoff before giving up.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
import sys
from typing import Any, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

logger = logging.getLogger(__name__)

_pool:          asyncpg.Pool | None = None
_last_error:    str | None          = None   # surfaced by health/status
_MAX_CONV_ROWS: int  = 10_000
_PRUNE_BATCH:   int  = 300
_PRUNE_EMERG: float  = 0.20

# Hostnames that REQUIRE SSL even when ?sslmode= is absent from the URL
_SSL_REQUIRED_PATTERNS = (
    "aivencloud.com",
    "aiven.io",
    "neon.tech",
    "supabase.co",
    ".cockroachlabs.cloud",
)


# ─────────────────────────────────────────────────────────────────────────────
# URL + SSL parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dsn(raw_url: str) -> tuple[str, dict]:
    """
    Split a DATABASE_URL into (clean_dsn, asyncpg_kwargs).

    asyncpg does NOT understand these query-string parameters:
      • sslmode  — must become ssl=<SSLContext>
      • sslcert / sslkey / sslrootcert / sslpassword — stripped

    SSL behaviour by sslmode value
    ──────────────────────────────
      disable               → no SSL
      allow / prefer        → SSL with CERT_NONE  (accepts self-signed)
      require               → SSL with CERT_NONE  (Aiven / most hosted DBs)
      verify-ca             → SSL with system CA  (strict, no hostname check)
      verify-full           → SSL with system CA  (strict + hostname check)

    Auto-force: if the hostname matches a known SSL-required provider
    (Aiven, Neon, Supabase…) and sslmode is still "disable", we upgrade
    it to "require" automatically.
    """
    # asyncpg requires postgresql:// scheme
    raw_url = raw_url.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(raw_url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    sslmode = params.pop("sslmode", "disable").lower()
    for key in ("sslcert", "sslkey", "sslrootcert", "sslpassword"):
        params.pop(key, None)

    # ── Auto-detect SSL-required providers ───────────────────────────────
    host = (parsed.hostname or "").lower()
    if sslmode == "disable" and any(p in host for p in _SSL_REQUIRED_PATTERNS):
        logger.warning(
            "[db] Host '%s' requires SSL — auto-upgrading sslmode to 'require'", host
        )
        sslmode = "require"

    new_query = urlencode(params)
    clean_dsn = urlunparse(parsed._replace(query=new_query))

    kwargs: dict = {}

    if sslmode == "disable":
        pass  # no ssl kwarg → plain connection

    elif sslmode in ("allow", "prefer", "require"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        kwargs["ssl"] = ctx
        logger.info("[db] SSL mode=%s → CERT_NONE context (host=%s)", sslmode, host)

    elif sslmode in ("verify-ca", "verify-full"):
        ctx = ssl.create_default_context()
        if sslmode == "verify-ca":
            ctx.check_hostname = False
        kwargs["ssl"] = ctx
        logger.info("[db] SSL mode=%s → strict context (host=%s)", sslmode, host)

    return clean_dsn, kwargs


# ─────────────────────────────────────────────────────────────────────────────
# Initialisation
# ─────────────────────────────────────────────────────────────────────────────

async def init(database_url: str, max_conv_rows: int = 10_000) -> None:
    """
    Tạo connection pool và đảm bảo schema tồn tại.
    Thử lại tối đa 3 lần với 5s backoff.
    An toàn khi DATABASE_URL rỗng — bot chạy in-memory.
    """
    global _pool, _last_error, _MAX_CONV_ROWS

    _MAX_CONV_ROWS = max_conv_rows

    if not database_url:
        _last_error = "DATABASE_URL env var is not set"
        logger.warning(
            "[db] DATABASE_URL is not set — running in-memory only.\n"
            "     Set DATABASE_URL on Render to your Postgres connection string."
        )
        return

    # Mask credentials for safe logging
    try:
        _p = urlparse(database_url)
        safe_url = f"{_p.scheme}://***@{_p.hostname}:{_p.port}{_p.path}"
    except Exception:
        safe_url = "(unparseable URL)"

    logger.info("[db] Connecting to: %s", safe_url)

    try:
        clean_dsn, ssl_kwargs = _parse_dsn(database_url)
    except Exception as exc:
        _last_error = f"URL parse error: {exc}"
        logger.error("[db] Cannot parse DATABASE_URL: %s", exc)
        return

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            pool = await asyncio.wait_for(
                asyncpg.create_pool(
                    clean_dsn,
                    min_size        = 1,
                    max_size        = 5,
                    command_timeout = 10,
                    **ssl_kwargs,
                ),
                timeout = 20,
            )
            _pool      = pool
            _last_error = None
            await _create_schema()
            logger.info(
                "[db] PostgreSQL connected ✓  (attempt %d/%d, max_conv_rows=%d)",
                attempt, max_attempts, _MAX_CONV_ROWS,
            )
            return  # success

        except asyncio.TimeoutError:
            _last_error = f"Connection timed out after 20 s (attempt {attempt}/{max_attempts})"
            logger.warning("[db] %s", _last_error)

        except ssl.SSLError as exc:
            _last_error = f"SSL handshake failed: {exc}"
            logger.error(
                "[db] SSL error (attempt %d/%d): %s\n"
                "     Make sure DATABASE_URL contains ?sslmode=require for Aiven.",
                attempt, max_attempts, exc,
            )

        except Exception as exc:
            _last_error = str(exc)
            logger.error("[db] Connection failed (attempt %d/%d): %s", attempt, max_attempts, exc)

        if attempt < max_attempts:
            logger.info("[db] Retrying in 5 s…")
            await asyncio.sleep(5)

    logger.error(
        "[db] All %d connection attempts failed — running in-memory only.\n"
        "     Last error: %s",
        max_attempts, _last_error,
    )
    _pool = None


async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("[db] Pool closed.")


def is_ready() -> bool:
    return _pool is not None


def last_error() -> Optional[str]:
    """Return the most recent connection error, or None if connected / never tried."""
    return _last_error


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ─────────────────────────────────────────────────────────────────────────────

async def _create_schema() -> None:
    async with _pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key        TEXT PRIMARY KEY,
                value      JSONB       NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id         BIGSERIAL   PRIMARY KEY,
                conv_id    TEXT        NOT NULL,
                role       TEXT        NOT NULL,
                content    TEXT        NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_conv_id
            ON conversations (conv_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_conv_id_asc
            ON conversations (id ASC)
        """)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_storage_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "no space left", "disk full", "out of disk", "storage quota",
        "could not extend", "file too large", "no space", "disk quota exceeded",
    ))


async def _prune_oldest(conn: asyncpg.Connection, n: int) -> int:
    result = await conn.execute("""
        DELETE FROM conversations
        WHERE id IN (
            SELECT id FROM conversations ORDER BY id ASC LIMIT $1
        )
    """, n)
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


async def _maybe_prune(conn: asyncpg.Connection) -> None:
    total: int = await conn.fetchval("SELECT COUNT(*) FROM conversations")
    if total >= _MAX_CONV_ROWS:
        deleted = await _prune_oldest(conn, _PRUNE_BATCH)
        logger.info("[db] Pruned %d rows (table had %d / %d).",
                    deleted, total, _MAX_CONV_ROWS)


async def _emergency_prune(conn: asyncpg.Connection) -> None:
    total: int = await conn.fetchval("SELECT COUNT(*) FROM conversations")
    n = max(_PRUNE_BATCH, int(total * _PRUNE_EMERG))
    deleted = await _prune_oldest(conn, n)
    logger.warning("[db] Emergency pruned %d rows (table had %d).", deleted, total)


# ─────────────────────────────────────────────────────────────────────────────
# bot_config CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def config_get_all() -> dict[str, Any]:
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            rows = await conn.fetch("SELECT key, value FROM bot_config")
        return {r["key"]: json.loads(r["value"]) for r in rows}
    except Exception as exc:
        logger.error("[db] config_get_all: %s", exc)
        return {}


async def config_set(key: str, value: Any) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bot_config (key, value, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value = EXCLUDED.value, updated_at = NOW()
            """, key, json.dumps(value, ensure_ascii=False))
    except Exception as exc:
        logger.error("[db] config_set(%s): %s", key, exc)


async def config_delete(key: str) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM bot_config WHERE key = $1", key)
    except Exception as exc:
        logger.error("[db] config_delete(%s): %s", key, exc)


# ─────────────────────────────────────────────────────────────────────────────
# conversations CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def conv_load_all(max_per_conv: int) -> dict[str, list[dict]]:
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            id_rows = await conn.fetch("SELECT DISTINCT conv_id FROM conversations")
            result: dict[str, list[dict]] = {}
            for row in id_rows:
                cid      = row["conv_id"]
                msg_rows = await conn.fetch("""
                    SELECT role, content
                    FROM (
                        SELECT id, role, content
                        FROM   conversations
                        WHERE  conv_id = $1
                        ORDER  BY id DESC
                        LIMIT  $2
                    ) sub
                    ORDER BY id ASC
                """, cid, max_per_conv)
                result[cid] = [
                    {"role": r["role"], "parts": [{"text": r["content"]}]}
                    for r in msg_rows
                ]
        logger.info("[db] conv_load_all: loaded %d conversations.", len(result))
        return result
    except Exception as exc:
        logger.error("[db] conv_load_all: %s", exc)
        return {}


async def conv_push(conv_id: str, role: str, content: str) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await _maybe_prune(conn)
            await conn.execute(
                "INSERT INTO conversations (conv_id, role, content) VALUES ($1, $2, $3)",
                conv_id, role, content,
            )
    except asyncpg.PostgresError as exc:
        if _is_storage_error(exc):
            logger.warning("[db] Storage pressure — emergency prune + retry.")
            try:
                async with _pool.acquire() as conn:
                    await _emergency_prune(conn)
                    await conn.execute(
                        "INSERT INTO conversations (conv_id, role, content) VALUES ($1, $2, $3)",
                        conv_id, role, content,
                    )
            except Exception as exc2:
                logger.error("[db] conv_push retry failed: %s", exc2)
        else:
            logger.error("[db] conv_push(%s): %s", conv_id, exc)
    except Exception as exc:
        logger.error("[db] conv_push(%s): %s", conv_id, exc)


async def conv_delete(conv_id: str) -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("DELETE FROM conversations WHERE conv_id = $1", conv_id)
    except Exception as exc:
        logger.error("[db] conv_delete(%s): %s", conv_id, exc)


async def conv_delete_all() -> None:
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("TRUNCATE conversations")
        logger.info("[db] conversations table truncated.")
    except Exception as exc:
        logger.error("[db] conv_delete_all: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Stats  (used by /status command and health endpoint)
# ─────────────────────────────────────────────────────────────────────────────

async def stats() -> dict:
    if not _pool:
        result = {"ready": False}
        if _last_error:
            result["error"] = _last_error
        return result
    try:
        async with _pool.acquire() as conn:
            conv_rows   = await conn.fetchval("SELECT COUNT(*) FROM conversations")
            config_rows = await conn.fetchval("SELECT COUNT(*) FROM bot_config")
        return {
            "ready":         True,
            "conv_rows":     conv_rows,
            "config_rows":   config_rows,
            "max_conv_rows": _MAX_CONV_ROWS,
        }
    except Exception as exc:
        logger.error("[db] stats: %s", exc)
        return {"ready": False, "error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Standalone script — python db.py
# ─────────────────────────────────────────────────────────────────────────────
#
# Dùng làm bước đầu trong Start Command của Render:
#   python db.py && python main.py
#
# Luồng hoạt động:
#   1. Đọc DATABASE_URL từ env
#   2. Kết nối đến PostgreSQL (retry 3 lần)
#   3. Tạo bảng / index nếu chưa tồn tại (CREATE TABLE IF NOT EXISTS)
#   4. In kết quả ra stdout
#   5. exit 0 → main.py chạy tiếp
#      exit 1 → main.py KHÔNG chạy (tránh bot chạy mà không có DB)
#
if __name__ == "__main__":
    import os

    logging.basicConfig(
        format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        level   = logging.INFO,
        stream  = sys.stdout,
    )

    # Lấy config trực tiếp từ env (không import config.py để tránh vòng phụ thuộc)
    _db_url      = os.getenv("DATABASE_URL", "")
    _max_rows    = int(os.getenv("MAX_CONV_ROWS", "10000"))

    async def _run_migration() -> None:
        print("=" * 55, flush=True)
        print("  db.py — Database setup & connection check", flush=True)
        print("=" * 55, flush=True)

        if not _db_url:
            print("\n❌  DATABASE_URL không được thiết lập.", flush=True)
            print("   Thêm biến môi trường DATABASE_URL vào Render.", flush=True)
            sys.exit(1)

        # Che credentials khi log
        try:
            _p = urlparse(_db_url)
            safe = f"{_p.scheme}://***@{_p.hostname}:{_p.port}{_p.path}"
        except Exception:
            safe = "(unparseable URL)"

        print(f"\n🔌  Kết nối: {safe}", flush=True)
        print(f"    MAX_CONV_ROWS = {_max_rows}", flush=True)

        await init(_db_url, max_conv_rows=_max_rows)

        if not is_ready():
            err = last_error() or "không rõ nguyên nhân"
            print(f"\n❌  Kết nối thất bại: {err}", flush=True)
            print("\n   Kiểm tra lại DATABASE_URL và đảm bảo DB đang chạy.", flush=True)
            sys.exit(1)

        # Lấy thống kê để xác nhận schema hoạt động
        s = await stats()
        print(f"\n✅  Kết nối thành công!", flush=True)
        print(f"    conversations : {s.get('conv_rows', 0):,} rows", flush=True)
        print(f"    bot_config    : {s.get('config_rows', 0):,} rows", flush=True)
        print(f"    Schema        : OK (tables & indexes ready)", flush=True)
        print("\n   → Tiếp tục khởi động main.py...\n", flush=True)

        await close()
        sys.exit(0)

    asyncio.run(_run_migration())
