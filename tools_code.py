"""
Safe Python code interpreter.
Runs code in a subprocess with a hard timeout; captures stdout/stderr.
"""
import asyncio
import logging
import subprocess
import sys
import textwrap

logger = logging.getLogger(__name__)

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
        return f"```\n{output.rstrip()}\n```"
    except subprocess.TimeoutExpired:
        return "❌ Code chạy quá 15 giây, đã dừng."
    except Exception as e:
        logger.error("run_python: %s", e)
        return f"❌ Lỗi thực thi: {e}"
