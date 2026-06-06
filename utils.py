"""Text processing utilities."""
import html
import re
from typing import Optional

MAX_LEN = 4000  # Telegram hard limit is 4096; keep margin for safety


# ─────────────────────────────────────────────────────────────
# Markdown → Telegram HTML  (#4)
# ─────────────────────────────────────────────────────────────
def md_to_html(text: str) -> str:
    """
    Convert Gemini Markdown output → Telegram HTML.
    Order: code blocks → inline code → escape HTML → formatting.
    """
    parts: list[tuple[str, str]] = []
    last = 0

    # 1. Extract code blocks first (protect content from escaping)
    for m in re.finditer(r"```(\w*)\n?(.*?)```", text, re.DOTALL):
        if m.start() > last:
            parts.append(("text", text[last:m.start()]))
        content = html.escape(m.group(2).strip())
        parts.append(("pre", f"<pre><code>{content}</code></pre>"))
        last = m.end()
    if last < len(text):
        parts.append(("text", text[last:]))

    out_parts: list[str] = []
    for kind, content in parts:
        if kind == "pre":
            out_parts.append(content)
            continue

        # 2. Extract inline code
        sub_parts: list[tuple[str, str]] = []
        sub_last = 0
        for m in re.finditer(r"`([^`]+)`", content):
            if m.start() > sub_last:
                sub_parts.append(("text", content[sub_last:m.start()]))
            sub_parts.append(("code", html.escape(m.group(1))))
            sub_last = m.end()
        if sub_last < len(content):
            sub_parts.append(("text", content[sub_last:]))

        for sub_kind, sub_content in sub_parts:
            if sub_kind == "code":
                out_parts.append(f"<code>{sub_content}</code>")
            else:
                t = html.escape(sub_content)
                # Headers → bold
                t = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", t, flags=re.MULTILINE)
                # Bold (**text** or __text__)
                t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t, flags=re.DOTALL)
                t = re.sub(r"__(.+?)__",     r"<b>\1</b>", t, flags=re.DOTALL)
                # Italic (*text* or _text_) — only when not a list bullet
                t = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<i>\1</i>", t)
                t = re.sub(r"(?<!_)_(?!_)(.+?)(?<!_)_(?!_)", r"<i>\1</i>", t)
                # Bullet points
                t = re.sub(r"^[-*+]\s+", "• ", t, flags=re.MULTILINE)
                out_parts.append(t)

    return "".join(out_parts)


# ─────────────────────────────────────────────────────────────
# Message splitting
# ─────────────────────────────────────────────────────────────
def split_message(text: str, max_len: int = MAX_LEN) -> list[str]:
    """
    Split text into Telegram-safe chunks, preferring natural break points:
    paragraph → newline → sentence → word.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while len(text) > max_len:
        cut = -1
        pos = text.rfind("\n\n", 0, max_len)
        if pos > max_len // 3:
            cut = pos
        if cut == -1:
            pos = text.rfind("\n", 0, max_len)
            if pos > max_len // 3:
                cut = pos
        if cut == -1:
            for sep in (". ", "! ", "? ", "。", "！", "？"):
                pos = text.rfind(sep, 0, max_len)
                if pos > max_len // 3:
                    cut = pos + len(sep)
                    break
        if cut == -1:
            cut = max_len

        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)
    return chunks


# ─────────────────────────────────────────────────────────────
# Misc helpers
# ─────────────────────────────────────────────────────────────
def merge(parts: list[str]) -> str:
    """Merge rapidly-sent message fragments into one prompt."""
    return "\n".join(p.strip() for p in parts if p.strip())


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>\"'{}|\\^`\[\]]+", text)


def parse_uid(s: str) -> Optional[int]:
    s = s.strip().lstrip("@")
    return int(s) if s.lstrip("-").isdigit() else None


def fmt_ids(ids: list[int]) -> str:
    return ", ".join(str(i) for i in ids) if ids else "<i>(trống)</i>"
