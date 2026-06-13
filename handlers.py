"""
Telegram event handlers:
  - handle_message  : text + ảnh + file + audio + video + sticker + voice
  - handle_callback : inline-button presses (follow-up + model selection)

Nâng cấp:
  [CTX] Đọc TẤT CẢ tin nhắn trong group (kể cả người khác) làm context.
        Chỉ trigger AI khi: private chat / reply bot / mention / owner.
  [FILE] Hỗ trợ nhận dạng và lưu context cho document/audio/video/sticker.
  [EDIT] tg_edit_message tự fallback sang edit_message_caption cho media msg.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time as _time
from typing import Optional

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import ContextTypes

from datetime import datetime, timezone
import state
from state import FeedEntry
import utils
from agent import build_system_prompt, generate_followup, run_agent
from i18n import t
from config import DEFAULT_LANG
from config import (
    ENABLE_FOLLOWUP,
    ENABLE_PLUGINS,
    FOLLOWUP_COUNT,
    GROUP_CONTEXT_ENABLED,
    MESSAGE_MERGE_DELAY,
    MODELS,
    OWNER_ID,
)
from tools_telegram import TelegramContext, TOOL_STATUS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Follow-up question cache
# ─────────────────────────────────────────────────────────────
_fq_cache:  dict[str, list[str]] = {}
_fq_expiry: dict[str, float]     = {}
_FQ_TTL = 7200


def _fq_store(questions: list[str]) -> str:
    key = hashlib.md5(f"{_time.monotonic()}".encode()).hexdigest()[:10]
    _fq_cache[key]  = questions
    _fq_expiry[key] = _time.monotonic() + _FQ_TTL
    now = _time.monotonic()
    for k in [k for k, t in _fq_expiry.items() if now > t]:
        _fq_cache.pop(k, None)
        _fq_expiry.pop(k, None)
    return key


def _fq_get(key: str, idx: int) -> str | None:
    qs = _fq_cache.get(key)
    if qs is None or idx >= len(qs):
        return None
    return qs[idx]


# ─────────────────────────────────────────────────────────────
# Model label map
# ─────────────────────────────────────────────────────────────
_MODEL_LABELS: dict[str, str] = {
    "gemini-3.1-flash-lite":               "3.1 Flash Lite ⚡ (mặc định)",
    "gemini-3.5-flash":                    "3.5 Flash 🌟",
    "gemini-3-flash-preview":              "3 Flash Preview 🔭",
    "gemini-2.5-flash":                    "2.5 Flash 🚀",
    "gemini-2.5-flash-lite-preview-06-17": "2.5 Flash Lite 🪶",
    "gemini-2.0-flash":                    "2.0 Flash 💨",
    "gemini-2.0-flash-lite":               "2.0 Flash Lite 💤",
    "gemini-1.5-pro":                      "1.5 Pro 🧠",
    "gemini-1.5-flash":                    "1.5 Flash ✨",
    "gemini-1.5-flash-8b":                 "1.5 Flash 8B 🌩️",
}


# ─────────────────────────────────────────────────────────────
# Message text extractor  (text / photo / document / audio / video / sticker)
# ─────────────────────────────────────────────────────────────

def _extract_text(msg: Message, bot_username: str) -> Optional[str]:
    """
    Lấy nội dung text từ mọi loại tin nhắn.
    Trả về None nếu không xử lý được.
    """
    mention = f"@{bot_username}"

    if msg.text:
        return msg.text.replace(mention, "").strip() or None

    caption = (msg.caption or "").replace(mention, "").strip()

    if msg.photo:
        photo = msg.photo[-1]
        base = f"[📸 ảnh — file_id: {photo.file_id}]"
        return f"{caption}\n{base}" if caption else base

    if msg.document:
        d    = msg.document
        name = d.file_name or "file"
        base = f"[📎 file: {name} ({_fmt_size(d.file_size)}) — file_id: {d.file_id}]"
        return f"{caption}\n{base}" if caption else base

    if msg.audio:
        a    = msg.audio
        name = a.file_name or a.title or "audio"
        base = f"[🎵 audio: {name} ({_fmt_size(a.file_size)}) — file_id: {a.file_id}]"
        return f"{caption}\n{base}" if caption else base

    if msg.video:
        v    = msg.video
        name = v.file_name or "video"
        base = f"[🎬 video: {name} ({_fmt_size(v.file_size)}) — file_id: {v.file_id}]"
        return f"{caption}\n{base}" if caption else base

    if msg.voice:
        base = f"[🎤 voice message ({_fmt_size(msg.voice.file_size)}) — file_id: {msg.voice.file_id}]"
        return base

    if msg.video_note:
        base = f"[📹 video note — file_id: {msg.video_note.file_id}]"
        return base

    if msg.sticker:
        s    = msg.sticker
        emoji = s.emoji or ""
        base  = f"[🎭 sticker {emoji} — file_id: {s.file_id}]"
        return base

    if msg.animation:
        base = f"[🎬 GIF/animation — file_id: {msg.animation.file_id}]"
        return f"{caption}\n{base}" if caption else base

    return None


def _fmt_size(size_bytes: Optional[int]) -> str:
    if not size_bytes:
        return "?"
    if size_bytes < 1024:
        return f"{size_bytes}B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes // 1024}KB"
    return f"{size_bytes // 1024 // 1024}MB"


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _make_tg_ctx(bot, chat_id, user_id, message_id, thread_id,
                 chat_title, user_name) -> TelegramContext:
    return TelegramContext(
        bot        = bot,
        chat_id    = chat_id,
        user_id    = user_id,
        message_id = message_id,
        thread_id  = thread_id,
        chat_title = chat_title,
        user_name  = user_name,
    )


async def _keep_typing(bot, chat_id: int, thread_id: Optional[int]):
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Send chunks (MD→HTML, optional keyboard on last chunk)
# ─────────────────────────────────────────────────────────────

async def _send_chunks(
    bot,
    chat_id:     int,
    text:        str,
    thread_id:   Optional[int],
    reply_to_id: Optional[int],
    keyboard:    Optional[InlineKeyboardMarkup] = None,
) -> list[Message]:
    chunks = utils.split_message(text)
    sent:   list[Message] = []
    for i, chunk in enumerate(chunks):
        kb = keyboard if (i == len(chunks) - 1) else None
        try:
            msg = await bot.send_message(
                chat_id             = chat_id,
                text                = utils.md_to_html(chunk),
                parse_mode          = "HTML",
                message_thread_id   = thread_id,
                reply_to_message_id = reply_to_id if i == 0 else None,
                reply_markup        = kb,
            )
            sent.append(msg)
        except Exception as e:
            logger.error("send_chunks: %s", e)
    return sent


# ─────────────────────────────────────────────────────────────
# Background follow-up attach
# ─────────────────────────────────────────────────────────────

async def _attach_followup(last_msg: Message, history: list, response: str, lang: str = DEFAULT_LANG):
    try:
        follow_ups = await generate_followup(history, response, FOLLOWUP_COUNT, lang=lang)
        if not follow_ups:
            return
        cache_key = _fq_store(follow_ups)
        keyboard  = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                q[:60] + ("…" if len(q) > 60 else ""),
                callback_data=f"fu:{cache_key}:{i}",
            )]
            for i, q in enumerate(follow_ups)
        ])
        await last_msg.edit_reply_markup(reply_markup=keyboard)
    except Exception as e:
        logger.debug("_attach_followup: %s", e)


# ─────────────────────────────────────────────────────────────
# Core conversation processor
# ─────────────────────────────────────────────────────────────

async def _process(
    bot,
    chat_id:     int,
    user_id:     int,
    message_id:  int,
    thread_id:   Optional[int],
    is_private:  bool,
    chat_title:  str,
    user_name:   str,
    text:        str,
    reply_to_id: Optional[int] = None,
):
    cid         = state.conv_id(chat_id, user_id, thread_id, is_private,
                                state.topic_mode(chat_id))
    cfg         = state.get_cfg(cid)
    lang        = cfg.get("lang", DEFAULT_LANG)
    model_pref  = cfg.get("model")
    use_plugins = cfg.get("plugins", ENABLE_PLUGINS)
    custom_sys  = cfg.get("system_prompt")

    tg_ctx        = _make_tg_ctx(bot, chat_id, user_id, message_id,
                                 thread_id, chat_title, user_name)
    system_prompt = custom_sys or build_system_prompt(tg_ctx, lang=lang)
    history       = state.get_history(cid)

    status_msg: Optional[Message] = None
    try:
        status_msg = await bot.send_message(
            chat_id           = chat_id,
            text              = t("processing", lang),
            message_thread_id = thread_id,
        )
    except Exception:
        pass

    async def status_cb(tool_name: str):
        label = TOOL_STATUS.get(tool_name, f"⚙️ {tool_name}…")
        if status_msg:
            try:
                await status_msg.edit_text(label)
            except Exception:
                pass

    typing_task = asyncio.create_task(_keep_typing(bot, chat_id, thread_id))

    try:
        response = await run_agent(
            tg_ctx        = tg_ctx,
            user_text     = text,
            history       = history,
            system_prompt = system_prompt,
            model         = model_pref,
            use_plugins   = use_plugins,
            status_cb     = status_cb,
        )
    except Exception as e:
        logger.error("run_agent error: %s", e, exc_info=True)
        response = t("error.agent", lang)
    finally:
        typing_task.cancel()
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

    # Lưu lịch sử: dùng [Name]: text cho group để nhất quán với push_context
    user_entry = f"[{user_name}]: {text}" if not is_private else text
    state.push(cid, "user",  user_entry)
    state.push(cid, "model", response)

    sent = await _send_chunks(bot, chat_id, response, thread_id, reply_to_id)

    if ENABLE_FOLLOWUP and sent:
        asyncio.create_task(
            _attach_followup(sent[-1], state.get_history(cid), response, lang=lang)
        )


# ─────────────────────────────────────────────────────────────
# Message accumulation + delayed dispatch
# ─────────────────────────────────────────────────────────────

async def _delayed_dispatch(
    bot, accu_key, chat_id, user_id, message_id,
    thread_id, is_private, chat_title, user_name, reply_to_id,
):
    try:
        await asyncio.sleep(MESSAGE_MERGE_DELAY)
        msgs = state.pending_texts.pop(accu_key, [])
        if not msgs:
            return
        merged = utils.merge(msgs)
        await _process(bot, chat_id, user_id, message_id, thread_id,
                       is_private, chat_title, user_name, merged, reply_to_id)
    finally:
        # Only drop our own task reference — a newer message may have
        # already replaced it with a fresh task in state.pending_tasks.
        if state.pending_tasks.get(accu_key) is asyncio.current_task():
            state.pending_tasks.pop(accu_key, None)


def _build_accu_key(chat_id: int, user_id: int, thread_id: Optional[int]) -> str:
    return f"{chat_id}:{user_id}:{thread_id or 0}"


# ─────────────────────────────────────────────────────────────
# Main message handler
# Hỗ trợ: text, photo, document, audio, video, voice, sticker, animation
# ─────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg:
        return

    user = update.effective_user
    chat = update.effective_chat
    if not user:
        return

    bot_username = context.bot.username
    is_private   = chat.type == ChatType.PRIVATE

    # ── Xác định xem có trigger AI không ──────────────────────
    is_reply_to_bot = (
        msg.reply_to_message is not None
        and msg.reply_to_message.from_user is not None
        and msg.reply_to_message.from_user.id == context.bot.id
    )
    raw_text     = msg.text or msg.caption or ""
    is_mentioned = f"@{bot_username}" in raw_text
    is_owner     = (user.id == OWNER_ID)

    # ── Auth: chỉ owner mới được interact ───────────────────────
    # Người khác → chỉ lưu context (nếu bật), không bao giờ reply
    if not is_owner:
        text = _extract_text(msg, bot_username)
        if text is not None and not is_private and GROUP_CONTEXT_ENABLED:
            thread_id = getattr(msg, "message_thread_id", None)
            user_name = user.full_name or str(user.id)
            cid = state.conv_id(chat.id, user.id, thread_id, is_private,
                                state.topic_mode(chat.id))
            state.push_context(cid, user_name, text)
            # ── Feed buffer: lưu tất cả tin nhóm để /feed xem lại ─
            username = f"@{user.username}" if user.username else ""
            state.feed_push(FeedEntry(
                chat_id   = chat.id,
                msg_id    = msg.message_id,
                date      = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date,
                user_id   = user.id,
                user_name = user_name,
                username  = username,
                text      = text,
            ))
        return  # non-owner → dừng, không reply

    # ── Owner: chỉ reply khi ping/reply bot (trong nhóm) ──────
    should_respond = is_private or is_reply_to_bot or is_mentioned

    # ── Lấy nội dung tin nhắn ─────────────────────────────────
    text = _extract_text(msg, bot_username)
    if text is None:
        return

    thread_id   = getattr(msg, "message_thread_id", None)
    user_name   = user.full_name or str(user.id)
    chat_title  = getattr(chat, "title", None) or chat.effective_name or "Chat"

    # ── [CTX] Lưu context tin nhắn owner không trigger ────────
    if not is_private and GROUP_CONTEXT_ENABLED and not should_respond:
        cid = state.conv_id(chat.id, user.id, thread_id, is_private,
                            state.topic_mode(chat.id))
        state.push_context(cid, user_name, text)
        return  # Không respond → dừng tại đây

    if not should_respond:
        return

    # ── Thêm nội dung replied-to message làm prefix ───────────
    if msg.reply_to_message:
        rtext = (msg.reply_to_message.text or msg.reply_to_message.caption or "")[:500]
        if rtext:
            ruser = (msg.reply_to_message.from_user.full_name
                     if msg.reply_to_message.from_user else "Unknown")
            text = f'[Reply to {ruser}: "{rtext}"]\n{text}'

    # ── Bỏ @mention khỏi text ─────────────────────────────────
    text = text.replace(f"@{bot_username}", "").strip()
    if not text:
        return

    reply_to_id = msg.message_id
    accu_key    = _build_accu_key(chat.id, user.id, thread_id)

    state.pending_texts[accu_key].append(text)

    if accu_key in state.pending_tasks:
        state.pending_tasks[accu_key].cancel()

    task = asyncio.create_task(
        _delayed_dispatch(
            context.bot, accu_key,
            chat.id, user.id, msg.message_id,
            thread_id, is_private, chat_title, user_name, reply_to_id,
        )
    )
    state.pending_tasks[accu_key] = task


# ─────────────────────────────────────────────────────────────
# Callback handler (follow-up buttons + model selection)
# ─────────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or update.effective_user.id != OWNER_ID:
        return
    await query.answer()

    data = query.data or ""
    msg  = query.message
    chat = update.effective_chat

    # ── Model selection ───────────────────────────────────────
    if data.startswith("setmodel:"):
        model_name = data[9:]
        if model_name not in MODELS:
            return
        thread_id = getattr(msg, "message_thread_id", None)
        is_priv   = chat.type == ChatType.PRIVATE
        cid       = state.conv_id(chat.id, OWNER_ID, thread_id, is_priv,
                                  state.topic_mode(chat.id))
        # get lang for this conv
        thread_id = getattr(msg, "message_thread_id", None)
        is_priv   = chat.type == ChatType.PRIVATE
        cid       = state.conv_id(chat.id, OWNER_ID, thread_id, is_priv,
                                  state.topic_mode(chat.id))
        state.set_cfg(cid, model=model_name)
        _lang = state.get_cfg(cid).get("lang", DEFAULT_LANG)
        label = _MODEL_LABELS.get(model_name, model_name)
        try:
            await query.edit_message_text(
                t("model.switched", _lang, label=label),
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ── Feed actions ─────────────────────────────────────────
    if data.startswith("fd:"):
        await _handle_feed_action(query, context, data)
        return

    # ── Follow-up questions ───────────────────────────────────
    if data.startswith("fu:"):
        parts = data.split(":", 2)
        if len(parts) != 3:
            return
        _, cache_key, idx_str = parts
        try:
            question = _fq_get(cache_key, int(idx_str))
        except (ValueError, TypeError):
            question = None
        if not question:
            # Get lang for expired followup message
            _fc_chat = query.message.chat if query.message else None
            _fc_tid  = getattr(query.message, "message_thread_id", None) if query.message else None
            _fc_priv = (_fc_chat.type == ChatType.PRIVATE) if _fc_chat else True
            _fc_cid  = state.conv_id(_fc_chat.id if _fc_chat else 0, OWNER_ID,
                                     _fc_tid, _fc_priv, False)
            _fc_lang = state.get_cfg(_fc_cid).get("lang", DEFAULT_LANG)
            await query.answer(
                "❌ Question expired." if _fc_lang == "en" else "❌ Câu hỏi đã hết hạn.",
                show_alert=True
            )
            return

        user      = query.from_user
        thread_id = getattr(msg, "message_thread_id", None)
        is_priv   = chat.type == ChatType.PRIVATE

        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except Exception:
            pass

        try:
            await context.bot.send_message(
                chat_id           = chat.id,
                text              = f"❓ {user.first_name}: {question}",
                message_thread_id = thread_id,
            )
        except Exception:
            pass

        chat_title = getattr(chat, "title", None) or chat.effective_name or "Chat"
        user_name  = user.full_name or str(user.id)

        await _process(
            context.bot,
            chat.id, user.id, msg.message_id,
            thread_id, is_priv, chat_title, user_name, question,
        )


# ─────────────────────────────────────────────────────────────
# Feed action handler
# callback_data format: "fd:{action}:{chat_id}:{msg_id_or_user_id}"
# ─────────────────────────────────────────────────────────────
async def _handle_feed_action(
    query: "CallbackQuery",
    context: ContextTypes.DEFAULT_TYPE,
    data: str,
) -> None:
    from datetime import datetime, timezone
    from telegram import ChatPermissions

    parts = data.split(":")
    if len(parts) != 4:
        await query.answer("❌ Dữ liệu không hợp lệ.")
        return

    _, action, raw_cid, raw_id = parts
    try:
        chat_id = int(raw_cid)
        tgt_id  = int(raw_id)
    except ValueError:
        await query.answer("❌ ID không hợp lệ.")
        return

    bot = context.bot

    # ── del ──────────────────────────────────────────────────
    if action == "del":
        try:
            await bot.delete_message(chat_id=chat_id, message_id=tgt_id)
            await query.answer("🗑️ Đã xóa.")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)

    # ── pin ──────────────────────────────────────────────────
    elif action == "pin":
        try:
            await bot.pin_chat_message(chat_id=chat_id, message_id=tgt_id,
                                        disable_notification=True)
            await query.answer("📌 Đã ghim.")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)

    # ── rep (reply context) ───────────────────────────────────
    elif action == "rep":
        # Post a prompt message so the owner knows to reply
        try:
            await bot.send_message(
                chat_id    = chat_id,
                text       = f"↩️ Reply tới tin nhắn <code>#{tgt_id}</code> — nhắn AI để compose trả lời.",
                parse_mode = "HTML",
                reply_to_message_id = tgt_id,
            )
            await query.answer("↩️ Đã set reply context.")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)

    # ── warn ─────────────────────────────────────────────────
    elif action == "warn":
        count = state.warn_add(chat_id, tgt_id)
        max_w = state.get_max_warns()
        msg_text = f"⚠️ User <code>{tgt_id}</code>: {count}/{max_w} cảnh cáo."
        if count >= max_w:
            try:
                await bot.ban_chat_member(chat_id=chat_id, user_id=tgt_id)
                state.warn_reset(chat_id, tgt_id)
                msg_text += f"\n🚫 Đạt max → đã BAN."
            except Exception as e:
                msg_text += f"\n❌ Auto-ban thất bại: {e}"
        await query.answer(f"⚠️ Warn {count}/{max_w}")
        try:
            await bot.send_message(chat_id=chat_id, text=msg_text, parse_mode="HTML")
        except Exception:
            pass

    # ── mute ─────────────────────────────────────────────────
    elif action == "mute":
        until = datetime.now(tz=timezone.utc) + __import__("datetime").timedelta(hours=1)
        perms = ChatPermissions(can_send_messages=False)
        try:
            await bot.restrict_chat_member(
                chat_id=chat_id, user_id=tgt_id, permissions=perms, until_date=until
            )
            await query.answer("🔇 Muted 1h.")
            await bot.send_message(chat_id=chat_id,
                                    text=f"🔇 Đã mute <code>{tgt_id}</code> 1h.",
                                    parse_mode="HTML")
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)

    # ── ban ───────────────────────────────────────────────────
    elif action == "ban":
        try:
            await bot.ban_chat_member(chat_id=chat_id, user_id=tgt_id)
            await query.answer("🚫 Banned.")
            await bot.send_message(chat_id=chat_id,
                                    text=f"🚫 Đã ban <code>{tgt_id}</code>.",
                                    parse_mode="HTML")
            try:
                await query.edit_message_reply_markup(reply_markup=None)
            except Exception:
                pass
        except Exception as e:
            await query.answer(f"❌ {e}", show_alert=True)

    else:
        await query.answer("❌ Action không xác định.")
