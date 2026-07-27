"""
Telegram action tools — everything a human admin can do.
All functions accept a TelegramContext that carries the bot instance
and the current chat/message context as defaults.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from telegram import (
    Bot,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReactionTypeEmoji,
)

import state
from i18n import DEFAULT_LANG, t

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Context object (passed into every tool execution)
# ─────────────────────────────────────────────────────────────
@dataclass
class TelegramContext:
    bot: Bot
    chat_id: int
    user_id: int
    message_id: int
    thread_id: Optional[int] = None
    chat_title: str          = ""
    user_name: str           = ""
    lang: str                = DEFAULT_LANG


def _resolve_chat(ctx: TelegramContext, chat_id_arg: Any) -> int | str:
    """Return provided chat_id or fall back to current chat."""
    if chat_id_arg:
        raw = str(chat_id_arg).strip()
        if raw.lstrip("-").isdigit():
            return int(raw)
        return raw  # @username
    return ctx.chat_id


_TME_RE = re.compile(r"(?:https?://)?t\.me/(\w{5,})", re.IGNORECASE)
_TG_USER_LINK_RE = re.compile(r"tg://user\?id=(\d+)", re.IGNORECASE)


def _extract_handle_or_id(raw: str) -> tuple[Optional[int], Optional[str]]:
    """Parse deep-link forms into (numeric_id, username_handle).
    Exactly one of the two is set, or both None if `raw` matched nothing
    special (caller should treat it as a plain @username/username)."""
    m = _TG_USER_LINK_RE.search(raw)
    if m:
        return int(m.group(1)), None
    m = _TME_RE.search(raw)
    if m:
        return None, m.group(1)
    return None, None


async def _resolve_user(ctx: TelegramContext, user_id_or_username: Any) -> Optional[int]:
    """
    Resolve a tool-provided user_id argument to a numeric Telegram user ID.
    Tries, in order:
      1. Numeric ID (int, numeric string, or "tg://user?id=NNN" deep link)
         → returned as-is.
      2. "@username" / "username" / "t.me/username" link → looked up in the
         locally-learned user directory (works for anyone the bot has ever
         seen a message, mention, join/leave event, or admin-list entry
         from — which covers ordinary group members that Telegram's own
         get_chat() usually CANNOT resolve).
      3. ctx.bot.get_chat("@username") — works for channels/bots/users who
         already have a chat with the bot.
      4. Live admin-list scan of the current chat (get_chat_administrators)
         — catches admins/owners the bot hasn't directly seen chat from yet.
         Every admin found this way is also cached into the directory, so
         subsequent lookups (for any of them) become instant.

    Returns None if resolution fails.
    """
    if user_id_or_username is None:
        return None
    raw = str(user_id_or_username).strip()
    if raw.lstrip("-").isdigit():
        return int(raw)

    deep_id, deep_handle = _extract_handle_or_id(raw)
    if deep_id is not None:
        return deep_id
    handle = (deep_handle or raw.lstrip("@")).strip()
    if not handle:
        return None

    known_id = state.lookup_user_id(handle)
    if known_id:
        return known_id

    try:
        chat = await ctx.bot.get_chat(f"@{handle}")
        if getattr(chat, "id", None):
            return chat.id
    except Exception as e:
        logger.debug("[tg] get_chat fallback failed for @%s: %s", handle, e)

    # Last resort: scan the current chat's admin list. This resolves admins
    # the bot has never received a message from (common when adding the bot
    # to an already-established group) and warms the cache for everyone
    # found so future lookups — including for OTHER admins — are instant.
    try:
        admins = await ctx.bot.get_chat_administrators(ctx.chat_id)
        target_lc = handle.lower()
        found: Optional[int] = None
        for m in admins:
            au = m.user
            state.remember_user(au.id, au.username, au.full_name or "")
            if au.username and au.username.lower() == target_lc:
                found = au.id
        if found is not None:
            return found
    except Exception as e:
        logger.debug("[tg] admin-list fallback failed for @%s: %s", handle, e)

    return None


def _user_not_found_msg(raw: Any, lang: str = DEFAULT_LANG) -> str:
    handle = str(raw).strip().lstrip("@")
    suggestions = state.search_similar_usernames(handle)
    hint = (
        t("tools.user_not_found_hint", lang,
          suggestions=", ".join("@" + s for s in suggestions))
        if suggestions else ""
    )
    return t("tools.user_not_found", lang, raw=raw, hint=hint)



# ─────────────────────────────────────────────────────────────
# Tool declarations (Gemini function-calling schema)
# ─────────────────────────────────────────────────────────────
TG_TOOL_DECLS = [
    {
        "name": "tg_send_message",
        "description": (
            "Send a text message. parse_mode='HTML' enables formatting and "
            "inline clickable links: <a href='URL'>link text</a>. "
            "Also supports <b>bold</b>, <i>italic</i>, <code>code</code>. "
            "Leave parse_mode empty for plain text with no special rendering."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text":        {"type": "STRING", "description": "Message text"},
                "parse_mode":  {"type": "STRING", "description": "HTML to enable links/formatting, empty for plain text"},
                "chat_id":     {"type": "STRING", "description": "Target chat ID or @username (blank = current chat)"},
                "reply_to_id": {"type": "NUMBER", "description": "Message ID to reply to"},
                "thread_id":   {"type": "NUMBER", "description": "Topic/thread ID"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "tg_react",
        "description": (
            "React to a Telegram message with an emoji reaction. "
            "Popular emojis: 👍 ❤️ 🔥 🎉 😂 👏 🤔 😱 🤩 💯 ⚡ 🏆 🍾 💪 🫡"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "emoji":      {"type": "STRING", "description": "Reaction emoji character"},
                "message_id": {"type": "NUMBER", "description": "Message ID to react to (default: current message)"},
                "chat_id":    {"type": "STRING", "description": "Chat ID (default: current chat)"},
                "is_big":     {"type": "BOOLEAN", "description": "Send big reaction animation"},
            },
            "required": ["emoji"],
        },
    },
    {
        "name": "tg_delete_message",
        "description": "Delete a message. Requires bot to have 'Delete messages' admin permission.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id": {"type": "NUMBER", "description": "ID of message to delete"},
                "chat_id":    {"type": "STRING", "description": "Chat ID (default: current)"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "tg_pin_message",
        "description": "Pin a message in a chat. Requires admin rights.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id":           {"type": "NUMBER",  "description": "Message ID to pin"},
                "chat_id":              {"type": "STRING",  "description": "Chat ID (default: current)"},
                "disable_notification": {"type": "BOOLEAN", "description": "Pin silently (no notification)"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "tg_unpin_message",
        "description": "Unpin a specific message (or all messages if message_id omitted).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id": {"type": "NUMBER", "description": "Message ID to unpin (omit for all)"},
                "chat_id":    {"type": "STRING", "description": "Chat ID (default: current)"},
            },
        },
    },
    {
        "name": "tg_ban_user",
        "description": "Permanently ban (kick) a user from the chat. Requires admin rights.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "Telegram user ID (number) or @username." + " Bot auto-resolves @username if it has seen that user before; use tg_resolve_user to check first if unsure."},
                "chat_id": {"type": "STRING", "description": "Chat ID (default: current)"},
                "reason":  {"type": "STRING", "description": "Ban reason (optional, shown in audit log)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_unban_user",
        "description": "Unban a previously banned user and allow them to rejoin.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID (number) or @username."},
                "chat_id": {"type": "STRING", "description": "Chat ID (default: current)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_mute_user",
        "description": "Restrict a user from sending messages for a given duration.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id":          {"type": "STRING", "description": "User ID (number) or @username to mute."},
                "duration_minutes": {"type": "NUMBER", "description": "Mute duration in minutes (0 = permanent)"},
                "chat_id":          {"type": "STRING", "description": "Chat ID (default: current)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_unmute_user",
        "description": "Restore full messaging rights to a muted user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID (number) or @username."},
                "chat_id": {"type": "STRING"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_forward_message",
        "description": "Forward a message from one chat to another.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id":   {"type": "NUMBER", "description": "Message ID to forward"},
                "to_chat_id":   {"type": "STRING", "description": "Destination chat ID or @username"},
                "from_chat_id": {"type": "STRING", "description": "Source chat (default: current chat)"},
            },
            "required": ["message_id", "to_chat_id"],
        },
    },
    {
        "name": "tg_copy_message",
        "description": "Copy a message to another chat without the 'Forwarded from' label.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id":   {"type": "NUMBER", "description": "Message ID to copy"},
                "to_chat_id":   {"type": "STRING", "description": "Destination chat ID or @username"},
                "from_chat_id": {"type": "STRING", "description": "Source chat (default: current)"},
                "caption":      {"type": "STRING", "description": "Override caption (optional)"},
            },
            "required": ["message_id", "to_chat_id"],
        },
    },
    {
        "name": "tg_send_poll",
        "description": "Create an interactive poll in a Telegram chat.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "question":               {"type": "STRING", "description": "Poll question"},
                "options": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "2-10 answer options",
                },
                "chat_id":                {"type": "STRING",  "description": "Chat ID (default: current)"},
                "is_anonymous":           {"type": "BOOLEAN", "description": "Anonymous votes (default true)"},
                "allows_multiple_answers":{"type": "BOOLEAN", "description": "Allow multiple selections"},
            },
            "required": ["question", "options"],
        },
    },
    {
        "name": "tg_get_chat_info",
        "description": "Get details about a Telegram chat, channel, group, or user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "chat_id": {"type": "STRING", "description": "Chat ID or @username"},
            },
            "required": ["chat_id"],
        },
    },
    {
        "name": "tg_get_chat_members_count",
        "description": "Get the number of members in a group or channel.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "chat_id": {"type": "STRING", "description": "Chat ID or @username (default: current)"},
            },
        },
    },
    {
        "name": "tg_send_dice",
        "description": "Send an animated emoji (dice/game) to the chat.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "emoji":   {"type": "STRING", "description": "One of: 🎲 🎯 🏀 ⚽ 🎳 🎰"},
                "chat_id": {"type": "STRING", "description": "Chat ID (default: current)"},
            },
            "required": ["emoji"],
        },
    },
    {
        "name": "tg_promote_admin",
        "description": "Promote a user to admin with configurable permissions (owner only).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id":                {"type": "STRING", "description": "User ID (số) hoặc @username."},
                "chat_id":                {"type": "STRING"},
                "can_delete_messages":    {"type": "BOOLEAN"},
                "can_manage_topics":      {"type": "BOOLEAN"},
                "can_pin_messages":       {"type": "BOOLEAN"},
                "can_invite_users":       {"type": "BOOLEAN"},
                "can_restrict_members":   {"type": "BOOLEAN"},
                "custom_title":           {"type": "STRING", "description": "Custom admin title"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_demote_admin",
        "description": "Remove all admin rights from a user.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID (number) or @username."},
                "chat_id": {"type": "STRING"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_set_chat_title",
        "description": "Change the title of a group or channel.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "title":   {"type": "STRING", "description": "New chat title"},
                "chat_id": {"type": "STRING"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "tg_set_chat_description",
        "description": "Set or update the description of a group or channel.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description": {"type": "STRING"},
                "chat_id":     {"type": "STRING"},
            },
            "required": ["description"],
        },
    },
]


# ─────────────────────────────────────────────────────────────
# Tool implementations
# ─────────────────────────────────────────────────────────────
async def tg_send_message(ctx: TelegramContext, text: str, chat_id=None,
                          reply_to_id=None, thread_id=None,
                          parse_mode: str = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    thr    = int(thread_id) if thread_id else ctx.thread_id
    pm     = parse_mode.strip() or None   # None = plain text
    try:
        msg = await ctx.bot.send_message(
            chat_id             = target,
            text                = text[:4096],
            parse_mode          = pm,
            message_thread_id   = thr,
            reply_to_message_id = int(reply_to_id) if reply_to_id else None,
        )
        return t("tools.sent_message", ctx.lang, mid=msg.message_id, target=target)
    except Exception as e:
        logger.error("tg_send_message: %s", e)
        return t("tools.send_failed", ctx.lang, err=e)


async def tg_react(ctx: TelegramContext, emoji: str, message_id=None,
                   chat_id=None, is_big: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    mid    = int(message_id) if message_id else ctx.message_id
    try:
        await ctx.bot.set_message_reaction(
            chat_id    = target,
            message_id = mid,
            reaction   = [ReactionTypeEmoji(emoji=emoji)],
            is_big     = bool(is_big),
        )
        return t("tools.reacted", ctx.lang, emoji=emoji, mid=mid)
    except Exception as e:
        logger.error("tg_react: %s", e)
        return t("tools.react_failed", ctx.lang, err=e)


async def tg_delete_message(ctx: TelegramContext, message_id: int,
                             chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.delete_message(chat_id=target, message_id=int(message_id))
        return t("tools.deleted_message", ctx.lang, mid=message_id)
    except Exception as e:
        logger.error("tg_delete_message: %s", e)
        return t("tools.delete_failed", ctx.lang, err=e)


async def tg_pin_message(ctx: TelegramContext, message_id: int,
                          chat_id=None, disable_notification: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.pin_chat_message(
            chat_id              = target,
            message_id           = int(message_id),
            disable_notification = bool(disable_notification),
        )
        return t("tools.pinned_message", ctx.lang, mid=message_id)
    except Exception as e:
        logger.error("tg_pin_message: %s", e)
        return t("tools.pin_failed", ctx.lang, err=e)


async def tg_unpin_message(ctx: TelegramContext, message_id=None,
                            chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        if message_id:
            await ctx.bot.unpin_chat_message(chat_id=target,
                                             message_id=int(message_id))
            return t("tools.unpinned_message", ctx.lang, mid=message_id)
        else:
            await ctx.bot.unpin_all_chat_messages(chat_id=target)
            return t("tools.unpinned_all", ctx.lang)
    except Exception as e:
        logger.error("tg_unpin: %s", e)
        return t("tools.unpin_failed", ctx.lang, err=e)


async def tg_ban_user(ctx: TelegramContext, user_id: int,
                       chat_id=None, reason: str = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.ban_chat_member(chat_id=target, user_id=uid)
        if reason:
            return t("tools.banned_user_reason", ctx.lang, uid=uid, reason=reason)
        return t("tools.banned_user", ctx.lang, uid=uid)
    except Exception as e:
        logger.error("tg_ban_user: %s", e)
        return t("tools.ban_failed", ctx.lang, err=e)


async def tg_unban_user(ctx: TelegramContext, user_id: int,
                         chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.unban_chat_member(
            chat_id=target, user_id=uid, only_if_banned=True
        )
        return t("tools.unbanned_user", ctx.lang, uid=uid)
    except Exception as e:
        logger.error("tg_unban: %s", e)
        return t("tools.unban_failed", ctx.lang, err=e)


async def tg_mute_user(ctx: TelegramContext, user_id: int,
                        duration_minutes: float = 0, chat_id=None) -> str:
    target  = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    perms   = ChatPermissions(can_send_messages=False)
    until   = None
    if duration_minutes and duration_minutes > 0:
        until = datetime.now(tz=timezone.utc) + timedelta(minutes=float(duration_minutes))
    try:
        await ctx.bot.restrict_chat_member(
            chat_id    = target,
            user_id    = uid,
            permissions= perms,
            until_date = until,
        )
        dur = (t("tools.mute_minutes", ctx.lang, n=duration_minutes) if duration_minutes
               else t("tools.mute_forever", ctx.lang))
        return t("tools.muted_user", ctx.lang, uid=uid, dur=dur)
    except Exception as e:
        logger.error("tg_mute: %s", e)
        return t("tools.mute_failed", ctx.lang, err=e)


async def tg_unmute_user(ctx: TelegramContext, user_id: int,
                          chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    perms  = ChatPermissions(
        can_send_messages        = True,
        can_send_polls           = True,
        can_send_other_messages  = True,
        can_add_web_page_previews= True,
        can_change_info          = False,
        can_invite_users         = True,
        can_pin_messages         = False,
    )
    try:
        await ctx.bot.restrict_chat_member(
            chat_id=target, user_id=uid, permissions=perms
        )
        return t("tools.unmuted_user", ctx.lang, uid=uid)
    except Exception as e:
        logger.error("tg_unmute: %s", e)
        return t("tools.unmute_failed", ctx.lang, err=e)


async def tg_forward_message(ctx: TelegramContext, message_id: int,
                              to_chat_id: str, from_chat_id=None) -> str:
    src  = _resolve_chat(ctx, from_chat_id)
    dest = _resolve_chat(ctx, to_chat_id)
    try:
        await ctx.bot.forward_message(
            chat_id      = dest,
            from_chat_id = src,
            message_id   = int(message_id),
        )
        return t("tools.forwarded_message", ctx.lang, mid=message_id, dest=dest)
    except Exception as e:
        logger.error("tg_forward: %s", e)
        return t("tools.forward_failed", ctx.lang, err=e)


async def tg_copy_message(ctx: TelegramContext, message_id: int,
                           to_chat_id: str, from_chat_id=None,
                           caption: str = None) -> str:
    src  = _resolve_chat(ctx, from_chat_id)
    dest = _resolve_chat(ctx, to_chat_id)
    try:
        kwargs: dict = {"chat_id": dest, "from_chat_id": src,
                        "message_id": int(message_id)}
        if caption:
            kwargs["caption"] = caption
        await ctx.bot.copy_message(**kwargs)
        return t("tools.copied_message", ctx.lang, mid=message_id, dest=dest)
    except Exception as e:
        logger.error("tg_copy: %s", e)
        return t("tools.copy_failed", ctx.lang, err=e)


async def tg_send_poll(ctx: TelegramContext, question: str,
                        options: list[str], chat_id=None,
                        is_anonymous: bool = True,
                        allows_multiple_answers: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    opts   = [str(o) for o in options[:10]]
    if len(opts) < 2:
        return t("tools.poll_needs_options", ctx.lang)
    try:
        msg = await ctx.bot.send_poll(
            chat_id                  = target,
            question                 = question[:300],
            options                  = opts,
            is_anonymous             = bool(is_anonymous),
            allows_multiple_answers  = bool(allows_multiple_answers),
            message_thread_id        = ctx.thread_id,
        )
        return t("tools.poll_created", ctx.lang, mid=msg.message_id, n=len(opts))
    except Exception as e:
        logger.error("tg_send_poll: %s", e)
        return t("tools.poll_failed", ctx.lang, err=e)


async def tg_get_chat_info(ctx: TelegramContext, chat_id: str) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        chat = await ctx.bot.get_chat(chat_id=target)
        lines = [
            t("tools.chat_info_name", ctx.lang, name=chat.effective_name),
            t("tools.chat_info_id", ctx.lang, id=chat.id),
            t("tools.chat_info_type", ctx.lang, type=chat.type),
        ]
        if chat.username:
            lines.append(t("tools.chat_info_username", ctx.lang, username=chat.username))
        if chat.description:
            lines.append(t("tools.chat_info_description", ctx.lang, desc=chat.description[:300]))
        if chat.invite_link:
            lines.append(t("tools.chat_info_invite", ctx.lang, link=chat.invite_link))
        return "\n".join(lines)
    except Exception as e:
        logger.error("tg_get_chat_info: %s", e)
        return t("tools.get_chat_info_failed", ctx.lang, err=e)


async def tg_get_chat_members_count(ctx: TelegramContext,
                                    chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        count = await ctx.bot.get_chat_member_count(chat_id=target)
        return t("tools.members_count", ctx.lang, target=target, count=count)
    except Exception as e:
        return t("tools.members_count_failed", ctx.lang, err=e)


async def tg_send_dice(ctx: TelegramContext, emoji: str,
                        chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    valid  = {"🎲", "🎯", "🏀", "⚽", "🎳", "🎰"}
    if emoji not in valid:
        emoji = "🎲"
    try:
        msg = await ctx.bot.send_dice(
            chat_id=target, emoji=emoji, message_thread_id=ctx.thread_id
        )
        return t("tools.dice_sent", ctx.lang, emoji=emoji, value=msg.dice.value)
    except Exception as e:
        return t("tools.dice_failed", ctx.lang, err=e)


async def tg_promote_admin(ctx: TelegramContext, user_id: int,
                            chat_id=None,
                            can_delete_messages: bool = True,
                            can_manage_topics:   bool = True,
                            can_pin_messages:    bool = True,
                            can_invite_users:    bool = True,
                            can_restrict_members:bool = False,
                            custom_title: str    = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.promote_chat_member(
            chat_id               = target,
            user_id               = uid,
            can_delete_messages   = can_delete_messages,
            can_manage_topics     = can_manage_topics,
            can_pin_messages      = can_pin_messages,
            can_invite_users      = can_invite_users,
            can_restrict_members  = can_restrict_members,
            can_manage_chat       = True,
        )
        if custom_title:
            await ctx.bot.set_chat_administrator_custom_title(
                chat_id=target, user_id=uid, custom_title=custom_title[:16]
            )
        return t("tools.promoted_admin", ctx.lang, uid=uid)
    except Exception as e:
        return t("tools.promote_failed", ctx.lang, err=e)


async def tg_demote_admin(ctx: TelegramContext, user_id: int,
                           chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.promote_chat_member(
            chat_id               = target,
            user_id               = uid,
            can_manage_chat       = False,
            can_delete_messages   = False,
            can_manage_video_chats= False,
            can_restrict_members  = False,
            can_promote_members   = False,
            can_change_info       = False,
            can_invite_users      = False,
            can_pin_messages      = False,
        )
        return t("tools.demoted_admin", ctx.lang, uid=uid)
    except Exception as e:
        return t("tools.demote_failed", ctx.lang, err=e)


async def tg_set_chat_title(ctx: TelegramContext, title: str,
                             chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.set_chat_title(chat_id=target, title=title[:255])
        return t("tools.title_changed", ctx.lang, title=title)
    except Exception as e:
        return t("tools.title_failed", ctx.lang, err=e)


async def tg_set_chat_description(ctx: TelegramContext, description: str,
                                   chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.set_chat_description(chat_id=target, description=description[:255])
        return t("tools.description_updated", ctx.lang)
    except Exception as e:
        return t("tools.description_failed", ctx.lang, err=e)


# ─────────────────────────────────────────────────────────────
# Dispatcher map  name → coroutine
# ─────────────────────────────────────────────────────────────
TG_HANDLERS: dict[str, Any] = {
    "tg_send_message":          tg_send_message,
    "tg_react":                 tg_react,
    "tg_delete_message":        tg_delete_message,
    "tg_pin_message":           tg_pin_message,
    "tg_unpin_message":         tg_unpin_message,
    "tg_ban_user":              tg_ban_user,
    "tg_unban_user":            tg_unban_user,
    "tg_mute_user":             tg_mute_user,
    "tg_unmute_user":           tg_unmute_user,
    "tg_forward_message":       tg_forward_message,
    "tg_copy_message":          tg_copy_message,
    "tg_send_poll":             tg_send_poll,
    "tg_get_chat_info":         tg_get_chat_info,
    "tg_get_chat_members_count":tg_get_chat_members_count,
    "tg_send_dice":             tg_send_dice,
    "tg_promote_admin":         tg_promote_admin,
    "tg_demote_admin":          tg_demote_admin,
    "tg_set_chat_title":        tg_set_chat_title,
    "tg_set_chat_description":  tg_set_chat_description,
}

# Status messages displayed while tools run
TOOL_STATUS: dict[str, str] = {
    "web_search":               "tool_status.web_search",
    "fetch_url":                "tool_status.fetch_url",
    "arxiv_search":             "tool_status.arxiv_search",
    "run_python":               "tool_status.run_python",
    "tg_send_message":          "tool_status.tg_send_message",
    "tg_react":                 "tool_status.tg_react",
    "tg_delete_message":        "tool_status.tg_delete_message",
    "tg_pin_message":           "tool_status.tg_pin_message",
    "tg_unpin_message":         "tool_status.tg_unpin_message",
    "tg_ban_user":              "tool_status.tg_ban_user",
    "tg_unban_user":            "tool_status.tg_unban_user",
    "tg_mute_user":             "tool_status.tg_mute_user",
    "tg_unmute_user":           "tool_status.tg_unmute_user",
    "tg_forward_message":       "tool_status.tg_forward_message",
    "tg_copy_message":          "tool_status.tg_copy_message",
    "tg_send_poll":             "tool_status.tg_send_poll",
    "tg_get_chat_info":         "tool_status.tg_get_chat_info",
    "tg_get_chat_members_count":"tool_status.tg_get_chat_members_count",
    "tg_send_dice":             "tool_status.tg_send_dice",
    "tg_promote_admin":         "tool_status.tg_promote_admin",
    "tg_demote_admin":          "tool_status.tg_demote_admin",
    "tg_set_chat_title":        "tool_status.tg_set_chat_title",
    "tg_set_chat_description":  "tool_status.tg_set_chat_description",
}


def tool_status_text(tool_name: str, lang: str = DEFAULT_LANG) -> str:
    """Localized 'tool is running…' label, with a generic fallback."""
    key = TOOL_STATUS.get(tool_name)
    return t(key, lang) if key else f"⚙️ {tool_name}…"


# ─────────────────────────────────────────────────────────────
# NEW: tg_send_photo  &  tg_edit_message
# ─────────────────────────────────────────────────────────────
TG_TOOL_DECLS.extend([
    {
        "name": "tg_send_photo",
        "description": (
            "Send a photo to a Telegram chat using a URL or file_id. "
            "Optionally add a caption (Markdown supported)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "photo":     {"type": "STRING", "description": "Photo URL (https://…) or Telegram file_id"},
                "caption":   {"type": "STRING", "description": "Optional caption text (Markdown OK)"},
                "chat_id":   {"type": "STRING", "description": "Target chat ID or @username (blank = current)"},
                "thread_id": {"type": "NUMBER", "description": "Topic/thread ID"},
            },
            "required": ["photo"],
        },
    },
    {
        "name": "tg_edit_message",
        "description": (
            "Edit the text of a previously sent message. "
            "The bot must be the author of the message."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "message_id": {"type": "NUMBER", "description": "ID of the message to edit"},
                "text":       {"type": "STRING", "description": "New message text"},
                "chat_id":    {"type": "STRING", "description": "Chat ID (default: current)"},
            },
            "required": ["message_id", "text"],
        },
    },
])


async def tg_send_photo(ctx: TelegramContext, photo: str,
                        caption: str = "", chat_id=None, thread_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    thr    = int(thread_id) if thread_id else ctx.thread_id
    try:
        msg = await ctx.bot.send_photo(
            chat_id           = target,
            photo             = photo,
            caption           = caption[:1024] if caption else None,
            parse_mode        = "HTML" if caption else None,
            message_thread_id = thr,
        )
        return t("tools.photo_sent", ctx.lang, mid=msg.message_id, target=target)
    except Exception as e:
        logger.error("tg_send_photo: %s", e)
        return t("tools.photo_failed", ctx.lang, err=e)


async def tg_edit_message(ctx: TelegramContext, message_id: int,
                          text: str, chat_id=None,
                          parse_mode: str = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    pm     = parse_mode.strip() or None
    try:
        await ctx.bot.edit_message_text(
            chat_id    = target,
            message_id = int(message_id),
            text       = text[:4096],
            parse_mode = pm,
        )
        return t("tools.message_edited", ctx.lang, mid=message_id)
    except Exception as e:
        logger.error("tg_edit_message: %s", e)
        return t("tools.edit_failed", ctx.lang, err=e)


# Register new handlers + status labels
TG_HANDLERS["tg_send_photo"]    = tg_send_photo
TG_HANDLERS["tg_edit_message"]  = tg_edit_message
TOOL_STATUS["tg_send_photo"] = "tool_status.tg_send_photo"
TOOL_STATUS["tg_edit_message"] = "tool_status.tg_edit_message"


# ─────────────────────────────────────────────────────────────
# NEW: tg_send_sticker  &  tg_send_animation
# ─────────────────────────────────────────────────────────────
TG_TOOL_DECLS.extend([
    {
        "name": "tg_send_sticker",
        "description": (
            "Send a sticker to a Telegram chat. "
            "Pass a Telegram file_id (from any sticker the bot has seen) "
            "or a public URL to a .webp / .tgs / .webm file."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "sticker":     {"type": "STRING", "description": "Sticker file_id or .webp/.tgs URL"},
                "chat_id":     {"type": "STRING", "description": "Target chat ID or @username (blank = current)"},
                "reply_to_id": {"type": "NUMBER", "description": "Message ID to reply to"},
                "thread_id":   {"type": "NUMBER", "description": "Topic/thread ID"},
            },
            "required": ["sticker"],
        },
    },
    {
        "name": "tg_send_animation",
        "description": (
            "Send a GIF or video animation to a Telegram chat. "
            "Pass a Telegram file_id or a public URL to a .gif / .mp4 file. "
            "Optional caption supports HTML formatting."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "animation":   {"type": "STRING", "description": "GIF file_id or .gif/.mp4 URL"},
                "caption":     {"type": "STRING", "description": "Optional caption (HTML OK: <b>, <a href=...>, etc.)"},
                "chat_id":     {"type": "STRING", "description": "Target chat ID or @username (blank = current)"},
                "reply_to_id": {"type": "NUMBER", "description": "Message ID to reply to"},
                "thread_id":   {"type": "NUMBER", "description": "Topic/thread ID"},
            },
            "required": ["animation"],
        },
    },
])


async def tg_send_sticker(ctx: TelegramContext, sticker: str,
                          chat_id=None, reply_to_id=None, thread_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    thr    = int(thread_id) if thread_id else ctx.thread_id
    try:
        msg = await ctx.bot.send_sticker(
            chat_id             = target,
            sticker             = sticker,
            message_thread_id   = thr,
            reply_to_message_id = int(reply_to_id) if reply_to_id else None,
        )
        return t("tools.sticker_sent", ctx.lang, mid=msg.message_id, target=target)
    except Exception as e:
        logger.error("tg_send_sticker: %s", e)
        return t("tools.sticker_failed", ctx.lang, err=e)


async def tg_send_animation(ctx: TelegramContext, animation: str,
                            caption: str = "", chat_id=None,
                            reply_to_id=None, thread_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    thr    = int(thread_id) if thread_id else ctx.thread_id
    try:
        msg = await ctx.bot.send_animation(
            chat_id             = target,
            animation           = animation,
            caption             = caption[:1024] if caption else None,
            parse_mode          = "HTML" if caption else None,
            message_thread_id   = thr,
            reply_to_message_id = int(reply_to_id) if reply_to_id else None,
        )
        return t("tools.animation_sent", ctx.lang, mid=msg.message_id, target=target)
    except Exception as e:
        logger.error("tg_send_animation: %s", e)
        return t("tools.animation_failed", ctx.lang, err=e)


# Register handlers + status labels
TG_HANDLERS["tg_send_sticker"]   = tg_send_sticker
TG_HANDLERS["tg_send_animation"] = tg_send_animation
TOOL_STATUS["tg_send_sticker"] = "tool_status.tg_send_sticker"
TOOL_STATUS["tg_send_animation"] = "tool_status.tg_send_animation"


# ═════════════════════════════════════════════════════════════
# UPGRADE: tg_edit_message  — hỗ trợ cả text lẫn media message
# ═════════════════════════════════════════════════════════════
#
# Vấn đề cũ: edit_message_text() fail với "there is no text in the message"
# khi tin nhắn đính kèm ảnh/file.  Phải dùng edit_message_caption() thay thế.
#
# Fix: thử edit_message_text → nếu lỗi "no text" → fallback edit_message_caption
#
# Ghi đè handler đã đăng ký ở trên:

async def tg_edit_message(ctx: TelegramContext, message_id: int,
                          text: str, chat_id=None,
                          parse_mode: str = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    mid    = int(message_id)
    pm     = parse_mode.strip() or None

    # Thử edit text trước (cho tin nhắn thuần text)
    try:
        await ctx.bot.edit_message_text(
            chat_id    = target,
            message_id = mid,
            text       = text[:4096],
            parse_mode = pm,
        )
        return t("tools.message_edited", ctx.lang, mid=message_id)
    except Exception as e:
        err = str(e).lower()
        # Telegram reports this error when the message has media (photo/file/video...)
        is_media_msg = (
            "there is no text in the message to edit" in err
            or "message can't be edited" in err
        )
        if not is_media_msg:
            logger.error("tg_edit_message text: %s", e)
            return t("tools.edit_failed", ctx.lang, err=e)

    # Fallback: edit the caption of a media message
    try:
        await ctx.bot.edit_message_caption(
            chat_id    = target,
            message_id = mid,
            caption    = text[:1024],
            parse_mode = pm,
        )
        return t("tools.caption_edited", ctx.lang, mid=message_id)
    except Exception as e2:
        logger.error("tg_edit_message caption fallback: %s", e2)
        return t("tools.caption_edit_failed", ctx.lang, err=e2)


# Cập nhật dispatcher (ghi đè entry cũ)
TG_HANDLERS["tg_edit_message"] = tg_edit_message


# ═════════════════════════════════════════════════════════════
# NEW: tg_send_document — gửi file mọi định dạng (RAM cache)
# ═════════════════════════════════════════════════════════════
import io as _io
import mimetypes as _mimetypes

import file_cache as _fc
from telegram import InputFile as _InputFile

TG_TOOL_DECLS.append({
    "name": "tg_send_document",
    "description": (
        "Gửi file bất kỳ định dạng tới chat Telegram. "
        "Truyền URL công khai hoặc Telegram file_id. "
        "Tự động nhận dạng loại file và dùng đúng method: "
        "audio → send_audio, video → send_video, image → send_photo, "
        "còn lại → send_document. "
        "File được cache trong RAM để lần sau gửi lại nhanh hơn (không upload lại). "
        "Giới hạn: 200 MB."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_ref":   {
                "type": "STRING",
                "description": "URL công khai (https://...) hoặc Telegram file_id",
            },
            "caption":    {"type": "STRING",  "description": "Caption (HTML OK)"},
            "chat_id":    {"type": "STRING",  "description": "Chat ID hoặc @username (mặc định: chat hiện tại)"},
            "thread_id":  {"type": "NUMBER",  "description": "Topic/thread ID"},
            "filename":   {"type": "STRING",  "description": "Tên file hiển thị (tuỳ chọn, ghi đè tên tự đoán)"},
            "force_doc":  {"type": "BOOLEAN", "description": "Luôn dùng send_document thay vì auto-detect"},
        },
        "required": ["file_ref"],
    },
})


def _pick_send_method(mime: str, force_doc: bool):
    """Chọn method Telegram phù hợp theo MIME type."""
    if force_doc:
        return "document"
    if not mime:
        return "document"
    m = mime.split(";")[0].strip().lower()
    if m.startswith("image/"):
        return "photo"
    if m.startswith("audio/") or m in ("application/ogg",):
        return "audio"
    if m.startswith("video/"):
        return "video"
    return "document"


async def tg_send_document(
    ctx: TelegramContext,
    file_ref: str,
    caption: str   = "",
    chat_id        = None,
    thread_id      = None,
    filename: str  = "",
    force_doc: bool = False,
) -> str:
    target   = _resolve_chat(ctx, chat_id)
    thr      = int(thread_id) if thread_id else ctx.thread_id
    cap      = caption[:1024] if caption else None
    pm       = "HTML" if cap else None
    cache_key: str | None = None

    # ── Phân loại: URL hay file_id ────────────────────────────
    is_url = file_ref.startswith("http://") or file_ref.startswith("https://")

    if is_url:
        cache_key = file_ref
        entry     = _fc.get(file_ref)

        if entry and entry.tg_file_id:
            # ✅ Đã upload trước rồi → dùng file_id (không tốn bandwidth)
            send_input = entry.tg_file_id
            mime       = entry.mime
            fname      = filename or entry.filename
            logger.info("[tg_send_document] Reuse file_id cho %s", file_ref[:60])
        else:
            if not entry:
                # Tải về RAM
                entry = await _fc.download(file_ref)
                if not entry:
                    return t("tools.file_url_fetch_failed", ctx.lang, ref=file_ref)

            fname = filename or entry.filename
            buf   = _io.BytesIO(entry.data)
            buf.name = fname
            send_input = _InputFile(buf, filename=fname)
            mime       = entry.mime
    else:
        # Telegram file_id — gửi trực tiếp
        send_input = file_ref
        mime       = ""
        fname      = filename or "file"
        cache_key  = None

    method = _pick_send_method(mime, force_doc)
    logger.info("[tg_send_document] method=%s file=%s", method, fname)

    try:
        msg = None
        if method == "photo":
            msg = await ctx.bot.send_photo(
                chat_id=target, photo=send_input,
                caption=cap, parse_mode=pm, message_thread_id=thr,
            )
            tg_fid = msg.photo[-1].file_id if msg.photo else None

        elif method == "audio":
            msg = await ctx.bot.send_audio(
                chat_id=target, audio=send_input,
                caption=cap, parse_mode=pm, message_thread_id=thr,
                filename=fname,
            )
            tg_fid = msg.audio.file_id if msg.audio else None

        elif method == "video":
            msg = await ctx.bot.send_video(
                chat_id=target, video=send_input,
                caption=cap, parse_mode=pm, message_thread_id=thr,
                filename=fname,
            )
            tg_fid = msg.video.file_id if msg.video else None

        else:  # document
            msg = await ctx.bot.send_document(
                chat_id=target, document=send_input,
                caption=cap, parse_mode=pm, message_thread_id=thr,
                filename=fname,
            )
            tg_fid = msg.document.file_id if msg.document else None

        # Cache Telegram file_id để lần sau không cần upload lại
        if cache_key and tg_fid:
            _fc.set_tg_file_id(cache_key, tg_fid)
            logger.info("[tg_send_document] Đã lưu file_id cho %s", cache_key[:60])

        size_info = f"{len(entry.data) // 1024} KB" if is_url and entry else fname
        return t("tools.file_sent", ctx.lang, method=method, fname=fname, size=size_info, target=target, mid=msg.message_id)

    except Exception as e:
        logger.error("tg_send_document: %s", e)
        return t("tools.file_send_failed", ctx.lang, err=e)


# Đăng ký handler + status
TG_HANDLERS["tg_send_document"] = tg_send_document
TOOL_STATUS["tg_send_document"] = "tool_status.tg_send_document"


# ═════════════════════════════════════════════════════════════════════════════
# NEW TOOLS: leave_chat, invite_user, create_invite_link, send_media_group,
#            get_user_info
# ═════════════════════════════════════════════════════════════════════════════
from telegram import InputMediaPhoto as _IMP, InputMediaVideo as _IMV

TG_TOOL_DECLS.extend([
    {
        "name": "tg_leave_chat",
        "description": "Bot tự thoát khỏi một nhóm/kênh.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "chat_id": {"type": "STRING", "description": "Chat ID hoặc @username (mặc định: chat hiện tại)"},
            },
        },
    },
    {
        "name": "tg_create_invite_link",
        "description": "Tạo link mời vào nhóm/kênh. Có thể giới hạn số lần dùng và thời gian hết hạn.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "chat_id":       {"type": "STRING", "description": "Chat ID (mặc định: hiện tại)"},
                "name":          {"type": "STRING", "description": "Tên link (tuỳ chọn)"},
                "expire_hours":  {"type": "NUMBER", "description": "Hết hạn sau N giờ (0 = không hết hạn)"},
                "member_limit":  {"type": "NUMBER", "description": "Giới hạn số lượt dùng (0 = không giới hạn)"},
                "creates_join_request": {"type": "BOOLEAN", "description": "Yêu cầu duyệt thay vì vào thẳng"},
            },
        },
    },
    {
        "name": "tg_invite_user",
        "description": "Thêm trực tiếp một user vào nhóm/kênh (bot phải có quyền Invite Users).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id":  {"type": "STRING", "description": "Telegram user ID (số) hoặc @username."},
                "chat_id":  {"type": "STRING", "description": "Chat ID đích (mặc định: hiện tại)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_resolve_user",
        "description": (
            "Tra numeric Telegram user ID từ @username (hoặc link t.me/username, "
            "tg://user?id=...). Dùng khi cần xác nhận user_id trước khi "
            "ban/mute/warn/promote/... hoặc khi muốn báo lỗi rõ ràng nếu bot "
            "chưa từng thấy user đó (thay vì để hành động thất bại). "
            "Resolve được nếu: bot đã từng thấy tin nhắn/mention/join-leave của "
            "user này, HOẶC user đó hiện là admin của chat hiện tại."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "username": {"type": "STRING", "description": "@username, username, hoặc link t.me/username / tg://user?id=..."},
            },
            "required": ["username"],
        },
    },
    {
        "name": "tg_send_media_group",
        "description": (
            "Gửi album gồm nhiều ảnh và/hoặc video trong một tin nhắn duy nhất. "
            "Truyền danh sách URL hoặc file_id. "
            "Tối đa 10 media mỗi album. Caption chỉ áp dụng cho media đầu tiên."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "media": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "type":    {"type": "STRING", "description": "photo hoặc video"},
                            "media":   {"type": "STRING", "description": "URL hoặc file_id"},
                            "caption": {"type": "STRING", "description": "Caption (chỉ item đầu tiên)"},
                        },
                    },
                    "description": "Danh sách media [{type, media, caption?}]",
                },
                "chat_id":   {"type": "STRING", "description": "Chat ID (mặc định: hiện tại)"},
                "thread_id": {"type": "NUMBER", "description": "Topic/thread ID"},
            },
            "required": ["media"],
        },
    },
    {
        "name": "tg_get_user_info",
        "description": "Lấy thông tin chi tiết về một user Telegram: tên, username, status trong nhóm, v.v.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "Telegram user ID (số) hoặc @username."},
                "chat_id": {"type": "STRING", "description": "Chat để kiểm tra status (mặc định: hiện tại)"},
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "tg_set_user_title",
        "description": "Đặt title tuỳ chỉnh cho admin trong nhóm.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "user_id": {"type": "STRING", "description": "User ID (số) hoặc @username."},
                "title":   {"type": "STRING", "description": "Title hiển thị (tối đa 16 ký tự)"},
                "chat_id": {"type": "STRING"},
            },
            "required": ["user_id", "title"],
        },
    },
])


async def tg_leave_chat(ctx: TelegramContext, chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.leave_chat(chat_id=target)
        return t("tools.left_chat", ctx.lang, target=target)
    except Exception as e:
        logger.error("tg_leave_chat: %s", e)
        return t("tools.leave_chat_failed", ctx.lang, err=e)


async def tg_create_invite_link(ctx: TelegramContext, chat_id=None,
                                 name: str = "", expire_hours: float = 0,
                                 member_limit: int = 0,
                                 creates_join_request: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    until  = None
    if expire_hours and expire_hours > 0:
        until = datetime.now(tz=timezone.utc) + timedelta(hours=float(expire_hours))
    try:
        link = await ctx.bot.create_chat_invite_link(
            chat_id              = target,
            name                 = name[:32] if name else None,
            expire_date          = until,
            member_limit         = int(member_limit) if member_limit else None,
            creates_join_request = bool(creates_join_request),
        )
        parts = [t("tools.invite_link_created", ctx.lang, target=target),
                 t("tools.invite_link_line", ctx.lang, link=link.invite_link)]
        if name:
            parts.append(t("tools.invite_link_name", ctx.lang, name=name))
        if expire_hours:
            parts.append(t("tools.invite_link_expiry", ctx.lang, hours=expire_hours))
        if member_limit:
            parts.append(t("tools.invite_link_limit", ctx.lang, limit=member_limit))
        return "\n".join(parts)
    except Exception as e:
        logger.error("tg_create_invite_link: %s", e)
        return t("tools.invite_link_failed", ctx.lang, err=e)


async def tg_invite_user(ctx: TelegramContext, user_id: int, chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.add_chat_member(chat_id=target, user_id=uid)
        return t("tools.invited_user", ctx.lang, uid=uid, target=target)
    except Exception as e:
        logger.error("tg_invite_user: %s", e)
        return t("tools.invite_user_failed", ctx.lang, err=e)


async def tg_resolve_user(ctx: TelegramContext, username: str) -> str:
    handle = str(username).strip().lstrip("@")
    if not handle:
        return t("tools.resolve_missing_username", ctx.lang)
    uid = await _resolve_user(ctx, f"@{handle}")
    if uid is None:
        return _user_not_found_msg(f"@{handle}", ctx.lang)
    known = state.get_known_user(uid)
    extra = f" ({known['name']})" if known and known.get("name") else ""
    return t("tools.resolved_user", ctx.lang, handle=handle, uid=uid, extra=extra)


async def tg_send_media_group(ctx: TelegramContext, media: list,
                               chat_id=None, thread_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    thr    = int(thread_id) if thread_id else ctx.thread_id
    if not media:
        return t("tools.media_group_empty", ctx.lang)

    items = []
    for i, m in enumerate(media[:10]):
        kind    = str(m.get("type", "photo")).lower()
        src     = m.get("media", "")
        caption = m.get("caption", "") if i == 0 else None
        if not src:
            continue
        if kind == "video":
            items.append(_IMV(media=src, caption=caption, parse_mode="HTML" if caption else None))
        else:
            items.append(_IMP(media=src, caption=caption, parse_mode="HTML" if caption else None))

    if not items:
        return t("tools.media_group_invalid", ctx.lang)
    try:
        msgs = await ctx.bot.send_media_group(
            chat_id=target, media=items, message_thread_id=thr
        )
        return t("tools.media_group_sent", ctx.lang, n=len(msgs), target=target)
    except Exception as e:
        logger.error("tg_send_media_group: %s", e)
        return t("tools.media_group_failed", ctx.lang, err=e)


async def tg_get_user_info(ctx: TelegramContext, user_id: int, chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    lines  = []
    try:
        member = await ctx.bot.get_chat_member(chat_id=target, user_id=uid)
        u = member.user
        lines += [
            t("tools.user_info_name", ctx.lang, name=u.full_name),
            t("tools.user_info_id", ctx.lang, id=u.id),
        ]
        if u.username:
            lines.append(t("tools.user_info_username", ctx.lang, username=u.username))
        lines.append(t("tools.user_info_status", ctx.lang, status=member.status))
        if hasattr(member, "custom_title") and member.custom_title:
            lines.append(t("tools.user_info_title", ctx.lang, title=member.custom_title))
        if u.is_bot:
            lines.append(t("tools.user_info_is_bot", ctx.lang))
    except Exception:
        known = state.get_known_user(uid)
        lines.append(t("tools.user_info_fetch_failed", ctx.lang, uid=uid))
        if known:
            if known.get("name"):
                lines.append(t("tools.user_info_name", ctx.lang, name=known['name']))
            if known.get("username"):
                lines.append(t("tools.user_info_username", ctx.lang, username=known['username']))
    return "\n".join(lines) if lines else t("tools.user_info_not_found", ctx.lang, uid=uid)


async def tg_set_user_title(ctx: TelegramContext, user_id: int,
                             title: str, chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    uid = await _resolve_user(ctx, user_id)
    if uid is None:
        return _user_not_found_msg(user_id, ctx.lang)
    try:
        await ctx.bot.set_chat_administrator_custom_title(
            chat_id=target, user_id=uid, custom_title=title[:16]
        )
        return t("tools.user_title_set", ctx.lang, title=title, uid=uid)
    except Exception as e:
        return t("tools.user_title_failed", ctx.lang, err=e)


TG_HANDLERS["tg_leave_chat"]        = tg_leave_chat
TG_HANDLERS["tg_create_invite_link"]= tg_create_invite_link
TG_HANDLERS["tg_invite_user"]       = tg_invite_user
TG_HANDLERS["tg_resolve_user"]      = tg_resolve_user
TG_HANDLERS["tg_send_media_group"]  = tg_send_media_group
TG_HANDLERS["tg_get_user_info"]     = tg_get_user_info
TG_HANDLERS["tg_set_user_title"]    = tg_set_user_title

TOOL_STATUS["tg_leave_chat"] = "tool_status.tg_leave_chat"
TOOL_STATUS["tg_create_invite_link"] = "tool_status.tg_create_invite_link"
TOOL_STATUS["tg_invite_user"] = "tool_status.tg_invite_user"
TOOL_STATUS["tg_resolve_user"] = "tool_status.tg_resolve_user"
TOOL_STATUS["tg_send_media_group"] = "tool_status.tg_send_media_group"
TOOL_STATUS["tg_get_user_info"] = "tool_status.tg_get_user_info"
TOOL_STATUS["tg_set_user_title"] = "tool_status.tg_set_user_title"
