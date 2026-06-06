"""
Entry point.
Builds the Application, wires all handlers, then runs either
webhook mode (Render / cloud) or long-polling (local dev).

Startup sequence
----------------
  PTB calls post_init(_on_startup) after app.initialize().
  _on_startup:  (1) init DB pool + schema
                (2) load all persisted state into memory
  Then the bot begins accepting updates.
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


# ---------------------------------------------------------------------------
# Startup hook (runs inside PTB's event loop - works for both modes)
# ---------------------------------------------------------------------------

async def _on_startup(app: Application) -> None:
    """
    PTB post_init hook.
    Initialises the DB pool, ensures schema, then loads state into memory.
    """
    await db.init(DATABASE_URL, max_conv_rows=MAX_CONV_ROWS)
    await state.load_all_async()
    logger.info("Startup complete — owner=%d, db_ready=%s", OWNER_ID, db.is_ready())


async def _on_shutdown(app: Application) -> None:
    """PTB post_shutdown hook — gracefully close the DB pool."""
    await db.close()


# ---------------------------------------------------------------------------
# Application builder
# ---------------------------------------------------------------------------

def build_application() -> Application:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_on_startup)
        .post_shutdown(_on_shutdown)
        .build()
    )

    # Commands
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("sysreset", cmd_sysreset))
    app.add_handler(CommandHandler("model",    cmd_model))
    app.add_handler(CommandHandler("setmodel", cmd_model))
    app.add_handler(CommandHandler("plugins",  cmd_plugins))
    app.add_handler(CommandHandler("status",   cmd_status))
    app.add_handler(CommandHandler("topic",    cmd_topic))

    # Messages: text + photo
    app.add_handler(MessageHandler(
        (filters.TEXT | filters.PHOTO) & ~filters.COMMAND,
        handle_message,
    ))

    # Inline buttons (follow-up + model selection)
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


# ---------------------------------------------------------------------------
# Webhook mode (Render / cloud)
# ---------------------------------------------------------------------------

async def run_webhook(app: Application) -> None:
    path     = f"/{BOT_TOKEN}"
    full_url = f"{WEBHOOK_URL.rstrip('/')}{path}"

    async def tg_handler(request: web.Request) -> web.Response:
        # Validate secret token
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
        db_status = "connected" if db.is_ready() else "offline"
        return web.Response(text=f"Bot running | DB: {db_status}")

    aio = web.Application()
    aio.router.add_get("/",   health)
    aio.router.add_post(path, tg_handler)

    await app.initialize()    # triggers post_init -> _on_startup
    await app.start()
    await app.bot.set_webhook(
        url                  = full_url,
        allowed_updates      = Update.ALL_TYPES,
        drop_pending_updates = True,
        secret_token         = WEBHOOK_SECRET or None,
    )
    logger.info("Webhook registered: %s", full_url)

    runner = web.AppRunner(aio)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Listening on 0.0.0.0:%d", PORT)

    try:
        await asyncio.Event().wait()   # run forever
    finally:
        await app.stop()
        await app.shutdown()           # triggers post_shutdown -> _on_shutdown
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------

def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is not set."); return
    if not OWNER_ID:
        logger.error("OWNER_ID is not set."); return
    if not GEMINI_KEYS:
        logger.error("GEMINI_KEYS is not set."); return

    application = build_application()

    if WEBHOOK_URL:
        logger.info("Mode: Webhook -> %s", WEBHOOK_URL)
        asyncio.run(run_webhook(application))
    else:
        logger.info("Mode: Polling (local dev)")
        # run_polling manages its own event loop; post_init fires inside it.
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
