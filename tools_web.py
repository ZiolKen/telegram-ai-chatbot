"""
Web-based tools: DuckDuckGo/Google search, URL extraction, ArXiv lookup.
Each public function is async and returns a plain string for the LLM.
Includes SSRF protection on fetch_url (#2).
"""
import asyncio
import ipaddress
import logging
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from config import GOOGLE_API_KEY, GOOGLE_CSE_ID

logger = logging.getLogger(__name__)

# ── Tool declarations ─────────────────────────────────────────────────────
WEB_TOOL_DECLS = [
    {
        "name": "web_search",
        "description": (
            "Search the internet for current information, news, facts, "
            "prices, or any topic that may have changed recently. "
            "Prefer 'google' engine when GOOGLE_API_KEY is set."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "engine": {
                    "type": "STRING",
                    "description": "Search engine to use",
                    "enum": ["duckduckgo", "google"],
                },
            },
            "required": ["query"],
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
                "url": {"type": "STRING", "description": "Full https:// URL to fetch"},
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
                "query":       {"type": "STRING", "description": "Research topic or paper title"},
                "max_results": {"type": "NUMBER", "description": "Number of papers to return (1-5)"},
            },
            "required": ["query"],
        },
    },
]


# ── SSRF Protection (#2) ──────────────────────────────────────────────────
_BLOCKED_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),     # loopback
    ipaddress.ip_network("10.0.0.0/8"),       # private
    ipaddress.ip_network("172.16.0.0/12"),    # private
    ipaddress.ip_network("192.168.0.0/16"),   # private
    ipaddress.ip_network("169.254.0.0/16"),   # link-local / cloud metadata
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),          # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),         # IPv6 private
]
_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Returns (is_safe, reason)."""
    try:
        p = urlparse(url)
    except Exception:
        return False, "URL không hợp lệ"

    if p.scheme not in ("http", "https"):
        return False, f"Scheme <code>{p.scheme}</code> không được phép, chỉ http/https"

    host = (p.hostname or "").lower().rstrip(".")
    if not host:
        return False, "Không có hostname"

    if host in _BLOCKED_HOSTNAMES:
        return False, f"Hostname <code>{host}</code> bị chặn"

    try:
        ip = ipaddress.ip_address(host)
        for net in _BLOCKED_RANGES:
            if ip in net:
                return False, f"IP <code>{host}</code> thuộc dải nội bộ bị chặn"
    except ValueError:
        pass  # Normal hostname — OK

    return True, ""


# ── Web Search ────────────────────────────────────────────────────────────
async def web_search(query: str, engine: str = "duckduckgo") -> str:
    if engine == "google" and GOOGLE_API_KEY and GOOGLE_CSE_ID:
        return await _google(query)
    return await _ddg(query)


async def _ddg(query: str) -> str:
    try:
        from duckduckgo_search import DDGS
        loop = asyncio.get_event_loop()
        hits = await loop.run_in_executor(
            None,
            lambda: list(DDGS().text(query, max_results=6)),
        )
        if not hits:
            return "Không tìm thấy kết quả."
        lines = []
        for h in hits:
            title = h.get("title", "")
            href  = h.get("href", "")
            body  = h.get("body", "")[:350]
            lines.append(f"**{title}**\n{href}\n{body}")
        return "\n\n".join(lines)
    except ImportError:
        return "⚠️ duckduckgo-search chưa cài. Chạy: pip install duckduckgo-search"
    except Exception as e:
        logger.error("DDG search: %s", e)
        return f"Lỗi tìm kiếm: {e}"


async def _google(query: str) -> str:
    url = "https://www.googleapis.com/customsearch/v1"
    params = {"key": GOOGLE_API_KEY, "cx": GOOGLE_CSE_ID, "q": query, "num": 6}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(url, params=params) as r:
                if r.status != 200:
                    return f"Google Search lỗi HTTP {r.status}"
                data = await r.json()
        items = data.get("items", [])
        if not items:
            return "Không tìm thấy kết quả Google."
        lines = [
            f"**{i.get('title','')}**\n{i.get('link','')}\n{i.get('snippet','')}"
            for i in items
        ]
        return "\n\n".join(lines)
    except Exception as e:
        logger.error("Google search: %s", e)
        return f"Lỗi Google Search: {e}"


# ── URL Fetch (with SSRF protection) ─────────────────────────────────────
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    )
}


async def fetch_url(url: str) -> str:
    # SSRF check (#2)
    safe, reason = _is_safe_url(url)
    if not safe:
        return f"❌ URL bị chặn: {reason}"

    try:
        async with aiohttp.ClientSession(
            headers=_HEADERS,
            timeout=aiohttp.ClientTimeout(total=20),
        ) as s:
            async with s.get(url) as r:
                if r.status != 200:
                    return f"Không thể tải URL (HTTP {r.status})"

                # Block binary content types
                ct = r.headers.get("Content-Type", "")
                if not any(t in ct for t in ("text/", "application/json", "application/xml")):
                    return f"❌ Content-Type <code>{ct}</code> không phải text, bỏ qua."

                html_content = await r.text(errors="replace")

        soup = BeautifulSoup(html_content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        body = soup.find("article") or soup.find("main") or soup.body or soup
        text = "\n".join(
            line.strip() for line in body.get_text(separator="\n").splitlines()
            if line.strip()
        )
        if len(text) > 9000:
            text = text[:9000] + "\n…[nội dung bị cắt bớt]"
        return f"Nội dung từ {url}:\n\n{text}"
    except Exception as e:
        logger.error("fetch_url %s: %s", url, e)
        return f"Lỗi tải URL: {e}"


# ── ArXiv Search ─────────────────────────────────────────────────────────
async def arxiv_search(query: str, max_results: int = 3) -> str:
    max_results = max(1, min(5, int(max_results)))
    try:
        import arxiv
        loop = asyncio.get_event_loop()

        def _run():
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
        logger.error("arxiv_search: %s", e)
        return f"Lỗi tìm kiếm ArXiv: {e}"
