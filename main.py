"""
Entry point.

Startup sequence (webhook mode)
────────────────────────────────
  Dùng với Start Command:  python db.py && python main.py

  db.py chạy trước:
    • Kết nối PostgreSQL, tạo schema, exit 0 — xác nhận DB sẵn sàng

  main.py khởi động:
    1. Kết nối DB (nhanh vì db.py đã xác nhận DB sống)
    2. Load state từ DB vào memory
    3. Web server lên → Render health check pass
    4. PTB Application init (.updater(None) để tránh hang)
    5. Webhook đăng ký → bot nhận messages

Tại sao KHÔNG dùng background task nữa:
  Background task (cách cũ) → health check luôn thấy "initialising…" vì
  DB init chạy song song, chưa xong thì health check đã hỏi.
  Cách mới: db.py đã confirm DB OK → main.py connect ngay (< 2s) →
  khi web server lên thì DB đã sẵn sàng → health check thấy "connected ✓".
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
import file_cache
import state
from config import (
    BOT_TOKEN, DATABASE_URL, FILE_CACHE_MAX_MB, GEMINI_KEYS, MAX_CONV_ROWS,
    OWNER_ID, PORT, WEBHOOK_SECRET, WEBHOOK_URL,
)
from commands import (
    cmd_help, cmd_model, cmd_plugins,
    cmd_lang,
    cmd_reset, cmd_start, cmd_status,
    cmd_sysreset, cmd_topic,
    # New moderation commands
    cmd_del, cmd_pin,
    cmd_ban, cmd_unban,
    cmd_mute, cmd_unmute,
    cmd_addadmin, cmd_rmadmin,
    cmd_warn, cmd_warns, cmd_resetwarns,
    cmd_feed, cmd_cancel,
)
from handlers import handle_callback, handle_message

logging.basicConfig(
    format  = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    level   = logging.INFO,
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Application builder
# ─────────────────────────────────────────────────────────────────────────────

def build_application() -> Application:
    builder = Application.builder().token(BOT_TOKEN)

    if WEBHOOK_URL:
        # Bắt buộc khi dùng webhook thủ công: tắt Updater để tránh hang
        # trong updater.initialize() — đây là nguyên nhân gốc của "initialising…"
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
    app.add_handler(CommandHandler("lang",     cmd_lang))
    # ── Moderation commands ───────────────────────────────────
    app.add_handler(CommandHandler("del",        cmd_del))
    app.add_handler(CommandHandler("pin",        cmd_pin))
    app.add_handler(CommandHandler("ban",        cmd_ban))
    app.add_handler(CommandHandler("unban",      cmd_unban))
    app.add_handler(CommandHandler("mute",       cmd_mute))
    app.add_handler(CommandHandler("unmute",     cmd_unmute))
    app.add_handler(CommandHandler("addadmin",   cmd_addadmin))
    app.add_handler(CommandHandler("rmadmin",    cmd_rmadmin))
    app.add_handler(CommandHandler("warn",       cmd_warn))
    app.add_handler(CommandHandler("warns",      cmd_warns))
    app.add_handler(CommandHandler("resetwarns", cmd_resetwarns))
    app.add_handler(CommandHandler("feed",       cmd_feed))
    app.add_handler(CommandHandler("cancel",     cmd_cancel))
    app.add_handler(MessageHandler(
        (
            filters.TEXT
            | filters.PHOTO
            | filters.Document.ALL
            | filters.AUDIO
            | filters.VIDEO
            | filters.VOICE
            | filters.VIDEO_NOTE
            | filters.Sticker.ALL
            | filters.ANIMATION
        ) & ~filters.COMMAND,
        handle_message,
    ))
    app.add_handler(CallbackQueryHandler(handle_callback))


# ─────────────────────────────────────────────────────────────────────────────
# Webhook mode
# ─────────────────────────────────────────────────────────────────────────────

async def run_webhook(app: Application) -> None:
    path     = f"/{BOT_TOKEN}"
    full_url = f"{WEBHOOK_URL.rstrip('/')}{path}"

    # ── Health endpoint ───────────────────────────────────────────────────
    async def health(request: web.Request) -> web.Response:
        db_ready = db.is_ready()
        err      = db.last_error()
        if db_ready:
            db_status = "connected ✓"
        elif err:
            db_status = f"offline — {err}"
        else:
            # Chỉ xảy ra nếu DATABASE_URL không được set (in-memory mode)
            db_status = "disabled (no DATABASE_URL)"

        return web.Response(text="\n".join([
            "🤖 Bot is running",
            f"DB : {db_status}",
            f"ENV: DATABASE_URL={'SET' if DATABASE_URL else 'NOT SET'}",
        ]))

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

    # ── 1. Kết nối DB (synchronous — db.py đã xác nhận DB sống rồi) ──────
    #       Không dùng background task nữa → health check sẽ thấy ngay
    if DATABASE_URL:
        logger.info("[startup] Connecting to database…")
        await db.init(DATABASE_URL, max_conv_rows=MAX_CONV_ROWS)
        if db.is_ready():
            logger.info("[startup] DB connected ✓")
            await state.load_all_async()
            logger.info("[startup] State loaded from DB ✓")
        else:
            # db.py đã pass nhưng main.py vẫn fail → log rõ để debug
            logger.error(
                "[startup] DB connection failed in main.py: %s\n"
                "          Bot sẽ chạy in-memory (history mất khi restart).",
                db.last_error(),
            )
    else:
        logger.warning("[startup] DATABASE_URL not set — in-memory only.")

    # ── Init file cache (RAM only) ──────────────────────────────────────────
    file_cache.configure(FILE_CACHE_MAX_MB)
    logger.info("[startup] File cache: %d MB limit", FILE_CACHE_MAX_MB)

    # ── 2. Web server lên (Render health check pass từ đây) ───────────────
    aio = web.Application()
    aio.router.add_get("/",   health)
    aio.router.add_post(path, tg_handler)

    runner = web.AppRunner(aio)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    logger.info("[startup] Web server up on port %d ✓", PORT)

    # ── 3. PTB init (.updater(None) đã set → không hang) ─────────────────
    await app.initialize()
    await app.start()

    # ── 4. Đăng ký webhook ────────────────────────────────────────────────
    await app.bot.set_webhook(
        url                  = full_url,
        allowed_updates      = Update.ALL_TYPES,
        drop_pending_updates = True,
        secret_token         = WEBHOOK_SECRET or None,
    )
    logger.info("[startup] Webhook set ✓  %s", full_url)
    logger.info("[startup] Bot fully ready — waiting for messages")

    try:
        await asyncio.Event().wait()
    finally:
        await app.stop()
        await app.shutdown()
        await db.close()
        await runner.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Long-polling mode (local dev — không dùng webhook)
# ─────────────────────────────────────────────────────────────────────────────

async def run_polling(app: Application) -> None:
    """Chế độ local: kết nối DB rồi dùng polling thay vì webhook."""
    if DATABASE_URL:
        logger.info("[startup] Connecting to database…")
        await db.init(DATABASE_URL, max_conv_rows=MAX_CONV_ROWS)
        if db.is_ready():
            logger.info("[startup] DB connected ✓")
            await state.load_all_async()
        else:
            logger.warning("[startup] DB offline: %s", db.last_error())
    else:
        logger.warning("[startup] DATABASE_URL not set — in-memory only.")

    await app.initialize()
    await app.start()
    await app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("[startup] Polling started ✓")

    try:
        await asyncio.Event().wait()
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()
        await db.close()


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

    application = build_application()
    _register_handlers(application)

    if WEBHOOK_URL:
        logger.info("Mode: Webhook → %s", WEBHOOK_URL)
        asyncio.run(run_webhook(application))
    else:
        logger.info("Mode: Polling (local dev)")
        asyncio.run(run_polling(application))


if __name__ == "__main__":
    main()
