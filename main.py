import os
import re
import json
import logging
import asyncio
import aiohttp
from aiohttp import web
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ==========================================
# CẤU HÌNH BIẾN MÔI TRƯỜNG (ENVIRONMENT)
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
GEMINI_KEYS = [k.strip() for k in os.getenv("GEMINI_KEYS", "").split(",") if k.strip()]
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # VD: https://my-bot.onrender.com

# ==========================================
# DANH SÁCH MODEL HỢP LỆ (đã xác minh tồn tại)
# ==========================================
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview",
    "gemini-3.5-flash",
    "gemini-2.5-flash",          # Mạnh nhất, ưu tiên cao nhất
    "gemini-2.5-flash-lite-preview-06-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
]

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==========================================
# HỆ THỐNG GEMINI VỚI MULTI-SHARD & RETRY
# ==========================================
async def get_gemini_response(prompt: str, system_prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7}
    }

    # FIX: Tăng timeout lên 30s để tránh lỗi trên Render (latency cao hơn local)
    timeout = aiohttp.ClientTimeout(total=30)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        for key in GEMINI_KEYS:
            for model in MODELS:
                url = (
                    f"https://generativelanguage.googleapis.com/v1beta"
                    f"/models/{model}:generateContent?key={key}"
                )
                try:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data["candidates"][0]["content"]["parts"][0]["text"]
                        elif resp.status == 429:
                            logger.warning(f"Key {key[:5]}... Model {model}: hết quota (429). Thử tiếp...")
                            continue
                        elif resp.status == 404:
                            logger.warning(f"Model {model} không tồn tại (404). Bỏ qua...")
                            break  # Thử key tiếp, model này không hợp lệ
                        else:
                            error_text = await resp.text()
                            logger.error(f"Lỗi {resp.status} từ {model}: {error_text}")
                            continue
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout khi gọi {model}. Thử tiếp...")
                    continue
                except Exception as e:
                    logger.error(f"Lỗi mạng khi gọi Gemini: {e}")
                    continue

    return "❌ Xin lỗi sếp, tất cả API Key và Model đều hết hạn mức hoặc gặp sự cố."


# ==========================================
# XỬ LÝ LỆNH TỪ AI (HÀNH ĐỘNG ADMIN)
# ==========================================
async def execute_admin_actions(
    action_json: dict, update: Update, context: ContextTypes.DEFAULT_TYPE
):
    action = action_json.get("action")
    target_id = action_json.get("user_id")
    msg_id = action_json.get("message_id")
    chat_id = update.effective_chat.id

    try:
        if action == "ban" and target_id:
            await context.bot.ban_chat_member(chat_id, target_id)
        elif action == "mute" and target_id:
            await context.bot.restrict_chat_member(
                chat_id, target_id,
                permissions=ChatPermissions(can_send_messages=False)
            )
        elif action == "delete" and msg_id:
            await context.bot.delete_message(chat_id, msg_id)
        elif action == "pin" and msg_id:
            await context.bot.pin_chat_message(chat_id, msg_id)
    except Exception as e:
        logger.error(f"Không thể thực thi hành động {action}: {e}")


