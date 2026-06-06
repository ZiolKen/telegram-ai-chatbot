"""
Slash-command handlers.
Auth: OWNER_ID only — all other users are silently ignored (#0).
"""
from __future__ import annotations

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import state
import utils
import db
from config import DEFAULT_MODEL, ENABLE_FOLLOWUP, ENABLE_PLUGINS, MODELS, OWNER_ID
from handlers import _MODEL_LABELS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _get_conv_id(update: Update) -> str:
    user      = update.effective_user
    chat      = update.effective_chat
    msg       = update.message
    thread_id = getattr(msg, "message_thread_id", None) if msg else None
    is_priv   = chat.type == ChatType.PRIVATE
    return state.conv_id(chat.id, user.id, thread_id, is_priv,
                         state.topic_mode(chat.id))


async def _reply(update: Update, text: str):
    """Reply using HTML parse mode (#4)."""
    await update.message.reply_text(text, parse_mode="HTML")


def _owner_only(update: Update) -> bool:
    """Return True and silently drop if not owner (#0)."""
    return update.effective_user.id == OWNER_ID


# ─────────────────────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    await _reply(update,
        "🤖 <b>AI Agent Telegram — Siêu mạnh</b>\n\n"
        "Tôi có thể làm <b>mọi thứ</b> một admin con người có thể làm:\n"
        "• Gửi tin nhắn tới nhóm/kênh khác\n"
        "• Thả emoji reaction\n"
        "• Ban / Mute / Forward / Ghim / Sửa tin nhắn\n"
        "• Gửi ảnh, tạo poll, tung xúc xắc\n"
        "• Tìm kiếm web, đọc URL, tìm paper, chạy code Python\n\n"
        "Gõ /help để xem toàn bộ lệnh."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return

    model_lines = "\n".join(
        f"• <code>{m}</code>" + ("  ✅" if m == DEFAULT_MODEL else "")
        for m in MODELS
    )
    text = (
        "📖 <b>Lệnh có sẵn</b>\n\n"
        "<b>💬 Hội thoại</b>\n"
        "<code>/reset</code>  — Xóa lịch sử chat hiện tại\n"
        "<code>/sysreset</code> — Xóa toàn bộ lịch sử\n"
        "<code>/status</code> — Xem cấu hình của chat này\n"
        "<code>/model</code>  — Chọn model AI (inline keyboard)\n"
        "<code>/plugins [on|off]</code> — Bật/tắt plugins\n"
        "<code>/topic [on|off]</code>   — Topic isolation (nhóm)\n\n"
        "<b>🔌 Plugins</b>\n"
        "• 🌐 Web search (DuckDuckGo / Google)\n"
        "• 🔗 URL reader / summarizer\n"
        "• 📚 ArXiv paper search\n"
        "• 💻 Python interpreter\n"
        "• 📤 Gửi tin/ảnh tới nhóm/kênh khác\n"
        "• ✏️ Sửa tin nhắn đã gửi\n"
        "• 😊 React • 📌 Pin • 🗑️ Xóa • ↪️ Forward\n"
        "• 🚫 Ban • 🔇 Mute • 📊 Poll • 🎲 Dice • và nhiều hơn\n\n"
        "<b>📋 Models</b>\n"
        f"{model_lines}"
    )
    await _reply(update, text)


# ─────────────────────────────────────────────────────────────
# /reset  /sysreset
# ─────────────────────────────────────────────────────────────
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid = _get_conv_id(update)
    state.clear(cid)
    await _reply(update, "🗑️ Đã xóa lịch sử hội thoại.")


async def cmd_sysreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    state.clear_all()
    await _reply(update, "🗑️ Đã xóa <b>toàn bộ</b> lịch sử hội thoại.")


