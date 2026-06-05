"""
Slash-command handlers.
Every handler follows the same pattern:
  1. Check permission
  2. Parse args
  3. Mutate state or reply with info
"""
from __future__ import annotations

import logging
from typing import Optional

from telegram import Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import state
import utils
from config import DEFAULT_MODEL, ENABLE_FOLLOWUP, ENABLE_PLUGINS, MODELS

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Small helpers
# ─────────────────────────────────────────────────────────────
def _get_conv_id(update: Update) -> str:
    user      = update.effective_user
    chat      = update.effective_chat
    msg       = update.message
    thread_id = getattr(msg, "message_thread_id", None) if msg else None
    is_priv   = chat.type == ChatType.PRIVATE
    return state.conv_id(
        chat.id, user.id, thread_id, is_priv,
        state.topic_mode(chat.id),
    )


async def _resolve_target(update: Update, args: list[str]) -> Optional[int]:
    """
    Extract a target user_id from:
      1. A replied-to message
      2. The first command argument
    """
    msg = update.message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    if args:
        return utils.parse_uid(args[0])
    return None


async def _reply(update: Update, text: str):
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    is_adm = state.is_admin(update.effective_user.id)
    await _reply(update,
        "🤖 *AI Agent Telegram — Siêu mạnh*\n\n"
        "Tôi có thể làm *mọi thứ* một admin con người có thể làm:\n"
        "• Gửi tin nhắn tới nhóm/kênh khác\n"
        "• Thả emoji reaction\n"
        "• Ban / Mute / Forward / Ghim tin nhắn\n"
        "• Tạo poll, tung xúc xắc\n"
        "• Tìm kiếm web, đọc URL, tìm paper, chạy code Python\n\n"
        "Gõ `/help` để xem toàn bộ lệnh."
        + ("\n\n👑 Bạn là *Admin*." if is_adm else "")
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    is_adm = state.is_admin(update.effective_user.id)

    text = (
        "📖 *Lệnh có sẵn*\n\n"
        "*💬 Hội thoại*\n"
        "`/reset`  — Xóa lịch sử chat hiện tại\n"
        "`/status` — Xem cấu hình của chat này\n"
        "`/model [tên]` — Xem/đổi model AI\n"
        "`/plugins [on|off]` — Bật/tắt tất cả plugins\n\n"
        "*🔌 Plugins*\n"
        "• 🌐 Web search (DuckDuckGo / Google)\n"
        "• 🔗 URL reader / summarizer\n"
        "• 📚 ArXiv paper search\n"
        "• 💻 Python interpreter\n"
        "• 📤 Gửi tin nhắn tới nhóm/kênh khác\n"
        "• 😊 React emoji • 📌 Pin • 🗑️ Delete • ↪️ Forward\n"
        "• 🚫 Ban • 🔇 Mute • 📊 Poll • 🎲 Dice • và nhiều hơn\n\n"
    )
    if is_adm:
        text += (
            "*🔑 Admin*\n"
            "`/admin list|add|remove [id]`\n"
            "`/whitelist list|add|remove [id]`\n"
            "`/blacklist list|add|remove [id]`\n"
            "`/topic on|off` — Topic isolation mode\n"
            "`/sysreset` — Xóa toàn bộ lịch sử\n\n"
            "*📋 Models*\n"
            + "\n".join(
                f"• `{m}`" + ("  ✅" if m == DEFAULT_MODEL else "")
                for m in MODELS
            )
        )
    await _reply(update, text)


# ─────────────────────────────────────────────────────────────
# /reset  /sysreset
# ─────────────────────────────────────────────────────────────
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    cid = _get_conv_id(update)
    state.clear(cid)
    await _reply(update, "🗑️ Đã xóa lịch sử hội thoại.")


async def cmd_sysreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_admin(update.effective_user.id):
        await _reply(update, "❌ Chỉ admin mới dùng được lệnh này.")
        return
    state.clear_all()
    await _reply(update, "🗑️ Đã xóa *toàn bộ* lịch sử hội thoại.")


# ─────────────────────────────────────────────────────────────
# /model
# ─────────────────────────────────────────────────────────────
async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    cid      = _get_conv_id(update)
    cfg      = state.get_cfg(cid)
    current  = cfg.get("model", DEFAULT_MODEL)
    args     = (update.message.text or "").split()[1:]

    if not args:
        lines = [
            f"• `{m}`" + ("  ← hiện tại" if m == current else "")
            for m in MODELS
        ]
        await _reply(update,
            f"🤖 *Model hiện tại:* `{current}`\n\n"
            "*Các model:*\n" + "\n".join(lines) +
            "\n\nDùng `/model tên_model` để đổi."
        )
        return

    name = args[0]
    if name not in MODELS:
        await _reply(update, f"❌ Model `{name}` không hợp lệ.")
        return
    state.set_cfg(cid, model=name)
    await _reply(update, f"✅ Đã đổi sang model `{name}`.")


# ─────────────────────────────────────────────────────────────
# /plugins
# ─────────────────────────────────────────────────────────────
async def cmd_plugins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    cid  = _get_conv_id(update)
    cfg  = state.get_cfg(cid)
    cur  = cfg.get("plugins", ENABLE_PLUGINS)
    args = (update.message.text or "").split()[1:]

    if not args:
        await _reply(update,
            f"🔌 Plugins: {'✅ Bật' if cur else '❌ Tắt'}\n"
            "Dùng `/plugins on` hoặc `/plugins off`."
        )
        return

    if args[0].lower() in ("on", "1", "true", "bật"):
        state.set_cfg(cid, plugins=True)
        await _reply(update, "🔌 Plugins: ✅ Đã bật")
    elif args[0].lower() in ("off", "0", "false", "tắt"):
        state.set_cfg(cid, plugins=False)
        await _reply(update, "🔌 Plugins: ❌ Đã tắt")
    else:
        await _reply(update, "Dùng `/plugins on` hoặc `/plugins off`.")


# ─────────────────────────────────────────────────────────────
# /status
# ─────────────────────────────────────────────────────────────
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.allowed(update.effective_user.id):
        return
    user = update.effective_user
    chat = update.effective_chat
    cid  = _get_conv_id(update)
    cfg  = state.get_cfg(cid)
    hist = state.get_history(cid)
    tm   = state.topic_mode(chat.id)

    await _reply(update,
        f"📊 *Trạng thái*\n\n"
        f"🆔 Conv  : `{cid}`\n"
        f"📝 Lịch sử: {len(hist)} tin nhắn\n"
        f"🤖 Model  : `{cfg.get('model', DEFAULT_MODEL)}`\n"
        f"🔌 Plugins: {'✅' if cfg.get('plugins', ENABLE_PLUGINS) else '❌'}\n"
        f"💬 Followup: {'✅' if ENABLE_FOLLOWUP else '❌'}\n"
        f"🏷️ Topic Mode: {'✅' if tm else '❌'}\n"
        f"👤 Admin  : {'✅' if state.is_admin(user.id) else '❌'}\n"
        f"👑 Owner  : {'✅' if state.is_owner(user.id) else '❌'}"
    )


# ─────────────────────────────────────────────────────────────
# /topic
# ─────────────────────────────────────────────────────────────
async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_admin(update.effective_user.id):
        await _reply(update, "❌ Chỉ admin mới dùng được lệnh này.")
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
            "Dùng `/topic on` hoặc `/topic off`."
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
        await _reply(update, "Dùng `/topic on` hoặc `/topic off`.")


# ─────────────────────────────────────────────────────────────
# /admin
# ─────────────────────────────────────────────────────────────
async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_owner(update.effective_user.id):
        await _reply(update, "❌ Chỉ chủ bot mới dùng được lệnh này.")
        return

    args = (update.message.text or "").split()[1:]
    sub  = args[0].lower() if args else ""

    if sub == "list":
        await _reply(update,
            f"👑 *Admins:*\n{utils.fmt_ids(state.get_admins())}"
        )
        return

    target = await _resolve_target(update, args[1:] if len(args) > 1 else [])
    if not target:
        await _reply(update,
            "Dùng: `/admin list|add|remove [user_id]`\n"
            "Hoặc reply tin nhắn của user rồi dùng lệnh."
        )
        return

    if sub == "add":
        state.add_admin(target)
        await _reply(update, f"✅ Đã thêm `{target}` vào danh sách admin.")
    elif sub == "remove":
        if state.is_owner(target):
            await _reply(update, "❌ Không thể xóa chủ bot khỏi admin.")
            return
        state.rm_admin(target)
        await _reply(update, f"✅ Đã xóa `{target}` khỏi danh sách admin.")
    else:
        await _reply(update, "Dùng: `/admin list|add|remove [user_id]`")


# ─────────────────────────────────────────────────────────────
# /whitelist
# ─────────────────────────────────────────────────────────────
async def cmd_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_admin(update.effective_user.id):
        await _reply(update, "❌ Không có quyền."); return

    args = (update.message.text or "").split()[1:]
    sub  = args[0].lower() if args else ""

    if sub == "list":
        wl = state.get_whitelist()
        await _reply(update,
            f"🔓 *Whitelist:*\n{utils.fmt_ids(wl)}\n\n"
            + ("_(Trống = tất cả mọi người được dùng bot)_" if not wl else "")
        )
        return

    target = await _resolve_target(update, args[1:] if len(args) > 1 else [])
    if not target:
        await _reply(update,
            "🔓 *Whitelist* — nếu không trống, chỉ user trong này được dùng bot.\n\n"
            "Dùng: `/whitelist list|add|remove [user_id]`"
        )
        return

    if sub == "add":
        state.add_whitelist(target)
        await _reply(update, f"✅ Đã thêm `{target}` vào whitelist.")
    elif sub == "remove":
        state.rm_whitelist(target)
        await _reply(update, f"✅ Đã xóa `{target}` khỏi whitelist.")
    else:
        await _reply(update, "Dùng: `/whitelist list|add|remove [user_id]`")


# ─────────────────────────────────────────────────────────────
# /blacklist
# ─────────────────────────────────────────────────────────────
async def cmd_blacklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_admin(update.effective_user.id):
        await _reply(update, "❌ Không có quyền."); return

    args = (update.message.text or "").split()[1:]
    sub  = args[0].lower() if args else ""

    if sub == "list":
        bl = state.get_blacklist()
        await _reply(update, f"🚫 *Blacklist:*\n{utils.fmt_ids(bl)}")
        return

    target = await _resolve_target(update, args[1:] if len(args) > 1 else [])
    if not target:
        await _reply(update,
            "🚫 *Blacklist* — user bị chặn hoàn toàn.\n\n"
            "Dùng: `/blacklist list|add|remove [user_id]`"
        )
        return

    if sub == "add":
        state.add_blacklist(target)
        await _reply(update, f"🚫 Đã chặn user `{target}`.")
    elif sub == "remove":
        state.rm_blacklist(target)
        await _reply(update, f"✅ Đã bỏ chặn user `{target}`.")
    else:
        await _reply(update, "Dùng: `/blacklist list|add|remove [user_id]`")


# ─────────────────────────────────────────────────────────────
# /access  (combined view)
# ─────────────────────────────────────────────────────────────
async def cmd_access(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not state.is_admin(update.effective_user.id):
        await _reply(update, "❌ Không có quyền."); return
    await _reply(update,
        f"👑 *Admins:*\n{utils.fmt_ids(state.get_admins())}\n\n"
        f"🔓 *Whitelist:*\n{utils.fmt_ids(state.get_whitelist())}\n\n"
        f"🚫 *Blacklist:*\n{utils.fmt_ids(state.get_blacklist())}"
    )
