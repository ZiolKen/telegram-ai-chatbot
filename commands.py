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

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape as _html_escape
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
from config import (
    DEFAULT_LANG, DEFAULT_MODEL, DEFAULT_THINKING_LEVEL, ENABLE_FOLLOWUP,
    ENABLE_GROUNDING, ENABLE_PLUGINS, GEMINI_KEYS, MODELS, OWNER_ID,
)
from handlers import _MODEL_LABELS
from i18n import t, lang_list_str, lang_name, SUPPORTED
from tools_web import get_search_engine_status
import config
import crypto
import utils
import group_context
import monitor_proxy

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
        # Try resolving @username: local directory first (learned passively
        # from every message the bot has seen — works for regular group
        # members, which Telegram's get_chat() usually cannot resolve),
        # then fall back to get_chat() for channels/bots.
        handle   = args[0].lstrip("@")
        known_id = state.lookup_user_id(handle)
        if known_id:
            return known_id, args[1:]
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
        "<b>📡 Monitor & Proxy & Ngữ cảnh</b>" if lang == "vi" else "<b>📡 Monitor, Proxy & Context</b>",
        ("• <code>/setgroup &lt;id|here&gt;</code> — Đặt nhóm đích quan sát / relay" if lang == "vi" else "• <code>/setgroup &lt;id|here&gt;</code> — Set target group for monitor / relay"),
        ("• <code>/monitor [on|off]</code> — Giám sát tin nhóm thời gian thực về DM" if lang == "vi" else "• <code>/monitor [on|off]</code> — Real-time group monitor pushed to DM"),
        ("• <code>/proxy [on|off]</code> — Bật/tắt relay 2 chiều DM ⇄ nhóm" if lang == "vi" else "• <code>/proxy [on|off]</code> — 2-way DM ⇄ group relay mode"),
        ("• <code>/purge</code> (reply) · <code>/purge &lt;n&gt;</code> · <code>/purgeuser</code> — Xóa tin hàng loạt" if lang == "vi" else "• <code>/purge</code> (reply) · <code>/purge &lt;n&gt;</code> · <code>/purgeuser</code> — Bulk delete messages"),
        ("• <code>/tomtat [n]</code> — Tóm tắt diễn biến nhóm bằng AI Gemini" if lang == "vi" else "• <code>/tomtat [n]</code> — Summarize group discussion with Gemini"),
        ("• <code>/aictx [n|clear]</code> — Xem / cấu hình bối cảnh nhóm gửi AI" if lang == "vi" else "• <code>/aictx [n|clear]</code> — Configure group context size / clear"),
        ("• <code>/encstatus</code> — Kiểm tra trạng thái mã hóa Fernet" if lang == "vi" else "• <code>/encstatus</code> — Check Fernet cryptography encryption status"),
        ("• <code>/thinking [low|med|high]</code> — Mức độ suy luận Gemini" if lang == "vi" else "• <code>/thinking [low|med|high]</code> — Gemini thinking level"),
        ("• <code>/grounding [on|off]</code> — Bật/tắt Google Search Grounding" if lang == "vi" else "• <code>/grounding [on|off]</code> — Toggle Google Search Grounding"),
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
        await _reply(update, t("unmute.done", _lang(update), uid=uid))
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
    "can_manage_chat":        True,
    "can_delete_messages":    True,
    "can_pin_messages":       True,
    "can_invite_users":       True,
    "can_manage_video_chats": True,
    "can_manage_topics":      True,
}

