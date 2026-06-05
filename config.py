"""Central configuration — loaded from environment variables."""
import os

# ── Bot ───────────────────────────────────────────────────────
BOT_TOKEN: str      = os.getenv("BOT_TOKEN", "")
OWNER_ID: int       = int(os.getenv("OWNER_ID", "0"))
PORT: int           = int(os.getenv("PORT", 8080))
WEBHOOK_URL: str    = os.getenv("WEBHOOK_URL", "")

# ── Gemini ────────────────────────────────────────────────────
GEMINI_KEYS: list[str] = [
    k.strip() for k in os.getenv("GEMINI_KEYS", "").split(",") if k.strip()
]
DEFAULT_MODEL: str = os.getenv("DEFAULT_MODEL", "gemini-2.5-flash")
MODELS: list[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite-preview-06-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]

# ── Search (optional) ─────────────────────────────────────────
GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
GOOGLE_CSE_ID: str  = os.getenv("GOOGLE_CSE_ID", "")

# ── Features ──────────────────────────────────────────────────
ENABLE_PLUGINS: bool  = os.getenv("ENABLE_PLUGINS",  "true").lower() == "true"
ENABLE_FOLLOWUP: bool = os.getenv("ENABLE_FOLLOWUP", "true").lower() == "true"
FOLLOWUP_COUNT: int   = int(os.getenv("FOLLOWUP_COUNT", "3"))

# ── Conversation ──────────────────────────────────────────────
MAX_HISTORY: int           = int(os.getenv("MAX_HISTORY", "40"))
MESSAGE_MERGE_DELAY: float = float(os.getenv("MESSAGE_MERGE_DELAY", "1.5"))

# ── Data ──────────────────────────────────────────────────────
DATA_DIR: str = "data"
