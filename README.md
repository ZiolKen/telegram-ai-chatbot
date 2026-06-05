# 🤖 Telegram AI Agent — Siêu mạnh

Chatbot Telegram được cấp siêu năng lực bởi Gemini AI + Function Calling.
Bot có thể làm **mọi thứ** một admin con người có thể làm trên Telegram.

---

## ✨ Tính năng

| Nhóm | Tính năng |
|------|-----------|
| 🧠 **AI** | Gemini với multi-key rotation, multi-model fallback, function calling |
| 🌐 **Web** | Tìm kiếm DuckDuckGo & Google, đọc URL, tìm paper ArXiv |
| 💻 **Code** | Chạy Python an toàn trong subprocess (timeout 15s) |
| 📤 **Telegram Actions** | Gửi tin nhắn tới nhóm/kênh bất kỳ, react emoji, pin, xóa, forward, copy, poll, dice |
| 👮 **Moderation** | Ban, unban, mute, unmute, promote/demote admin |
| ⚙️ **Quản trị chat** | Đổi tên, mô tả, đếm thành viên, lấy thông tin chat |
| 🏷️ **Topic Mode** | Cô lập lịch sử + cấu hình theo từng topic trong Supergroup |
| 👥 **Multi-user** | Mỗi user có hội thoại riêng; trong topic mode thì chia sẻ theo topic |
| 📏 **Long text** | Tự động ghép tin nhắn dài liên tiếp; chia nhỏ câu trả lời dài |
| 💡 **Follow-up** | Tự sinh 3 câu hỏi gợi ý sau mỗi câu trả lời (click để hỏi tiếp) |
| 🔐 **Access Control** | Whitelist, Blacklist, Admin — lưu persistent vào file JSON |

---

## 🚀 Cài đặt

### 1. Clone và cài dependencies

```bash
git clone <repo>
cd telegram-ai-chatbot
pip install -r requirements.txt
```

### 2. Biến môi trường

