"""
tools_web.py — Web search, URL fetch, ArXiv.

Engine priority for web_search():
  1. Google CSE  (if GOOGLE_API_KEY + GOOGLE_CSE_ID set)
  2. DuckDuckGo  (fallback, with retry + jitter)

The `engine` parameter has been removed from the tool declaration:
  • AI was sometimes passing engine="duckduckgo" from the enum, bypassing
    Google CSE even when configured.
  • Engine selection is now fully automatic and internal.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import random
import time
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from config import GOOGLE_API_KEY, GOOGLE_CSE_ID

logger = logging.getLogger(__name__)

# Evaluated once at startup — logged so misconfiguration is visible.
_GOOGLE_READY = bool(GOOGLE_API_KEY and GOOGLE_CSE_ID)
if _GOOGLE_READY:
    logger.info("[web] Google CSE ready (key=%.8s… cx=%.8s…)",
                GOOGLE_API_KEY, GOOGLE_CSE_ID)
else:
    logger.info("[web] Google CSE not configured — will use DuckDuckGo")


# ── Tool declarations ─────────────────────────────────────────────────────
WEB_TOOL_DECLS = [
    {
        "name": "web_search",
        "description": (
            "Search the internet for current information, news, facts, "
            "prices, or any topic that may have changed recently. "
            "Uses the best available search engine automatically."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Search query",
                },
            },
            "required": ["query"],
            # engine parameter intentionally removed — AI was overriding
            # auto-selection and bypassing Google CSE.
        },
    },
    {
        "name": "fetch_url",
        "description": (
            "Fetch and extract readable text from a web page or article. "
            "Use when the user shares a URL and wants a summary or answer "
            "based on its content."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "url": {
                    "type": "STRING",
                    "description": "Full https:// URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "arxiv_search",
        "description": (
            "Search arXiv.org for academic/research papers. "
            "Returns title, authors, abstract, and link."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Research topic or paper title",
                },
                "max_results": {
                    "type": "NUMBER",
                    "description": "Number of papers to return (1–5)",
                },
            },
            "required": ["query"],
        },
    },
]


# ── SSRF protection ───────────────────────────────────────────────────────
_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / AWS metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _is_safe_url(url: str) -> tuple[bool, str]:
    try:
        p = urlparse(url)
    except Exception:
        return False, "URL không hợp lệ"
    if p.scheme not in ("http", "https"):
        return False, f"Scheme '{p.scheme}' không được phép"
    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return False, "Không có hostname"
    if host in _BLOCKED_HOSTNAMES:
        return False, f"Hostname '{host}' bị chặn"
    try:
        ip = ipaddress.ip_address(host)
        for net in _BLOCKED_RANGES:
            if ip in net:
                return False, f"IP '{host}' thuộc dải nội bộ bị chặn"
    except ValueError:
        pass
    return True, ""


# ── Web search — public entry point ──────────────────────────────────────
async def web_search(query: str, engine: str = "auto") -> str:
    """
    Engine selection (fully automatic — `engine` arg kept for internal use
    but is no longer exposed in the tool declaration):
      1. Google CSE if configured.
      2. DuckDuckGo with retry+jitter as fallback.
    """
    if _GOOGLE_READY and engine != "duckduckgo":
        try:
            result = await _google(query)
            if result is not None:
                logger.debug("[web] Google CSE OK for: %s", query[:60])
                return result
            logger.warning("[web] Google CSE returned no result, falling back to DDG")
        except Exception as e:
            logger.warning("[web] Google CSE error (%s), falling back to DDG", e)

    return await _ddg(query)


# ── Google CSE ────────────────────────────────────────────────────────────
async def _google(query: str) -> str | None:
    """
    Returns formatted result string, or None on any failure
    (caller will fall back to DDG).
    """
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": GOOGLE_API_KEY,
        "cx":  GOOGLE_CSE_ID,
        "q":   query,
        "num": 8,
    }
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as s:
            async with s.get(url, params=params) as r:
                if r.status == 429:
                    logger.warning("[web] Google CSE rate-limited (429)")
                    return None
                if r.status == 403:
                    logger.error("[web] Google CSE 403 — check API key / CSE ID")
                    return None
                if r.status != 200:
                    logger.error("[web] Google CSE HTTP %d", r.status)
                    return None
                data = await r.json()

        items = data.get("items", [])
        if not items:
            # Return empty-string sentinel so caller knows Google worked
            # but found nothing (no need to fall back to DDG).
            return "Không tìm thấy kết quả nào."

        lines = [
            f"**{i.get('title', '')}**\n{i.get('link', '')}\n{i.get('snippet', '')}"
            for i in items
        ]
        return "\n\n".join(lines)

    except asyncio.TimeoutError:
        logger.warning("[web] Google CSE timeout")
        return None
    except Exception as e:
        logger.error("[web] Google CSE unexpected error: %s", e)
        return None


# ── DuckDuckGo ────────────────────────────────────────────────────────────
# DDG rate-limits by IP. Mitigation strategy:
#   • Use a persistent DDGS session across retries (not a new one each time).
#   • Exponential backoff with random jitter so concurrent callers don't
#     all retry simultaneously.
#   • Vary the backend (wt-wt / us-en) across attempts.
#   • Handle both old RatelimitException and new DuckDuckGoSearchException.

_DDG_BACKENDS = [
    {"region": "wt-wt", "safesearch": "off"},
    {"region": "us-en", "safesearch": "moderate"},
    {"region": "wt-wt", "safesearch": "moderate"},
]
# Seconds to wait before each attempt: [immediate, ~5s, ~15s]
_DDG_DELAYS = [0, 5, 15]


async def _ddg(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        return "⚠️ duckduckgo-search not installed. Run: pip install duckduckgo-search"

    # Collect whichever exception classes exist in this version
    exc_classes: tuple = (Exception,)
    try:
        from duckduckgo_search.exceptions import RatelimitException
        exc_classes = (RatelimitException,)
    except ImportError:
        pass
    try:
        from duckduckgo_search.exceptions import DuckDuckGoSearchException
        exc_classes = (*exc_classes, DuckDuckGoSearchException)
    except ImportError:
        pass

    loop = asyncio.get_running_loop()
    last_err: Exception | None = None

    for attempt, base_delay in enumerate(_DDG_DELAYS):
        if base_delay > 0:
            # Jitter ±30% so concurrent calls don't all hit DDG at once
            jitter = base_delay * random.uniform(0.7, 1.3)
            logger.info("[web] DDG retry %d/3 — waiting %.1fs", attempt + 1, jitter)
            await asyncio.sleep(jitter)

        backend = _DDG_BACKENDS[attempt % len(_DDG_BACKENDS)]
        try:
            hits = await loop.run_in_executor(
                None,
                lambda b=backend: list(
                    DDGS().text(
                        query,
                        max_results=8,
                        region=b["region"],
                        safesearch=b["safesearch"],
                    )
                ),
            )
            if not hits:
                return "Không tìm thấy kết quả."

            lines = [
                f"**{h.get('title', '')}**\n{h.get('href', '')}\n{h.get('body', '')[:350]}"
                for h in hits
            ]
            if attempt > 0:
                logger.info("[web] DDG succeeded on attempt %d", attempt + 1)
            return "\n\n".join(lines)

        except exc_classes as e:
            last_err = e
            logger.warning("[web] DDG rate-limited (attempt %d/3): %s", attempt + 1, e)
            continue
        except Exception as e:
            logger.error("[web] DDG unexpected error: %s", e)
            return f"Lỗi tìm kiếm: {e}"

    logger.error("[web] DDG failed after 3 attempts. Last error: %s", last_err)
    return (
        "⚠️ DuckDuckGo đang rate-limit sau 3 lần thử.\n"
        "Thử lại sau vài phút, hoặc cấu hình GOOGLE_API_KEY + GOOGLE_CSE_ID "
        "để dùng Google Search thay thế."
    )


# ── URL fetch ─────────────────────────────────────────────────────────────
_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
}


async def fetch_url(url: str) -> str:
    safe, reason = _is_safe_url(url)
    if not safe:
        return f"❌ URL bị chặn: {reason}"

    try:
        async with aiohttp.ClientSession(
            headers=_FETCH_HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as s:
            async with s.get(url, allow_redirects=True) as r:
                if r.status != 200:
                    return f"Không thể tải URL (HTTP {r.status})"
                ct = r.headers.get("Content-Type", "")
                if not any(x in ct for x in ("text/", "application/json", "application/xml")):
                    return f"❌ Content-Type '{ct}' không phải text, bỏ qua."
                html_content = await r.text(errors="replace")

        soup = BeautifulSoup(html_content, "lxml")
        for tag in soup(["script", "style", "nav", "footer",
                          "header", "aside", "noscript"]):
            tag.decompose()

        body = soup.find("article") or soup.find("main") or soup.body or soup
        text = "\n".join(
            line.strip()
            for line in body.get_text(separator="\n").splitlines()
            if line.strip()
        )
        if len(text) > 9000:
            text = text[:9000] + "\n…[nội dung bị cắt bớt]"
        return f"Nội dung từ {url}:\n\n{text}"

    except asyncio.TimeoutError:
        return f"❌ Timeout khi tải: {url}"
    except Exception as e:
        logger.error("[web] fetch_url %s: %s", url, e)
        return f"Lỗi tải URL: {e}"


# ── ArXiv ─────────────────────────────────────────────────────────────────
async def arxiv_search(query: str, max_results: int = 3) -> str:
    max_results = max(1, min(5, int(max_results)))
    try:
        import arxiv
        loop = asyncio.get_running_loop()

        def _run() -> list:
            client = arxiv.Client()
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance,
            )
            return list(client.results(search))

        papers = await loop.run_in_executor(None, _run)
        if not papers:
            return "Không tìm thấy paper nào trên ArXiv."

        blocks = []
        for p in papers:
            authors = ", ".join(str(a) for a in p.authors[:3])
            if len(p.authors) > 3:
                authors += " et al."
            blocks.append(
                f"**{p.title}**\n"
                f"👤 {authors}  •  📅 {p.published.strftime('%Y-%m-%d')}\n"
                f"🔗 {p.entry_id}\n"
                f"📄 {p.summary[:600]}…"
            )
        return "\n\n---\n\n".join(blocks)

    except ImportError:
        return "⚠️ Gói arxiv chưa cài. Chạy: pip install arxiv"
    except Exception as e:
        logger.error("[web] arxiv_search: %s", e)
        return f"Lỗi tìm kiếm ArXiv: {e}"
