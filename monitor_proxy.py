"""
monitor_proxy.py — Group Real-Time Monitoring, Two-Way DM Proxy Relay, and AI Summarization.
"""
from __future__ import annotations

import asyncio
import html
import logging

from telegram import (
    Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message,
    InputMediaPhoto, InputMediaVideo, InputMediaDocument, InputMediaAudio,
)

from config import MONITOR_MODE, OWNER_ID, PROXY_MODE, TARGET_GROUP_ID
import bot_identity
import db
import group_context
import state
import config

logger = logging.getLogger(__name__)

# In-memory settings, initialized from config / DB
_settings: dict = {
    "target_group_id": TARGET_GROUP_ID,
    "monitor_mode":    MONITOR_MODE,
    "proxy_mode":      PROXY_MODE,
    "monitor_dm":      True,      # đẩy DM của người lạ gửi tới bot về owner (khi Monitor bật)
}


async def init_settings() -> None:
    """Load monitor & proxy settings from database if available."""
    all_cfg = await db.config_get_all()
    if "target_group_id" in all_cfg:
        _settings["target_group_id"] = int(all_cfg["target_group_id"])
    if "monitor_mode" in all_cfg:
        _settings["monitor_mode"] = bool(all_cfg["monitor_mode"])
    if "proxy_mode" in all_cfg:
        _settings["proxy_mode"] = bool(all_cfg["proxy_mode"])
    if "monitor_dm" in all_cfg:
        _settings["monitor_dm"] = bool(all_cfg["monitor_dm"])
    if "ai_ctx_chars" in all_cfg:
        config.AI_CTX_CHARS = max(500, min(int(all_cfg["ai_ctx_chars"]), 20000))
    if "ai_log_groups" in all_cfg:
        config.GROUP_CONTEXT_ENABLED = bool(all_cfg["ai_log_groups"])
    if "ai_ctx_msgs" in all_cfg:
        config.AI_CTX_MSGS = max(0, min(int(all_cfg["ai_ctx_msgs"]), 100))


def get_target_group_id() -> int:
    return _settings.get("target_group_id", 0)


def set_target_group_id(chat_id: int) -> None:
    _settings["target_group_id"] = chat_id
    state._fire(db.config_set("target_group_id", chat_id))


def is_monitor_on() -> bool:
    return bool(_settings.get("monitor_mode", False))


def set_monitor(enabled: bool) -> None:
    _settings["monitor_mode"] = enabled
    state._fire(db.config_set("monitor_mode", enabled))


def is_monitor_dm_on() -> bool:
    return bool(_settings.get("monitor_dm", True))


def set_monitor_dm(enabled: bool) -> None:
    _settings["monitor_dm"] = enabled
    state._fire(db.config_set("monitor_dm", enabled))


def is_proxy_on() -> bool:
    return bool(_settings.get("proxy_mode", False))


def set_proxy(enabled: bool) -> None:
    _settings["proxy_mode"] = enabled
    state._fire(db.config_set("proxy_mode", enabled))


# ─────────────────────────────────────────────────────────────
# Real-time Monitor: push group events to Owner DM
# ─────────────────────────────────────────────────────────────

def _monitor_keyboard(chat_id: int, msg_id: int, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↩️ Trả lời", callback_data=f"mon:rep:{chat_id}:{msg_id}"),
            InlineKeyboardButton("🗑️ Xóa",    callback_data=f"mon:del:{chat_id}:{msg_id}"),
        ],
        [
            InlineKeyboardButton("⚠️ Cảnh cáo", callback_data=f"mon:warn:{chat_id}:{user_id}"),
            InlineKeyboardButton("🔇 Mute 1h", callback_data=f"mon:mute:{chat_id}:{user_id}"),
        ]
    ])


