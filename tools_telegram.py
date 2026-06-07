"""
Telegram action tools — everything a human admin can do.
All functions accept a TelegramContext that carries the bot instance
and the current chat/message context as defaults.
"""
from __future__ import annotations

import logging
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


def _resolve_chat(ctx: TelegramContext, chat_id_arg: Any) -> int | str:
    """Return provided chat_id or fall back to current chat."""
    if chat_id_arg:
        raw = str(chat_id_arg).strip()
        if raw.lstrip("-").isdigit():
            return int(raw)
        return raw  # @username
    return ctx.chat_id


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
                "user_id": {"type": "NUMBER", "description": "Telegram user ID to ban"},
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
                "user_id": {"type": "NUMBER"},
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
                "user_id":          {"type": "NUMBER", "description": "User ID to mute"},
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
                "user_id": {"type": "NUMBER"},
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
                "user_id":                {"type": "NUMBER"},
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
                "user_id": {"type": "NUMBER"},
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
        return f"✅ Đã gửi tin nhắn (ID {msg.message_id}) tới {target}."
    except Exception as e:
        logger.error("tg_send_message: %s", e)
        return f"❌ Gửi thất bại: {e}"


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
        return f"✅ Đã react {emoji} vào tin nhắn {mid}."
    except Exception as e:
        logger.error("tg_react: %s", e)
        return f"❌ React thất bại: {e}"


