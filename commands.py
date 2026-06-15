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
  /fulladmin @user        — Promote với TOÀN BỘ quyền admin
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
from config import DEFAULT_LANG, DEFAULT_MODEL, ENABLE_FOLLOWUP, ENABLE_PLUGINS, MODELS, OWNER_ID
from handlers import _MODEL_LABELS
from i18n import t, lang_list_str, lang_name, SUPPORTED

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


def _lang(update: Update) -> str:
    """Return the language code for the current conversation."""
    cid = _get_conv_id(update)
    return state.get_cfg(cid).get("lang", DEFAULT_LANG)


def _parse_uid_arg(arg: str) -> Optional[int]:
    """Parse '@username' or numeric user_id. Returns int or None."""
    s = arg.strip().lstrip("@")
    return int(s) if s.lstrip("-").isdigit() else None


def _parse_duration(s: str) -> Optional[int]:
    """
    Parse duration string → seconds.
    Units: s=seconds  m=minutes  h=hours  d=days  w=weeks  mo=months  y=years
    Examples: "30s" "5m" "2h" "1d" "1w" "3mo" "1y" "1h30m"
    Note: "m" = minutes (NOT months). Use "mo" for months.
    """
    UNITS = {
        "s":  1,
        "m":  60,           # minutes
        "h":  3600,
        "d":  86400,
        "w":  604800,
        "mo": 2592000,      # months (30 days)
        "y":  31536000,
    }
    total = 0
    # Match "mo" before "m" to avoid mis-parsing "1mo" as "1m" + leftover "o"
    for num, unit in re.findall(r"(\d+)\s*(mo|[smhdwy])", s.lower()):
        total += int(num) * UNITS.get(unit, 0)
    return total if total > 0 else None


def _fmt_duration(secs: int) -> str:
    if secs <= 0:        return "∞"
    if secs < 60:        return f"{secs}s"
    if secs < 3600:      return f"{secs // 60}m"
    if secs < 86400:     return f"{secs // 3600}h"
    if secs < 604800:    return f"{secs // 86400}d"
    if secs < 2592000:   return f"{secs // 604800}w"
    if secs < 31536000:  return f"{secs // 2592000}mo"
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
    await _reply(update, t("start", _lang(update)))


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    lang       = _lang(update)
    model_lines = "\n".join(
        f"• <code>{m}</code>" + ("  ✅" if m == DEFAULT_MODEL else "")
        for m in MODELS
    )
    lines = [
        t("help.title", lang), "",
        f"<b>{t('help.mod', lang)}</b>",
        t("help.del",          lang),
        t("help.pin",          lang),
        t("help.ban",          lang),
        t("help.unban",        lang),
        t("help.mute",         lang),
        t("help.unmute",       lang),
        t("help.addadmin",     lang),
        t("help.addadmin.flags", lang),
        t("help.rmadmin",      lang),
        t("help.warn",         lang),
        t("help.warns",        lang),
        t("help.resetwarns",   lang),
        t("help.feed",         lang),
        "",
        f"<b>{t('help.ai', lang)}</b>",
        t("help.reset",        lang),
        t("help.sysreset",     lang),
        t("help.model",        lang),
        t("help.plugins",      lang),
        t("help.topic",        lang),
        t("help.status",       lang),
        t("help.lang",         lang),
        "",
        f"<b>{t('help.models.title', lang)}</b>\n{model_lines}",
    ]
    await _reply(update, "\n".join(lines))


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
        await _reply(update, t("need.reply", _lang(update)))
        return

    try:
        await context.bot.delete_message(chat_id=chat.id, message_id=target_id)
        # Also delete the /del command message itself
        try:
            await msg.delete()
        except Exception:
            pass
    except Exception as e:
        await _reply(update, t("del.fail", _lang(update), err=e))


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
        await _reply(update, t("need.reply.pin", _lang(update)))
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
        await _reply(update, t("pin.fail", _lang(update), err=e))


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
        await _reply(update, t("need.target", _lang(update)))
        return

    reason = " ".join(rest) if rest else ""
    try:
        await context.bot.ban_chat_member(chat_id=chat.id, user_id=uid)
        lang = _lang(update)
        text = t("ban.done", lang, uid=uid)
        if reason:
            text += t("ban.reason", lang, reason=reason)
        await _reply(update, text)
    except Exception as e:
        await _reply(update, t("ban.fail", _lang(update), err=e))


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, t("need.target", _lang(update)))
        return
    try:
        await context.bot.unban_chat_member(chat_id=chat.id, user_id=uid,
                                             only_if_banned=True)
        await _reply(update, t("unban.done", _lang(update), uid=uid))
    except Exception as e:
        await _reply(update, t("unban.fail", _lang(update), err=e))


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
        await _reply(update, t("mute.usage", _lang(update)))
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
        lang = _lang(update)
        dur_label = _fmt_duration(secs) if secs else t("mute.perm", lang)
        await _reply(update, t("mute.done", lang, uid=uid, dur=dur_label))
    except Exception as e:
        await _reply(update, t("mute.fail", _lang(update), err=e))


