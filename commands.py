"""
commands.py — Static slash-command handlers.
Auth: OWNER_ID only.

New commands:
  /del [msg_id]           — Xóa tin nhắn đang reply hoặc theo ID
  /pin [silent]           — Ghim tin nhắn đang reply
  /ban @user [reason]     — Ban user
  /unban @user            — Unban user
  /mute @user <duration>  — Mute: 30s, 2h, 1d, 1w, 3m, 1y
  /unmute @user           — Unmute user
  /addadmin @user [flags] — Promote với quyền tuỳ chọn
  /rmadmin @user          — Demote admin
  /warn @user [reason]    — Cảnh cáo user (auto-ban tại MAX_WARNS)
  /warns [@user]          — Xem số lần cảnh cáo
  /resetwarns @user       — Reset cảnh cáo
  /feed [n]               — Xem n tin nhắn gần nhất trong buffer
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import (
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import db
import state
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


async def _reply(update: Update, text: str, **kwargs):
    await update.message.reply_text(text, parse_mode="HTML", **kwargs)


def _owner_only(update: Update) -> bool:
    return update.effective_user.id == OWNER_ID


def _parse_uid_arg(arg: str) -> Optional[int]:
    """Parse '@username' or numeric user_id. Returns int or None."""
    s = arg.strip().lstrip("@")
    return int(s) if s.lstrip("-").isdigit() else None


def _parse_duration(s: str) -> Optional[int]:
    """
    Parse duration string → seconds.
    Supported units: s h d w m(onths) y
    Examples: "30s" "2h" "1d" "1w" "3m" "1y" "1h30m"
    Returns None if unparseable.
    """
    UNITS = {
        "s":  1,
        "h":  3600,
        "d":  86400,
        "w":  604800,
        "m":  2592000,    # 30 days
        "y":  31536000,   # 365 days
    }
    total = 0
    for num, unit in re.findall(r"(\d+)\s*([smhdwy])", s.lower()):
        total += int(num) * UNITS.get(unit, 0)
    return total if total > 0 else None


def _fmt_duration(secs: int) -> str:
    if secs <= 0:
        return "vĩnh viễn"
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    if secs < 604800:
        return f"{secs // 86400}d"
    if secs < 2592000:
        return f"{secs // 604800}w"
    if secs < 31536000:
        return f"{secs // 2592000}mo"
    return f"{secs // 31536000}y"


async def _resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           args: list[str]) -> tuple[Optional[int], list[str]]:
    """
    Extract user_id from:
      1. Replied-to message's sender
      2. First arg as @username or numeric ID
    Returns (user_id, remaining_args).
    """
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id, args

    if args:
        uid = _parse_uid_arg(args[0])
        if uid:
            return uid, args[1:]
        # Try resolving @username via Telegram
        handle = args[0].lstrip("@")
        try:
            member = await context.bot.get_chat(handle)
            if hasattr(member, "id"):
                return member.id, args[1:]
        except Exception:
            pass

    return None, args


# ─────────────────────────────────────────────────────────────
# /start  /help
# ─────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    await _reply(update,
        "🤖 <b>AI Agent Telegram</b>\n\n"
        "Gõ /help để xem toàn bộ lệnh."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    model_lines = "\n".join(
        f"• <code>{m}</code>" + ("  ✅" if m == DEFAULT_MODEL else "")
        for m in MODELS
    )
    await _reply(update,
        "📖 <b>Lệnh có sẵn</b>\n\n"
        "<b>🛡️ Quản lý nhóm</b>\n"
        "<code>/del [id]</code>          — Xóa tin nhắn (reply hoặc ID)\n"
        "<code>/pin [silent]</code>       — Ghim tin nhắn đang reply\n"
        "<code>/ban [@u] [lý do]</code>   — Ban user\n"
        "<code>/unban @u</code>           — Unban user\n"
        "<code>/mute [@u] &lt;tg&gt;</code>  — Mute (30s 2h 1d 1w 3m 1y)\n"
        "<code>/unmute @u</code>          — Unmute user\n"
        "<code>/addadmin [@u] [flags]</code> — Promote admin\n"
        "   Flags: <code>del pin inv restrict topics title:Tên</code>\n"
        "<code>/rmadmin @u</code>         — Demote admin\n"
        "<code>/warn [@u] [lý do]</code>  — Cảnh cáo (auto-ban lúc max)\n"
        "<code>/warns [@u]</code>         — Xem số lần cảnh cáo\n"
        "<code>/resetwarns @u</code>      — Reset cảnh cáo\n"
        "<code>/feed [n]</code>           — n tin nhắn gần nhất (mặc định 5)\n\n"
        "<b>💬 Hội thoại AI</b>\n"
        "<code>/reset</code>   — Xóa lịch sử chat\n"
        "<code>/sysreset</code> — Xóa tất cả lịch sử\n"
        "<code>/model</code>   — Chọn model AI\n"
        "<code>/plugins [on|off]</code> — Bật/tắt plugins\n"
        "<code>/topic [on|off]</code>   — Topic isolation\n"
        "<code>/status</code>  — Trạng thái bot\n\n"
        f"<b>📋 Models</b>\n{model_lines}"
    )


# ─────────────────────────────────────────────────────────────
# /del
# ─────────────────────────────────────────────────────────────

async def cmd_del(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    # Priority: reply > arg > current message
    if msg.reply_to_message:
        target_id = msg.reply_to_message.message_id
    elif args and args[0].lstrip("-").isdigit():
        target_id = int(args[0])
    else:
        await _reply(update, "❌ Reply vào tin nhắn cần xóa hoặc cung cấp message ID.")
        return

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=target_id)
        # Also delete the /del command message itself
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await _reply(update, f"❌ Xóa thất bại: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────
# /pin
# ─────────────────────────────────────────────────────────────

async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    if not msg.reply_to_message:
        await _reply(update, "❌ Reply vào tin nhắn cần ghim.")
        return

    silent = "silent" in args or "s" in args
    try:
        await context.bot.pin_chat_message(
            chat_id              = chat.id,
            message_id           = msg.reply_to_message.message_id,
            disable_notification = silent,
        )
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await _reply(update, f"❌ Ghim thất bại: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────
# /ban  /unban
# ─────────────────────────────────────────────────────────────

async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, rest = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Cung cấp @user hoặc reply vào tin nhắn của họ.")
        return

    reason = " ".join(rest) if rest else ""
    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=uid)
        text = f"🚫 Đã ban user <code>{uid}</code>"
        if reason:
            text += f"\n📋 Lý do: {reason}"
        await _reply(update, text)
    except Exception as e:
        await _reply(update, f"❌ Ban thất bại: <code>{e}</code>")


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Cung cấp @user hoặc reply.")
        return
    try:
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=uid,
                                             only_if_banned=True)
        await _reply(update, f"✅ Đã unban user <code>{uid}</code>.")
    except Exception as e:
        await _reply(update, f"❌ Unban thất bại: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────
# /mute  /unmute
# ─────────────────────────────────────────────────────────────

async def cmd_mute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, rest = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update,
            "❌ Cú pháp: <code>/mute @user &lt;thời gian&gt;</code>\n"
            "Ví dụ: <code>/mute @user 1h</code> | <code>30s</code> | "
            "<code>1d</code> | <code>1w</code> | <code>3m</code> | <code>1y</code>"
        )
        return

    # Duration from remaining args
    dur_str = " ".join(rest)
    secs    = _parse_duration(dur_str) if dur_str else 0
    until   = None
    if secs and secs > 0:
        until = datetime.now(tz=timezone.utc) + timedelta(seconds=secs)

    perms = ChatPermissions(can_send_messages=False)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id, user_id=uid, permissions=perms, until_date=until
        )
        dur_label = _fmt_duration(secs) if secs else "vĩnh viễn"
        await _reply(update, f"🔇 Đã mute <code>{uid}</code> — {dur_label}")
    except Exception as e:
        await _reply(update, f"❌ Mute thất bại: <code>{e}</code>")


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Cung cấp @user hoặc reply.")
        return

    perms = ChatPermissions(
        can_send_messages       = True,
        can_send_polls          = True,
        can_send_other_messages = True,
        can_add_web_page_previews = True,
        can_invite_users        = True,
    )
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat.id, user_id=uid, permissions=perms
        )
        await _reply(update, f"🔊 Đã unmute <code>{uid}</code>.")
    except Exception as e:
        await _reply(update, f"❌ Unmute thất bại: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────
# /addadmin  /rmadmin
# ─────────────────────────────────────────────────────────────
# Permission flags (case-insensitive):
#   del      → can_delete_messages
#   pin      → can_pin_messages
#   inv      → can_invite_users
#   restrict → can_restrict_members
#   topics   → can_manage_topics
#   promote  → can_promote_members
#   info     → can_change_info
#   video    → can_manage_video_chats
#   post     → can_post_messages  (channels)
#   title:X  → custom_title

_PERM_FLAGS = {
    "del":      "can_delete_messages",
    "delete":   "can_delete_messages",
    "pin":      "can_pin_messages",
    "inv":      "can_invite_users",
    "invite":   "can_invite_users",
    "restrict": "can_restrict_members",
    "topics":   "can_manage_topics",
    "promote":  "can_promote_members",
    "info":     "can_change_info",
    "video":    "can_manage_video_chats",
    "post":     "can_post_messages",
}

_DEFAULT_ADMIN_PERMS = {
    "can_manage_chat":       True,
    "can_delete_messages":   True,
    "can_pin_messages":      True,
    "can_invite_users":      True,
    "can_manage_video_chats":True,
}


async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, rest = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update,
            "❌ Cú pháp: <code>/addadmin @user [flags]</code>\n"
            "Flags: <code>del pin inv restrict topics promote info video post title:Tên</code>\n"
            "Không truyền flag → dùng quyền mặc định (del, pin, inv, video)"
        )
        return

    # Parse flags
    perms     = dict(_DEFAULT_ADMIN_PERMS)
    title     = ""
    has_flags = False

    for token in rest:
        t = token.lower()
        if t.startswith("title:"):
            title     = token[6:][:16]
        elif t in _PERM_FLAGS:
            perms[_PERM_FLAGS[t]] = True
            has_flags = True
        else:
            # Ignore unknown tokens (e.g. leftover reason text)
            pass

    if not has_flags and not rest:
        pass  # Use defaults as-is
    elif has_flags:
        # Reset all optional perms to False, only set specified ones
        for v in _PERM_FLAGS.values():
            perms.setdefault(v, False)

    try:
        await context.bot.promote_chat_member(
            chat_id = chat.id,
            user_id = uid,
            **perms,
        )
        if title:
            await context.bot.set_chat_administrator_custom_title(
                chat_id=chat.id, user_id=uid, custom_title=title
            )

        granted = [k for k, v in perms.items() if v and k != "can_manage_chat"]
        flags_str = ", ".join(f"<code>{k.replace('can_','')}</code>" for k in granted)
        text = f"👑 Đã promote <code>{uid}</code> thành admin"
        if title:
            text += f" (<b>{title}</b>)"
        if flags_str:
            text += f"\n📋 Quyền: {flags_str}"
        await _reply(update, text)
    except Exception as e:
        await _reply(update, f"❌ Promote thất bại: <code>{e}</code>")


async def cmd_rmadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Cung cấp @user hoặc reply.")
        return
    try:
        await context.bot.promote_chat_member(
            chat_id=chat.id, user_id=uid,
            can_manage_chat        = False,
            can_delete_messages    = False,
            can_manage_video_chats = False,
            can_restrict_members   = False,
            can_promote_members    = False,
            can_change_info        = False,
            can_invite_users       = False,
            can_pin_messages       = False,
        )
        await _reply(update, f"🔽 Đã demote <code>{uid}</code> (xóa quyền admin).")
    except Exception as e:
        await _reply(update, f"❌ Demote thất bại: <code>{e}</code>")


# ─────────────────────────────────────────────────────────────
# /warn  /warns  /resetwarns
# ─────────────────────────────────────────────────────────────

async def cmd_warn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, rest = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Reply vào tin nhắn hoặc cung cấp @user.")
        return

    reason = " ".join(rest) if rest else ""
    count  = state.warn_add(chat.id, uid)
    max_w  = state.get_max_warns()

    text = (
        f"⚠️ Đã cảnh cáo <code>{uid}</code> "
        f"(<b>{count}/{max_w}</b>)"
    )
    if reason:
        text += f"\n📋 Lý do: {reason}"

    if count >= max_w:
        # Auto-ban
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=uid)
            state.warn_reset(chat.id, uid)
            text += f"\n\n🚫 Đạt {max_w} cảnh cáo → Đã BAN tự động."
        except Exception as e:
            text += f"\n\n❌ Auto-ban thất bại: <code>{e}</code>"

    await _reply(update, text)


async def cmd_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    if args or msg.reply_to_message:
        uid, _ = await _resolve_target(update, context, args)
        if uid:
            count = state.warn_get(chat.id, uid)
            max_w = state.get_max_warns()
            await _reply(update,
                f"⚠️ User <code>{uid}</code>: <b>{count}/{max_w}</b> cảnh cáo.")
            return

    # Show all warned users in this chat
    all_warns = state.warn_get_all(chat.id)
    if not all_warns:
        await _reply(update, "✅ Không có ai bị cảnh cáo trong chat này.")
        return
    max_w = state.get_max_warns()
    lines = [f"⚠️ <b>Danh sách cảnh cáo</b> (max {max_w}):"]
    for uid, cnt in sorted(all_warns.items(), key=lambda x: -x[1]):
        lines.append(f"• <code>{uid}</code>: {cnt}/{max_w}")
    await _reply(update, "\n".join(lines))


async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, "❌ Cung cấp @user hoặc reply.")
        return
    state.warn_reset(chat.id, uid)
    await _reply(update, f"✅ Đã reset cảnh cáo của <code>{uid}</code>.")


# ─────────────────────────────────────────────────────────────
# /feed  — recent message buffer with action keyboard
# ─────────────────────────────────────────────────────────────

def _feed_keyboard(entry: "state.FeedEntry") -> InlineKeyboardMarkup:
    cid = entry.chat_id
    mid = entry.msg_id
    uid = entry.user_id
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↩️ Reply",  callback_data=f"fd:rep:{cid}:{mid}"),
            InlineKeyboardButton("🗑️ Del",    callback_data=f"fd:del:{cid}:{mid}"),
            InlineKeyboardButton("📌 Pin",    callback_data=f"fd:pin:{cid}:{mid}"),
        ],
        [
            InlineKeyboardButton("⚠️ Warn",  callback_data=f"fd:warn:{cid}:{uid}"),
            InlineKeyboardButton("🔇 Mute",  callback_data=f"fd:mute:{cid}:{uid}"),
            InlineKeyboardButton("🚫 Ban",   callback_data=f"fd:ban:{cid}:{uid}"),
        ],
    ])


async def cmd_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    if chat.type == ChatType.PRIVATE:
        await _reply(update, "❌ /feed chỉ hoạt động trong nhóm.")
        return

    n       = int(args[0]) if (args and args[0].isdigit()) else 5
    entries = state.feed_get(chat.id, n)
    buf_sz  = state.feed_size(chat.id)

    if not entries:
        await _reply(update,
            "📋 Buffer trống — bot cần đọc tin nhắn nhóm trước.\n"
            "Đảm bảo <code>GROUP_CONTEXT_ENABLED=true</code> trong config."
        )
        return

    # Header
    await _reply(update,
        f"📋 <b>{len(entries)} tin gần nhất</b> (buffer: {buf_sz}):"
    )

    # One message per entry with action keyboard
    for e in entries:
        date_str = e.date.strftime("%Y-%m-%d %H:%M")
        uhandle  = f" (@{e.username.lstrip('@')})" if e.username else ""
        text_preview = e.text[:300] + ("…" if len(e.text) > 300 else "")

        caption = (
            f"📨 <b>#{e.msg_id}</b> | {date_str}\n"
            f"👤 {e.user_name}{uhandle}\n"
            f"─────────────────\n"
            f"{text_preview}"
        )
        try:
            await context.bot.send_message(
                chat_id   = msg.chat_id,
                text      = caption,
                parse_mode= "HTML",
                reply_markup = _feed_keyboard(e),
            )
        except Exception as exc:
            logger.error("feed send entry: %s", exc)


# ─────────────────────────────────────────────────────────────
# /reset  /sysreset  /model  /plugins  /status  /topic
# ─────────────────────────────────────────────────────────────

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    state.clear(_get_conv_id(update))
    await _reply(update, "🗑️ Đã xóa lịch sử hội thoại.")


async def cmd_sysreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    state.clear_all()
    await _reply(update, "🗑️ Đã xóa <b>toàn bộ</b> lịch sử.")


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid     = _get_conv_id(update)
    current = state.get_cfg(cid).get("model", DEFAULT_MODEL)
    args    = (update.message.text or "").split()[1:]

    if args and args[0] in MODELS:
        state.set_cfg(cid, model=args[0])
        await _reply(update, f"✅ Đã đổi sang <b>{_MODEL_LABELS.get(args[0], args[0])}</b>")
        return

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


async def cmd_plugins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid  = _get_conv_id(update)
    cfg  = state.get_cfg(cid)
    cur  = cfg.get("plugins", ENABLE_PLUGINS)
    args = (update.message.text or "").split()[1:]
    if not args:
        await _reply(update, f"🔌 Plugins: {'✅ Bật' if cur else '❌ Tắt'}\n"
                     "Dùng <code>/plugins on</code> hoặc <code>/plugins off</code>.")
        return
    if args[0].lower() in ("on", "1", "true", "bật"):
        state.set_cfg(cid, plugins=True)
        await _reply(update, "🔌 Plugins: ✅ Đã bật")
    elif args[0].lower() in ("off", "0", "false", "tắt"):
        state.set_cfg(cid, plugins=False)
        await _reply(update, "🔌 Plugins: ❌ Đã tắt")
    else:
        await _reply(update, "Dùng <code>/plugins on</code> hoặc <code>/plugins off</code>.")


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

    db_info = await db.stats()
    if db_info.get("ready"):
        cr, mr = db_info["conv_rows"], db_info["max_conv_rows"]
        pct    = int(cr / mr * 100) if mr else 0
        bar    = "█" * (pct // 10) + "░" * (10 - pct // 10)
        db_line = f"\n\n🗄️ <b>PostgreSQL</b>\n   {cr:,} / {mr:,}  ({pct}%)\n   [{bar}]"
    elif "error" in db_info:
        db_line = f"\n\n🗄️ PostgreSQL: ❌ <code>{db_info['error'][:60]}</code>"
    else:
        db_line = "\n\n🗄️ PostgreSQL: ⚠️ In-memory only"

    feed_count = state.feed_size(chat.id) if chat.type != ChatType.PRIVATE else 0
    await _reply(update,
        f"📊 <b>Trạng thái</b>\n\n"
        f"🆔 Conv   : <code>{cid}</code>\n"
        f"📝 Lịch sử: {len(hist)} tin\n"
        f"🤖 Model  : <b>{label}</b>\n"
        f"🔌 Plugins: {'✅' if cfg.get('plugins', ENABLE_PLUGINS) else '❌'}\n"
        f"💬 Followup: {'✅' if ENABLE_FOLLOWUP else '❌'}\n"
        f"🏷️ Topic Mode: {'✅' if tm else '❌'}\n"
        f"📋 Feed buffer: {feed_count} tin"
        f"{db_line}"
    )


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
        await _reply(update, f"🏷️ Topic Mode: {'✅ Bật' if cur else '❌ Tắt'}\n"
                     "Dùng <code>/topic on</code> hoặc <code>/topic off</code>.")
        return
    if args[0].lower() in ("on", "bật"):
        state.set_topic_mode(chat.id, True)
        await _reply(update, "🏷️ Topic Mode: ✅ Đã bật")
    elif args[0].lower() in ("off", "tắt"):
        state.set_topic_mode(chat.id, False)
        await _reply(update, "🏷️ Topic Mode: ❌ Đã tắt")
    else:
        await _reply(update, "Dùng <code>/topic on</code> hoặc <code>/topic off</code>.")
