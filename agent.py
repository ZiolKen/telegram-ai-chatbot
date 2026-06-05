"""
Core AI agent — orchestrates Gemini API calls and multi-turn tool use.

Flow per user message:
  1. Build request: history + user text + all tool declarations
  2. POST to Gemini
  3. If model returns functionCall(s) → execute tools → send results back
  4. Repeat until model returns plain text (max MAX_TOOL_ROUNDS per request)
  5. Return final text
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import aiohttp

from config import DEFAULT_MODEL, GEMINI_KEYS, MODELS
from tools_code import CODE_TOOL_DECLS, run_python
from tools_telegram import TG_TOOL_DECLS, TG_HANDLERS, TelegramContext
from tools_web import (
    WEB_TOOL_DECLS,
    arxiv_search,
    fetch_url,
    web_search,
)

logger = logging.getLogger(__name__)

# ── Combined tool manifest ─────────────────────────────────────
ALL_TOOL_DECLS = WEB_TOOL_DECLS + CODE_TOOL_DECLS + TG_TOOL_DECLS

MAX_TOOL_ROUNDS = 12        # safety cap for tool-use loops
GEMINI_TIMEOUT  = aiohttp.ClientTimeout(total=90)
BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


# ─────────────────────────────────────────────────────────────
# Low-level Gemini call
# ─────────────────────────────────────────────────────────────
async def _gemini(
    session:       aiohttp.ClientSession,
    api_key:       str,
    model:         str,
    contents:      list[dict],
    system_prompt: str,
    tools:         Optional[list],
) -> dict | None:
    """Single Gemini API call.  Returns response dict or None on failure."""
    url = f"{BASE_URL}/{model}:generateContent?key={api_key}"
    payload: dict = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 8192,
        },
    }
    if tools:
        payload["tools"]       = [{"function_declarations": tools}]
        payload["tool_config"] = {"function_calling_config": {"mode": "AUTO"}}

    try:
        async with session.post(url, json=payload) as r:
            if r.status == 200:
                return await r.json()
            if r.status == 429:
                logger.warning("Rate-limit: key=%.8s model=%s", api_key, model)
                return None
            if r.status == 404:
                logger.warning("Model not found: %s", model)
                return {"_skip_model": True}
            body = await r.text()
            logger.error("Gemini %s [%s]: %s", r.status, model, body[:200])
            return None
    except asyncio.TimeoutError:
        logger.warning("Timeout: %s", model)
        return None
    except Exception as e:
        logger.error("Network error calling Gemini: %s", e)
        return None


# ─────────────────────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────────────────────
async def _dispatch(
    name:    str,
    args:    dict,
    tg_ctx:  Optional[TelegramContext],
    status_cb: Optional[Callable] = None,
) -> str:
    """Execute a named tool and return its string result."""
    if status_cb:
        asyncio.create_task(status_cb(name))

    # Web tools
    if name == "web_search":
        return await web_search(args.get("query", ""), args.get("engine", "duckduckgo"))
    if name == "fetch_url":
        return await fetch_url(args.get("url", ""))
    if name == "arxiv_search":
        return await arxiv_search(args.get("query", ""), args.get("max_results", 3))

    # Code tool
    if name == "run_python":
        return await run_python(args.get("code", ""))

    # Telegram tools
    if name in TG_HANDLERS:
        if not tg_ctx:
            return "⚠️ Không có Telegram context."
        fn = TG_HANDLERS[name]
        # Remove `ctx` from args dict — it is the first positional param
        return await fn(tg_ctx, **{k: v for k, v in args.items()})

    return f"⚠️ Tool không xác định: {name}"


# ─────────────────────────────────────────────────────────────
# Public: run the full agent loop
# ─────────────────────────────────────────────────────────────
async def run_agent(
    tg_ctx:        Optional[TelegramContext],
    user_text:     str,
    history:       list[dict],
    system_prompt: str,
    model:         Optional[str] = None,
    use_plugins:   bool = True,
    status_cb:     Optional[Callable] = None,  # async fn(tool_name) → None
) -> str:
    """
    Drive a Gemini conversation with full multi-turn tool use.
    Returns the final text reply.
    """
    preferred  = model or DEFAULT_MODEL
    model_list = [preferred] + [m for m in MODELS if m != preferred]
    tools      = ALL_TOOL_DECLS if use_plugins else None

    # Build initial contents
    base_contents = list(history) + [
        {"role": "user", "parts": [{"text": user_text}]}
    ]

    async with aiohttp.ClientSession(timeout=GEMINI_TIMEOUT) as session:
        for api_key in GEMINI_KEYS:
            for model_name in model_list:
                contents = list(base_contents)

                for _round in range(MAX_TOOL_ROUNDS):
                    resp = await _gemini(
                        session, api_key, model_name,
                        contents, system_prompt, tools,
                    )
                    if resp is None:
                        break                      # try next model
                    if resp.get("_skip_model"):
                        break                      # model 404 — try next

                    try:
                        candidate = resp["candidates"][0]
                        content   = candidate["content"]
                        parts     = content.get("parts", [])
                    except (KeyError, IndexError):
                        logger.error("Unexpected Gemini response: %s",
                                     str(resp)[:300])
                        break

                    fn_calls   = [p for p in parts if "functionCall" in p]
                    text_parts = [p.get("text", "") for p in parts if "text" in p]

                    if not fn_calls:
                        # ── Terminal text response ──────────────────────
                        return "\n".join(text_parts).strip()

                    # ── Execute all requested tools ─────────────────────
                    fn_responses = []
                    for fc_part in fn_calls:
                        fc      = fc_part["functionCall"]
                        fn_name = fc["name"]
                        fn_args = fc.get("args") or {}
                        logger.info("Tool call: %s(%s)", fn_name,
                                    str(fn_args)[:120])
                        result = await _dispatch(fn_name, fn_args,
                                                 tg_ctx, status_cb)
                        fn_responses.append({
                            "functionResponse": {
                                "name":     fn_name,
                                "response": {"result": result},
                            }
                        })

                    # Append model's function-call turn + our results
                    contents.append(content)        # model turn (function_call)
                    contents.append({               # user turn  (function_result)
                        "role":  "user",
                        "parts": fn_responses,
                    })

                # If we broke out of the tool loop due to an error,
                # try the next model
    return "❌ Tất cả API key và model đều không phản hồi. Vui lòng thử lại."


# ─────────────────────────────────────────────────────────────
# Follow-up question generator
# ─────────────────────────────────────────────────────────────
async def generate_followup(
    history:      list[dict],
    last_response: str,
    count:        int = 3,
) -> list[str]:
    """Generate concise follow-up questions the user might ask next."""
    prompt = (
        f"Dựa trên cuộc hội thoại vừa rồi và câu trả lời sau, "
        f"hãy tạo đúng {count} câu hỏi tiếp theo ngắn gọn mà người dùng "
        f"có thể muốn hỏi. Chỉ trả về các câu hỏi, mỗi câu một dòng, "
        f"không đánh số, không thêm gì khác.\n\n"
        f"Câu trả lời vừa rồi:\n{last_response[:600]}"
    )
    try:
        result = await run_agent(
            tg_ctx        = None,
            user_text     = prompt,
            history       = history[-6:],
            system_prompt = (
                "Bạn tạo câu hỏi tiếp theo ngắn gọn, tự nhiên "
                "dựa trên ngữ cảnh hội thoại."
            ),
            use_plugins   = False,
        )
        qs = [q.strip() for q in result.splitlines() if q.strip()]
        return qs[:count]
    except Exception as e:
        logger.error("generate_followup: %s", e)
        return []


# ─────────────────────────────────────────────────────────────
# System prompt builder
# ─────────────────────────────────────────────────────────────
def build_system_prompt(tg_ctx: TelegramContext) -> str:
    now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""Bạn là một AI Agent cực kỳ mạnh mẽ hoạt động trên Telegram.
Bạn có thể làm MỌI thứ mà một admin con người có thể làm — bao gồm gửi tin nhắn \
tới các nhóm/kênh khác, react emoji, xóa/ghim tin nhắn, ban/mute user, \
tạo poll, forward tin nhắn, và nhiều hơn nữa.

═══ THÔNG TIN PHIÊN HIỆN TẠI ═══
🕐 Thời gian : {now}
💬 Chat      : {tg_ctx.chat_title or "Private"} (ID: {tg_ctx.chat_id})
👤 Người dùng: {tg_ctx.user_name} (ID: {tg_ctx.user_id})
📨 Message ID: {tg_ctx.message_id}
🧵 Thread ID : {tg_ctx.thread_id or "N/A"}

═══ CÔNG CỤ CÓ SẴN ═══
🌐 web_search       — Tìm kiếm web (DuckDuckGo / Google)
🔗 fetch_url        — Đọc nội dung trang web / bài báo
📚 arxiv_search     — Tìm paper khoa học
💻 run_python       — Chạy code Python (math, xử lý dữ liệu, v.v.)

📤 tg_send_message  — Gửi tin nhắn tới BẤT KỲ chat nào bot đang là thành viên
😊 tg_react         — Thả emoji reaction vào tin nhắn
🗑️ tg_delete_message— Xóa tin nhắn
📌 tg_pin_message   — Ghim / tg_unpin_message bỏ ghim
🚫 tg_ban_user      — Ban / tg_unban_user bỏ ban
🔇 tg_mute_user     — Mute / tg_unmute_user bỏ mute
↪️ tg_forward_message— Forward tin nhắn
📋 tg_copy_message  — Copy tin nhắn (không có nhãn "Forwarded")
📊 tg_send_poll     — Tạo poll
ℹ️ tg_get_chat_info — Xem thông tin chat
👥 tg_get_chat_members_count — Đếm thành viên
🎲 tg_send_dice     — Tung xúc xắc / game emoji
👑 tg_promote_admin / tg_demote_admin — Cấp/thu quyền admin
✏️ tg_set_chat_title / tg_set_chat_description — Chỉnh sửa chat

═══ NGUYÊN TẮC ═══
• Sử dụng tool chủ động khi cần thông tin thực tế hoặc hành động Telegram.
• Trả lời ngắn gọn, súc tích. Dùng Markdown khi phù hợp.
• Khi thực hiện hành động Telegram, hãy báo cáo kết quả.
• Mặc định chat_id là chat hiện tại ({tg_ctx.chat_id}) nếu không chỉ định.
• Có thể gọi nhiều tool trong một lượt nếu cần."""