async def cmd_unmute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, t("need.target", _lang(update)))
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
        await _reply(update, t("unmute.fail", _lang(update), err=e))


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
        await _reply(update, t("addadmin.usage", _lang(update)))
        return

    # Parse flags
    perms     = dict(_DEFAULT_ADMIN_PERMS)
    title     = ""
    has_flags = False

    for token in rest:
        tok = token.lower()
        if tok.startswith("title:"):
            title     = token[6:][:16]
        elif tok in _PERM_FLAGS:
            perms[_PERM_FLAGS[tok]] = True
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

        lang = _lang(update)
        granted = [k for k, v in perms.items() if v and k != "can_manage_chat"]
        flags_str = ", ".join(f"<code>{k.replace('can_','')}</code>" for k in granted)
        text = t("addadmin.done", lang, uid=uid)
        if title:
            text += t("addadmin.title", lang, title=title)
        if flags_str:
            text += t("addadmin.perms", lang, perms=flags_str)
        await _reply(update, text)
    except Exception as e:
        await _reply(update, t("addadmin.fail", _lang(update), err=e))


# ─────────────────────────────────────────────────────────────
# /fulladmin — promote with EVERY available admin permission
# ─────────────────────────────────────────────────────────────
# Usage: /fulladmin @user [title:X]   (or reply to the user's message)
# Grants all rights supported by promote_chat_member, including
# can_promote_members — the new admin can then promote others too.

_FULL_ADMIN_PERMS = {
    "can_manage_chat":        True,
    "can_delete_messages":    True,
    "can_manage_video_chats": True,
    "can_restrict_members":   True,
    "can_promote_members":    True,
    "can_change_info":        True,
    "can_invite_users":       True,
    "can_post_messages":      True,
    "can_edit_messages":      True,
    "can_pin_messages":       True,
    "can_manage_topics":      True,
}


async def cmd_fulladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, rest = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, t("addadmin.usage", _lang(update)))
        return

    title = ""
    for token in rest:
        if token.lower().startswith("title:"):
            title = token[6:][:16]

    try:
        await context.bot.promote_chat_member(
            chat_id = chat.id,
            user_id = uid,
            **_FULL_ADMIN_PERMS,
        )
        if title:
            await context.bot.set_chat_administrator_custom_title(
                chat_id=chat.id, user_id=uid, custom_title=title
            )

        lang = _lang(update)
        text = t("addadmin.done", lang, uid=uid) + " 👑 (full privileges)"
        if title:
            text += t("addadmin.title", lang, title=title)
        await _reply(update, text)
    except Exception as e:
        await _reply(update, t("addadmin.fail", _lang(update), err=e))


async def cmd_rmadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, t("need.target", _lang(update)))
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
        await _reply(update, t("rmadmin.done", _lang(update), uid=uid))
    except Exception as e:
        await _reply(update, t("rmadmin.fail", _lang(update), err=e))


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

    lang = _lang(update)
    text = t("warn.added", lang, uid=uid, count=count, max=max_w)
    if reason:
        text += t("warn.reason", lang, reason=reason)

    if count >= max_w:
        # Auto-ban
        try:
            await context.bot.ban_chat_member(chat_id=chat.id, user_id=uid)
            state.warn_reset(chat.id, uid)
            text += t("warn.banned", lang, max=max_w)
        except Exception as e:
            text += t("warn.ban_fail", lang, err=e)

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
            await _reply(update, t("warns.single", _lang(update), uid=uid, count=count, max=max_w))
            return

    # Show all warned users in this chat
    all_warns = state.warn_get_all(chat.id)
    if not all_warns:
        await _reply(update, t("warns.none", _lang(update)))
        return
    max_w = state.get_max_warns()
    lang = _lang(update)
    lines = [t("warns.title", lang, max=max_w)]
    for uid, cnt in sorted(all_warns.items(), key=lambda x: -x[1]):
        lines.append(f"• <code>{uid}</code>: {cnt}/{max_w}")
    await _reply(update, "\n".join(lines))


async def cmd
