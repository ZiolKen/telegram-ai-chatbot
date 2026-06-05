"""
Entry point.
Builds the Application, registers all handlers, then runs either
webhook mode (for Render / cloud hosting) or long-polling (local dev).
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

import state
from config import BOT_TOKEN, GEMINI_KEYS, OWNER_ID, PORT, WEBHOOK_URL
from commands import (
    cmd_access,
    cmd_admin,
    cmd_blacklist,
    cmd_help,
    cmd_model,
    cmd_plugins,
    cmd_reset,
    cmd_start,
    cmd_status,
    cmd_sysreset,
    cmd_topic,
    cmd_whitelist,
)
from handlers import handle_callback, handle_message

logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def build_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).build()

    # ── Commands ──────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("reset",      cmd_reset))
    app.add_handler(CommandHandler("sysreset",   cmd_sysreset))
    app.add_handler(CommandHandler("model",      cmd_model))
    app.add_handler(CommandHandler("setmodel",   cmd_model))
    app.add_handler(CommandHandler("plugins",    cmd_plugins))
    app.add_handler(CommandHandler("status",     cmd_status))
    app.add_handler(CommandHandler("topic",      cmd_topic))
    app.add_handler(CommandHandler("admin",      cmd_admin))
    app.add_handler(CommandHandler("whitelist",  cmd_whitelist))
    app.add_handler(CommandHandler("blacklist",  cmd_blacklist))
    app.add_handler(CommandHandler("access",     cmd_access))

    # ── Messages ──────────────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_message,
    ))

    # ── Inline buttons (follow-up questions) ─────────────────
    app.add_handler(CallbackQueryHandler(handle_callback))

    return app


# ─────────────────────────────────────────────────────────────
# Webhook mode  (Render / cloud)
# ─────────────────────────────────────────────────────────────
async def run_webhook(app: Application):
    path     = f"/{BOT_TOKEN}"
    full_url = f"{WEBHOOK_URL.rstrip('/')}{path}"

    async def tg_handler(request: web.Request) -> web.Response:
        try:
            data   = await request.json()
            update = Update.de_json(data, app.bot)
            await app.process_update(update)
        except Exception as e:
            logger.error("Webhook process error: %s", e)
        return web.Response(text="OK")

    async def health(request: web.Request) -> web.Response:
        return web.Response(text="🤖 Bot is running!")

    aio = web.Application()
    aio.router.add_get("/",    health)
    aio.router.add_post(path,  tg_handler)

    await app.initialize()
    await app.start()
    await app.bot.set_webhook(
        url             = full_url,
        allowed_updates = Update.ALL_TYPES,
        drop_pending_updates = True,
    )
    logger.info("Webhook registered: %s", full_url)

    runner = web.AppRunner(aio)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("Server listening on 0.0.0.0:%d", PORT)

    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        await app.shutdown()
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────
# Entry
# ─────────────────────────────────────────────────────────────
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN không được thiết lập."); return
    if not OWNER_ID:
        logger.error("OWNER_ID không được thiết lập."); return
    if not GEMINI_KEYS:
        logger.error("GEMINI_KEYS không được thiết lập."); return

    state.load_all()
    logger.info(
        "State loaded — owner=%d  admins=%d  whitelist=%d  blacklist=%d",
        OWNER_ID,
        len(state.get_admins()),
        len(state.get_whitelist()),
        len(state.get_blacklist()),
    )

    application = build_application()

    if WEBHOOK_URL:
        logger.info("Mode: Webhook → %s", WEBHOOK_URL)
        asyncio.run(run_webhook(application))
    else:
        logger.info("Mode: Polling (local dev)")
        application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
