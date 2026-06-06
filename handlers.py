"""
Telegram event handlers:
  - handle_message  : text + photo messages (with accumulation / merge)
  - handle_callback : inline-button presses (follow-up + model selection)
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

import state
import utils
from agent import build_system_prompt, generate_followup, run_agent
from config import (
    ENABLE_FOLLOWUP,
    ENABLE_PLUGINS,
    FOLLOWUP_COUNT,
    MESSAGE_MERGE_DELAY,
    MODELS,
    OWNER_ID,
)
from tools_telegram import TelegramContext, TOOL_STATUS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Follow-up question cache  (#3 — fix callback_data overflow)
# Key: 10-char hex  →  list[str]   (TTL 2h)
# ─────────────────────────────────────────────────────────────
_fq_cache:  dict[str, list[str]] = {}
_fq_expiry: dict[str, float]     = {}
_FQ_TTL = 7200  # seconds


def _fq_store(questions: list[str]) -> str:
    key = hashlib.md5(f"{_time.monotonic()}".encode()).hexdigest()[:10]
    _fq_cache[key]  = questions
    _fq_expiry[key] = _time.monotonic() + _FQ_TTL
    # Evict expired keys
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
# Model label map  (for inline keyboard #10)
# ─────────────────────────────────────────────────────────────
_MODEL_LABELS: dict[str, str] = {
    "gemini-3.1-flash-lite":            "3.1 Flash Lite ⚡ (mặc định)",
    "gemini-3.5-flash":                 "3.5 Flash 🌟",
    "gemini-3-flash-preview":           "3 Flash Preview 🔭",
    "gemini-2.5-flash":                 "2.5 Flash 🚀",
    "gemini-2.5-flash-lite-preview-06-17": "2.5 Flash Lite 🪶",
    "gemini-2.0-flash":                 "2.0 Flash 💨",
    "gemini-2.0-flash-lite":            "2.0 Flash Lite 💤",
    "gemini-1.5-pro":                   "1.5 Pro 🧠",
    "gemini-1.5-flash":                 "1.5 Flash ✨",
    "gemini-1.5-flash-8b":              "1.5 Flash 8B 🌩️",
}


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
    """Send 'typing…' every 4 s until cancelled."""
    try:
        while True:
            await bot.send_chat_action(chat_id=chat_id, action="typing")
            await asyncio.sleep(4)
    except asyncio.CancelledError:
        pass
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Send chunks  (#4 HTML, #3 keyboard, #5 returns list[Message])
# ─────────────────────────────────────────────────────────────
async def _send_chunks(
    bot,
    chat_id:      int,
    text:         str,
    thread_id:    Optional[int],
    reply_to_id:  Optional[int],
    keyboard:     Optional[InlineKeyboardMarkup] = None,
) -> list[Message]:
    """Split text, convert MD→HTML, send with optional keyboard on last chunk."""
    chunks = utils.split_message(text)
    sent: list[Message] = []
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
# Background follow-up attach  (#5 — send first, attach later)
# ─────────────────────────────────────────────────────────────
async def _attach_followup(last_msg: Message, history: list, response: str):
    """Runs in background: generate follow-ups then edit last message to attach keyboard."""
    try:
        follow_ups = await generate_followup(history, response, FOLLOWUP_COUNT)
        if not follow_ups:
            return
        cache_key = _fq_store(follow_ups)
        keyboard  = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                q[:60] + ("…" if len(q) > 60 else ""),
                callback_data=f"fu:{cache_key}:{i}",   # ~18 bytes ✅
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
    model_pref  = cfg.get("model")
    use_plugins = cfg.get("plugins", ENABLE_PLUGINS)
    custom_sys  = cfg.get("system_prompt")

    tg_ctx        = _make_tg_ctx(bot, chat_id, user_id, message_id,
                                 thread_id, chat_title, user_name)
    system_prompt = custom_sys or build_system_prompt(tg_ctx)
    history       = state.get_history(cid)

    # Status message
    status_msg: Optional[Message] = None
    try:
        status_msg = await bot.send_message(
            chat_id           = chat_id,
            text              = "⏳ Đang xử lý…",
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
        response = "❌ Có lỗi xảy ra khi xử lý. Thử lại nhé."   # #7 — no leak
    finally:
        typing_task.cancel()
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

    state.push(cid, "user",  text)
    state.push(cid, "model", response)

    # 1. Send response immediately (#5)
    sent = await _send_chunks(bot, chat_id, response, thread_id, reply_to_id)

    # 2. Generate follow-ups in background (#5)
    if ENABLE_FOLLOWUP and sent:
        asyncio.create_task(
            _attach_followup(sent[-1], state.get_history(cid), response)
        )


# ─────────────────────────────────────────────────────────────
# Message accumulation + delayed dispatch
# ─────────────────────────────────────────────────────────────
async def _delayed_dispatch(
    bot, accu_key, chat_id, user_id, message_id,
    thread_id, is_private, chat_title, user_name, reply_to_id,
):
    await asyncio.sleep(MESSAGE_MERGE_DELAY)
    msgs = state.pending_texts.pop(accu_key, [])
    if not msgs:
        return
    merged = utils.merge(msgs)
    await _process(bot, chat_id, user_id, message_id, thread_id,
                   is_private, chat_title, user_name, merged, reply_to_id)


def _build_accu_key(chat_id: int, user_id: int, thread_id: Optional[int]) -> str:
    return f"{chat_id}:{user_id}:{thread_id or 0}"   # #6 — include thread_id


# ─────────────────────────────────────────────────────────────
# Main message handler (text + photo)
# ─────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg:
        return

    user = update.effective_user
    chat = update.effective_chat

    # Auth: owner only (#0)
    if user.id != OWNER_ID:
        return

    bot_username = context.bot.username
    is_private   = chat.type == ChatType.PRIVATE
    is_reply     = (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.id == context.bot.id
    )
    is_mentioned = f"@{bot_username}" in (msg.text or msg.caption or "")

    if not (is_private or is_reply or is_mentioned):
        return

    # Build text from message (text or photo+caption)
    if msg.photo:
        # Photo message — describe it for the AI
        caption = msg.caption or ""
        if is_mentioned:
            caption = caption.replace(f"@{bot_username}", "").strip()
        # Use the largest photo
        photo = msg.photo[-1]
        text = f"[User đã gửi ảnh, file_id: {photo.file_id}]"
        if caption:
            text = f"{caption}\n{text}"
        if not caption and not is_private:
            return  # no caption in group = ignore
    elif msg.text:
        text = msg.text
        if is_mentioned:
            text = text.replace(f"@{bot_username}", "").strip()
        if not text:
            return
    else:
        return

    thread_id   = getattr(msg, "message_thread_id", None)
    reply_to_id = msg.message_id
    accu_key    = _build_accu_key(chat.id, user.id, thread_id)   # #6
    chat_title  = getattr(chat, "title", None) or chat.effective_name or "Chat"
    user_name   = user.full_name or str(user.id)

    # Include replied-to message content as context
    if msg.reply_to_message and msg.reply_to_message.text:
        rtext = msg.reply_to_message.text[:500]
        ruser = (msg.reply_to_message.from_user.full_name
                 if msg.reply_to_message.from_user else "Unknown")
        text = f'[Reply to {ruser}: "{rtext}"]\n{text}'

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

    # ── Model selection (#10) ─────────────────────────────────
    if data.startswith("setmodel:"):
        model_name = data[9:]
        if model_name not in MODELS:
            return
        thread_id  = getattr(msg, "message_thread_id", None)
        is_priv    = chat.type == ChatType.PRIVATE
        cid        = state.conv_id(chat.id, OWNER_ID, thread_id, is_priv,
                                   state.topic_mode(chat.id))
        state.set_cfg(cid, model=model_name)
        label = _MODEL_LABELS.get(model_name, model_name)
        try:
            await query.edit_message_text(
                f"✅ Đã chuyển sang <b>{label}</b>",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return

    # ── Follow-up questions (#3) ──────────────────────────────
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
            await query.answer("❌ Câu hỏi đã hết hạn.", show_alert=True)
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
