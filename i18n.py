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
        "help.addadmin.flags": "   Flags: <code>del pin inv restrict topics title:Name full</code>  (<b>full</b>=all)",
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
        "model.fallback_note": "⚠️ Configured as <b>{configured}</b>, but the last reply actually came from <b>{actual}</b> (auto fallback — quota/rate-limit).",

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
        "status.model_fallback": "🤖 Model     : <b>{actual}</b> <i>(configured: {configured} — auto fallback active)</i>",
        "status.plugins":  "🔌 Plugins",
        "status.followup": "💬 Follow-up",
        "status.topic":    "🏷️ Topic Mode",
        "status.feed":     "📋 Feed buffer",
        "status.msgs_unit":"messages",
        "status.db.ok":    "\n\n🗄️ <b>PostgreSQL</b>\n   {rows:,} / {max_rows:,}  ({pct}%)\n   [{bar}]",
        "status.db.err":   "\n\n🗄️ PostgreSQL: ❌ <code>{err}</code>",
        "status.db.off":   "\n\n🗄️ PostgreSQL: ⚠️ In-memory only",

        # Moderation
        "need.target":      "❌ Reply to a message, provide a numeric user ID, or @username (only works if the bot has already seen a message from that user).",
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
            "<b>full</b> → all admin permissions at once\n"
            "No flags → default (del, pin, inv, video)"
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
        "feed.header.group": "📋 <b>{n} recent messages</b> from <code>{chat_id}</code> (buffer: {buf}):",
        "feed.empty.group":  "📋 Buffer for <code>{chat_id}</code> is empty.\nMake sure <code>GROUP_CONTEXT_ENABLED=true</code> is set.",
        "feed.no_data":      "📋 No feed data yet.\nAdd the bot to a group with <code>GROUP_CONTEXT_ENABLED=true</code>, then use <code>/feed &lt;group_id&gt; [n]</code>.",
        "feed.multi_group":  "📋 Multiple groups in buffer. Specify one:\n<code>/feed &lt;group_id&gt; [n]</code>\n\nAvailable:\n{ids}",

        # handlers.py
        "processing":   "⏳",
        "error.agent":  "❌ Processing failed. Please try again.",
        "followup.header": "💡 <b>You might also ask:</b>",

        # ─── tools_telegram.py — AI tool results (user-facing) ─────────────
        "tools.user_not_found":       "❌ Could not resolve user_id for '{raw}'.{hint} The bot auto-resolves @username if it has previously seen a message/mention/join-leave from that user, or if they're an admin of the current chat. If it still doesn't work: reply to one of their messages, or provide a numeric user ID (or a tg://user?id=... link).",
        "tools.user_not_found_hint":  " Did you mean: {suggestions}?",
        "tools.resolve_missing_username": "❌ Missing username to look up.",
        "tools.resolved_user":        "✅ @{handle} → user_id: {uid}{extra}",
        "tools.sent_message":        "✅ Message sent (ID {mid}) to {target}.",
        "tools.send_failed":         "❌ Failed to send: {err}",
        "tools.reacted":             "✅ Reacted {emoji} to message {mid}.",
        "tools.react_failed":        "❌ React failed: {err}",
        "tools.deleted_message":     "✅ Deleted message {mid}.",
        "tools.delete_failed":       "❌ Delete failed: {err}",
        "tools.pinned_message":      "✅ Pinned message {mid}.",
        "tools.pin_failed":          "❌ Pin failed: {err}",
        "tools.unpinned_message":    "✅ Unpinned message {mid}.",
        "tools.unpinned_all":        "✅ Unpinned all messages.",
        "tools.unpin_failed":        "❌ Unpin failed: {err}",
        "tools.banned_user":         "✅ Banned user {uid}.",
        "tools.banned_user_reason":  "✅ Banned user {uid} (reason: {reason}).",
        "tools.ban_failed":          "❌ Ban failed: {err}",
        "tools.unbanned_user":       "✅ Unbanned user {uid}.",
        "tools.unban_failed":        "❌ Unban failed: {err}",
        "tools.muted_user":          "✅ Muted user {uid} ({dur}).",
        "tools.mute_minutes":        "{n} min",
        "tools.mute_forever":        "forever",
        "tools.mute_failed":         "❌ Mute failed: {err}",
        "tools.unmuted_user":        "✅ Unmuted user {uid}.",
        "tools.unmute_failed":       "❌ Unmute failed: {err}",
        "tools.forwarded_message":   "✅ Forwarded message {mid} → {dest}.",
        "tools.forward_failed":      "❌ Forward failed: {err}",
        "tools.copied_message":      "✅ Copied message {mid} → {dest}.",
        "tools.copy_failed":         "❌ Copy failed: {err}",
        "tools.poll_needs_options":  "❌ Poll needs at least 2 options.",
        "tools.poll_created":        "✅ Created poll (ID {mid}) with {n} options.",
        "tools.poll_failed":         "❌ Failed to create poll: {err}",
        "tools.chat_info_name":        "📛 Name: {name}",
        "tools.chat_info_id":          "🆔 ID: {id}",
        "tools.chat_info_type":        "📂 Type: {type}",
        "tools.chat_info_username":    "🔗 Username: @{username}",
        "tools.chat_info_description": "📄 Description: {desc}",
        "tools.chat_info_invite":      "🔗 Invite: {link}",
        "tools.get_chat_info_failed":  "❌ Failed to get chat info: {err}",
        "tools.members_count":         "👥 Chat {target} has {count:,} members.",
        "tools.members_count_failed":  "❌ Failed to get member count: {err}",
        "tools.dice_sent":           "✅ Sent {emoji} (result: {value}).",
        "tools.dice_failed":         "❌ Failed to send dice: {err}",
        "tools.promoted_admin":      "✅ Promoted user {uid} to admin.",
        "tools.promote_failed":      "❌ Promote failed: {err}",
        "tools.demoted_admin":       "✅ Demoted user {uid} (admin rights removed).",
        "tools.demote_failed":       "❌ Demote failed: {err}",
        "tools.title_changed":       "✅ Chat title changed to '{title}'.",
        "tools.title_failed":        "❌ Failed to change title: {err}",
        "tools.description_updated": "✅ Chat description updated.",
        "tools.description_failed":  "❌ Failed to update description: {err}",
        "tools.photo_sent":          "✅ Sent photo (ID {mid}) to {target}.",
        "tools.photo_failed":        "❌ Failed to send photo: {err}",
        "tools.message_edited":      "✅ Edited message {mid}.",
        "tools.edit_failed":         "❌ Edit failed: {err}",
        "tools.caption_edited":       "✅ Edited caption of message {mid}.",
        "tools.caption_edit_failed":  "❌ Caption edit failed: {err}",
        "tools.sticker_sent":        "✅ Sent sticker (ID {mid}) to {target}.",
        "tools.sticker_failed":      "❌ Failed to send sticker: {err}",
        "tools.animation_sent":      "✅ Sent animation/GIF (ID {mid}) to {target}.",
        "tools.animation_failed":    "❌ Failed to send animation: {err}",
        "tools.file_url_fetch_failed": "❌ Could not download file from URL: {ref}",
        "tools.file_sent":           "✅ Sent {method} '{fname}' ({size}) to {target} (msg_id={mid}).",
        "tools.file_send_failed":    "❌ Failed to send file: {err}",
        "tools.left_chat":           "✅ Bot left chat {target}.",
        "tools.leave_chat_failed":   "❌ Failed to leave chat: {err}",
        "tools.invite_link_created": "✅ Created invite link for {target}:",
        "tools.invite_link_line":    "🔗 {link}",
        "tools.invite_link_name":    "📛 Name: {name}",
        "tools.invite_link_expiry":  "⏰ Expires in {hours}h",
        "tools.invite_link_limit":   "👥 Limit: {limit} uses",
        "tools.invite_link_failed":  "❌ Failed to create invite link: {err}",
        "tools.invited_user":        "✅ Added user {uid} to {target}.",
        "tools.invite_user_failed":  "❌ Failed to invite user: {err}",
        "tools.media_group_empty":   "❌ Media list is empty.",
        "tools.media_group_invalid": "❌ No valid media.",
        "tools.media_group_sent":    "✅ Sent album of {n} media to {target}.",
        "tools.media_group_failed":  "❌ Failed to send media group: {err}",
        "tools.user_info_name":      "👤 {name}",
        "tools.user_info_id":        "🆔 ID: {id}",
        "tools.user_info_username":  "🔗 @{username}",
        "tools.user_info_status":    "📋 Status: {status}",
        "tools.user_info_title":     "🏷️ Title: {title}",
        "tools.user_info_is_bot":    "🤖 Bot: Yes",
        "tools.user_info_fetch_failed": "🆔 ID: {uid} (could not fetch info from this chat)",
        "tools.user_info_not_found": "Not found user {uid}.",
        "tools.user_title_set":      "✅ Set title '{title}' for user {uid}.",
        "tools.user_title_failed":   "❌ Failed to set title: {err}",

        # ─── tools_telegram.py — status labels shown while a tool runs ─────
        "tool_status.web_search":               "🌐 Searching the web…",
        "tool_status.fetch_url":                "🔗 Reading web page…",
        "tool_status.arxiv_search":              "📚 Searching ArXiv…",
        "tool_status.run_python":                "💻 Running Python code…",
        "tool_status.tg_send_message":           "📤 Sending message…",
        "tool_status.tg_react":                  "😊 Adding reaction…",
        "tool_status.tg_delete_message":         "🗑️ Deleting message…",
        "tool_status.tg_pin_message":            "📌 Pinning message…",
        "tool_status.tg_unpin_message":          "📌 Unpinning…",
        "tool_status.tg_ban_user":               "🚫 Banning user…",
        "tool_status.tg_unban_user":             "✅ Unbanning user…",
        "tool_status.tg_mute_user":              "🔇 Muting user…",
        "tool_status.tg_unmute_user":            "🔊 Unmuting user…",
        "tool_status.tg_forward_message":        "↪️ Forwarding message…",
        "tool_status.tg_copy_message":           "📋 Copying message…",
        "tool_status.tg_send_poll":              "📊 Creating poll…",
        "tool_status.tg_get_chat_info":          "ℹ️ Getting chat info…",
        "tool_status.tg_get_chat_members_count": "👥 Counting members…",
        "tool_status.tg_send_dice":              "🎲 Rolling dice…",
        "tool_status.tg_promote_admin":          "👑 Promoting admin…",
        "tool_status.tg_demote_admin":           "🔽 Demoting admin…",
        "tool_status.tg_set_chat_title":         "✏️ Renaming chat…",
        "tool_status.tg_set_chat_description":   "📝 Updating description…",
        "tool_status.tg_send_photo":             "🖼️ Sending photo…",
        "tool_status.tg_edit_message":           "✏️ Editing message…",
        "tool_status.tg_send_sticker":           "🎭 Sending sticker…",
        "tool_status.tg_send_animation":         "🎬 Sending animation/GIF…",
        "tool_status.tg_send_document":          "📤 Sending file…",
        "tool_status.tg_leave_chat":             "🚪 Leaving chat…",
        "tool_status.tg_create_invite_link":     "🔗 Creating invite link…",
        "tool_status.tg_invite_user":            "➕ Inviting user…",
        "tool_status.tg_send_media_group":       "🖼️ Sending album…",
        "tool_status.tg_get_user_info":          "👤 Getting user info…",
        "tool_status.tg_set_user_title":         "🏷️ Setting title…",
        "tool_status.tg_resolve_user":           "🔎 Resolving user…",

        # Inbound file content (file_process.py / handlers._extract_media)
        "file.content_header":     "--- Content of file '{filename}' ---",
        "file.truncated":          "\n…[content truncated — too long]",
        "file.xlsx_rows_truncated": "…[more rows, truncated]",
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
        "help.addadmin.flags": "   Flags: <code>del pin inv restrict topics title:Tên full</code>  (<b>full</b>=tất cả)",
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
        "model.fallback_note": "⚠️ Đang chọn <b>{configured}</b>, nhưng câu trả lời gần nhất thực ra đến từ <b>{actual}</b> (tự fallback — do hết quota/rate-limit).",

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
        "status.model_fallback": "🤖 Model     : <b>{actual}</b> <i>(đã chọn: {configured} — đang tự fallback)</i>",
        "status.plugins":  "🔌 Plugins",
        "status.followup": "💬 Followup",
        "status.topic":    "🏷️ Topic Mode",
        "status.feed":     "📋 Feed buffer",
        "status.msgs_unit":"tin",
        "status.db.ok":    "\n\n🗄️ <b>PostgreSQL</b>\n   {rows:,} / {max_rows:,}  ({pct}%)\n   [{bar}]",
        "status.db.err":   "\n\n🗄️ PostgreSQL: ❌ <code>{err}</code>",
        "status.db.off":   "\n\n🗄️ PostgreSQL: ⚠️ In-memory only",

        # Moderation
        "need.target":      "❌ Reply vào tin nhắn của họ, cung cấp user ID (số), hoặc @username (chỉ dùng được nếu bot đã từng thấy tin nhắn của người đó).",
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
            "<b>full</b> → tất cả quyền admin cùng lúc\n"
            "Không truyền flag → mặc định (del, pin, inv, video)"
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
        "feed.header.group":"📋 <b>{n} tin gần nhất</b> từ <code>{chat_id}</code> (buffer: {buf}):",
        "feed.empty.group": "📋 Buffer của <code>{chat_id}</code> trống.\nĐảm bảo <code>GROUP_CONTEXT_ENABLED=true</code> trong config.",
        "feed.no_data":     "📋 Chưa có dữ liệu feed.\nThêm bot vào nhóm với <code>GROUP_CONTEXT_ENABLED=true</code>, sau đó dùng <code>/feed &lt;group_id&gt; [n]</code>.",
        "feed.multi_group": "📋 Có nhiều nhóm trong buffer. Chỉ định cụ thể:\n<code>/feed &lt;group_id&gt; [n]</code>\n\nCó sẵn:\n{ids}",

        # handlers.py
        "processing":      "⏳",
        "error.agent":     "❌ Xử lý thất bại. Vui lòng thử lại.",
        "followup.header": "💡 <b>Bạn có thể hỏi tiếp:</b>",

        # ─── tools_telegram.py — kết quả tool AI (hiển thị cho user) ───────
        "tools.user_not_found":       "❌ Không tìm được user_id cho '{raw}'.{hint} Bot tự resolve được @username nếu đã từng thấy tin nhắn/mention/join-leave của người đó, hoặc nếu họ là admin của chat hiện tại. Nếu vẫn không được: hãy reply vào tin nhắn của họ, hoặc cung cấp user ID dạng số (hoặc link tg://user?id=...).",
        "tools.user_not_found_hint":  " Ý bạn có phải: {suggestions}?",
        "tools.resolve_missing_username": "❌ Thiếu username cần tra.",
        "tools.resolved_user":        "✅ @{handle} → user_id: {uid}{extra}",
        "tools.sent_message":        "✅ Đã gửi tin nhắn (ID {mid}) tới {target}.",
        "tools.send_failed":         "❌ Gửi thất bại: {err}",
        "tools.reacted":             "✅ Đã react {emoji} vào tin nhắn {mid}.",
        "tools.react_failed":        "❌ React thất bại: {err}",
        "tools.deleted_message":     "✅ Đã xóa tin nhắn {mid}.",
        "tools.delete_failed":       "❌ Xóa thất bại: {err}",
        "tools.pinned_message":      "✅ Đã ghim tin nhắn {mid}.",
        "tools.pin_failed":          "❌ Ghim thất bại: {err}",
        "tools.unpinned_message":    "✅ Đã bỏ ghim tin nhắn {mid}.",
        "tools.unpinned_all":        "✅ Đã bỏ ghim tất cả tin nhắn.",
        "tools.unpin_failed":        "❌ Bỏ ghim thất bại: {err}",
        "tools.banned_user":         "✅ Đã ban user {uid}.",
        "tools.banned_user_reason":  "✅ Đã ban user {uid} (lý do: {reason}).",
        "tools.ban_failed":          "❌ Ban thất bại: {err}",
        "tools.unbanned_user":       "✅ Đã unban user {uid}.",
        "tools.unban_failed":        "❌ Unban thất bại: {err}",
        "tools.muted_user":          "✅ Đã mute user {uid} ({dur}).",
        "tools.mute_minutes":        "{n} phút",
        "tools.mute_forever":        "vĩnh viễn",
        "tools.mute_failed":         "❌ Mute thất bại: {err}",
        "tools.unmuted_user":        "✅ Đã unmute user {uid}.",
        "tools.unmute_failed":       "❌ Unmute thất bại: {err}",
        "tools.forwarded_message":   "✅ Đã forward tin nhắn {mid} → {dest}.",
        "tools.forward_failed":      "❌ Forward thất bại: {err}",
        "tools.copied_message":      "✅ Đã copy tin nhắn {mid} → {dest}.",
        "tools.copy_failed":         "❌ Copy thất bại: {err}",
        "tools.poll_needs_options":  "❌ Poll cần ít nhất 2 lựa chọn.",
        "tools.poll_created":        "✅ Đã tạo poll (ID {mid}) với {n} lựa chọn.",
        "tools.poll_failed":         "❌ Tạo poll thất bại: {err}",
        "tools.chat_info_name":        "📛 Tên: {name}",
        "tools.chat_info_id":          "🆔 ID: {id}",
        "tools.chat_info_type":        "📂 Loại: {type}",
        "tools.chat_info_username":    "🔗 Username: @{username}",
        "tools.chat_info_description": "📄 Mô tả: {desc}",
        "tools.chat_info_invite":      "🔗 Invite: {link}",
        "tools.get_chat_info_failed":  "❌ Lấy thông tin thất bại: {err}",
        "tools.members_count":         "👥 Chat {target} có {count:,} thành viên.",
        "tools.members_count_failed":  "❌ Lấy số thành viên thất bại: {err}",
        "tools.dice_sent":           "✅ Đã gửi {emoji} (kết quả: {value}).",
        "tools.dice_failed":         "❌ Gửi dice thất bại: {err}",
        "tools.promoted_admin":      "✅ Đã promote user {uid} thành admin.",
        "tools.promote_failed":      "❌ Promote thất bại: {err}",
        "tools.demoted_admin":       "✅ Đã demote user {uid} (xóa quyền admin).",
        "tools.demote_failed":       "❌ Demote thất bại: {err}",
        "tools.title_changed":       "✅ Đã đổi tên chat thành '{title}'.",
        "tools.title_failed":        "❌ Đổi tên thất bại: {err}",
        "tools.description_updated": "✅ Đã cập nhật mô tả chat.",
        "tools.description_failed":  "❌ Cập nhật mô tả thất bại: {err}",
        "tools.photo_sent":          "✅ Đã gửi ảnh (ID {mid}) tới {target}.",
        "tools.photo_failed":        "❌ Gửi ảnh thất bại: {err}",
        "tools.message_edited":      "✅ Đã sửa tin nhắn {mid}.",
        "tools.edit_failed":         "❌ Sửa thất bại: {err}",
        "tools.caption_edited":       "✅ Đã sửa caption tin nhắn {mid}.",
        "tools.caption_edit_failed":  "❌ Sửa caption thất bại: {err}",
        "tools.sticker_sent":        "✅ Đã gửi sticker (ID {mid}) tới {target}.",
        "tools.sticker_failed":      "❌ Gửi sticker thất bại: {err}",
        "tools.animation_sent":      "✅ Đã gửi animation/GIF (ID {mid}) tới {target}.",
        "tools.animation_failed":    "❌ Gửi animation thất bại: {err}",
        "tools.file_url_fetch_failed": "❌ Không thể tải file từ URL: {ref}",
        "tools.file_sent":           "✅ Đã gửi {method} '{fname}' ({size}) tới {target} (msg_id={mid}).",
        "tools.file_send_failed":    "❌ Gửi file thất bại: {err}",
        "tools.left_chat":           "✅ Bot đã thoát khỏi chat {target}.",
        "tools.leave_chat_failed":   "❌ Thoát chat thất bại: {err}",
        "tools.invite_link_created": "✅ Đã tạo invite link cho {target}:",
        "tools.invite_link_line":    "🔗 {link}",
        "tools.invite_link_name":    "📛 Tên: {name}",
        "tools.invite_link_expiry":  "⏰ Hết hạn sau {hours}h",
        "tools.invite_link_limit":   "👥 Giới hạn: {limit} người",
        "tools.invite_link_failed":  "❌ Tạo invite link thất bại: {err}",
        "tools.invited_user":        "✅ Đã thêm user {uid} vào {target}.",
        "tools.invite_user_failed":  "❌ Mời user thất bại: {err}",
        "tools.media_group_empty":   "❌ Danh sách media trống.",
        "tools.media_group_invalid": "❌ Không có media hợp lệ.",
        "tools.media_group_sent":    "✅ Đã gửi album {n} media tới {target}.",
        "tools.media_group_failed":  "❌ Gửi media group thất bại: {err}",
        "tools.user_info_name":      "👤 {name}",
        "tools.user_info_id":        "🆔 ID: {id}",
        "tools.user_info_username":  "🔗 @{username}",
        "tools.user_info_status":    "📋 Status: {status}",
        "tools.user_info_title":     "🏷️ Title: {title}",
        "tools.user_info_is_bot":    "🤖 Bot: Có",
        "tools.user_info_fetch_failed": "🆔 ID: {uid} (không lấy được thông tin từ chat này)",
        "tools.user_info_not_found": "Không tìm thấy user {uid}.",
        "tools.user_title_set":      "✅ Đã đặt title '{title}' cho user {uid}.",
        "tools.user_title_failed":   "❌ Đặt title thất bại: {err}",

        # ─── tools_telegram.py — nhãn trạng thái khi tool đang chạy ────────
        "tool_status.web_search":               "🌐 Đang tìm kiếm web…",
        "tool_status.fetch_url":                "🔗 Đang đọc trang web…",
        "tool_status.arxiv_search":              "📚 Đang tìm kiếm ArXiv…",
        "tool_status.run_python":                "💻 Đang chạy code Python…",
        "tool_status.tg_send_message":           "📤 Đang gửi tin nhắn…",
        "tool_status.tg_react":                  "😊 Đang thả reaction…",
        "tool_status.tg_delete_message":         "🗑️ Đang xóa tin nhắn…",
        "tool_status.tg_pin_message":            "📌 Đang ghim tin nhắn…",
        "tool_status.tg_unpin_message":          "📌 Đang bỏ ghim…",
        "tool_status.tg_ban_user":               "🚫 Đang ban user…",
        "tool_status.tg_unban_user":             "✅ Đang unban user…",
        "tool_status.tg_mute_user":              "🔇 Đang mute user…",
        "tool_status.tg_unmute_user":            "🔊 Đang unmute user…",
        "tool_status.tg_forward_message":        "↪️ Đang forward tin nhắn…",
        "tool_status.tg_copy_message":           "📋 Đang copy tin nhắn…",
        "tool_status.tg_send_poll":              "📊 Đang tạo poll…",
        "tool_status.tg_get_chat_info":          "ℹ️ Đang lấy thông tin chat…",
        "tool_status.tg_get_chat_members_count": "👥 Đang đếm thành viên…",
        "tool_status.tg_send_dice":              "🎲 Đang tung xúc xắc…",
        "tool_status.tg_promote_admin":          "👑 Đang promote admin…",
        "tool_status.tg_demote_admin":           "🔽 Đang demote admin…",
        "tool_status.tg_set_chat_title":         "✏️ Đang đổi tên chat…",
        "tool_status.tg_set_chat_description":   "📝 Đang cập nhật mô tả…",
        "tool_status.tg_send_photo":             "🖼️ Đang gửi ảnh…",
        "tool_status.tg_edit_message":           "✏️ Đang sửa tin nhắn…",
        "tool_status.tg_send_sticker":           "🎭 Đang gửi sticker…",
        "tool_status.tg_send_animation":         "🎬 Đang gửi animation/GIF…",
        "tool_status.tg_send_document":          "📤 Đang gửi file…",
        "tool_status.tg_leave_chat":             "🚪 Đang thoát chat…",
        "tool_status.tg_create_invite_link":     "🔗 Đang tạo invite link…",
        "tool_status.tg_invite_user":            "➕ Đang mời user…",
        "tool_status.tg_send_media_group":       "🖼️ Đang gửi album…",
        "tool_status.tg_get_user_info":          "👤 Đang lấy thông tin user…",
        "tool_status.tg_set_user_title":         "🏷️ Đang đặt title…",
        "tool_status.tg_resolve_user":           "🔎 Đang tra user…",

        # Inbound file content (file_process.py / handlers._extract_media)
        "file.content_header":     "--- Nội dung file '{filename}' ---",
        "file.truncated":          "\n…[nội dung bị cắt bớt vì quá dài]",
        "file.xlsx_rows_truncated": "…[còn nhiều dòng hơn, đã cắt bớt]",
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