| Biến | Bắt buộc | Mô tả |
|------|----------|-------|
| `BOT_TOKEN` | ✅ | Token từ [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | ✅ | Telegram user ID của chủ bot |
| `GEMINI_KEYS` | ✅ | Các API key Gemini cách nhau dấu phẩy |
| `WEBHOOK_URL` | Render | URL public của server (VD: `https://mybot.onrender.com`) |
| `PORT` | Render | Cổng server (mặc định `8080`) |
| `GOOGLE_API_KEY` | Tùy chọn | Google Custom Search API key |
| `GOOGLE_CSE_ID` | Tùy chọn | Google Custom Search Engine ID |
| `DEFAULT_MODEL` | Tùy chọn | Model mặc định (mặc định: `gemini-2.5-flash`) |
| `MAX_HISTORY` | Tùy chọn | Số tin nhắn lưu lịch sử (mặc định: `40`) |
| `ENABLE_FOLLOWUP` | Tùy chọn | Bật gợi ý câu hỏi (mặc định: `true`) |
| `ENABLE_PLUGINS` | Tùy chọn | Bật plugins (mặc định: `true`) |

### 3. Chạy local (polling)

```bash
export BOT_TOKEN="..."
export OWNER_ID="123456789"
export GEMINI_KEYS="key1,key2,key3"
python main.py
```

### 4. Deploy lên Render (webhook)

1. Tạo **Web Service** trên [render.com](https://render.com)
2. Build command: `pip install -r requirements.txt`
3. Start command: `python main.py`
4. Thêm Environment Variables (bảng trên)
5. Đặt `WEBHOOK_URL` = URL Render cấp cho bạn

---

## 📋 Lệnh

### Cơ bản (mọi người)
| Lệnh | Mô tả |
|------|-------|
| `/start` | Giới thiệu bot |
| `/help` | Xem toàn bộ lệnh |
| `/reset` | Xóa lịch sử hội thoại hiện tại |
| `/status` | Xem cấu hình của cuộc hội thoại này |
| `/model` | Xem model đang dùng |
| `/model gemini-2.0-flash` | Đổi model |
| `/plugins on\|off` | Bật/tắt tất cả plugins & tools |

### Admin
| Lệnh | Mô tả |
|------|-------|
| `/topic on\|off` | Bật/tắt topic isolation mode |
| `/whitelist add\|remove [id]` | Quản lý whitelist |
| `/blacklist add\|remove [id]` | Quản lý blacklist |
| `/access` | Xem toàn bộ whitelist/blacklist |
| `/sysreset` | Xóa toàn bộ lịch sử |

### Owner (chủ bot)
| Lệnh | Mô tả |
|------|-------|
| `/admin add\|remove [id]` | Cấp/thu quyền admin |
| `/admin list` | Xem danh sách admin |

> **Tip:** Hầu hết lệnh admin đều hỗ trợ reply vào tin nhắn của user thay vì nhập ID.

---

## 💬 Cách dùng trong Telegram

### Chat riêng (Private)
Nhắn tin trực tiếp với bot — luôn phản hồi.

### Nhóm / Supergroup
- **@mention**: `@YourBot tìm giúp tao thông tin về...`
- **Reply**: Reply vào tin nhắn bot để tiếp tục hội thoại

### Topic Mode (Supergroup với Topics)
Bật với `/topic on`. Sau đó:
- Mỗi topic có lịch sử, model, plugin riêng
- Dùng lệnh `/model` hoặc `/plugins` trong topic nào thì chỉ ảnh hưởng topic đó

---

## 🔌 Ví dụ prompt

```
# Tìm kiếm web
Tìm tin tức về AI mới nhất hôm nay

# Đọc URL
Tóm tắt bài viết này: https://example.com/article

# Chạy code
Tính 100 số nguyên tố đầu tiên bằng Python

# Gửi tin nhắn tới nhóm khác
Gửi "Cuộc họp lúc 3h chiều nay!" tới @mygroup

# React emoji
React 🔥 vào tin nhắn trên

# Tạo poll
Tạo poll "Ăn gì trưa nay?" với các lựa chọn: Phở, Bún bò, Cơm tấm, Bánh mì

# Tìm paper khoa học
Tìm 3 paper mới nhất về large language models trên ArXiv
```

---

## 🏗️ Kiến trúc

```
main.py          — Entry point, webhook/polling setup
config.py        — Environment variables
state.py         — In-memory state + JSON persistence
agent.py         — Gemini agent loop (multi-turn function calling)
tools_web.py     — DuckDuckGo, Google, URL fetch, ArXiv
tools_code.py    — Python code interpreter
tools_telegram.py— 18+ Telegram actions (send, react, ban, poll…)
handlers.py      — Message accumulation, response sending
commands.py      — Slash command handlers
utils.py         — Text splitting, merging, helpers
data/            — Persisted JSON (admins, whitelist, blacklist, config)
```

### Agent loop

```
User message
    │
    ▼
Gemini API ──────────────────────────────────────┐
    │                                             │
    ├─ functionCall (tool request)                │
    │       │                                     │
    │       ▼                                     │
    │  Execute tool (web/code/telegram)           │
    │       │                                     │
    │  functionResponse ──────────────────────────┘
    │        (loop max 12 rounds)
    │
    └─ text (final answer)
            │
            ▼
    Split if > 4000 chars
    Add follow-up question buttons
    Send to Telegram
```

---

## 📝 Lưu ý

- Bot cần được thêm vào nhóm/kênh đích **trước** khi dùng lệnh `tg_send_message` tới đó
- Các thao tác admin (ban, mute, pin, xóa) yêu cầu bot có quyền admin trong nhóm
- Code execution bị giới hạn 15 giây và không có quyền truy cập mạng
- Lịch sử hội thoại reset khi restart server (chưa có persistent storage cho conversations)
