"""
Telegram event handlers:
  - handle_message  : text messages (with accumulation / merge)
  - handle_callback : inline-button presses (follow-up questions)
"""
from __future__ import annotations

import asyncio
import logging
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
from config import ENABLE_FOLLOWUP, FOLLOWUP_COUNT, MESSAGE_MERGE_DELAY, ENABLE_PLUGINS
from tools_telegram import TelegramContext, TOOL_STATUS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _make_tg_ctx(
    bot,
    chat_id:   int,
    user_id:   int,
    message_id: int,
    thread_id:  Optional[int],
    chat_title: str,
    user_name:  str,
) -> TelegramContext:
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


async def _send_chunks(
    bot,
    chat_id:        int,
    text:           str,
    thread_id:      Optional[int],
    reply_to_id:    Optional[int],
    follow_ups:     list[str],
):
    """Split text into Telegram-safe parts and send with optional follow-up keyboard."""
    chunks = utils.split_message(text)
    for i, chunk in enumerate(chunks):
        keyboard = None
        if i == len(chunks) - 1 and follow_ups:
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(q, callback_data=f"fu:{q[:200]}")]
                for q in follow_ups
            ])
        try:
            await bot.send_message(
                chat_id             = chat_id,
                text                = chunk,
                message_thread_id   = thread_id,
                reply_to_message_id = reply_to_id if i == 0 else None,
                reply_markup        = keyboard,
            )
        except Exception as e:
            logger.error("send_chunks: %s", e)


# ─────────────────────────────────────────────────────────────
# Core conversation processor
# ─────────────────────────────────────────────────────────────
async def _process(
    bot,
    chat_id:    int,
    user_id:    int,
    message_id: int,
    thread_id:  Optional[int],
    is_private: bool,
    chat_title: str,
    user_name:  str,
    text:       str,
    reply_to_id: Optional[int] = None,
):
    cid = state.conv_id(
        chat_id, user_id, thread_id, is_private,
        state.topic_mode(chat_id),
    )
    cfg  = state.get_cfg(cid)
    model_pref  = cfg.get("model")
    use_plugins = cfg.get("plugins", ENABLE_PLUGINS)
    custom_sys  = cfg.get("system_prompt")

    tg_ctx = _make_tg_ctx(
        bot, chat_id, user_id, message_id,
        thread_id, chat_title, user_name,
    )
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

    # Callback to update status message with current tool
    async def status_cb(tool_name: str):
        label = TOOL_STATUS.get(tool_name, f"⚙️ {tool_name}…")
        if status_msg:
            try:
                await status_msg.edit_text(label)
            except Exception:
                pass

    # Typing indicator (runs in parallel)
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
        logger.error("run_agent: %s", e, exc_info=True)
        response = f"❌ Lỗi xử lý: {e}"
    finally:
        typing_task.cancel()
        if status_msg:
            try:
                await status_msg.delete()
            except Exception:
                pass

    # Persist history (only text turns)
    state.push(cid, "user",  text)
    state.push(cid, "model", response)

    # Follow-up questions (parallel)
    follow_ups: list[str] = []
    if ENABLE_FOLLOWUP:
        try:
            follow_ups = await generate_followup(
                state.get_history(cid), response, FOLLOWUP_COUNT
            )
        except Exception:
            pass

    await _send_chunks(
        bot, chat_id, response, thread_id, reply_to_id, follow_ups
    )


# ─────────────────────────────────────────────────────────────
# Message accumulation + delayed dispatch
# ─────────────────────────────────────────────────────────────
async def _delayed_dispatch(
    bot,
    accu_key:   str,
    chat_id:    int,
    user_id:    int,
    message_id: int,
    thread_id:  Optional[int],
    is_private: bool,
    chat_title: str,
    user_name:  str,
    reply_to_id: Optional[int],
):
    await asyncio.sleep(MESSAGE_MERGE_DELAY)
    msgs = state.pending_texts.pop(accu_key, [])
    if not msgs:
        return
    merged = utils.merge(msgs)
    await _process(
        bot, chat_id, user_id, message_id, thread_id,
        is_private, chat_title, user_name, merged, reply_to_id,
    )


# ─────────────────────────────────────────────────────────────
# Main message handler
# ─────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg or not msg.text:
        return

    user = update.effective_user
    chat = update.effective_chat

    # Access control
    if not state.allowed(user.id):
        return

    bot_username = context.bot.username
    is_private   = chat.type == ChatType.PRIVATE
    is_reply     = (
        msg.reply_to_message
        and msg.reply_to_message.from_user
        and msg.reply_to_message.from_user.id == context.bot.id
    )
    is_mentioned = f"@{bot_username}" in (msg.text or "")

    if not (is_private or is_reply or is_mentioned):
        return

    text = msg.text
    if is_mentioned:
        text = text.replace(f"@{bot_username}", "").strip()
    if not text:
        return

    thread_id    = getattr(msg, "message_thread_id", None)
    reply_to_id  = msg.message_id
    accu_key     = f"{chat.id}:{user.id}"
    chat_title   = getattr(chat, "title", None) or chat.effective_name or "Chat"
    user_name    = user.full_name or str(user.id)

    # Also include replied-to message content as context
    if msg.reply_to_message and msg.reply_to_message.text:
        rtext = msg.reply_to_message.text[:500]
        ruser = (msg.reply_to_message.from_user.full_name
                 if msg.reply_to_message.from_user else "Unknown")
        text = f"[Reply to {ruser}: \"{rtext}\"]\n{text}"

    state.pending_texts[accu_key].append(text)

    # Cancel existing timer and restart
    if accu_key in state.pending_tasks:
        state.pending_tasks[accu_key].cancel()

    task = asyncio.create_task(
        _delayed_dispatch(
            context.bot,
            accu_key,
            chat.id,
            user.id,
            msg.message_id,
            thread_id,
            is_private,
            chat_title,
            user_name,
            reply_to_id,
        )
    )
    state.pending_tasks[accu_key] = task


# ─────────────────────────────────────────────────────────────
# Callback handler (inline follow-up buttons)
# ─────────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()

    data = query.data or ""
    if not data.startswith("fu:"):
        return

    question = data[3:]
    user     = query.from_user
    if not state.allowed(user.id):
        return

    msg       = query.message
    chat      = update.effective_chat
    thread_id = getattr(msg, "message_thread_id", None)
    is_private= chat.type == ChatType.PRIVATE

    # Remove keyboard from original message
    try:
        await query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass

    # Echo the chosen question visually
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
        chat.id,
        user.id,
        msg.message_id,
        thread_id,
        is_private,
        chat_title,
        user_name,
        question,
    )
