"""
db.py — Async PostgreSQL persistence layer (asyncpg).

Supports Aiven, Render, Supabase, Neon, and any standard Postgres provider.

Key fix: asyncpg does NOT parse ?sslmode=require from the DSN — the param is
silently ignored, causing connection failures on SSL-required hosts (Aiven, etc).
This module strips SSL-related query params from the URL and passes a proper
ssl.SSLContext to create_pool() instead.
"""

from __future__ import annotations

import asyncio
import json
import logging
import ssl
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import asyncpg

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None
_MAX_CONV_ROWS: int = 10_000
_PRUNE_BATCH:   int = 300
_PRUNE_EMERG:  float = 0.20


# ─────────────────────────────────────────────────────────────────────────────
# URL + SSL parsing
# ─────────────────────────────────────────────────────────────────────────────

def _parse_dsn(raw_url: str) -> tuple[str, dict]:
    """
    Split a DATABASE_URL into (clean_dsn, asyncpg_kwargs).

    asyncpg cannot handle these query-string parameters:
      • sslmode  — must become ssl=<SSLContext>
      • sslcert / sslkey / sslrootcert / sslpassword — unused here

    SSL behaviour by sslmode value
    ──────────────────────────────
      disable               → no SSL (default)
      allow / prefer        → SSL with CERT_NONE  (accepts self-signed)
      require               → SSL with CERT_NONE  (Aiven / most hosted DBs)
      verify-ca             → SSL with system CA bundle (strict)
      verify-full           → SSL with system CA bundle + hostname check (strict)

    Aiven gives ?sslmode=require with a self-signed CA, so CERT_NONE is correct
    unless the user also provides the CA cert via AIVEN_CA_CERT env var.
    """
    # Normalise postgres:// → postgresql:// (asyncpg requirement)
    raw_url = raw_url.replace("postgres://", "postgresql://", 1)

    parsed = urlparse(raw_url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    sslmode = params.pop("sslmode", "disable").lower()
    for key in ("sslcert", "sslkey", "sslrootcert", "sslpassword"):
        params.pop(key, None)

    new_query = urlencode(params)
    clean_dsn = urlunparse(parsed._replace(query=new_query))

    kwargs: dict = {}

    if sslmode == "disable":
        pass  # no ssl kwarg

    elif sslmode in ("allow", "prefer", "require"):
        # Most hosted providers (Aiven, Railway, Fly.io) use self-signed certs
        # behind their own CA — CERT_NONE accepts them without the CA file.
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        kwargs["ssl"] = ctx
        logger.debug("[db] SSL mode=%s → CERT_NONE context", sslmode)

    elif sslmode in ("verify-ca", "verify-full"):
        # Full verification against system CA bundle
        ctx = ssl.create_default_context()
        if sslmode == "verify-ca":
            ctx.check_hostname = False
        kwargs["ssl"] = ctx
        logger.debug("[db] SSL mode=%s → strict context", sslmode)

    return clean_dsn, kwargs


# ─────────────────────────────────────────────────────────────────────────────
# Initialisation
# ─────────────────────────────────────────────────────────────────────────────

async def init(database_url: str, max_conv_rows: int = 10_000) -> None:
    """
    Create the connection pool and ensure the schema exists.
    Called once at startup via PTB post_init hook.
    Safe with an empty DATABASE_URL — bot runs in-memory only.
    """
    global _pool, _MAX_CONV_ROWS

    _MAX_CONV_ROWS = max_conv_rows

    if not database_url:
        logger.warning("[db] DATABASE_URL not set — running in-memory only.")
        return

    clean_dsn, ssl_kwargs = _parse_dsn(database_url)

    try:
        # Wrap in wait_for so a network failure doesn't hang startup forever
        _pool = await asyncio.wait_for(
            asyncpg.create_pool(
                clean_dsn,
                min_size        = 1,
                max_size        = 5,
                command_timeout = 10,   # per-query timeout (seconds)
                **ssl_kwargs,
            ),
            timeout = 20,              # total startup timeout
        )
        await _create_schema()
        logger.info("[db] PostgreSQL connected — max_conv_rows=%d", _MAX_CONV_ROWS)

    except asyncio.TimeoutError:
        logger.error(
            "[db] Connection timed out after 20 s. "
            "Check host/port and that the DB allows external connections."
        )
        _pool = None

    except ssl.SSLError as exc:
        logger.error(
            "[db] SSL handshake failed: %s. "
            "Ensure DATABASE_URL contains ?sslmode=require for Aiven.", exc
        )
        _pool = None

    except Exception as exc:
        logger.error("[db] Connection failed: %s — running in-memory only.", exc)
        _pool = None


async def close() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("[db] Pool closed.")


def is_ready() -> bool:
    return _pool is not None


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
# Stats  (used by /status command)
# ─────────────────────────────────────────────────────────────────────────────

async def stats() -> dict:
    if not _pool:
        return {"ready": False}
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
