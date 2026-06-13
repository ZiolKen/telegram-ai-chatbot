"""Central configuration — loaded from environment variables."""
import os

# ── Bot ───────────────────────────────────────────────────────────────────
BOT_TOKEN: str      = os.getenv("BOT_TOKEN", "")
OWNER_ID: int       = int(os.getenv("OWNER_ID", "0"))
PORT: int           = int(os.getenv("PORT", 8080))
WEBHOOK_URL: str    = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

# ── PostgreSQL ────────────────────────────────────────────────────────────
DATABASE_URL: str  = os.getenv("DATABASE_URL", "")
MAX_CONV_ROWS: int = int(os.getenv("MAX_CONV_ROWS", "10000"))

# ── Gemini ────────────────────────────────────────────────────────────────
GEMINI_KEYS: list[str] = [
    k.strip() for k in os.getenv("GEMINI_KEYS", "").split(",") if k.strip()
]
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gemini-3.1-flash-lite")
MODELS: list[str] = [
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite-preview-06-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-pro",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
]

# ── Search (optional) ─────────────────────────────────────────────────────
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID: str  = os.getenv("GOOGLE_CSE_ID", "")

# ── Features ─────────────────────────────────────────────────────────────
ENABLE_PLUGINS: bool  = os.getenv("ENABLE_PLUGINS",  "true").lower() == "true"
ENABLE_FOLLOWUP: bool = os.getenv("ENABLE_FOLLOWUP", "true").lower() == "true"
FOLLOWUP_COUNT: int   = int(os.getenv("FOLLOWUP_COUNT", "3"))

# ── Conversation ─────────────────────────────────────────────────────────
MAX_HISTORY: int           = int(os.getenv("MAX_HISTORY", "40"))
MESSAGE_MERGE_DELAY: float = float(os.getenv("MESSAGE_MERGE_DELAY", "1.5"))

# ── Group Context Mode ────────────────────────────────────────────────────
# Khi bật: bot đọc VÀ lưu TẤT CẢ tin nhắn trong group vào conv chung
# (không chỉ tin nhắn của owner), giúp AI có context đầy đủ hơn.
# conv_id của group = g:{chat_id} (shared toàn group) thay vì g:{chat_id}:u:{uid}
GROUP_CONTEXT_ENABLED: bool = os.getenv("GROUP_CONTEXT_ENABLED", "true").lower() == "true"

# ── File Cache (RAM only, NO disk/DB) ─────────────────────────────────────
# Tổng dung lượng tối đa cho file cache trong RAM. Files được evict LRU
# khi vượt giới hạn. Cache xóa hoàn toàn khi Render restart.
FILE_CACHE_MAX_MB: int = int(os.getenv("FILE_CACHE_MAX_MB", "256"))

# ── Language ─────────────────────────────────────────────────────────────
# Default UI + AI prompt language for new conversations.
# Per-conversation lang overrides this (stored in DB via conv_cfg).
DEFAULT_LANG: str = os.getenv("DEFAULT_LANG", "en")   # "en" | "vi"

# ── Data dir ─────────────────────────────────────────────────────────────
DATA_DIR: str = "data"
