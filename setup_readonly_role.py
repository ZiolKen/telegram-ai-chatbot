"""
One-off / idempotent setup: creates (or updates the password of) a
SELECT-only PostgreSQL role, meant to be used as DB_READONLY_URL for the
run_python sandbox (see tools_code.py / README.md "Security Notes").

Designed to run from Render's Build Command, chained with &&:

    pip install -r requirements.txt && python setup_readonly_role.py

Safe to run on every deploy — it's idempotent: if the role already exists,
it only resets the password and re-applies grants, it never errors out or
drops anything.

Required env vars (set these in Render's dashboard BEFORE deploying):
    DATABASE_URL     - already required by the bot; the admin/writable DSN
                        used here ONLY to create the new role (not stored).
    BOT_RO_PASSWORD  - password you choose for the new read-only role.
                        Pick something random; you'll need it once to build
                        DB_READONLY_URL, then you can forget it.

Optional:
    BOT_RO_USER      - role name (default: bot_ro)

If either DATABASE_URL or BOT_RO_PASSWORD is missing, this script prints a
message and exits 0 (does NOT fail the build) — the bot works fine without
DB_READONLY_URL, this is purely opt-in.

After the build finishes, open the build logs and look for a line like:

    [setup_readonly_role] DB_READONLY_URL=postgresql://bot_ro:...@host:port/db?sslmode=require

Copy that whole value into Render's env vars as DB_READONLY_URL, then trigger
a redeploy (env var changes alone don't restart a running service on Render
unless you set "Deploy on env var change", so redeploy manually if needed).
"""
import asyncio
import os
import re
import sys
from urllib.parse import urlparse

import asyncpg


def _ident(name: str) -> str:
    """Safely quote a SQL identifier (role/db name) — rejects anything odd."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"Invalid identifier (letters/digits/underscore only): {name!r}")
    return f'"{name}"'


def _literal(value: str) -> str:
    """Safely quote a SQL string literal (for the password)."""
    return "'" + value.replace("'", "''") + "'"


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    ro_password  = os.environ.get("BOT_RO_PASSWORD", "")
    ro_user      = os.environ.get("BOT_RO_USER", "bot_ro")

    if not database_url:
        print("[setup_readonly_role] DATABASE_URL not set — skipping (build continues).")
        return 0
    if not ro_password:
        print(
            "[setup_readonly_role] BOT_RO_PASSWORD not set — skipping (build continues). "
            "Set BOT_RO_PASSWORD in Render env vars if you want DB_READONLY_URL auto-created."
        )
        return 0

    try:
        user_q = _ident(ro_user)
    except ValueError as e:
        print(f"[setup_readonly_role] {e} — skipping.")
        return 0

    parsed = urlparse(database_url)
    dbname = parsed.path.lstrip("/") or "defaultdb"
    db_q   = _ident(dbname)

    conn = await asyncpg.connect(database_url)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", ro_user)
        if exists:
            await conn.execute(f"ALTER ROLE {user_q} WITH LOGIN PASSWORD {_literal(ro_password)}")
            print(f"[setup_readonly_role] Role {ro_user!r} already existed — password reset.")
        else:
            await conn.execute(f"CREATE ROLE {user_q} WITH LOGIN PASSWORD {_literal(ro_password)}")
            print(f"[setup_readonly_role] Created role {ro_user!r}.")

        await conn.execute(f"GRANT CONNECT ON DATABASE {db_q} TO {user_q}")
        await conn.execute(f"GRANT USAGE ON SCHEMA public TO {user_q}")
        await conn.execute(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {user_q}")
        await conn.execute(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {user_q}"
        )
        print(f"[setup_readonly_role] Granted CONNECT/USAGE/SELECT (+ default privileges) to {ro_user!r}.")
    except Exception as e:
        # Never fail the whole deploy because of this optional step.
        print(f"[setup_readonly_role] ERROR: {e} — build continues, DB_READONLY_URL NOT created.")
        return 0
    finally:
        await conn.close()

    query = parsed.query or "sslmode=require"
    dsn = f"postgresql://{ro_user}:{ro_password}@{parsed.hostname}:{parsed.port}/{dbname}?{query}"
    print(f"[setup_readonly_role] DB_READONLY_URL={dsn}")
    print("[setup_readonly_role] ^ copy that into Render env vars as DB_READONLY_URL, then redeploy.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
