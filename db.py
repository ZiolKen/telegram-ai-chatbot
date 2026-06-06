"""
db.py — Async PostgreSQL persistence layer (asyncpg).

Schema
------
  bot_config    : key-value store for topic_mode and conv_cfg settings
  conversations : individual message turns, auto-pruned when storage is tight

Design goals
------------
  • Bot works fully in-memory if DATABASE_URL is not set or DB is unreachable.
  • All DB writes are fire-and-forget (never block the message handler).
  • Conversations table behaves like a circular RAM buffer:
      when total rows hit MAX_CONV_ROWS, the oldest rows are deleted first.
  • On hard storage errors (disk full / quota), an emergency prune reclaims
      ≥20 % of rows before retrying the failed insert.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

# ── Module-level pool (None = not connected) ─────────────────────────────────
_pool: asyncpg.Pool | None = None

# ── Knobs ─────────────────────────────────────────────────────────────────────
# Default row budget for conversations table.
# Override with env var MAX_CONV_ROWS (set in config.py, passed in via init()).
_MAX_CONV_ROWS: int = 10_000
_PRUNE_BATCH:   int = 300      # rows deleted in a normal prune pass
_PRUNE_EMERG:   float = 0.20   # fraction deleted in an emergency prune


# ─────────────────────────────────────────────────────────────────────────────
# Initialisation
# ─────────────────────────────────────────────────────────────────────────────

async def init(database_url: str, max_conv_rows: int = 10_000) -> None:
    """
    Create the connection pool and ensure the schema exists.
    Call once at startup (via PTB post_init hook).
    Safe to call with an empty DATABASE_URL — bot will run without persistence.
    """
    global _pool, _MAX_CONV_ROWS

    _MAX_CONV_ROWS = max_conv_rows

    if not database_url:
        logger.warning("[db] DATABASE_URL not set — running in-memory only.")
        return

    # Render (and some others) give postgres:// — asyncpg needs postgresql://
    url = database_url.replace("postgres://", "postgresql://", 1)

    try:
        _pool = await asyncpg.create_pool(
            url,
            min_size        = 1,
            max_size        = 5,        # safe for Render free tier (max 97 conns)
            command_timeout = 10,       # seconds per SQL command
        )
        await _create_schema()
        logger.info("[db] PostgreSQL connected — max_conv_rows=%d", _MAX_CONV_ROWS)
    except Exception as exc:
        logger.error("[db] Connection failed: %s — running in-memory only.", exc)
        _pool = None


async def close() -> None:
    """Gracefully close the connection pool at shutdown."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("[db] Pool closed.")


def is_ready() -> bool:
    """True when a live pool exists."""
    return _pool is not None


# ─────────────────────────────────────────────────────────────────────────────
# Schema bootstrap
# ─────────────────────────────────────────────────────────────────────────────

async def _create_schema() -> None:
    async with _pool.acquire() as conn:
        # Key-value table for settings (topic_mode, conv_cfg)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_config (
                key        TEXT PRIMARY KEY,
                value      JSONB       NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Conversation messages table
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
    """Heuristic: detect disk-full / quota-exceeded Postgres errors."""
    msg = str(exc).lower()
    return any(kw in msg for kw in (
        "no space left", "disk full", "out of disk", "storage quota",
        "could not extend", "file too large",
        # Render-specific
        "no space", "disk quota exceeded",
    ))


async def _prune_oldest(conn: asyncpg.Connection, n: int) -> int:
    """Delete the *n* oldest rows from conversations. Returns rows deleted."""
    result = await conn.execute("""
        DELETE FROM conversations
        WHERE id IN (
            SELECT id FROM conversations
            ORDER BY id ASC
            LIMIT $1
        )
    """, n)
    # asyncpg returns e.g. "DELETE 300"
    try:
        return int(result.split()[-1])
    except (IndexError, ValueError):
        return 0


async def _maybe_prune(conn: asyncpg.Connection) -> None:
    """
    If the table has reached MAX_CONV_ROWS, delete the oldest PRUNE_BATCH rows
    to make room — keeps the table from growing forever.
    """
    total: int = await conn.fetchval("SELECT COUNT(*) FROM conversations")
    if total >= _MAX_CONV_ROWS:
        deleted = await _prune_oldest(conn, _PRUNE_BATCH)
        logger.info("[db] Pruned %d rows (table had %d / %d).",
                    deleted, total, _MAX_CONV_ROWS)


async def _emergency_prune(conn: asyncpg.Connection) -> None:
    """
    Storage pressure detected — delete at least 20 % of rows to reclaim space.
    Called after a storage-error INSERT fails; we then retry the INSERT.
    """
    total: int = await conn.fetchval("SELECT COUNT(*) FROM conversations")
    n = max(_PRUNE_BATCH, int(total * _PRUNE_EMERG))
    deleted = await _prune_oldest(conn, n)
    logger.warning("[db] Emergency pruned %d rows (table had %d).", deleted, total)


# ─────────────────────────────────────────────────────────────────────────────
# bot_config  CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def config_get_all() -> dict[str, Any]:
    """
    Load every row from bot_config.
    Returns {} on error or when DB is not ready.
    Used at startup only.
    """
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
    """Upsert a single key in bot_config."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO bot_config (key, value, updated_at)
                VALUES ($1, $2::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE
                    SET value      = EXCLUDED.value,
                        updated_at = NOW()
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
# conversations  CRUD
# ─────────────────────────────────────────────────────────────────────────────

async def conv_load_all(max_per_conv: int) -> dict[str, list[dict]]:
    """
    Load the most-recent *max_per_conv* messages for every conv_id.
    Returns { conv_id: [{"role": ..., "parts": [{"text": ...}]}, ...] }.
    Called once at startup to restore in-memory state.
    """
    if not _pool:
        return {}
    try:
        async with _pool.acquire() as conn:
            # Distinct conv_ids present in the table
            id_rows = await conn.fetch(
                "SELECT DISTINCT conv_id FROM conversations"
            )
            result: dict[str, list[dict]] = {}
            for row in id_rows:
                cid = row["conv_id"]
                msg_rows = await conn.fetch("""
                    SELECT role, content
                    FROM (
                        SELECT id, role, content
                        FROM conversations
                        WHERE conv_id = $1
                        ORDER BY id DESC
                        LIMIT $2
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
    """
    Insert a message row.
    • Pruning check runs before every insert (deletes oldest rows when full).
    • On a storage error the insert is retried once after an emergency prune.
    """
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
            logger.warning("[db] Storage pressure on conv_push — emergency prune + retry.")
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
    """Delete all messages belonging to *conv_id*."""
    if not _pool:
        return
    try:
        async with _pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM conversations WHERE conv_id = $1", conv_id
            )
    except Exception as exc:
        logger.error("[db] conv_delete(%s): %s", conv_id, exc)


async def conv_delete_all() -> None:
    """Truncate the entire conversations table (used by /sysreset)."""
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
    """
    Return a dict with DB stats for the /status command.
    Keys: ready, conv_rows, config_rows, max_conv_rows
    """
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