# ─────────────────────────────────────────────────────────────
# /model  — inline keyboard (#10)
# ─────────────────────────────────────────────────────────────
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid     = _get_conv_id(update)
    current = state.get_cfg(cid).get("model", DEFAULT_MODEL)
    args    = (update.message.text or "").split()[1:]

    # Backward-compat: /model gemini-xxx sets directly
    if args and args[0] in MODELS:
        state.set_cfg(cid, model=args[0])
        label = _MODEL_LABELS.get(args[0], args[0])
        await _reply(update, f"✅ Đã đổi sang <b>{label}</b>")
        return

    # Show inline keyboard
    buttons = [
        [InlineKeyboardButton(
            ("✅ " if m == current else "") + _MODEL_LABELS.get(m, m),
            callback_data=f"setmodel:{m}",
        )]
        for m in MODELS
    ]
    await update.message.reply_text(
        f"🤖 Model hiện tại: <code>{current}</code>\n\nChọn model:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────────────────────
# /plugins
# ─────────────────────────────────────────────────────────────
async def cmd_plugins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid  = _get_conv_id(update)
    cfg  = state.get_cfg(cid)
    cur  = cfg.get("plugins", ENABLE_PLUGINS)
    args = (update.message.text or "").split()[1:]

    if not args:
        await _reply(update,
            f"🔌 Plugins: {'✅ Bật' if cur else '❌ Tắt'}\n"
            "Dùng <code>/plugins on</code> hoặc <code>/plugins off</code>."
        )
        return

    if args[0].lower() in ("on", "1", "true", "bật"):
        state.set_cfg(cid, plugins=True)
        await _reply(update, "🔌 Plugins: ✅ Đã bật")
    elif args[0].lower() in ("off", "0", "false", "tắt"):
        state.set_cfg(cid, plugins=False)
        await _reply(update, "🔌 Plugins: ❌ Đã tắt")
    else:
        await _reply(update, "Dùng <code>/plugins on</code> hoặc <code>/plugins off</code>.")


# ─────────────────────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat  = update.effective_chat
    cid   = _get_conv_id(update)
    cfg   = state.get_cfg(cid)
    hist  = state.get_history(cid)
    tm    = state.topic_mode(chat.id)
    model = cfg.get("model", DEFAULT_MODEL)
    label = _MODEL_LABELS.get(model, model)

    # DB stats (async — awaited here, not fire-and-forget)
    db_info = await db.stats()
    if db_info.get("ready"):
        conv_rows = db_info["conv_rows"]
        max_rows  = db_info["max_conv_rows"]
        pct       = int(conv_rows / max_rows * 100) if max_rows else 0
        bar       = "█" * (pct // 10) + "░" * (10 - pct // 10)
        db_line   = (
            f"\n\n🗄️ <b>PostgreSQL</b>\n"
            f"   Rows : {conv_rows:,} / {max_rows:,}  ({pct}%)\n"
            f"   [{bar}]"
        )
    elif not db_info.get("ready") and "error" in db_info:
        db_line = f"\n\n🗄️ PostgreSQL: ❌ <code>{db_info['error'][:60]}</code>"
    else:
        db_line = "\n\n🗄️ PostgreSQL: ⚠️ Không kết nối (in-memory only)"

    await _reply(update,
        f"📊 <b>Trạng thái</b>\n\n"
        f"🆔 Conv   : <code>{cid}</code>\n"
        f"📝 Lịch sử: {len(hist)} tin nhắn (RAM)\n"
        f"🤖 Model  : <b>{label}</b>\n"
        f"       <code>{model}</code>\n"
        f"🔌 Plugins: {'✅' if cfg.get('plugins', ENABLE_PLUGINS) else '❌'}\n"
        f"💬 Followup: {'✅' if ENABLE_FOLLOWUP else '❌'}\n"
        f"🏷️ Topic Mode: {'✅' if tm else '❌'}"
        f"{db_line}"
    )


# ─────────────────────────────────────────────────────────────
# /topic
# ─────────────────────────────────────────────────────────────
async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await _reply(update, "❌ Topic Mode chỉ áp dụng cho nhóm.")
        return

    cur  = state.topic_mode(chat.id)
    args = (update.message.text or "").split()[1:]

    if not args:
        await _reply(update,
            f"🏷️ Topic Mode: {'✅ Bật' if cur else '❌ Tắt'}\n"
            "Dùng <code>/topic on</code> hoặc <code>/topic off</code>."
        )
        return

    if args[0].lower() in ("on", "bật"):
        state.set_topic_mode(chat.id, True)
        await _reply(update,
            "🏷️ Topic Mode: ✅ Đã bật\n\n"
            "Mỗi topic sẽ có lịch sử, model, và cấu hình plugin riêng."
        )
    elif args[0].lower() in ("off", "tắt"):
        state.set_topic_mode(chat.id, False)
        await _reply(update, "🏷️ Topic Mode: ❌ Đã tắt")
    else:
        await _reply(update, "Dùng <code>/topic on</code> hoặc <code>/topic off</code>.")