# ==========================================
# TRÁI TIM CỦA BOT (XỬ LÝ TIN NHẮN)
# ==========================================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text:
        return

    if msg.from_user.id != OWNER_ID:
        return

    is_pm = update.effective_chat.type == "private"
    bot_username = (await context.bot.get_me()).username
    is_reply_to_bot = (
        msg.reply_to_message
        and msg.reply_to_message.from_user.id == context.bot.id
    )
    is_pinged = f"@{bot_username}" in msg.text

    if not (is_pm or is_reply_to_bot or is_pinged):
        return

    reply_user_id = msg.reply_to_message.from_user.id if msg.reply_to_message else "None"
    reply_msg_id = msg.reply_to_message.message_id if msg.reply_to_message else "None"

    system_prompt = f"""
Bạn là một AI cá nhân mạnh mẽ trên Telegram, chỉ phục vụ một người chủ duy nhất.
Bạn có thái độ ngầu, ngắn gọn và phục tùng sếp.
Bạn có quyền admin. Nếu sếp yêu cầu ban, mute, delete, hoặc pin, hãy xuất JSON sau Ở CUỐI CÂU TRẢ LỜI:
<ACTION>{{"action": "tên_lệnh", "user_id": id_người_dùng, "message_id": id_tin_nhắn}}</ACTION>

Các lệnh hợp lệ: ban, mute, delete, pin.

Thông tin hiện tại:
- Chat ID: {update.effective_chat.id}
- ID người sếp đang reply: {reply_user_id}
- ID tin nhắn sếp đang reply: {reply_msg_id}

Ví dụ: Sếp reply một người và nói "Ban nó đi":
"Đã rõ thưa sếp! <ACTION>{{"action": "ban", "user_id": {reply_user_id}}}</ACTION>"
"""

    user_prompt = msg.text.replace(f"@{bot_username}", "").strip()

    typing_msg = await msg.reply_text("⏳ Đang xử lý...")

    ai_response = await get_gemini_response(user_prompt, system_prompt)

    action_match = re.search(r"<ACTION>(.*?)</ACTION>", ai_response, re.DOTALL)
    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            await execute_admin_actions(action_json, update, context)
            ai_response = ai_response.replace(action_match.group(0), "").strip()
        except Exception as e:
            logger.error(f"Lỗi parse JSON Action: {e}")

    await typing_msg.delete()
    if ai_response:
        await msg.reply_text(ai_response)


# ==========================================
# KHỞI ĐỘNG SERVER (WEBHOOK + HEALTH CHECK)
# ==========================================
async def run_with_webhook(application: Application):
    """
    FIX CHÍNH: Thay thế app.run_webhook() bằng aiohttp server tự quản lý.
    Lý do: PTB's built-in webhook server không có route GET /, khiến
    Render health check nhận 404 → service bị coi là unhealthy → restart vô tận.
    
    Server này có 2 route:
      GET  /          → Health check cho Render (trả về 200 OK)
      POST /{TOKEN}   → Nhận update từ Telegram
    """
    webhook_path = f"/{BOT_TOKEN}"
    full_webhook_url = f"{WEBHOOK_URL}{webhook_path}"

    # Handler nhận update từ Telegram
    async def telegram_webhook(request: web.Request) -> web.Response:
        try:
            data = await request.json()
            update = Update.de_json(data, application.bot)
            await application.process_update(update)
        except Exception as e:
            logger.error(f"Lỗi xử lý webhook update: {e}")
        return web.Response(text="OK")

    # Handler health check — Render yêu cầu GET / trả về 2xx
    async def health_check(request: web.Request) -> web.Response:
        return web.Response(text="Bot is running!")

    # Khởi tạo aiohttp app
    aio_app = web.Application()
    aio_app.router.add_get("/", health_check)
    aio_app.router.add_post(webhook_path, telegram_webhook)

    # Khởi động PTB application
    await application.initialize()
    await application.start()

    # Đăng ký webhook với Telegram
    await application.bot.set_webhook(
        url=full_webhook_url,
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,  # Bỏ qua update cũ từ lúc bot offline
    )
    logger.info(f"Webhook đã được đăng ký tại: {full_webhook_url}")

    # Chạy aiohttp server
    runner = web.AppRunner(aio_app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    logger.info(f"Server đang lắng nghe tại 0.0.0.0:{PORT}")

    # Giữ server chạy mãi
    try:
        await asyncio.Event().wait()
    finally:
        await application.stop()
        await application.shutdown()
        await runner.cleanup()


def main():
    if not BOT_TOKEN:
        logger.error("Thiếu BOT_TOKEN. Dừng lại.")
        return
    if not OWNER_ID:
        logger.error("Thiếu OWNER_ID. Dừng lại.")
        return
    if not GEMINI_KEYS:
        logger.error("Thiếu GEMINI_KEYS. Dừng lại.")
        return

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(MessageHandler(filters.TEXT, handle_message))

    if WEBHOOK_URL:
        logger.info("Chế độ: Webhook (Render)")
        asyncio.run(run_with_webhook(application))
    else:
        logger.info("Chế độ: Polling (Local)")
        application.run_polling()


if __name__ == "__main__":
    main()
