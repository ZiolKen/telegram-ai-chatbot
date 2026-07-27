"""
Python code interpreter — owner-only sandbox.

This bot gates ALL AI/tool interactions to OWNER_ID (see handlers.py:
`if not is_owner: ... return`), so run_python is never reachable by anyone
except the bot owner. Because of that, this sandbox intentionally does NOT
block os/network/filesystem access — the owner explicitly wants a general
"run whatever Python I ask for" tool.

Still isolated by:
  • separate subprocess (not in-process exec)
  • hard wall-clock timeout
  • explicit, minimal env passed to the subprocess (does NOT inherit the
    bot's full environment — BOT_TOKEN / DATABASE_URL / GEMINI_KEYS etc.
    are never visible to sandboxed code, only DB_READONLY_URL + PATH)
  • output truncated before being sent back to Telegram

If you ever change the owner-only gate in handlers.py, revisit this file —
the two are coupled.
"""
import asyncio
import io as _io
import logging
import os
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from typing import Optional, TYPE_CHECKING

import config

if TYPE_CHECKING:
    from tools_telegram import TelegramContext

logger = logging.getLogger(__name__)

# ── Tool declaration ──────────────────────────────────────────────────────
CODE_TOOL_DECLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python 3 code and return its stdout/stderr output. "
            "Full standard library is available (os, sys, subprocess, "
            "pathlib, socket, urllib, etc.) plus whatever third-party "
            "packages are installed in the bot's venv (requests, aiohttp, "
            "asyncpg, beautifulsoup4, ...). Code can read/write files and "
            "make outbound network requests. "
            "A read-only Postgres connection string is available as the "
            "env var DB_READONLY_URL — use asyncpg (already installed) to "
            "run SELECT queries against the bot's database, e.g.:\n"
            "import asyncio, asyncpg, os\n"
            "async def main():\n"
            "    conn = await asyncpg.connect(os.environ['DB_READONLY_URL'])\n"
            "    rows = await conn.fetch('SELECT ...')\n"
            "    print(rows)\n"
            "    await conn.close()\n"
            "asyncio.run(main())\n"
            "This tool only runs for the bot owner — there is no other "
            "sandboxing, so be careful with destructive filesystem/network "
            "operations."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "code": {
                    "type": "STRING",
                    "description": "Valid Python 3 source code to run",
                },
            },
            "required": ["code"],
        },
    },
]

# ── Sandbox wrapper ───────────────────────────────────────────────────────
# No import restrictions anymore — full stdlib + installed packages.
_WRAPPER = textwrap.dedent("""\
import sys, io as _io
sys.stdout = sys.stderr = _buf = _io.StringIO()
try:
{code}
except Exception as _e:
    print(f"{{type(_e).__name__}}: {{_e}}")
finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
print(_buf.getvalue(), end="")
""")

_TIMEOUT_SECONDS = 60
_TG_TEXT_LIMIT   = 3800   # leave headroom under Telegram's 4096 cap for HTML tags

# Explicit env for the subprocess — minimal, does NOT inherit bot secrets.
def _sandbox_env() -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": os.environ.get("HOME", "/tmp"),
    }
    if config.DB_READONLY_URL:
        env["DB_READONLY_URL"] = config.DB_READONLY_URL
    return env


async def _mirror_to_owner(tg_ctx: "TelegramContext", code: str, output: str) -> None:
    """
    Audit log: always send the FULL code + FULL output straight to the owner's
    chat, independent of whatever the AI decides to say afterwards. This is
    the source of truth — the model's chat reply may summarize/omit things,
    this never does.
    Never raises — a mirror failure must not break the actual tool result.
    """
    ts   = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    body = f"🔎 run_python @ {ts}\n\n――― code ―――\n{code}\n\n――― output ―――\n{output}"

    try:
        if len(body) <= _TG_TEXT_LIMIT:
            html = (
                f"🔎 <b>run_python</b> @ {ts}\n\n"
                f"<b>― code ―</b>\n<pre><code>{_escape(code)}</code></pre>\n"
                f"<b>― output ―</b>\n<pre><code>{_escape(output)}</code></pre>"
            )
            await tg_ctx.bot.send_message(
                chat_id=tg_ctx.chat_id,
                text=html,
                parse_mode="HTML",
                message_thread_id=tg_ctx.thread_id,
            )
        else:
            from telegram import InputFile
            buf = _io.BytesIO(body.encode("utf-8"))
            fname = f"run_python_{datetime.now(tz=timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
            await tg_ctx.bot.send_document(
                chat_id=tg_ctx.chat_id,
                document=InputFile(buf, filename=fname),
                caption=f"🔎 run_python @ {ts} (full code+output, too long for a message)",
                message_thread_id=tg_ctx.thread_id,
            )
    except Exception as e:
        logger.error("run_python mirror failed: %s", e)


def _escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def run_python(code: str, tg_ctx: Optional["TelegramContext"] = None) -> str:
    indented = textwrap.indent(code, "    ")
    script   = _WRAPPER.format(code=indented)

    loop = asyncio.get_event_loop()
    try:
        result: subprocess.CompletedProcess = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_SECONDS,
                env=_sandbox_env(),
            ),
        )
        full_output = (result.stdout or "") + (result.stderr or "")
        if not full_output.strip():
            full_output = "(không có output)"

        if tg_ctx is not None:
            await _mirror_to_owner(tg_ctx, code, full_output)

        output = full_output
        if len(output) > 3500:
            output = output[:3500] + "\n…[output bị cắt bớt]"
        return f"<pre><code>{output.rstrip()}</code></pre>"
    except subprocess.TimeoutExpired:
        msg = f"❌ Code chạy quá {_TIMEOUT_SECONDS} giây, đã dừng."
        if tg_ctx is not None:
            await _mirror_to_owner(tg_ctx, code, msg)
        return msg
    except Exception as e:
        logger.error("run_python: %s", e)
        if tg_ctx is not None:
            await _mirror_to_owner(tg_ctx, code, f"❌ Lỗi thực thi: {e}")
        return "❌ Có lỗi khi thực thi code."
