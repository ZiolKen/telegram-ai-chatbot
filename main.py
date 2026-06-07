"""
Entry point.

Startup sequence (webhook mode)
────────────────────────────────
  1. aiohttp web server starts IMMEDIATELY on PORT
     → Render health check passes right away
  2. PTB Application initialises (verifies bot token)
     → post_init fires → db.init() + state.load_all_async()
  3. Webhook is registered with Telegram
  4. Bot begins accepting updates

This order is intentional: if db.init() is slow (Aiven cold-start,
retry backoff), the health endpoint still returns 200 while the DB
is being connected in the background.
"""

import asyncio
import logging
import os

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
# PTB lifecycle hooks
# ─────────────────────────────────────────────────────────────────────────────

async def _on_startup(app: Application) -> None:
    """PTB post_init hook — init DB then load state."""
    logger.info("=== BOT STARTUP ===")
    logger.info("OWNER_ID      : %d", OWNER_ID)
    logger.info("DATABASE_URL  : %s",
                "SET ✓" if DATABASE_URL else "NOT SET ✗  (running in-memory only)")
    logger.info("WEBHOOK_URL   : %s", WEBHOOK_URL or "(polling mode)")

    await db.init(DATABASE_URL, max_conv_rows=MAX_CONV_ROWS)
    await state.load_all_async()

    logger.info(
        "=== STARTUP COMPLETE — db_ready=%s ===",
        db.is_ready(),
    )
    if not db.is_ready():
        err = db.last_error()
        logger.warning("DB offline reason: %s", err or "unknown")


async def _on_shutdown(app: Application) -> None:
    """PTB post_shutdown hook — close DB pool."""
    await db.close()


# ─────────────────────────────────────────────────────────────────────────────
# Application builder
# ─────────────────────────────────────────────────────────────────────────────

def build_application() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

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

    return app


# ─────────────────────────────────────────────────────────────────────────────
# Webhook mode  (Render / cloud)
# ─────────────────────────────────────────────────────────────────────────────

async def run_webhook(app: Application) -> None:
    path     = f"/{BOT_TOKEN}"
    full_url = f"{WEBHOOK_URL.rstrip('/')}{path}"

    # ── aiohttp handlers ─────────────────────────────────────────────────
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
        """
        Health endpoint — returns 200 always so Render marks deploy as live.
        Shows DB status + last error so you can diagnose from the browser.
        """
        db_ready = db.is_ready()
        err      = db.last_error()
        if db_ready:
            db_status = "connected ✓"
        elif err:
            db_status = f"offline — {err}"
        else:
            db_status = "initialising…"

        lines = [
            "🤖 Bot is running",
            f"DB : {db_status}",
            f"ENV: DATABASE_URL={'SET' if DATABASE_URL else 'NOT SET'}",
        ]
        return web.Response(text="\n".join(lines))

    # ── FIX: Start web server FIRST so Render health check passes ─────────
    # db.init() can take up to 20 s × 3 retries = 60 s worst case.
    # Starting the server first prevents Render from killing the process.
    aio    = web.Application()
    aio.router.add_get("/",   health)
    aio.router.add_post(path, tg_handler)

    runner = web.AppRunner(aio)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("✓ Web server listening on 0.0.0.0:%d", PORT)
    logger.info("  Health : http://localhost:%d/", PORT)

    # ── Now initialise PTB (triggers post_init → db.init) ─────────────────
    await app.initialize()   # post_init → _on_startup → db.init + state.load_all_async
    await app.start()
    await app.bot.set_webhook(
        url                  = full_url,
        allowed_updates      = Update.ALL_TYPES,
        drop_pending_updates = True,
        secret_token         = WEBHOOK_SECRET or None,
    )
    logger.info("✓ Webhook registered: %s", full_url)

    try:
        await asyncio.Event().wait()   # run forever
    finally:
        await app.stop()
        await app.shutdown()           # post_shutdown → db.close
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # Hard checks — these must be set or the bot is completely broken
    missing = [k for k, v in {
        "BOT_TOKEN":   BOT_TOKEN,
        "OWNER_ID":    OWNER_ID,
        "GEMINI_KEYS": GEMINI_KEYS,
    }.items() if not v]

    if missing:
        for k in missing:
            logger.error("REQUIRED env var %s is not set.", k)
        return

    # Soft warning — bot works without DB, just no persistence
    if not DATABASE_URL:
        logger.warning(
            "DATABASE_URL is not set.\n"
            "  Bot will work but conversation history will be lost on restart.\n"
            "  Add DATABASE_URL to your Render environment variables."
        )

    application = build_application()

    if WEBHOOK_URL:
        logger.info("Mode: Webhook -> %s", WEBHOOK_URL)
        asyncio.run(run_webhook(application))
    else:
        logger.info("Mode: Polling (local dev)")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
