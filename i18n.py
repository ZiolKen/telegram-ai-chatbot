"""
i18n.py — UI string tables for EN_US and VI_VN.

Usage
-----
    from i18n import t
    await _reply(update, t("reset.done", lang))
    await _reply(update, t("warn.added", lang, uid=uid, count=2, max=3))

All format kwargs are keyword-only and optional — if a key has no
placeholders the extra kwargs are silently ignored.
"""

from __future__ import annotations

SUPPORTED: dict[str, str] = {
    "en": "🇺🇸 English",
    "vi": "🇻🇳 Tiếng Việt",
}
DEFAULT_LANG = "en"

# ─────────────────────────────────────────────────────────────────────────────
# String tables
# Each value may contain {kwarg} placeholders for .format().
# ─────────────────────────────────────────────────────────────────────────────

_T: dict[str, dict[str, str]] = {

    # ═══════════════════════════════════════════════════════════════════════
    # EN_US
    # ═══════════════════════════════════════════════════════════════════════
    "en": {

        # /start
        "start": (
            "🤖 <b>AI Agent Telegram</b>\n\n"
            "Type /help to see all commands."
        ),

        # /help  ─ sections assembled in commands.py
        "help.title":          "📖 <b>Available Commands</b>",
        "help.mod":            "🛡️ Moderation",
        "help.del":            "<code>/del [id]</code>          — Delete a message (reply or ID)",
        "help.pin":            "<code>/pin [silent]</code>       — Pin the replied message",
        "help.ban":            "<code>/ban [@u] [reason]</code>  — Ban user",
        "help.unban":          "<code>/unban @u</code>           — Unban user",
        "help.mute":           "<code>/mute [@u] &lt;time&gt;</code>   — Mute (5m 2h 1d 1w 3mo 1y)",
        "help.unmute":         "<code>/unmute @u</code>          — Unmute user",
        "help.addadmin":       "<code>/addadmin [@u] [flags]</code> — Promote admin",
        "help.addadmin.flags": "   Flags: <code>del pin inv restrict topics title:Name</code>",
        "help.rmadmin":        "<code>/rmadmin @u</code>         — Demote admin",
        "help.warn":           "<code>/warn [@u] [reason]</code>  — Warn user (auto-ban at max)",
        "help.warns":          "<code>/warns [@u]</code>          — View warn count",
        "help.resetwarns":     "<code>/resetwarns @u</code>       — Reset warns",
        "help.feed":           "<code>/feed [group_id] [n]</code>   — Last n messages (default 5); use group_id from private chat",
        "help.ai":             "💬 AI Conversation",
        "help.reset":          "<code>/reset</code>     — Clear chat history",
        "help.sysreset":       "<code>/sysreset</code>  — Clear ALL history",
        "help.model":          "<code>/model</code>     — Select AI model",
        "help.plugins":        "<code>/plugins [on|off]</code> — Toggle plugins",
        "help.topic":          "<code>/topic [on|off]</code>   — Topic isolation",
        "help.status":         "<code>/status</code>    — Bot status",
        "help.lang":           "<code>/lang [en|vi]</code>     — Switch language",
        "help.models.title":   "📋 Models",

        # /reset
        "reset.done":    "🗑️ Conversation history cleared.",
        "sysreset.done": "🗑️ <b>All</b> conversation history cleared.",

        # /model
        "model.current":   "🤖 Current model: <code>{model}</code>\n\nSelect model:",
        "model.switched":  "✅ Switched to <b>{label}</b>",

        # /plugins
        "plugins.status":  "🔌 Plugins: {state}\nUse <code>/plugins on</code> or <code>/plugins off</code>.",
        "plugins.on":      "🔌 Plugins: ✅ Enabled",
        "plugins.off":     "🔌 Plugins: ❌ Disabled",
        "plugins.usage":   "Use <code>/plugins on</code> or <code>/plugins off</code>.",
        "plugins.enabled": "✅ Enabled",
        "plugins.disabled":"❌ Disabled",

        # /topic
        "topic.group_only":  "❌ Topic Mode only works in groups.",
        "topic.status":      "🏷️ Topic Mode: {state}\nUse <code>/topic on</code> or <code>/topic off</code>.",
        "topic.on":          "🏷️ Topic Mode: ✅ Enabled",
        "topic.off":         "🏷️ Topic Mode: ❌ Disabled",
        "topic.usage":       "Use <code>/topic on</code> or <code>/topic off</code>.",

        # /lang
        "lang.current":  "🌐 Language: {name}\n\nAvailable:\n{list}\n\nUse <code>/lang en</code> or <code>/lang vi</code>.",
        "lang.set":      "✅ Language set to <b>{name}</b>. Conversation history cleared.",
        "lang.invalid":  "❌ Unknown language. Available: {list}",

        # /status
        "status.title":    "📊 <b>Status</b>",
        "status.conv":     "🆔 Conv",
        "status.history":  "📝 History",
        "status.msgs":     "{n} messages",
        "status.model":    "🤖 Model",
        "status.plugins":  "🔌 Plugins",
        "status.followup": "💬 Follow-up",
        "status.topic":    "🏷️ Topic Mode",
        "status.feed":     "📋 Feed buffer",
        "status.msgs_unit":"messages",
        "status.db.ok":    "\n\n🗄️ <b>PostgreSQL</b>\n   {rows:,} / {max_rows:,}  ({pct}%)\n   [{bar}]",
        "status.db.err":   "\n\n🗄️ PostgreSQL: ❌ <code>{err}</code>",
        "status.db.off":   "\n\n🗄️ PostgreSQL: ⚠️ In-memory only",

        # Moderation
        "need.target":      "❌ Reply to a message or provide @user.",
        "need.reply":       "❌ Reply to the message to delete or provide a message ID.",
        "need.reply.pin":   "❌ Reply to the message to pin.",
        "del.fail":         "❌ Delete failed: <code>{err}</code>",
        "pin.fail":         "❌ Pin failed: <code>{err}</code>",

        "ban.done":    "🚫 Banned user <code>{uid}</code>",
        "ban.reason":  "\n📋 Reason: {reason}",
        "ban.fail":    "❌ Ban failed: <code>{err}</code>",
        "unban.done":  "✅ Unbanned user <code>{uid}</code>.",
        "unban.fail":  "❌ Unban failed: <code>{err}</code>",

        "mute.usage":  (
            "❌ Syntax: <code>/mute @user &lt;duration&gt;</code>\n"
            "Units: <code>s</code>=sec  <code>m</code>=min  <code>h</code>=hour  "
            "<code>d</code>=day  <code>w</code>=week  <code>mo</code>=month  <code>y</code>=year\n"
            "Example: <code>30s</code>  <code>5m</code>  <code>2h</code>  <code>1d</code>  "
            "<code>1w</code>  <code>3mo</code>  <code>1y</code>"
        ),
        "mute.done":  "🔇 Muted <code>{uid}</code> — {dur}",
        "mute.perm":  "permanent",
        "mute.fail":  "❌ Mute failed: <code>{err}</code>",
        "unmute.done":"🔊 Unmuted <code>{uid}</code>.",
        "unmute.fail":"❌ Unmute failed: <code>{err}</code>",

        # /cancel
        "cancel.done": "✅ Pending feed reply cancelled.",
        "cancel.none": "ℹ️ No pending feed reply to cancel.",

        # Feed → Reply (ForceReply flow)
        "feed.reply.sent":        "✅ Reply sent to message <code>#{msg_id}</code>.",
        "feed.reply.fail":        "❌ Send failed: {err}",
        "feed.reply.empty":       "❌ Empty message — reply cancelled.",
        "feed.reply.prompt_text": (
            "✏️ Type the message you want to <b>reply</b> to message "
            "<code>#{msg_id}</code> (group <code>{chat_id}</code>):\n\n"
            "<i>To cancel: /cancel</i>"
        ),
        "feed.reply.placeholder": "Type your reply…",
        "feed.reply.toast":       "✏️ Type your reply message.",

        # Feed action toasts (query.answer)
        "toast.deleted":        "🗑️ Deleted.",
        "toast.pinned":         "📌 Pinned.",
        "toast.invalid_data":   "❌ Invalid data.",
        "toast.invalid_id":     "❌ Invalid ID.",
        "toast.unknown_action": "❌ Unknown action.",

        # Feed warn/mute/ban group confirmation messages
        "feed.warn.msg":      "⚠️ User <code>{uid}</code>: {count}/{max} warnings.",
        "feed.warn.banned":   "\n🚫 Reached max → auto-banned.",
        "feed.warn.ban_fail": "\n❌ Auto-ban failed: {err}",
        "feed.mute.msg":      "🔇 Muted <code>{uid}</code> for 1h.",
        "feed.ban.msg":       "🚫 Banned <code>{uid}</code>.",

        "addadmin.usage": (
            "❌ Syntax: <code>/addadmin @user [flags]</code>\n"
            "Flags: <code>del pin inv restrict topics promote info video post title:Name</code>\n"
            "No flags → default permissions (del, pin, inv, video)"
        ),
        "addadmin.done":   "👑 Promoted <code>{uid}</code> as admin",
        "addadmin.title":  " (<b>{title}</b>)",
        "addadmin.perms":  "\n📋 Permissions: {perms}",
        "addadmin.fail":   "❌ Promote failed: <code>{err}</code>",
        "rmadmin.done":    "🔽 Demoted <code>{uid}</code> (admin rights removed).",
        "rmadmin.fail":    "❌ Demote failed: <code>{err}</code>",

        "warn.added":      "⚠️ Warned <code>{uid}</code> (<b>{count}/{max}</b>)",
        "warn.reason":     "\n📋 Reason: {reason}",
        "warn.banned":     "\n\n🚫 Reached {max} warns → Auto-banned.",
        "warn.ban_fail":   "\n\n❌ Auto-ban failed: <code>{err}</code>",
        "warns.single":    "⚠️ User <code>{uid}</code>: <b>{count}/{max}</b> warns.",
        "warns.none":      "✅ No one has been warned in this chat.",
        "warns.title":     "⚠️ <b>Warn list</b> (max {max}):",
        "resetwarns.done": "✅ Warns reset for <code>{uid}</code>.",

        "feed.group_only":   "❌ /feed only works in groups.",
        "feed.empty":        (
            "📋 Buffer empty — the bot needs to read group messages first.\n"
            "Make sure <code>GROUP_CONTEXT_ENABLED=true</code> in config."
        ),
        "feed.header":       "📋 <b>{n} recent messages</b> (buffer: {buf}):",

        # handlers.py
        "processing":   "⏳",
        "error.agent":  "❌ Processing failed. Please try again.",
        "followup.header": "💡 <b>You might also ask:</b>",
    },

    # ═══════════════════════════════════════════════════════════════════════
    # VI_VN
    # ═══════════════════════════════════════════════════════════════════════
    "vi": {

        # /start
        "start": (
            "🤖 <b>AI Agent Telegram</b>\n\n"
            "Gõ /help để xem toàn bộ lệnh."
        ),

        # /help
        "help.title":          "📖 <b>Lệnh có sẵn</b>",
        "help.mod":            "🛡️ Quản lý nhóm",
        "help.del":            "<code>/del [id]</code>          — Xóa tin nhắn (reply hoặc ID)",
        "help.pin":            "<code>/pin [silent]</code>       — Ghim tin nhắn đang reply",
        "help.ban":            "<code>/ban [@u] [lý do]</code>   — Ban user",
        "help.unban":          "<code>/unban @u</code>           — Unban user",
        "help.mute":           "<code>/mute [@u] &lt;tg&gt;</code>  — Mute (5m 2h 1d 1w 3mo 1y)",
        "help.unmute":         "<code>/unmute @u</code>          — Unmute user",
        "help.addadmin":       "<code>/addadmin [@u] [flags]</code> — Promote admin",
        "help.addadmin.flags": "   Flags: <code>del pin inv restrict topics title:Tên</code>",
        "help.rmadmin":        "<code>/rmadmin @u</code>         — Demote admin",
        "help.warn":           "<code>/warn [@u] [lý do]</code>  — Cảnh cáo (auto-ban lúc max)",
        "help.warns":          "<code>/warns [@u]</code>          — Xem số lần cảnh cáo",
        "help.resetwarns":     "<code>/resetwarns @u</code>       — Reset cảnh cáo",
        "help.feed":           "<code>/feed [group_id] [n]</code>   — n tin gần nhất; dùng group_id khi nhắn từ private chat",
        "help.ai":             "💬 Hội thoại AI",
        "help.reset":          "<code>/reset</code>     — Xóa lịch sử chat",
        "help.sysreset":       "<code>/sysreset</code>  — Xóa tất cả lịch sử",
        "help.model":          "<code>/model</code>     — Chọn model AI",
        "help.plugins":        "<code>/plugins [on|off]</code> — Bật/tắt plugins",
        "help.topic":          "<code>/topic [on|off]</code>   — Topic isolation",
        "help.status":         "<code>/status</code>    — Trạng thái bot",
        "help.lang":           "<code>/lang [en|vi]</code>     — Đổi ngôn ngữ",
        "help.models.title":   "📋 Models",

        # /reset
        "reset.done":    "🗑️ Đã xóa lịch sử hội thoại.",
        "sysreset.done": "🗑️ Đã xóa <b>toàn bộ</b> lịch sử.",

        # /model
        "model.current":  "🤖 Model hiện tại: <code>{model}</code>\n\nChọn model:",
        "model.switched": "✅ Đã đổi sang <b>{label}</b>",

        # /plugins
        "plugins.status":  "🔌 Plugins: {state}\nDùng <code>/plugins on</code> hoặc <code>/plugins off</code>.",
        "plugins.on":      "🔌 Plugins: ✅ Đã bật",
        "plugins.off":     "🔌 Plugins: ❌ Đã tắt",
        "plugins.usage":   "Dùng <code>/plugins on</code> hoặc <code>/plugins off</code>.",
        "plugins.enabled": "✅ Bật",
        "plugins.disabled":"❌ Tắt",

        # /topic
        "topic.group_only":  "❌ Topic Mode chỉ áp dụng cho nhóm.",
        "topic.status":      "🏷️ Topic Mode: {state}\nDùng <code>/topic on</code> hoặc <code>/topic off</code>.",
        "topic.on":          "🏷️ Topic Mode: ✅ Đã bật",
        "topic.off":         "🏷️ Topic Mode: ❌ Đã tắt",
        "topic.usage":       "Dùng <code>/topic on</code> hoặc <code>/topic off</code>.",

        # /lang
        "lang.current":  "🌐 Ngôn ngữ: {name}\n\nHỗ trợ:\n{list}\n\nDùng <code>/lang en</code> hoặc <code>/lang vi</code>.",
        "lang.set":      "✅ Đã đổi sang <b>{name}</b>. Lịch sử hội thoại đã được xóa.",
        "lang.invalid":  "❌ Ngôn ngữ không hợp lệ. Hỗ trợ: {list}",

        # /status
        "status.title":    "📊 <b>Trạng thái</b>",
        "status.conv":     "🆔 Conv",
        "status.history":  "📝 Lịch sử",
        "status.msgs":     "{n} tin",
        "status.model":    "🤖 Model",
        "status.plugins":  "🔌 Plugins",
        "status.followup": "💬 Followup",
        "status.topic":    "🏷️ Topic Mode",
        "status.feed":     "📋 Feed buffer",
        "status.msgs_unit":"tin",
        "status.db.ok":    "\n\n🗄️ <b>PostgreSQL</b>\n   {rows:,} / {max_rows:,}  ({pct}%)\n   [{bar}]",
        "status.db.err":   "\n\n🗄️ PostgreSQL: ❌ <code>{err}</code>",
        "status.db.off":   "\n\n🗄️ PostgreSQL: ⚠️ In-memory only",

        # Moderation
        "need.target":      "❌ Cung cấp @user hoặc reply vào tin nhắn của họ.",
        "need.reply":       "❌ Reply vào tin nhắn cần xóa hoặc cung cấp message ID.",
        "need.reply.pin":   "❌ Reply vào tin nhắn cần ghim.",
        "del.fail":         "❌ Xóa thất bại: <code>{err}</code>",
        "pin.fail":         "❌ Ghim thất bại: <code>{err}</code>",

        "ban.done":    "🚫 Đã ban user <code>{uid}</code>",
        "ban.reason":  "\n📋 Lý do: {reason}",
        "ban.fail":    "❌ Ban thất bại: <code>{err}</code>",
        "unban.done":  "✅ Đã unban user <code>{uid}</code>.",
        "unban.fail":  "❌ Unban thất bại: <code>{err}</code>",

        "mute.usage":  (
            "❌ Cú pháp: <code>/mute @user &lt;thời gian&gt;</code>\n"
            "Đơn vị: <code>s</code>=giây  <code>m</code>=phút  <code>h</code>=giờ  "
            "<code>d</code>=ngày  <code>w</code>=tuần  <code>mo</code>=tháng  <code>y</code>=năm\n"
            "Ví dụ: <code>30s</code>  <code>5m</code>  <code>2h</code>  <code>1d</code>  "
            "<code>1w</code>  <code>3mo</code>  <code>1y</code>"
        ),
        "mute.done":  "🔇 Đã mute <code>{uid}</code> — {dur}",
        "mute.perm":  "vĩnh viễn",
        "mute.fail":  "❌ Mute thất bại: <code>{err}</code>",
        "unmute.done":"🔊 Đã unmute <code>{uid}</code>.",
        "unmute.fail":"❌ Unmute thất bại: <code>{err}</code>",

        # /cancel
        "cancel.done": "✅ Đã hủy feed reply đang chờ.",
        "cancel.none": "ℹ️ Không có feed reply nào đang chờ.",

        # Feed → Reply (ForceReply flow)
        "feed.reply.sent":        "✅ Đã gửi reply vào tin <code>#{msg_id}</code>.",
        "feed.reply.fail":        "❌ Gửi thất bại: {err}",
        "feed.reply.empty":       "❌ Tin nhắn trống — hủy reply.",
        "feed.reply.prompt_text": (
            "✏️ Nhập tin nhắn bạn muốn <b>reply</b> vào tin "
            "<code>#{msg_id}</code> (nhóm <code>{chat_id}</code>):\n\n"
            "<i>Để hủy: /cancel</i>"
        ),
        "feed.reply.placeholder": "Nhập nội dung reply…",
        "feed.reply.toast":       "✏️ Hãy nhập tin nhắn reply.",

        # Feed action toasts (query.answer)
        "toast.deleted":        "🗑️ Đã xóa.",
        "toast.pinned":         "📌 Đã ghim.",
        "toast.invalid_data":   "❌ Dữ liệu không hợp lệ.",
        "toast.invalid_id":     "❌ ID không hợp lệ.",
        "toast.unknown_action": "❌ Action không xác định.",

        # Feed warn/mute/ban group confirmation messages
        "feed.warn.msg":      "⚠️ User <code>{uid}</code>: {count}/{max} cảnh cáo.",
        "feed.warn.banned":   "\n🚫 Đạt max → đã BAN.",
        "feed.warn.ban_fail": "\n❌ Auto-ban thất bại: {err}",
        "feed.mute.msg":      "🔇 Đã mute <code>{uid}</code> 1h.",
        "feed.ban.msg":       "🚫 Đã ban <code>{uid}</code>.",

        "addadmin.usage": (
            "❌ Cú pháp: <code>/addadmin @user [flags]</code>\n"
            "Flags: <code>del pin inv restrict topics promote info video post title:Tên</code>\n"
            "Không truyền flag → dùng quyền mặc định (del, pin, inv, video)"
        ),
        "addadmin.done":  "👑 Đã promote <code>{uid}</code> thành admin",
        "addadmin.title": " (<b>{title}</b>)",
        "addadmin.perms": "\n📋 Quyền: {perms}",
        "addadmin.fail":  "❌ Promote thất bại: <code>{err}</code>",
        "rmadmin.done":   "🔽 Đã demote <code>{uid}</code> (xóa quyền admin).",
        "rmadmin.fail":   "❌ Demote thất bại: <code>{err}</code>",

        "warn.added":    "⚠️ Đã cảnh cáo <code>{uid}</code> (<b>{count}/{max}</b>)",
        "warn.reason":   "\n📋 Lý do: {reason}",
        "warn.banned":   "\n\n🚫 Đạt {max} cảnh cáo → Đã BAN tự động.",
        "warn.ban_fail": "\n\n❌ Auto-ban thất bại: <code>{err}</code>",
        "warns.single":  "⚠️ User <code>{uid}</code>: <b>{count}/{max}</b> cảnh cáo.",
        "warns.none":    "✅ Không có ai bị cảnh cáo trong chat này.",
        "warns.title":   "⚠️ <b>Danh sách cảnh cáo</b> (max {max}):",
        "resetwarns.done":"✅ Đã reset cảnh cáo của <code>{uid}</code>.",

        "feed.group_only":  "❌ /feed chỉ hoạt động trong nhóm.",
        "feed.empty":       (
            "📋 Buffer trống — bot cần đọc tin nhắn nhóm trước.\n"
            "Đảm bảo <code>GROUP_CONTEXT_ENABLED=true</code> trong config."
        ),
        "feed.header":      "📋 <b>{n} tin gần nhất</b> (buffer: {buf}):",

        # handlers.py
        "processing":      "⏳",
        "error.agent":     "❌ Xử lý thất bại. Vui lòng thử lại.",
        "followup.header": "💡 <b>Bạn có thể hỏi tiếp:</b>",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def t(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """
    Look up a translation key.
    Falls back to EN if the key is missing in the target language.
    Format kwargs are applied with str.format() — silently ignored if unused.
    """
    lang = lang if lang in _T else DEFAULT_LANG
    text = _T[lang].get(key) or _T[DEFAULT_LANG].get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return text


def lang_name(lang: str) -> str:
    """Human-readable name for a language code."""
    return SUPPORTED.get(lang, lang)


def lang_list_str() -> str:
    """Formatted list of supported languages for display."""
    return "\n".join(f"• <code>{code}</code> — {name}" for code, name in SUPPORTED.items())
