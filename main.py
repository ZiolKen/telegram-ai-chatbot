"""
Entry point.

Startup sequence (webhook mode)
────────────────────────────────
  1. aiohttp web server starts IMMEDIATELY on PORT
     → Render health check passes right away
  2. PTB Application initialises — built with .updater(None) so
     app.initialize() doesn't block in updater.initialize()
  3. post_init fires → schedules db.init() as background task
     (health endpoint stays responsive the whole time)
  4. Webhook registered → bot accepts messages
  5. DB connects, state loaded — fully ready

Root cause of "initialising…" forever
───────────────────────────────────────
  PTB's default builder attaches an Updater (designed for long-polling).
  In custom webhook mode, updater.initialize() calls Telegram's getUpdates
  or related APIs and hangs indefinitely.  post_init sits behind it and
  never fires — db.init() is never called — health shows "initialising…".
  Fix: .updater(None) when WEBHOOK_URL is set.
"""

import asyncio
import logging

from aiohttp import web
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

import db
import state
from config import (
    BOT_TOKEN, DATABASE_URL, GEMINI_KEYS, MAX_CONV_ROWS,
    OWNER_ID, PORT, WEBHOOK_SECRET, WEBHOOK_URL,
)
from commands import (
    cmd_help, cmd_model, cmd_plugins,
    cmd_reset, cmd_start, cmd_status,
    cmd_sysreset, cmd_topic,
)
from handlers import handle_callback, handle_message

logging.basicConfig(
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level   = logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# DB initialisation — runs as background asyncio task
# ─────────────────────────────────────────────────────────────────────────────

async def _init_db_background() -> None:
    """
    Connect to Postgres and load state.
    Scheduled as a background task so it never blocks app.initialize()
    or the webhook server.  Messages arriving before this completes are
    handled normally — state.push() is safe when pool is None.
    """
    logger.info("[startup] DB init → DATABASE_URL %s",
                "SET ✓" if DATABASE_URL else "NOT SET ✗  (in-memory only)")
    await db.init(DATABASE_URL, max_conv_rows=MAX_CONV_ROWS)
    await state.load_all_async()
    logger.info("[startup] DB init complete — db_ready=%s", db.is_ready())
    if not db.is_ready():
        logger.warning("[startup] DB offline: %s", db.last_error() or "unknown")


# ─────────────────────────────────────────────────────────────────────────────
# PTB lifecycle hooks
# ─────────────────────────────────────────────────────────────────────────────

async def _on_startup(app: Application) -> None:
    """PTB post_init — returns immediately, DB runs in background."""
    logger.info("[startup] post_init fired ✓")
    asyncio.create_task(_init_db_background())


async def _on_shutdown(app: Application) -> None:
    """PTB post_shutdown — close DB pool."""
    await db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Application builder
# ─────────────────────────────────────────────────────────────────────────────

def build_application() -> Application:
    builder = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
    )

    if WEBHOOK_URL:
        # KEY FIX: disable the Updater in webhook mode.
        # Without this, updater.initialize() hangs → post_init never fires.
        # Polling mode (local dev) omits this — it still needs the Updater.
        builder = builder.updater(None)

    return builder.build()


def _register_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("sysreset", cmd_sysreset))
    app.add_handler(CommandHandler("model",    cmd_model))
    app.add_handler(CommandHandler("setmodel", cmd_model))
    app.add_handler(CommandHandler("plugins",  cmd_plugins))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("topic",    cmd_topic))
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
        handle_message,
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))


# ─────────────────────────────────────────────────────────────────────────────
# Webhook mode
# ─────────────────────────────────────────────────────────────────────────────

async def run_webhook(app: Application) -> None:
    path     = f"/{BOT_TOKEN}"
    full_url = f"{WEBHOOK_URL.rstrip('/')}{path}"

    async def tg_handler(request: web.Request) -> web.Response:
        if WEBHOOK_SECRET:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != WEBHOOK_SECRET:
                logger.warning("Webhook: invalid secret from %s", request.remote)
                return web.Response(status=403, text="Forbidden")
        try:
            data   = await request.json()
            update = Update.de_json(data, app.bot)
            await app.process_update(update)
        except Exception as exc:
            logger.error("Webhook process error: %s", exc)
        return web.Response(text="OK")

    async def health(request: web.Request) -> web.Response:
        db_ready = db.is_ready()
        err      = db.last_error()
        if db_ready:
            db_status = "connected ✓"
        elif err:
            db_status = f"offline — {err}"
        else:
            db_status = "initialising…"

        return web.Response(text="\n".join([
            "🤖 Bot is running",
            f"DB : {db_status}",
            f"ENV: DATABASE_URL={'SET' if DATABASE_URL else 'NOT SET'}",
        ]))

    # ── 1. Web server starts FIRST — Render health check passes now ───────
    aio = web.Application()
    aio.router.add_get("/",   health)
    aio.router.add_post(path, tg_handler)

    runner = web.AppRunner(aio)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("[startup] Web server up on port %d ✓", PORT)

    # ── 2. Init PTB — fast because .updater(None) skips updater init ─────
    #   post_init fires here → schedules _init_db_background as task
    await app.initialize()
    await app.start()

    # ── 3. Register webhook ───────────────────────────────────────────────
    await app.bot.set_webhook(
        url                  = full_url,
        allowed_updates      = Update.ALL_TYPES,
        drop_pending_updates = True,
        secret_token         = WEBHOOK_SECRET or None,
    )
    logger.info("[startup] Webhook set ✓  %s", full_url)
    logger.info("[startup] Bot ready — waiting for messages")

    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        await app.shutdown()
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    missing = [k for k, v in {
        "BOT_TOKEN":   BOT_TOKEN,
        "OWNER_ID":    OWNER_ID,
        "GEMINI_KEYS": GEMINI_KEYS,
    }.items() if not v]
    if missing:
        for k in missing:
            logger.error("REQUIRED env var not set: %s", k)
        return

    if not DATABASE_URL:
        logger.warning(
            "DATABASE_URL not set — history lost on restart.\n"
            "Add DATABASE_URL to Render env vars (Aiven connection string)."
        )

    application = build_application()
    _register_handlers(application)

    if WEBHOOK_URL:
        logger.info("Mode: Webhook → %s", WEBHOOK_URL)
        asyncio.run(run_webhook(application))
    else:
        logger.info("Mode: Polling (local dev)")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
