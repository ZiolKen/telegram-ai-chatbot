import os
import re
import json
import logging
import asyncio
import aiohttp
from telegram import Update, ChatPermissions
from telegram.ext import Application, MessageHandler, filters, ContextTypes

# ==========================================
# CẤU HÌNH BIẾN MÔI TRƯỜNG (ENVIRONMENT)
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
# Tách danh sách API Key bằng dấu phẩy
GEMINI_KEYS = [k.strip() for k in os.getenv("GEMINI_KEYS", "").split(",") if k.strip()]
PORT = int(os.getenv("PORT", 8080))
WEBHOOK_URL = os.getenv("WEBHOOK_URL") # Dành cho Render (VD: https://my-bot.onrender.com)

# Danh sách model miễn phí (Sắp xếp theo độ ưu tiên)
MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.0-flash", 
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-1.5-flash-8b"
]

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
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

    async with aiohttp.ClientSession() as session:
        for key in GEMINI_KEYS:
            for model in MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                try:
                    async with session.post(url, headers=headers, json=payload, timeout=20) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            return data['candidates'][0]['content']['parts'][0]['text']
                        elif resp.status == 429:
                            logger.warning(f"Key {key[:5]}... & Model {model} hết Quota (429). Chuyển đổi...")
                            continue # Thử model/key tiếp theo
                        else:
                            error_text = await resp.text()
                            logger.error(f"Lỗi {resp.status} từ {model}: {error_text}")
                            continue
                except Exception as e:
                    logger.error(f"Lỗi mạng khi gọi Gemini: {e}")
                    continue
                    
    return "❌ Xin lỗi sếp, tất cả các API Key và Model đều đã hết hạn mức hoặc gặp sự cố."

# ==========================================
# XỬ LÝ LỆNH TỪ AI (HÀNH ĐỘNG ADMIN)
# ==========================================
async def execute_admin_actions(action_json: dict, update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = action_json.get("action")
    target_id = action_json.get("user_id")
    msg_id = action_json.get("message_id")
    chat_id = update.effective_chat.id

    try:
        if action == "ban" and target_id:
            await context.bot.ban_chat_member(chat_id, target_id)
        elif action == "mute" and target_id:
            await context.bot.restrict_chat_member(chat_id, target_id, permissions=ChatPermissions(can_send_messages=False))
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

    # 1. BẢO MẬT: Chỉ nghe lời chủ nhân
    if msg.from_user.id != OWNER_ID:
        return

    is_pm = update.effective_chat.type == "private"
    bot_username = (await context.bot.get_me()).username
    is_reply_to_bot = msg.reply_to_message and msg.reply_to_message.from_user.id == context.bot.id
    is_pinged = f"@{bot_username}" in msg.text

    # Chỉ kích hoạt nếu là PM, hoặc reply bot, hoặc tag bot
    if not (is_pm or is_reply_to_bot or is_pinged):
        return

    # 2. XÂY DỰNG BỐI CẢNH (CONTEXT) CHO AI
    reply_user_id = msg.reply_to_message.from_user.id if msg.reply_to_message else "None"
    reply_msg_id = msg.reply_to_message.message_id if msg.reply_to_message else "None"

    system_prompt = f"""
    Bạn là một AI cá nhân mạnh mẽ trên Telegram, chỉ phục vụ một người chủ duy nhất. Bạn có thái độ ngầu, ngắn gọn và phục tùng sếp.
    Bạn có quyền admin. Nếu sếp yêu cầu bạn ban (cấm), mute (tắt tiếng), delete (xoá), hoặc pin (ghim) tin nhắn, hãy xuất ra định dạng JSON sau Ở CUỐI CÂU TRẢ LỜI:
    <ACTION>{{"action": "tên_lệnh", "user_id": id_người_dùng, "message_id": id_tin_nhắn}}</ACTION>
    
    Các lệnh hợp lệ: ban, mute, delete, pin.
    
    Thông tin hiện tại (để bạn điền vào JSON nếu cần thiết):
    - Chat ID hiện tại: {update.effective_chat.id}
    - ID người mà sếp đang reply: {reply_user_id}
    - ID tin nhắn mà sếp đang reply: {reply_msg_id}
    
    Ví dụ: Sếp reply một người và nói "Ban nó đi", bạn trả lời: "Đã rõ thưa sếp, tôi đã ban hắn! <ACTION>{{"action": "ban", "user_id": {reply_user_id}}}</ACTION>"
    """

    user_prompt = msg.text.replace(f"@{bot_username}", "").strip()

    # Phản hồi đang xử lý
    typing_msg = await msg.reply_text("⏳ Đang xử lý...")

    # 3. GỌI GEMINI & XOAY VÒNG KEY
    ai_response = await get_gemini_response(user_prompt, system_prompt)

    # 4. TÁCH LỆNH ACTION VÀ THỰC THI
    action_match = re.search(r"<ACTION>(.*?)</ACTION>", ai_response, re.DOTALL)
    if action_match:
        try:
            action_json = json.loads(action_match.group(1))
            await execute_admin_actions(action_json, update, context)
            # Xoá thẻ ACTION khỏi câu trả lời của AI để không hiện ra tin nhắn
            ai_response = ai_response.replace(action_match.group(0), "").strip()
        except Exception as e:
            logger.error(f"Lỗi parse JSON Action: {e}")

    # 5. GỬI KẾT QUẢ CHO SẾP
    await typing_msg.delete()
    if ai_response:
        await msg.reply_text(ai_response)

def main():
    if not BOT_TOKEN or not OWNER_ID:
        logger.error("Thiếu BOT_TOKEN hoặc OWNER_ID.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    # Lắng nghe mọi text message, logic lọc nằm bên trong hàm
    app.add_handler(MessageHandler(filters.TEXT, handle_message))

    # Chạy bằng Webhook (Bắt buộc cho Render)
    if WEBHOOK_URL:
        logger.info(f"Đang khởi động Webhook tại {WEBHOOK_URL}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            secret_token="sieu_bao_mat_cho_bot_cua_ban_123" # Tùy chọn bảo mật của Telegram
        )
    else:
        logger.info("Chạy chế độ Polling (Local)")
        app.run_polling()

if __name__ == "__main__":
    main()
