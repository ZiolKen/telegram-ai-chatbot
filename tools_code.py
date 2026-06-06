"""
Safe Python code interpreter.
Runs code in a subprocess with a hard timeout; captures stdout/stderr.
Includes AST + regex pre-scan to block dangerous patterns (#1).
"""
import ast
import asyncio
import logging
import re
import subprocess
import sys
import textwrap

logger = logging.getLogger(__name__)

# ── Tool declaration ──────────────────────────────────────────────────────
CODE_TOOL_DECLS = [
    {
        "name": "run_python",
        "description": (
            "Execute Python 3 code and return its stdout/stderr output. "
            "Useful for maths, data processing, sorting, encryption, "
            "string manipulation, or any calculation task. "
            "Has access to: math, json, re, datetime, random, itertools, "
            "functools, collections, statistics, base64, hashlib, decimal."
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

# ── Security: blocked modules (#1) ───────────────────────────────────────
_BLOCKED_MODULES = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "importlib", "ctypes", "multiprocessing", "threading",
    "signal", "resource", "pty", "tty", "termios",
    "http", "urllib", "urllib2", "requests", "aiohttp", "httpx",
    "ftplib", "smtplib", "poplib", "imaplib", "telnetlib",
    "paramiko", "fabric", "pexpect",
    "sqlite3", "psycopg2", "pymongo", "redis",
    "pickle", "shelve", "marshal",
    "code", "codeop", "compileall", "py_compile",
    "builtins",
}

_BLOCKED_PATTERNS = [
    r"__import__\s*\(",
    r"__builtins__",
    r"__class__\s*\.",
    r"__subclasses__\s*\(",
    r"getattr\s*\(\s*\w+\s*,\s*['\"]__",
    r"globals\s*\(\s*\)",
    r"locals\s*\(\s*\)",
    r"vars\s*\(\s*\)",
    r"exec\s*\(",
    r"eval\s*\(",
    r"compile\s*\(",
    r"open\s*\(",
    r"input\s*\(",
]


def _check_safe(code: str) -> str | None:
    """
    Returns None if code is safe.
    Returns error message if dangerous pattern detected.
    """
    # 1. AST parse — check import statements
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"❌ Syntax error: {e}"

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.Import):
                mods = [alias.name.split(".")[0] for alias in node.names]
            else:
                mods = [node.module.split(".")[0]] if node.module else []
            for mod in mods:
                if mod in _BLOCKED_MODULES:
                    return f"❌ Module <code>{mod}</code> không được phép."

    # 2. Regex scan for bypass patterns
    for pattern in _BLOCKED_PATTERNS:
        m = re.search(pattern, code)
        if m:
            return f"❌ Pattern không được phép: <code>{m.group()}</code>"

    return None  # Safe


# ── Sandbox wrapper ───────────────────────────────────────────────────────
_ALLOWED_IMPORTS = (
    "import math, json, re, datetime, random, itertools, "
    "functools, collections, statistics, base64, hashlib, decimal, time, string\n"
    "from datetime import datetime as _dt, timedelta\n"
    "from decimal import Decimal\n"
    "from collections import Counter, defaultdict, OrderedDict\n"
)

_WRAPPER = textwrap.dedent("""\
{allowed}
import sys, io as _io
_buf = _io.StringIO()
sys.stdout = sys.stderr = _buf
try:
{code}
except Exception as _e:
    print(f"{{type(_e).__name__}}: {{_e}}")
finally:
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__
print(_buf.getvalue(), end="")
""")


async def run_python(code: str) -> str:
    # Security scan before execution (#1)
    err = _check_safe(code)
    if err:
        return err

    indented = textwrap.indent(code, "    ")
    script   = _WRAPPER.format(allowed=_ALLOWED_IMPORTS, code=indented)

    loop = asyncio.get_event_loop()
    try:
        result: subprocess.CompletedProcess = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                timeout=15,
            ),
        )
        output = (result.stdout or "") + (result.stderr or "")
        if not output.strip():
            output = "(không có output)"
        if len(output) > 3500:
            output = output[:3500] + "\n…[output bị cắt bớt]"
        return f"<pre><code>{output.rstrip()}</code></pre>"
    except subprocess.TimeoutExpired:
        return "❌ Code chạy quá 15 giây, đã dừng."
    except Exception as e:
        logger.error("run_python: %s", e)
        return "❌ Có lỗi khi thực thi code."