# All non-channel permissions (used by the "full" flag)
_FULL_ADMIN_PERMS = {
    "can_manage_chat":        True,
    "can_delete_messages":    True,
    "can_manage_video_chats": True,
    "can_restrict_members":   True,
    "can_promote_members":    True,
    "can_change_info":        True,
    "can_invite_users":       True,
    "can_pin_messages":       True,
    "can_manage_topics":      True,
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
    title      = ""
    has_flags  = False
    use_full   = False
    explicit: set[str] = set()   # perm fields explicitly requested

    for token in rest:
        tok = token.lower()
        if tok.startswith("title:"):
            title = token[6:][:16]
        elif tok == "full":
            has_flags = True
            use_full  = True
        elif tok in _PERM_FLAGS:
            has_flags = True
            explicit.add(_PERM_FLAGS[tok])
        # Unknown tokens ignored (leftover text etc.)

    if use_full:
        # Grant every non-channel admin permission
        perms = dict(_FULL_ADMIN_PERMS)
    elif has_flags:
        # Start with the bare minimum, then only add what was explicitly requested
        perms = {"can_manage_chat": True}
        for field in set(_PERM_FLAGS.values()):
            perms[field] = field in explicit
    else:
        # No flags → use safe defaults
        perms = dict(_DEFAULT_ADMIN_PERMS)

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
        await _reply(update, t("need.target", _lang(update)))
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


async def cmd_resetwarns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    args = (msg.text or "").split()[1:]

    uid, _ = await _resolve_target(update, context, args)
    if not uid:
        await _reply(update, t("need.target", _lang(update)))
        return
    state.warn_reset(chat.id, uid)
    await _reply(update, t("resetwarns.done", _lang(update), uid=uid))


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


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel a pending feed-reply ForceReply prompt."""
    if not _owner_only(update):
        return
    chat = update.effective_chat
    # Cancel any pending_feed_reply for this chat
    # (scan all keys matching this chat_id)
    removed = [
        k for k in list(state.pending_feed_replies.keys())
        if k[0] == chat.id
    ]
    for k in removed:
        state.pending_feed_replies.pop(k, None)
    if removed:
        await _reply(update, t("cancel.done", _lang(update)))
    else:
        await _reply(update, t("cancel.none", _lang(update)))


async def cmd_feed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    msg  = update.message
    chat = update.effective_chat
    lang = _lang(update)
    args = (msg.text or "").split()[1:]
    is_private = chat.type == ChatType.PRIVATE

    # ── Resolve which group's feed to show ───────────────────
    # Group chat  : /feed [n]            → current group
    # Private chat: /feed <chat_id> [n]  → specified group
    #               /feed [n]            → auto-select if only 1 group buffered
    target_chat_id: int | None = None

    if not is_private:
        target_chat_id = chat.id
    else:
        # Try first arg as a group chat_id (negative int)
        if args and args[0].lstrip("-").isdigit():
            candidate = int(args[0])
            if candidate < 0:           # valid group id
                target_chat_id = candidate
                args = args[1:]         # consume the chat_id arg
        if target_chat_id is None:
            available = state.feed_list_chats()
            if len(available) == 1:
                target_chat_id = available[0]
            elif len(available) > 1:
                ids_fmt = "\n".join(f"• <code>{cid}</code>" for cid in available)
                await _reply(update, t("feed.multi_group", lang, ids=ids_fmt))
                return
            else:
                await _reply(update, t("feed.no_data", lang))
                return

    n       = int(args[0]) if (args and args[0].isdigit()) else 5
    entries = state.feed_get(target_chat_id, n)
    buf_sz  = state.feed_size(target_chat_id)

    if not entries:
        await _reply(update, t("feed.empty.group", lang, chat_id=target_chat_id))
        return

    await _reply(update, t("feed.header.group", lang, n=len(entries), chat_id=target_chat_id, buf=buf_sz))

    for e in entries:
        date_str     = e.date.strftime("%Y-%m-%d %H:%M")
        uhandle      = f" (@{e.username.lstrip('@')})" if e.username else ""
        text_preview = e.text[:300] + ("…" if len(e.text) > 300 else "")
        caption = (
            f"📨 <b>#{e.msg_id}</b> | {date_str}\n"
            f"👤 {e.user_name}{uhandle}\n"
            f"─────────────────\n"
            f"{text_preview}"
        )
        try:
            await context.bot.send_message(
                chat_id      = msg.chat_id,   # send to wherever /feed was called
                text         = caption,
                parse_mode   = "HTML",
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
    await _reply(update, t("reset.done", _lang(update)))


async def cmd_sysreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    state.clear_all()
    await _reply(update, t("sysreset.done", _lang(update)))


async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid       = _get_conv_id(update)
    cfg       = state.get_cfg(cid)
    current   = cfg.get("model", DEFAULT_MODEL)
    last_used = cfg.get("last_used_model")  # model THỰC SỰ trả lời gần nhất (có thể khác `current` do auto fallback)
    args      = (update.message.text or "").split()[1:]

    if args and args[0] in MODELS:
        # Chọn thủ công → xoá fallback cũ, tránh hiện cảnh báo lỗi thời
        state.set_cfg(cid, model=args[0], last_used_model=None)
        await _reply(update, t("model.switched", _lang(update), label=_MODEL_LABELS.get(args[0], args[0])))
        return

    lang = _lang(update)
    buttons = [
        [InlineKeyboardButton(
            ("✅ " if m == current else "⚡ " if m == last_used else "") + _MODEL_LABELS.get(m, m),
            callback_data=f"setmodel:{m}",
        )]
        for m in MODELS
    ]
    header = t("model.current", lang, model=current)
    if last_used and last_used != current:
        header += "\n\n" + t(
            "model.fallback_note", lang,
            configured=_MODEL_LABELS.get(current, current),
            actual=_MODEL_LABELS.get(last_used, last_used),
        )
    await update.message.reply_text(
        header,
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
        lang  = _lang(update)
        state_str = t("plugins.enabled" if cur else "plugins.disabled", lang)
        await _reply(update, t("plugins.status", lang, state=state_str))
        return
    if args[0].lower() in ("on", "1", "true", "bật"):
        state.set_cfg(cid, plugins=True)
        await _reply(update, t("plugins.on", _lang(update)))
    elif args[0].lower() in ("off", "0", "false", "tắt"):
        state.set_cfg(cid, plugins=False)
        await _reply(update, t("plugins.off", _lang(update)))
    else:
        await _reply(update, t("plugins.usage", _lang(update)))


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

    lang    = _lang(update)
    last_used = cfg.get("last_used_model")
    if last_used and last_used != model:
        model_line = t(
            "status.model_fallback", lang,
            actual=_MODEL_LABELS.get(last_used, last_used), configured=label,
        )
    else:
        model_line = f"{t('status.model', lang)}  : <b>{label}</b>"
    db_info = await db.stats()
    if db_info.get("ready"):
        cr, mr = db_info["conv_rows"], db_info["max_conv_rows"]
        pct    = int(cr / mr * 100) if mr else 0
        bar    = "█" * (pct // 10) + "░" * (10 - pct // 10)
        db_line = t("status.db.ok", lang, rows=cr, max_rows=mr, pct=pct, bar=bar)
    elif "error" in db_info:
        db_line = t("status.db.err", lang, err=db_info["error"][:60])
    else:
        db_line = t("status.db.off", lang)

    if chat.type != ChatType.PRIVATE:
        feed_count = state.feed_size(chat.id)
    else:
        feed_count = sum(state.feed_size(cid) for cid in state.feed_list_chats())
    plug_icon   = "✅" if cfg.get("plugins", ENABLE_PLUGINS) else "❌"
    follow_icon = "✅" if ENABLE_FOLLOWUP else "❌"
    topic_icon  = "✅" if tm else "❌"
    msgs_str    = t("status.msgs", lang, n=len(hist))

    # ── API keys & Webhook (real-time from Telegram) ───────────
    key_count = len(GEMINI_KEYS)
    key_line  = f"🔑 API Key  : <b>{key_count}</b> key{'s' if key_count != 1 else ''}"
    try:
        wh_info     = await context.bot.get_webhook_info()
        webhook_active = bool(wh_info.url)
        wh_icon     = "✅" if webhook_active else "❌"
    except Exception:
        wh_icon = "❓"
    wh_line = f"🔗 Webhook  : {wh_icon}"

    # ── Web search engine diagnostics ───────────────────────────
    se = get_search_engine_status()
    if se["tavily_configured"]:
        if se["ok"] is True:
            se_line = f"🔍 Search   : ✅ Tavily (last: {_html_escape(se['detail'][:60])})"
        elif se["ok"] is False:
            se_line = f"🔍 Search   : ⚠️ Tavily lỗi, đang fallback DDG (last: {_html_escape(se['detail'][:80])})"
        else:
            se_line = "🔍 Search   : ✅ Tavily đã cấu hình (chưa có lần gọi nào)"
    else:
        se_line = "🔍 Search   : ⚠️ DuckDuckGo only — thiếu env: TAVILY_API_KEY"

    # ── User directory (uid resolution) diagnostics ──────────────
    kn = state.known_user_count()
    persist_icon = "✅ DB" if db_info.get("ready") else "⚠️ RAM only (mất khi restart)"
    uid_line = f"🗂 Users    : <b>{kn}</b> known ({persist_icon})"

    thinking_val = cfg.get("thinking", DEFAULT_THINKING_LEVEL).upper()
    grounding_val = "✅" if cfg.get("grounding", ENABLE_GROUNDING) else "❌"

    tgt = monitor_proxy.get_target_group_id()
    tgt_str = f"<code>{tgt}</code>" if tgt else ("Chưa đặt" if lang == "vi" else "Not set")
    mon_icon = "✅ BẬT" if monitor_proxy.is_monitor_on() else "❌ Tắt"
    proxy_icon = "✅ BẬT" if monitor_proxy.is_proxy_on() else "❌ Tắt"
    enc_icon = "🛡️ Fernet" if crypto.is_crypto_active() else "⚠️ Plain"

    await _reply(update,
        f"{t('status.title', lang)}\n\n"
        f"{t('status.conv', lang)}   : <code>{cid}</code>\n"
        f"{t('status.history', lang)}: {msgs_str}\n"
        f"{model_line}\n"
        f"🧠 Thinking  : <b>{thinking_val}</b>\n"
        f"🌐 Grounding : {grounding_val}\n"
        f"🎯 Target GRP: {tgt_str}\n"
        f"👁️ Monitor   : {mon_icon}\n"
        f"📡 Proxy     : {proxy_icon}\n"
        f"🔐 Security  : {enc_icon}\n"
        f"{key_line}\n"
        f"{wh_line}\n"
        f"{se_line}\n"
        f"{uid_line}\n"
        f"{t('status.plugins', lang)}: {plug_icon}\n"
        f"{t('status.followup', lang)}: {follow_icon}\n"
        f"{t('status.topic', lang)}: {topic_icon}\n"
        f"{t('status.feed', lang)}: {feed_count} {t('status.msgs_unit', lang)}"
        f"{db_line}"
    )


async def cmd_thinking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid   = _get_conv_id(update)
    cfg   = state.get_cfg(cid)
    cur   = cfg.get("thinking", DEFAULT_THINKING_LEVEL)
    args  = (update.message.text or "").split()[1:]
    lang  = _lang(update)

    if not args:
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"{'✅ ' if cur == 'low' else ''}Low", callback_data="thinking:low"),
                InlineKeyboardButton(f"{'✅ ' if cur == 'medium' else ''}Medium", callback_data="thinking:medium"),
                InlineKeyboardButton(f"{'✅ ' if cur == 'high' else ''}High", callback_data="thinking:high"),
            ]
        ])
        msg_text = (
            f"🧠 <b>Gemini Thinking Level</b>\n\n"
            f"Hiện tại: <b>{cur.upper()}</b>\n"
            f"• <b>Low</b>: Nhanh nhất, tiết kiệm token (budget=0 cho Gemini 2.5)\n"
            f"• <b>Medium</b>: Cân bằng, suy luận vừa phải (mặc định)\n"
            f"• <b>High</b>: Suy luận sâu tối đa cho bài toán phức tạp\n\n"
            f"Chọn mức suy luận bên dưới:"
            if lang == "vi" else
            f"🧠 <b>Gemini Thinking Level</b>\n\n"
            f"Current: <b>{cur.upper()}</b>\n"
            f"• <b>Low</b>: Fastest, lowest token usage (budget=0 on 2.5)\n"
            f"• <b>Medium</b>: Balanced reasoning depth (default)\n"
            f"• <b>High</b>: Deep reasoning for complex math / code\n\n"
            f"Select reasoning level below:"
        )
        await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=kb)
        return

    choice = args[0].lower()
    if choice in ("low", "thấp"):
        state.set_cfg(cid, thinking="low")
        await _reply(update, "🧠 Thinking level: <b>LOW</b>" if lang != "vi" else "🧠 Mức độ suy luận: <b>THẤP (LOW)</b>")
    elif choice in ("medium", "vừa", "trung bình"):
        state.set_cfg(cid, thinking="medium")
        await _reply(update, "🧠 Thinking level: <b>MEDIUM</b>" if lang != "vi" else "🧠 Mức độ suy luận: <b>TRUNG BÌNH (MEDIUM)</b>")
    elif choice in ("high", "cao"):
        state.set_cfg(cid, thinking="high")
        await _reply(update, "🧠 Thinking level: <b>HIGH</b>" if lang != "vi" else "🧠 Mức độ suy luận: <b>CAO (HIGH)</b>")
    else:
        await _reply(update, "Usage: <code>/thinking low|medium|high</code>")


async def cmd_grounding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid   = _get_conv_id(update)
    cfg   = state.get_cfg(cid)
    cur   = cfg.get("grounding", ENABLE_GROUNDING)
    args  = (update.message.text or "").split()[1:]
    lang  = _lang(update)

    if not args:
        state_str = ("BẬT" if cur else "TẮT") if lang == "vi" else ("ON" if cur else "OFF")
        await _reply(
            update,
            f"🌐 Google Search Grounding: <b>{state_str}</b>\nNguồn trích dẫn: <b>{"BẬT" if cfg.get("grounding_sources") else "TẮT"}</b>\n(Gemini 3.x ghép được với tool; model khác chỉ khi không bật plugin)\nDùng: <code>/grounding on|off</code> · <code>/grounding src on|off</code>"
            if lang == "vi" else
            f"🌐 Google Search Grounding: <b>{state_str}</b>\nShow sources: <b>{"ON" if cfg.get("grounding_sources") else "OFF"}</b>\n(Gemini 3.x can combine with tools; other models only without plugins)\nUsage: <code>/grounding on|off</code> · <code>/grounding src on|off</code>"
        )
    elif args[0].lower() in ("src", "sources", "nguon", "nguồn"):
        val = (args[1].lower() if len(args) > 1 else "")
        if val in ("on", "1", "true", "bật"):
            state.set_cfg(cid, grounding_sources=True)
            await _reply(update, "📎 Đã BẬT hiển thị nguồn (khi Gemini có dùng Google Search)." if lang == "vi" else "📎 Sources display: <b>ON</b> (when Gemini used Google Search).")
        elif val in ("off", "0", "false", "tắt"):
            state.set_cfg(cid, grounding_sources=False)
            await _reply(update, "📎 Đã TẮT hiển thị nguồn." if lang == "vi" else "📎 Sources display: <b>OFF</b>.")
        else:
            await _reply(update, "Usage: <code>/grounding src on|off</code>")
    elif args[0].lower() in ("on", "1", "true", "bật"):
        state.set_cfg(cid, grounding=True)
        await _reply(update, "🌐 Google Search Grounding: <b>ON</b>" if lang != "vi" else "🌐 Đã <b>BẬT</b> Google Search Grounding.")
    elif args[0].lower() in ("off", "0", "false", "tắt"):
        state.set_cfg(cid, grounding=False)
        await _reply(update, "🌐 Google Search Grounding: <b>OFF</b>" if lang != "vi" else "🌐 Đã <b>TẮT</b> Google Search Grounding.")
    else:
        await _reply(update, "Usage: <code>/grounding on|off</code>")


async def cmd_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat = update.effective_chat
    if chat.type == ChatType.PRIVATE:
        await _reply(update, t("topic.group_only", _lang(update)))
        return
    cur  = state.topic_mode(chat.id)
    args = (update.message.text or "").split()[1:]
    if not args:
        lang = _lang(update)
        state_str = t("topic.on" if cur else "topic.off", lang).split(": ", 1)[1]
        await _reply(update, t("topic.status", lang, state=state_str))
        return
    if args[0].lower() in ("on", "bật"):
        state.set_topic_mode(chat.id, True)
        await _reply(update, t("topic.on", _lang(update)))
    elif args[0].lower() in ("off", "tắt"):
        state.set_topic_mode(chat.id, False)
        await _reply(update, t("topic.off", _lang(update)))
    else:
        await _reply(update, t("topic.usage", _lang(update)))

# ─────────────────────────────────────────────────────────────
# /lang  — switch UI + AI language
# ─────────────────────────────────────────────────────────────

async def cmd_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    cid  = _get_conv_id(update)
    cfg  = state.get_cfg(cid)
    cur  = cfg.get("lang", DEFAULT_LANG)
    args = (update.message.text or "").split()[1:]

    if not args:
        await _reply(update, t(
            "lang.current", cur,
            name=lang_name(cur),
            list=lang_list_str(),
        ))
        return

    code = args[0].lower().strip()
    if code not in SUPPORTED:
        await _reply(update, t("lang.invalid", cur, list=", ".join(SUPPORTED)))
        return

    # Switch language only — history is preserved
    state.set_cfg(cid, lang=code)
    await _reply(update, t("lang.set", code, name=lang_name(code)))


# ─────────────────────────────────────────────────────────────
# /setgroup  /monitor  /proxy  /tomtat  /aictx  /encstatus
# ─────────────────────────────────────────────────────────────

async def cmd_setgroup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat = update.effective_chat
    args = (update.message.text or "").split()[1:]
    lang = _lang(update)

    if not args:
        cur = monitor_proxy.get_target_group_id()
        if cur:
            await _reply(update, f"🎯 Nhóm đích hiện tại: <code>{cur}</code>\nĐổi nhóm: <code>/setgroup &lt;id|here&gt;</code>" if lang == "vi" else f"🎯 Current target group: <code>{cur}</code>\nChange: <code>/setgroup &lt;id|here&gt;</code>")
        else:
            await _reply(update, "🎯 Chưa đặt nhóm đích.\nVào nhóm gõ <code>/setgroup here</code> hoặc gõ <code>/setgroup &lt;id&gt;</code>." if lang == "vi" else "🎯 No target group configured.\nRun <code>/setgroup here</code> in the group or <code>/setgroup &lt;id&gt;</code>.")
        return

    arg = args[0].lower().strip()
    if arg == "here":
        if chat.type == ChatType.PRIVATE:
            await _reply(update, "❌ Lệnh <code>/setgroup here</code> chỉ dùng được trong nhóm." if lang == "vi" else "❌ <code>/setgroup here</code> can only be used in a group.")
            return
        target_id = chat.id
    else:
        try:
            target_id = int(arg)
        except ValueError:
            await _reply(update, "❌ ID nhóm phải là số nguyên (vd: <code>-1001234567890</code>)." if lang == "vi" else "❌ Group ID must be an integer.")
            return

    monitor_proxy.set_target_group_id(target_id)
    await _reply(update, f"✅ Đã đặt nhóm đích: <code>{target_id}</code>\nGiờ bạn có thể dùng <code>/monitor</code> và <code>/proxy</code>." if lang == "vi" else f"✅ Target group set to: <code>{target_id}</code>\nYou can now use <code>/monitor</code> and <code>/proxy</code>.")


async def cmd_monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    args = (update.message.text or "").split()[1:]
    cur = monitor_proxy.is_monitor_on()
    lang = _lang(update)
    target = monitor_proxy.get_target_group_id()

    if not args:
        state_str = "BẬT" if cur else "TẮT"
        target_str = f"<code>{target}</code>" if target else ("Chưa đặt — dùng /setgroup" if lang == "vi" else "Not set — use /setgroup")
        await _reply(
            update,
            f"👁️ <b>Giám sát nhóm (Monitor)</b>: <b>{state_str}</b>\n"
            f"🎯 Nhóm quan sát: {target_str}\n\n"
            f"• <code>/monitor on</code>: Bật đẩy tin nhắn nhóm về DM\n"
            f"• <code>/monitor off</code>: Tắt giám sát\n"
            f"• <code>/monitor dm on|off</code>: Báo DM của người lạ gửi bot (hiện: <b>{'BẬT' if monitor_proxy.is_monitor_dm_on() else 'TẮT'}</b>)\n"
            f"• <code>/setgroup</code>: Chọn nhóm cần quan sát"
            if lang == "vi" else
            f"👁️ <b>Group Monitor</b>: <b>{'ON' if cur else 'OFF'}</b>\n"
            f"🎯 Target group: {target_str}\n\n"
            f"• <code>/monitor on</code>: Enable forwarding to DM\n"
            f"• <code>/monitor off</code>: Disable monitor\n"
            f"• <code>/monitor dm on|off</code>: Report DMs from strangers (now: <b>{'ON' if monitor_proxy.is_monitor_dm_on() else 'OFF'}</b>)\n"
            f"• <code>/setgroup</code>: Set target group"
        )
        return

    choice = args[0].lower().strip()
    if choice == "dm" and len(args) > 1 and args[1].lower() in ("on", "off", "1", "0", "bật", "tắt"):
        on = args[1].lower() in ("on", "1", "bật")
        monitor_proxy.set_monitor_dm(on)
        await _reply(update, f"📥 Giám sát DM: <b>{'BẬT' if on else 'TẮT'}</b> (cần /monitor on)." if lang == "vi" else f"📥 DM monitor: <b>{'ON' if on else 'OFF'}</b> (requires /monitor on).")
        return
    if choice in ("on", "1", "true", "bật"):
        monitor_proxy.set_monitor(True)
        await _reply(update, "👁️ Đã <b>BẬT</b> chế độ giám sát nhóm (Monitor)." if lang == "vi" else "👁️ Group Monitor is now <b>ON</b>.")
    elif choice in ("off", "0", "false", "tắt"):
        monitor_proxy.set_monitor(False)
        await _reply(update, "👁️ Đã <b>TẮT</b> chế độ giám sát nhóm (Monitor)." if lang == "vi" else "👁️ Group Monitor is now <b>OFF</b>.")
    else:
        await _reply(update, "Usage: <code>/monitor on|off</code> · <code>/monitor dm on|off</code>")


async def cmd_proxy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    if update.effective_chat.type != ChatType.PRIVATE:
        await _reply(update, "📡 Lệnh <code>/proxy</code> chỉ dùng trong DM riêng với bot!" if _lang(update) == "vi" else "📡 <code>/proxy</code> can only be used in private DM!")
        return

    args = (update.message.text or "").split()[1:]
    cur = monitor_proxy.is_proxy_on()
    lang = _lang(update)
    target = monitor_proxy.get_target_group_id()

    if not args:
        state_str = "BẬT" if cur else "TẮT"
        target_str = f"<code>{target}</code>" if target else "⚠️ Chưa đặt (dùng /setgroup)"
        await _reply(
            update,
            f"📡 <b>Chế độ Relay 2 chiều (Proxy)</b>: <b>{state_str}</b>\n"
            f"🎯 Nhóm đích: {target_str}\n\n"
            f"📖 <b>Cách dùng khi Proxy BẬT:</b>\n"
            f"• Gõ tin nhắn thường (hoặc gửi ảnh/file/voice) → bot gửi vào nhóm\n"
            f"• <code>reply &lt;msg_id&gt; &lt;nội dung&gt;</code> → reply vào tin cụ thể trong nhóm\n"
            f"• <code>del &lt;msg_id&gt;</code> → xóa tin trong nhóm\n"
            f"• <code>edit &lt;msg_id&gt; &lt;nội dung&gt;</code> → sửa tin bot đã gửi trong nhóm\n"
            f"• <code>/proxy off</code> → tắt relay, trở lại chat AI bình thường"
            if lang == "vi" else
            f"📡 <b>2-Way Proxy Relay</b>: <b>{'ON' if cur else 'OFF'}</b>\n"
            f"🎯 Target group: {target_str}\n\n"
            f"📖 <b>Usage while Proxy is ON:</b>\n"
            f"• Type normal message (or send media) → relayed to group\n"
            f"• <code>reply &lt;msg_id&gt; &lt;content&gt;</code> → reply to group message\n"
            f"• <code>del &lt;msg_id&gt;</code> → delete group message\n"
            f"• <code>edit &lt;msg_id&gt; &lt;content&gt;</code> → edit bot's message\n"
            f"• <code>/proxy off</code> → return to normal AI chat"
        )
        return

    choice = args[0].lower().strip()
    if choice in ("on", "1", "true", "bật"):
        if not target:
            await _reply(update, "⚠️ Hãy đặt nhóm đích trước: <code>/setgroup &lt;id&gt;</code>" if lang == "vi" else "⚠️ Set target group first: <code>/setgroup &lt;id&gt;</code>")
            return
        monitor_proxy.set_proxy(True)
        await _reply(update, f"📡 Đã <b>BẬT</b> Proxy Relay tới nhóm <code>{target}</code>." if lang == "vi" else f"📡 Proxy Relay is now <b>ON</b> for group <code>{target}</code>.")
    elif choice in ("off", "0", "false", "tắt"):
        monitor_proxy.set_proxy(False)
        await _reply(update, "📡 Đã <b>TẮT</b> Proxy Relay. Trở lại chế độ chat AI." if lang == "vi" else "📡 Proxy Relay is now <b>OFF</b>. Back to AI chat.")
    else:
        await _reply(update, "Usage: <code>/proxy on|off</code>")


async def cmd_tomtat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat = update.effective_chat
    lang = _lang(update)
    args = (update.message.text or "").split()[1:]

    # Determine which group to summarize
    if chat.type in ("group", "supergroup"):
        target_chat_id = chat.id
    else:
        target_chat_id = monitor_proxy.get_target_group_id()
        if not target_chat_id:
            await _reply(update, "⚠️ Bạn đang ở DM. Hãy cấu hình nhóm đích trước: <code>/setgroup &lt;id&gt;</code>" if lang == "vi" else "⚠️ You are in DM. Configure target group first: <code>/setgroup &lt;id&gt;</code>")
            return

    count = 50
    if args and args[0].isdigit():
        count = int(args[0])

    status_msg = await update.message.reply_text("⏳ <i>Đang đọc lịch sử nhóm và tạo tóm tắt bằng Gemini...</i>" if lang == "vi" else "⏳ <i>Reading group logs and generating summary with Gemini...</i>", parse_mode="HTML")

    try:
        summary = await monitor_proxy.summarize_chat(target_chat_id, count=count, lang=lang)
        chunks = utils.split_message(summary)
        for i, ch in enumerate(chunks):
            html_out = utils.md_to_html(ch)
            try:
                if i == 0:
                    await status_msg.edit_text(html_out, parse_mode="HTML")
                else:
                    await update.message.reply_text(html_out, parse_mode="HTML")
            except Exception:
                # HTML parse failure → plain-text fallback
                if i == 0:
                    await status_msg.edit_text(ch)
                else:
                    await update.message.reply_text(ch)
    except Exception as e:
        logger.error("cmd_tomtat error: %s", e)
        try:
            await status_msg.edit_text(f"❌ Lỗi tạo tóm tắt: {e}")
        except Exception:
            pass


async def cmd_aictx(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    chat = update.effective_chat
    lang = _lang(update)
    args = (update.message.text or "").split()[1:]

    target_id = chat.id if chat.type != ChatType.PRIVATE else monitor_proxy.get_target_group_id()

    if not args:
        ram_count = len(group_context.GROUP_HISTORY.get(target_id, [])) if target_id else 0
        await _reply(
            update,
            f"🧠 <b>Cấu hình Bối Cảnh Nhóm (AI Group Context)</b>\n\n"
            f"• Nhóm hiện tại: <code>{target_id or 'Chưa chọn'}</code>\n"
            f"• Số tin đính kèm mỗi lượt AI: <b>{config.AI_CTX_MSGS}</b> tin\n"
            f"• Giới hạn ký tự tối đa: <b>{config.AI_CTX_CHARS}</b> ký tự\n"
            f"• Tin đang đệm trong RAM: <b>{ram_count}</b> tin\n\n"
            f"Lệnh:\n"
            f"• <code>/aictx &lt;số tin&gt;</code>: Thay đổi số tin gửi AI (vd: <code>/aictx 40</code>)\n"
            f"• <code>/aictx chars &lt;n&gt;</code>: Đổi trần ký tự (500–20000)\n"
            f"• <code>/aictx log on|off</code>: Bật/tắt GHI lịch sử nhóm (hiện: <b>{'BẬT' if config.GROUP_CONTEXT_ENABLED else 'TẮT'}</b>)\n"
            f"• <code>/aictx clear</code>: Xóa sạch bộ nhớ ngữ cảnh nhóm này"
            if lang == "vi" else
            f"🧠 <b>AI Group Context Configuration</b>\n\n"
            f"• Current chat: <code>{target_id or 'None'}</code>\n"
            f"• Context messages per turn: <b>{config.AI_CTX_MSGS}</b>\n"
            f"• Character limit: <b>{config.AI_CTX_CHARS}</b> chars\n"
            f"• Buffered in RAM: <b>{ram_count}</b> msgs\n\n"
            f"Commands:\n"
            f"• <code>/aictx &lt;count&gt;</code>: Set message count (e.g. <code>/aictx 40</code>)\n"
            f"• <code>/aictx chars &lt;n&gt;</code>: Set char limit (500–20000)\n"
            f"• <code>/aictx log on|off</code>: Enable/disable group history LOGGING (now: <b>{'ON' if config.GROUP_CONTEXT_ENABLED else 'OFF'}</b>)\n"
            f"• <code>/aictx clear</code>: Clear group context for this chat"
        )
        return

    sub = args[0].lower().strip()
    if sub == "clear":
        if not target_id:
            await _reply(update, "❌ Chưa xác định nhóm cần xóa ngữ cảnh.")
            return
        group_context.clear_group_context(target_id)
        await _reply(update, f"🧹 Đã xóa sạch ngữ cảnh nhóm <code>{target_id}</code>." if lang == "vi" else f"🧹 Cleared context for chat <code>{target_id}</code>.")
    elif sub.isdigit():
        new_cnt = int(sub)
        config.AI_CTX_MSGS = max(0, min(new_cnt, 100))
        await db.config_set("ai_ctx_msgs", config.AI_CTX_MSGS)
        await _reply(update, f"✅ Đã đặt số tin bối cảnh nhóm: <b>{config.AI_CTX_MSGS}</b> tin." if lang == "vi" else f"✅ Group context messages set to: <b>{config.AI_CTX_MSGS}</b>.")
    elif sub == "chars" and len(args) > 1 and args[1].isdigit():
        config.AI_CTX_CHARS = max(500, min(int(args[1]), 20000))
        await db.config_set("ai_ctx_chars", config.AI_CTX_CHARS)
        await _reply(update, f"✅ Trần ký tự bối cảnh: <b>{config.AI_CTX_CHARS}</b>." if lang == "vi" else f"✅ Context char limit: <b>{config.AI_CTX_CHARS}</b>.")
    elif sub == "log" and len(args) > 1 and args[1].lower() in ("on", "off", "1", "0", "bật", "tắt"):
        on = args[1].lower() in ("on", "1", "bật")
        config.GROUP_CONTEXT_ENABLED = on
        await db.config_set("ai_log_groups", on)
        await _reply(update,
            ("✅ Đã BẬT ghi lịch sử nhóm." if on else "✅ Đã TẮT ghi lịch sử nhóm (tin mới sẽ không được lưu; dữ liệu cũ vẫn còn — dùng /aictx clear để xóa).")
            if lang == "vi" else
            ("✅ Group history logging <b>ON</b>." if on else "✅ Group history logging <b>OFF</b> (new messages are not stored; old data remains — use /aictx clear)."))
    else:
        await _reply(update, "Usage: <code>/aictx [&lt;count&gt; | chars &lt;n&gt; | log on|off | clear]</code>")


async def cmd_encstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _owner_only(update):
        return
    stat = crypto.get_crypto_status()
    lang = _lang(update)

    avail_icon = "✅ Có sẵn" if stat["available"] else "❌ Chưa cài"
    act_icon   = "🛡️ ĐANG BẬT" if stat["active"] else "⚠️ TẮT"

    await _reply(
        update,
        f"🔐 <b>Trạng Thái Mã Hóa Fernet (Cryptography)</b>\n\n"
        f"• Thư viện cryptography : {avail_icon}\n"
        f"• Trạng thái bảo vệ     : {act_icon}\n"
        f"• Nguồn khóa (Key source): <code>{stat['source']}</code>\n\n"
        f"<i>Fernet mã hóa nội dung hội thoại AI (bảng conversations). Lịch sử nhóm (chat_history) lưu plaintext để tìm kiếm được."
        + ("\n⚠️ Khóa đang lưu cùng DB — hãy đặt biến ENCRYPTION_KEY." if stat["source"] != "env" and stat["active"] else "") + "</i>"
        if lang == "vi" else
        f"🔐 <b>Fernet Encryption Status</b>\n\n"
        f"• Library installed : {avail_icon}\n"
        f"• Protection status : {act_icon}\n"
        f"• Key source        : <code>{stat['source']}</code>\n\n"
        f"<i>Fernet encrypts AI conversation content (conversations table). Group history (chat_history) is plaintext so it stays searchable."
        + ("\n⚠️ Key is stored in the same DB — set ENCRYPTION_KEY env var." if stat["source"] != "env" and stat["active"] else "") + "</i>"
    )


# ─────────────────────────────────────────────────────────────
# /purge  /purgeuser — xóa tin hàng loạt
# ─────────────────────────────────────────────────────────────
import purge as _purge


async def _flash(bot, chat_id: int, text: str, secs: int = 4) -> None:
    try:
        m = await bot.send_message(chat_id, text, parse_mode="HTML")
        await asyncio.sleep(secs)
        await m.delete()
    except Exception:
        pass


async def cmd_purge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/purge (reply vào tin đầu) | /purge <n> | thêm `force` để vượt giới hạn 200."""
    if not _owner_only(update):
        return
    msg, chat = update.message, update.effective_chat
    lang = _lang(update)
    if chat.type == ChatType.PRIVATE:
        await _reply(update, "🧹 /purge chỉ dùng trong nhóm." if lang == "vi" else "🧹 /purge works in groups only.")
        return
    args = [a.lower() for a in (msg.text or "").split()[1:]]
    force = "force" in args
    nums = [a for a in args if a.isdigit()]

    if msg.reply_to_message:
        res = await _purge.purge_range(context.bot, chat.id, msg.reply_to_message.message_id,
                                       msg.message_id, force=force)
    elif nums:
        res = await _purge.delete_last_n(context.bot, chat.id, int(nums[0]), msg.message_id)
        try:
            await msg.delete()
        except Exception:
            pass
    else:
        await _reply(update,
            "🧹 Reply vào tin <b>đầu tiên</b> muốn xóa, hoặc dùng <code>/purge &lt;n&gt;</code> (n tin gần nhất)."
            if lang == "vi" else
            "🧹 Reply to the <b>first</b> message to delete, or use <code>/purge &lt;n&gt;</code> (last n messages).")
        return

    if not res.get("ok"):
        extra = ("\nGõ <code>/purge force</code> (reply như cũ) nếu chắc chắn." if res.get("needs_force") and lang == "vi"
                 else "\nUse <code>/purge force</code> (reply as before) if you are sure." if res.get("needs_force") else "")
        await _reply(update, f"⚠️ {res.get('error')}{extra}")
        return
    note = f" (không xóa được {res['failed']})" if res.get("failed") else ""
    await _flash(context.bot, chat.id,
                 (f"✅ Đã xóa <b>{res['deleted']}</b> tin{note}." if lang == "vi" else f"✅ Deleted <b>{res['deleted']}</b> messages{note}."))


async def cmd_purgeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/purgeuser (reply | @user | id) — xóa các tin của người đó mà bot đã ghi lại."""
    if not _owner_only(update):
        return
    msg, chat = update.message, update.effective_chat
    lang = _lang(update)
    if chat.type == ChatType.PRIVATE:
        await _reply(update, "🧹 /purgeuser chỉ dùng trong nhóm." if lang == "vi" else "🧹 /purgeuser works in groups only.")
        return
    uid, _rest = await _resolve_target(update, context, (msg.text or "").split()[1:])
    if not uid:
        await _reply(update, "Dùng: reply vào tin của người đó hoặc <code>/purgeuser @user|id</code>." if lang == "vi"
                     else "Usage: reply to their message or <code>/purgeuser @user|id</code>.")
        return
    if uid == OWNER_ID:
        await _reply(update, "❌ Không xóa hàng loạt tin của chính chủ nhân." if lang == "vi" else "❌ Refusing to purge the owner's own messages.")
        return
    res = await _purge.purge_user(context.bot, chat.id, uid)
    try:
        await msg.delete()
    except Exception:
        pass
    if res.get("note"):
        await _flash(context.bot, chat.id, f"ℹ️ {res['note']}", 6)
        return
    note = f" (không xóa được {res['failed']})" if res.get("failed") else ""
    await _flash(context.bot, chat.id,
                 (f"✅ Đã xóa <b>{res['deleted']}</b> tin của <code>{uid}</code>{note}." if lang == "vi"
                  else f"✅ Deleted <b>{res['deleted']}</b> messages from <code>{uid}</code>{note}."))
