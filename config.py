"""Central configuration — loaded from environment variables."""
import os

# ── Bot ───────────────────────────────────────────────────────────────────
BOT_TOKEN: str      = os.getenv("BOT_TOKEN", "")
OWNER_ID: int       = int(os.getenv("OWNER_ID", "0"))
PORT: int           = int(os.getenv("PORT", 8080))
WEBHOOK_URL: str    = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET: str = os.getenv("WEBHOOK_SECRET", "")

# ── PostgreSQL ────────────────────────────────────────────────────────────
# Full connection string, e.g. postgresql://user:pass@host:5432/dbname
# Render sets this automatically when a Postgres service is linked.
DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# Max rows kept in the conversations table before the oldest are pruned.
# ~40 chars avg per part → 10 000 rows ≈ 400 KB of message text.
MAX_CONV_ROWS: int = int(os.getenv("MAX_CONV_ROWS", "10000"))

# ── Gemini ────────────────────────────────────────────────────────────────
GEMINI_KEYS: list[str] = [
    k.strip() for k in os.getenv("GEMINI_KEYS", "").split(",") if k.strip()
]
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gemini-3.1-flash-lite")
MODELS: list[str] = [
    # ── Gemini 3.x ───────────────────────────────────────────────────────
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    # ── Gemini 2.5 ───────────────────────────────────────────────────────
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite-preview-06-17",
    # ── Gemini 2.0 ───────────────────────────────────────────────────────
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    # ── Gemini 1.5 ───────────────────────────────────────────────────────
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

# ── Data dir (kept for compatibility; no longer used for JSON writes) ─────
DATA_DIR: str = "data"
