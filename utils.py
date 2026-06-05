"""Text processing utilities."""
import re
from typing import Optional

MAX_LEN = 4000   # Telegram hard limit is 4096; keep margin for safety


def split_message(text: str, max_len: int = MAX_LEN) -> list[str]:
    """
    Split text into Telegram-safe chunks, preferring natural break points
    in this order: paragraph → newline → sentence → word.
    """
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    while len(text) > max_len:
        cut = -1
        # paragraph break
        pos = text.rfind("\n\n", 0, max_len)
        if pos > max_len // 3:
            cut = pos
        # single newline
        if cut == -1:
            pos = text.rfind("\n", 0, max_len)
            if pos > max_len // 3:
                cut = pos
        # sentence boundary
        if cut == -1:
            for sep in (". ", "! ", "? ", "。", "！", "？"):
                pos = text.rfind(sep, 0, max_len)
                if pos > max_len // 3:
                    cut = pos + len(sep)
                    break
        # hard cut
        if cut == -1:
            cut = max_len

        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()

    if text:
        chunks.append(text)
    return chunks


def merge(parts: list[str]) -> str:
    """Merge rapidly-sent message fragments into one prompt."""
    return "\n".join(p.strip() for p in parts if p.strip())


def extract_urls(text: str) -> list[str]:
    return re.findall(r"https?://[^\s<>\"'{}|\\^`\[\]]+", text)


def parse_uid(s: str) -> Optional[int]:
    s = s.strip().lstrip("@")
    return int(s) if s.lstrip("-").isdigit() else None


def fmt_ids(ids: list[int]) -> str:
    return ", ".join(str(i) for i in ids) if ids else "_(trống)_"