async def tg_delete_message(ctx: TelegramContext, message_id: int,
                             chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.delete_message(chat_id=target, message_id=int(message_id))
        return f"✅ Đã xóa tin nhắn {message_id}."
    except Exception as e:
        logger.error("tg_delete_message: %s", e)
        return f"❌ Xóa thất bại: {e}"


async def tg_pin_message(ctx: TelegramContext, message_id: int,
                          chat_id=None, disable_notification: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.pin_chat_message(
            chat_id              = target,
            message_id           = int(message_id),
            disable_notification = bool(disable_notification),
        )
        return f"✅ Đã ghim tin nhắn {message_id}."
    except Exception as e:
        logger.error("tg_pin_message: %s", e)
        return f"❌ Ghim thất bại: {e}"


async def tg_unpin_message(ctx: TelegramContext, message_id=None,
                            chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        if message_id:
            await ctx.bot.unpin_chat_message(chat_id=target,
                                             message_id=int(message_id))
            return f"✅ Đã bỏ ghim tin nhắn {message_id}."
        else:
            await ctx.bot.unpin_all_chat_messages(chat_id=target)
            return "✅ Đã bỏ ghim tất cả tin nhắn."
    except Exception as e:
        logger.error("tg_unpin: %s", e)
        return f"❌ Bỏ ghim thất bại: {e}"


async def tg_ban_user(ctx: TelegramContext, user_id: int,
                       chat_id=None, reason: str = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.ban_chat_member(chat_id=target, user_id=int(user_id))
        msg = f"✅ Đã ban user {user_id}"
        if reason:
            msg += f" (lý do: {reason})"
        return msg + "."
    except Exception as e:
        logger.error("tg_ban_user: %s", e)
        return f"❌ Ban thất bại: {e}"


async def tg_unban_user(ctx: TelegramContext, user_id: int,
                         chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.unban_chat_member(
            chat_id=target, user_id=int(user_id), only_if_banned=True
        )
        return f"✅ Đã unban user {user_id}."
    except Exception as e:
        logger.error("tg_unban: %s", e)
        return f"❌ Unban thất bại: {e}"


async def tg_mute_user(ctx: TelegramContext, user_id: int,
                        duration_minutes: float = 0, chat_id=None) -> str:
    target  = _resolve_chat(ctx, chat_id)
    perms   = ChatPermissions(can_send_messages=False)
    until   = None
    if duration_minutes and duration_minutes > 0:
        until = datetime.now(tz=timezone.utc) + timedelta(minutes=float(duration_minutes))
    try:
        await ctx.bot.restrict_chat_member(
            chat_id    = target,
            user_id    = int(user_id),
            permissions= perms,
            until_date = until,
        )
        dur = f"{duration_minutes} phút" if duration_minutes else "vĩnh viễn"
        return f"✅ Đã mute user {user_id} ({dur})."
    except Exception as e:
        logger.error("tg_mute: %s", e)
        return f"❌ Mute thất bại: {e}"


async def tg_unmute_user(ctx: TelegramContext, user_id: int,
                          chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
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
            chat_id=target, user_id=int(user_id), permissions=perms
        )
        return f"✅ Đã unmute user {user_id}."
    except Exception as e:
        logger.error("tg_unmute: %s", e)
        return f"❌ Unmute thất bại: {e}"


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
        return f"✅ Đã forward tin nhắn {message_id} → {dest}."
    except Exception as e:
        logger.error("tg_forward: %s", e)
        return f"❌ Forward thất bại: {e}"


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
        return f"✅ Đã copy tin nhắn {message_id} → {dest}."
    except Exception as e:
        logger.error("tg_copy: %s", e)
        return f"❌ Copy thất bại: {e}"


async def tg_send_poll(ctx: TelegramContext, question: str,
                        options: list[str], chat_id=None,
                        is_anonymous: bool = True,
                        allows_multiple_answers: bool = False) -> str:
    target = _resolve_chat(ctx, chat_id)
    opts   = [str(o) for o in options[:10]]
    if len(opts) < 2:
        return "❌ Poll cần ít nhất 2 lựa chọn."
    try:
        msg = await ctx.bot.send_poll(
            chat_id                  = target,
            question                 = question[:300],
            options                  = opts,
            is_anonymous             = bool(is_anonymous),
            allows_multiple_answers  = bool(allows_multiple_answers),
            message_thread_id        = ctx.thread_id,
        )
        return f"✅ Đã tạo poll (ID {msg.message_id}) với {len(opts)} lựa chọn."
    except Exception as e:
        logger.error("tg_send_poll: %s", e)
        return f"❌ Tạo poll thất bại: {e}"


async def tg_get_chat_info(ctx: TelegramContext, chat_id: str) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        chat = await ctx.bot.get_chat(chat_id=target)
        lines = [
            f"📛 Tên: {chat.effective_name}",
            f"🆔 ID: {chat.id}",
            f"📂 Loại: {chat.type}",
        ]
        if chat.username:
            lines.append(f"🔗 Username: @{chat.username}")
        if chat.description:
            lines.append(f"📄 Mô tả: {chat.description[:300]}")
        if chat.invite_link:
            lines.append(f"🔗 Invite: {chat.invite_link}")
        return "\n".join(lines)
    except Exception as e:
        logger.error("tg_get_chat_info: %s", e)
        return f"❌ Lấy thông tin thất bại: {e}"


async def tg_get_chat_members_count(ctx: TelegramContext,
                                    chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        count = await ctx.bot.get_chat_member_count(chat_id=target)
        return f"👥 Chat {target} có {count:,} thành viên."
    except Exception as e:
        return f"❌ Lấy số thành viên thất bại: {e}"


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
        return f"✅ Đã gửi {emoji} (kết quả: {msg.dice.value})."
    except Exception as e:
        return f"❌ Gửi dice thất bại: {e}"


async def tg_promote_admin(ctx: TelegramContext, user_id: int,
                            chat_id=None,
                            can_delete_messages: bool = True,
                            can_manage_topics:   bool = False,
                            can_pin_messages:    bool = True,
                            can_invite_users:    bool = True,
                            can_restrict_members:bool = False,
                            custom_title: str    = "") -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.promote_chat_member(
            chat_id               = target,
            user_id               = int(user_id),
            can_delete_messages   = can_delete_messages,
            can_manage_topics     = can_manage_topics,
            can_pin_messages      = can_pin_messages,
            can_invite_users      = can_invite_users,
            can_restrict_members  = can_restrict_members,
            can_manage_chat       = True,
        )
        if custom_title:
            await ctx.bot.set_chat_administrator_custom_title(
                chat_id=target, user_id=int(user_id), custom_title=custom_title[:16]
            )
        return f"✅ Đã promote user {user_id} thành admin."
    except Exception as e:
        return f"❌ Promote thất bại: {e}"


async def tg_demote_admin(ctx: TelegramContext, user_id: int,
                           chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.promote_chat_member(
            chat_id               = target,
            user_id               = int(user_id),
            can_manage_chat       = False,
            can_delete_messages   = False,
            can_manage_video_chats= False,
            can_restrict_members  = False,
            can_promote_members   = False,
            can_change_info       = False,
            can_invite_users      = False,
            can_pin_messages      = False,
        )
        return f"✅ Đã demote user {user_id} (xóa quyền admin)."
    except Exception as e:
        return f"❌ Demote thất bại: {e}"


async def tg_set_chat_title(ctx: TelegramContext, title: str,
                             chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.set_chat_title(chat_id=target, title=title[:255])
        return f"✅ Đã đổi tên chat thành '{title}'."
    except Exception as e:
        return f"❌ Đổi tên thất bại: {e}"


async def tg_set_chat_description(ctx: TelegramContext, description: str,
                                   chat_id=None) -> str:
    target = _resolve_chat(ctx, chat_id)
    try:
        await ctx.bot.set_chat_description(chat_id=target, description=description[:255])
        return f"✅ Đã cập nhật mô tả chat."
    except Exception as e:
        return f"❌ Cập nhật mô tả thất bại: {e}"


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
    "web_search":               "🌐 Đang tìm kiếm web…",
    "fetch_url":                "🔗 Đang đọc trang web…",
    "arxiv_search":             "📚 Đang tìm kiếm ArXiv…",
    "run_python":               "💻 Đang chạy code Python…",
    "tg_send_message":          "📤 Đang gửi tin nhắn…",
    "tg_react":                 "😊 Đang thả reaction…",
    "tg_delete_message":        "🗑️ Đang xóa tin nhắn…",
    "tg_pin_message":           "📌 Đang ghim tin nhắn…",
    "tg_unpin_message":         "📌 Đang bỏ ghim…",
    "tg_ban_user":              "🚫 Đang ban user…",
    "tg_unban_user":            "✅ Đang unban user…",
    "tg_mute_user":             "🔇 Đang mute user…",
    "tg_unmute_user":           "🔊 Đang unmute user…",
    "tg_forward_message":       "↪️ Đang forward tin nhắn…",
    "tg_copy_message":          "📋 Đang copy tin nhắn…",
    "tg_send_poll":             "📊 Đang tạo poll…",
    "tg_get_chat_info":         "ℹ️ Đang lấy thông tin chat…",
    "tg_get_chat_members_count":"👥 Đang đếm thành viên…",
    "tg_send_dice":             "🎲 Đang tung xúc xắc…",
    "tg_promote_admin":         "👑 Đang promote admin…",
    "tg_demote_admin":          "🔽 Đang demote admin…",
    "tg_set_chat_title":        "✏️ Đang đổi tên chat…",
    "tg_set_chat_description":  "📝 Đang cập nhật mô tả…",
}


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
        return f"✅ Đã gửi ảnh (ID {msg.message_id}) tới {target}."
    except Exception as e:
        logger.error("tg_send_photo: %s", e)
        return f"❌ Gửi ảnh thất bại: {e}"


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
        return f"✅ Đã sửa tin nhắn {message_id}."
    except Exception as e:
        logger.error("tg_edit_message: %s", e)
        return f"❌ Sửa thất bại: {e}"


# Register new handlers + status labels
TG_HANDLERS["tg_send_photo"]    = tg_send_photo
TG_HANDLERS["tg_edit_message"]  = tg_edit_message
TOOL_STATUS["tg_send_photo"]    = "🖼️ Đang gửi ảnh…"
TOOL_STATUS["tg_edit_message"]  = "✏️ Đang sửa tin nhắn…"


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
        return f"✅ Đã gửi sticker (ID {msg.message_id}) tới {target}."
    except Exception as e:
        logger.error("tg_send_sticker: %s", e)
        return f"❌ Gửi sticker thất bại: {e}"


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
        return f"✅ Đã gửi animation/GIF (ID {msg.message_id}) tới {target}."
    except Exception as e:
        logger.error("tg_send_animation: %s", e)
        return f"❌ Gửi animation thất bại: {e}"


# Register handlers + status labels
TG_HANDLERS["tg_send_sticker"]   = tg_send_sticker
TG_HANDLERS["tg_send_animation"] = tg_send_animation
TOOL_STATUS["tg_send_sticker"]   = "🎭 Đang gửi sticker…"
TOOL_STATUS["tg_send_animation"] = "🎬 Đang gửi animation/GIF…"