async def push_group_monitor(bot: Bot, msg: Message, edited: bool = False) -> None:
    """Send real-time alert/forward of group message to Owner DM."""
    if not is_monitor_on() or not OWNER_ID:
        return
    chat = msg.chat
    if chat.type not in ("group", "supergroup"):
        return

    target = get_target_group_id()
    if target == 0 or chat.id != target:
        return          # privacy: monitor only the explicitly chosen group

    user = msg.from_user
    if user and user.id == OWNER_ID:
        return  # Do not echo owner's own messages to DM
    if bot_identity.is_self_user(user) or (user and user.id == bot.id):
        return  # Do not echo bot's own messages

    # Album (media group): gom lại gửi 1 lần thay vì N tin rời rạc
    if msg.media_group_id and not edited and (msg.photo or msg.video or msg.document or msg.audio):
        _queue_album(bot, msg)
        return

    user_name = user.full_name if user else "Unknown"
    uname = f" (@{user.username})" if (user and user.username) else ""
    ts = group_context.now_vn().strftime("%H:%M:%S %d/%m")
    tag = "✏️ [ĐÃ SỬA]" if edited else "[MONITOR]"

    header = (
        f"👁️ <b>{tag}</b> 👤 <b>{html.escape(user_name)}</b>{html.escape(uname)}"
        f"{' 🤖' if (user and user.is_bot) else ''}\n"
        f"📍 <code>{chat.title or chat.id}</code> · 🕐 {ts} · 📩 #{msg.message_id}"
    )

    kb = _monitor_keyboard(chat.id, msg.message_id, user.id if user else 0)

    try:
        if msg.text:
            text = f"{header}\n\n{html.escape(msg.text[:3000])}"
            await bot.send_message(OWNER_ID, text, parse_mode="HTML", reply_markup=kb)
        elif msg.photo:
            cap = f"{header}\n\n{html.escape(msg.caption[:800])}" if msg.caption else header
            await bot.send_photo(OWNER_ID, msg.photo[-1].file_id, caption=cap, parse_mode="HTML", reply_markup=kb)
        elif msg.video:
            cap = f"{header}\n\n{html.escape(msg.caption[:800])}" if msg.caption else header
            await bot.send_video(OWNER_ID, msg.video.file_id, caption=cap, parse_mode="HTML", reply_markup=kb)
        elif msg.sticker:
            await bot.send_message(OWNER_ID, header, parse_mode="HTML", reply_markup=kb)
            await bot.send_sticker(OWNER_ID, msg.sticker.file_id)
        elif msg.document:
            cap = f"{header}\n\n{html.escape(msg.caption[:800])}" if msg.caption else header
            await bot.send_document(OWNER_ID, msg.document.file_id, caption=cap, parse_mode="HTML", reply_markup=kb)
        elif msg.voice:
            await bot.send_voice(OWNER_ID, msg.voice.file_id, caption=header, parse_mode="HTML", reply_markup=kb)
        elif msg.audio:
            cap = f"{header}\n\n{html.escape(msg.caption[:800])}" if msg.caption else header
            await bot.send_audio(OWNER_ID, msg.audio.file_id, caption=cap, parse_mode="HTML", reply_markup=kb)
        elif msg.animation:
            cap = f"{header}\n\n{html.escape(msg.caption[:800])}" if msg.caption else header
            await bot.send_animation(OWNER_ID, msg.animation.file_id, caption=cap, parse_mode="HTML", reply_markup=kb)
        else:
            await bot.send_message(OWNER_ID, header, parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logger.warning("[monitor_proxy] push_group_monitor failed: %s", e)


# ── Album (media group) ───────────────────────────────────────
_ALBUMS: dict[str, dict] = {}


def _queue_album(bot: Bot, msg: Message) -> None:
    mg = str(msg.media_group_id)
    slot = _ALBUMS.get(mg)
    if slot is None:
        _ALBUMS[mg] = {"msgs": [msg]}
        state._fire(_flush_album(bot, mg))
    else:
        slot["msgs"].append(msg)


async def _flush_album(bot: Bot, mg: str) -> None:
    await asyncio.sleep(1.5)                      # đợi đủ ảnh/video của album
    slot = _ALBUMS.pop(mg, None)
    if not slot or not slot["msgs"]:
        return
    msgs = sorted(slot["msgs"], key=lambda m: m.message_id)
    first = msgs[0]
    chat, user = first.chat, first.from_user
    name = user.full_name if user else "Unknown"
    uname = f" (@{user.username})" if (user and user.username) else ""
    ts = group_context.now_vn().strftime("%H:%M:%S %d/%m")
    cap_text = next((m.caption for m in msgs if m.caption), "")
    header = (
        f"👁️ <b>[MONITOR · ALBUM {len(msgs)}]</b> 👤 <b>{html.escape(name)}</b>{html.escape(uname)}\n"
        f"📍 <code>{chat.title or chat.id}</code> · 🕐 {ts} · 📩 #{first.message_id}"
        + (f"\n\n{html.escape(cap_text[:600])}" if cap_text else "")
    )
    media = []
    for i, m in enumerate(msgs[:10]):
        cap = header if i == 0 else None
        kw = {"caption": cap, "parse_mode": "HTML"} if cap else {}
        if m.photo:
            media.append(InputMediaPhoto(m.photo[-1].file_id, **kw))
        elif m.video:
            media.append(InputMediaVideo(m.video.file_id, **kw))
        elif m.document:
            media.append(InputMediaDocument(m.document.file_id, **kw))
        elif m.audio:
            media.append(InputMediaAudio(m.audio.file_id, **kw))
    try:
        if media:
            await bot.send_media_group(OWNER_ID, media=media)
            await bot.send_message(
                OWNER_ID, f"⬆️ Album #{first.message_id}",
                reply_markup=_monitor_keyboard(chat.id, first.message_id, user.id if user else 0))
        else:
            await bot.send_message(OWNER_ID, header, parse_mode="HTML")
    except Exception as e:
        logger.warning("[monitor_proxy] album failed: %s", e)


# ── DM monitor: người lạ nhắn riêng cho bot → báo về owner ────
_DM_MEDIA_ATTRS = ("photo", "video", "sticker", "voice", "audio", "animation",
                   "video_note", "document", "poll", "location", "contact", "dice", "venue")


async def push_dm_monitor(bot: Bot, msg: Message, edited: bool = False) -> None:
    try:
        chat = getattr(msg, "chat", None)
        if not OWNER_ID or chat is None or chat.type != "private" or chat.id == OWNER_ID:
            return
        if not is_monitor_on() or not is_monitor_dm_on():
            return
        sender = msg.from_user
        if bot_identity.is_self_user(sender):
            return
        name = chat.full_name or chat.first_name or "?"
        uname = f" @{chat.username}" if chat.username else ""
        if bot_identity.is_other_bot(sender):
            uname += " 🤖 [BOT]"
        tag = "✏️ [DM · ĐÃ SỬA]" if edited else "📥 [DM]"
        header = (f"{tag}\n👤 {html.escape(name)}{html.escape(uname)} · id <code>{chat.id}</code>\n"
                  f"🕐 {group_context.now_vn().strftime('%H:%M %d/%m')} · #{msg.message_id}")
        text = (msg.text or msg.caption or "").strip()
        if any(getattr(msg, a, None) for a in _DM_MEDIA_ATTRS):
            await bot.send_message(OWNER_ID, header, parse_mode="HTML")
            await bot.copy_message(OWNER_ID, chat.id, msg.message_id)   # giữ nguyên media + caption
        else:
            await bot.send_message(
                OWNER_ID, f"{header}\n\n{html.escape(text[:3500])}" if text else header,
                parse_mode="HTML")
    except Exception as e:
        logger.warning("[monitor_proxy] dm monitor failed: %s", e)


async def dm_monitor_tap(update, context) -> None:
    """Handler group=-1: thấy mọi tin DM tới bot (kể cả lệnh), không chặn handler khác."""
    msg = update.effective_message
    if msg is None or msg.chat.type != "private":
        return
    state._fire(push_dm_monitor(context.bot, msg, edited=update.edited_message is not None))


# ─────────────────────────────────────────────────────────────
# Two-Way Proxy Relay: DM → Target Group
# ─────────────────────────────────────────────────────────────

async def handle_proxy_relay(bot: Bot, msg: Message) -> bool:
    """
    If Proxy is active, relay owner's DM message to the target group.
    Returns True if handled, False otherwise.
    """
    if not is_proxy_on():
        return False
    if msg.chat.type != "private":
        return False
    if not msg.from_user or msg.from_user.id != OWNER_ID:
        return False

    target = get_target_group_id()
    if not target:
        await msg.reply_text("⚠️ <b>Proxy bật nhưng chưa đặt nhóm đích!</b>\nDùng <code>/setgroup &lt;id&gt;</code> để cấu hình.", parse_mode="HTML")
        return True

    text = (msg.text or "").strip()

    # 1. reply <msg_id> <content>
    if text.lower().startswith("reply "):
        parts = text.split(None, 2)
        if len(parts) >= 3 and parts[1].isdigit():
            rep_id = int(parts[1])
            content = parts[2]
            try:
                sent = await bot.send_message(target, content, reply_to_message_id=rep_id)
                await msg.reply_text(f"✅ Đã trả lời tin #{rep_id} trong nhóm (msg_id: {sent.message_id}).", parse_mode="HTML")
                return True
            except Exception as e:
                await msg.reply_text(f"❌ Lỗi gửi reply vào nhóm: {e}")
                return True

    # 2. del <msg_id>
    if text.lower().startswith("del ") and len(text.split()) == 2 and text.split()[1].isdigit():
        del_id = int(text.split()[1])
        try:
            await bot.delete_message(target, del_id)
            await msg.reply_text(f"🗑️ Đã xóa tin #{del_id} trong nhóm.")
            return True
        except Exception as e:
            await msg.reply_text(f"❌ Lỗi xóa tin: {e}")
            return True

    # 3. edit <msg_id> <content>
    if text.lower().startswith("edit "):
        parts = text.split(None, 2)
        if len(parts) >= 3 and parts[1].isdigit():
            edit_id = int(parts[1])
            new_text = parts[2]
            try:
                await bot.edit_message_text(chat_id=target, message_id=edit_id, text=new_text)
                await msg.reply_text(f"✏️ Đã sửa tin #{edit_id} trong nhóm.")
                return True
            except Exception as e:
                await msg.reply_text(f"❌ Lỗi sửa tin: {e}")
                return True

    # 4. Normal relay (Text or Media)
    try:
        sent_any = True
        if msg.text:
            await bot.send_message(target, msg.text)
        elif msg.photo:
            await bot.send_photo(target, msg.photo[-1].file_id, caption=msg.caption)
        elif msg.video:
            await bot.send_video(target, msg.video.file_id, caption=msg.caption)
        elif msg.sticker:
            await bot.send_sticker(target, msg.sticker.file_id)
        elif msg.document:
            await bot.send_document(target, msg.document.file_id, caption=msg.caption)
        elif msg.voice:
            await bot.send_voice(target, msg.voice.file_id, caption=msg.caption)
        elif msg.audio:
            await bot.send_audio(target, msg.audio.file_id, caption=msg.caption)
        elif msg.animation:
            await bot.send_animation(target, msg.animation.file_id, caption=msg.caption)
        else:
            sent_any = False
        if sent_any:
            await msg.reply_text("✅ <i>Đã chuyển tiếp vào nhóm.</i>", parse_mode="HTML")
        else:
            await msg.reply_text("⚠️ Loại tin nhắn này chưa hỗ trợ relay.")
        return True
    except Exception as e:
        await msg.reply_text(f"❌ Lỗi relay vào nhóm: {e}")
        return True


# ─────────────────────────────────────────────────────────────
# AI Group Chat Summarizer (/tomtat)
# ─────────────────────────────────────────────────────────────

async def summarize_chat(chat_id: int, count: int = 50, lang: str = "vi") -> str:
    """Fetch recent messages and generate a structured executive summary via Gemini."""
    import agent

    rows = await db.chat_history_load(chat_id, limit=max(10, min(count, 150)))
    if not rows:
        return "Chưa có đủ lịch sử tin nhắn để tóm tắt cho nhóm này." if lang == "vi" else "Not enough message history to summarize for this chat."

    transcript_lines = []
    for r in rows:
        ts = group_context._fmt_time(r.get("ts", ""), True)
        uname = f" (@{r['username']})" if r.get("username") else ""
        transcript_lines.append(f"[{ts}] {r['name']}{uname}: {r['text']}")

    transcript = "\n".join(transcript_lines)

    is_vi = (lang == "vi")
    system_prompt = (
        "Bạn là trợ lý AI chuyên nghiệp phân tích và tóm tắt thảo luận nhóm Telegram.\n"
        "Hãy đọc biên bản trò chuyện bên dưới và tạo một bản tóm tắt súc tích, rõ ràng theo cấu trúc:\n"
        "1. 📌 TỔNG QUAN: (Tóm tắt trong 2-3 câu về chủ đề chính mà nhóm đang bàn luận)\n"
        "2. ⏱️ DIỄN BIẾN CHÍNH: (Các ý kiến, cuộc trò chuyện hoặc sự kiện nổi bật theo trình tự thời gian)\n"
        "3. 💡 KẾT LUẬN / ĐÁNG CHÚ Ý: (Các quyết định đã thống nhất, câu hỏi còn bỏ ngỏ hoặc việc cần làm)\n"
        "Dùng định dạng HTML hoặc Markdown rõ ràng."
        if is_vi else
        "You are an executive AI assistant summarizing Telegram group chat logs.\n"
        "Analyze the transcript and provide a structured summary:\n"
        "1. 📌 OVERVIEW: (2-3 sentences on the main discussion)\n"
        "2. ⏱️ KEY DEVELOPMENTS: (Timeline of significant points and events)\n"
        "3. 💡 ACTION ITEMS / HIGHLIGHTS: (Decisions made, open questions, or important notes)"
    )

    prompt = (
        f"Dưới đây là {len(rows)} tin nhắn gần nhất trong nhóm:\n\n{transcript}\n\nHãy tóm tắt nội dung trên."
        if is_vi else
        f"Below are the {len(rows)} most recent messages in the group:\n\n{transcript}\n\nPlease summarize them."
    )

    summary, _ = await agent.run_agent(
        tg_ctx        = None,
        user_text     = prompt,
        history       = [],
        system_prompt = system_prompt,
        use_plugins   = False,
        enable_grounding = False,     # tóm tắt chỉ dựa trên transcript — không search/không đọc link trong nhóm
    )
    return summary or ("Không thể tạo tóm tắt." if is_vi else "Unable to generate summary.")
