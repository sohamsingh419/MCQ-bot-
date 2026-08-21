"""Global-admin targeted delivery and broadcast composer."""
from __future__ import annotations

import shlex
from urllib.parse import urlparse

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import VALID_STATES, get_settings
from bot.handlers.start import INDIAN_STATES, STATE_PAGE_SIZE, state_page_count
from bot.services.delivery import DeliveryService

DRAFT_KEY = "delivery_draft"


def _is_bot_admin(user_id: int) -> bool:
    return user_id in get_settings().global_admin_ids


def _admin_notice() -> str:
    return "यह सुविधा केवल configured bot admins के लिए है। ADMIN_USER_IDS में अपना Telegram user ID जोड़ें।"


def _menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 राज्य के अनुसार भेजें", callback_data="deliver:mode:targeted")],
        [InlineKeyboardButton("📣 Broadcast भेजें", callback_data="deliver:mode:broadcast")],
        [InlineKeyboardButton("✖️ बंद करें", callback_data="deliver:close")],
    ])


def _audience_keyboard(mode: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👤 केवल users", callback_data=f"deliver:audience:{mode}:users")],
        [InlineKeyboardButton("👥 केवल groups", callback_data=f"deliver:audience:{mode}:groups")],
        [InlineKeyboardButton("👤👥 users और groups", callback_data=f"deliver:audience:{mode}:both")],
        [InlineKeyboardButton("← वापस", callback_data="deliver:home")],
    ])


def _state_keyboard(audience: str, page: int = 0) -> InlineKeyboardMarkup:
    total_pages = state_page_count()
    page = max(0, min(page, total_pages - 1))
    states = INDIAN_STATES[page * STATE_PAGE_SIZE:(page + 1) * STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 All India", callback_data=f"deliver:state:{audience}:All India")])
    for index in range(0, len(states), 2):
        rows.append([
            InlineKeyboardButton(state, callback_data=f"deliver:state:{audience}:{state}")
            for state in states[index:index + 2]
        ])
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅ पिछली सूची", callback_data=f"deliver:statepage:{audience}:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("अगली सूची ➡", callback_data=f"deliver:statepage:{audience}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("← recipients", callback_data="deliver:home")])
    return InlineKeyboardMarkup(rows)


def _content_keyboard(mode: str, audience: str, state: str | None) -> InlineKeyboardMarkup:
    state_token = state or "all"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Text message", callback_data=f"deliver:content:{mode}:{audience}:{state_token}:text")],
        [InlineKeyboardButton("📊 Forward MCQ poll", callback_data=f"deliver:content:{mode}:{audience}:{state_token}:poll")],
        [InlineKeyboardButton("🖼️ Photo", callback_data=f"deliver:content:{mode}:{audience}:{state_token}:photo")],
        [InlineKeyboardButton("🎬 Video", callback_data=f"deliver:content:{mode}:{audience}:{state_token}:video")],
        [InlineKeyboardButton("← वापस", callback_data="deliver:home")],
    ])


def _parse_inline_button(text: str) -> dict[str, str] | None:
    try:
        parts = shlex.split(text)
    except ValueError:
        return None
    if len(parts) < 2:
        return None
    label, url = " ".join(parts[:-1]).strip(), parts[-1]
    if not label or len(label) > 64:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return {"text": label, "url": url}


def _reply_content(message) -> tuple[str, str | None, dict[str, object]] | None:
    if message is None:
        return None
    if message.text and not message.text.startswith("/"):
        return "text", message.text, {}
    if message.photo:
        return "photo", message.caption, {"file_id": message.photo[-1].file_id}
    if message.video:
        return "video", message.caption, {"file_id": message.video.file_id}
    if message.poll and message.poll.type == "quiz":
        return "poll", message.poll.question, {
            "source_chat_id": message.chat_id,
            "source_message_id": message.message_id,
            "question": message.poll.question,
            "options": [option.text for option in message.poll.options],
            "correct_option": message.poll.correct_option_id,
        }
    return None


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm भेजें", callback_data="deliver:confirm")],
        [InlineKeyboardButton("✖️ रद्द करें", callback_data="deliver:cancel")],
    ])


async def delivery_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_user or not update.effective_message:
        return
    if not _is_bot_admin(update.effective_user.id):
        await update.effective_message.reply_text(_admin_notice())
        return
    raw_text = update.effective_message.text or ""
    command_name = raw_text.split(maxsplit=1)[0].split("@", 1)[0].lstrip("/").lower()
    raw_args = raw_text.split(None, 1)[1] if len(raw_text.split(None, 1)) == 2 else ""
    if command_name == "broadcast" and raw_args:
        reply = update.effective_message.reply_to_message
        button = _parse_inline_button(raw_args)
        content = _reply_content(reply)
        if button is None or content is None:
            await update.effective_message.reply_text(
                "Usage: reply to a text/photo/video/quiz-poll and write:\n"
                "/broadcast \"Button text\" https://example.com\n\n"
                "Button text max 64 characters; link must start with http:// or https://."
            )
            return
        content_type, content_text, payload = content
        payload["inline_button"] = button
        context.user_data[DRAFT_KEY] = {
            "mode": "broadcast", "audience": None, "state": None,
            "content_type": content_type, "content_text": content_text,
            "payload": payload, "content_ready": True,
        }
        await update.effective_message.reply_text(
            f"✅ Button set: {button['text']}\n🔗 {button['url']}\n\nअब recipients चुनें:",
            reply_markup=_audience_keyboard("broadcast"),
        )
        return
    context.user_data.pop(DRAFT_KEY, None)
    await update.effective_message.reply_text(
        "📨 *Admin delivery center*\n\n"
        "राज्य के अनुसार भेजें: चुने हुए राज्य वाले users/groups को ही content जाएगा।\n"
        "Broadcast: सभी users, सभी groups, या दोनों को content जाएगा।\n\n"
        "पहले delivery type चुनें।",
        reply_markup=_menu_keyboard(), parse_mode="Markdown",
    )


async def delivery_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.data is None or query.message is None or not query.data.startswith("deliver:"):
        return
    if not _is_bot_admin(query.from_user.id):
        await query.answer(_admin_notice(), show_alert=True)
        return
    parts = query.data.split(":")
    action = parts[1]

    if action in {"home", "cancel"}:
        context.user_data.pop(DRAFT_KEY, None)
        await query.answer()
        await query.edit_message_text("📨 *Admin delivery center*\n\nDelivery type चुनें।", reply_markup=_menu_keyboard(), parse_mode="Markdown")
        return
    if action == "close":
        context.user_data.pop(DRAFT_KEY, None)
        await query.answer()
        await query.edit_message_text("Admin delivery center बंद कर दिया गया है। दोबारा खोलने के लिए /targeted या /broadcast लिखें।")
        return
    if action == "mode" and len(parts) == 3:
        mode = parts[2]
        if mode not in {"targeted", "broadcast"}:
            await query.answer("अमान्य विकल्प", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(
            "किसे भेजना है?", reply_markup=_audience_keyboard(mode), parse_mode="Markdown"
        )
        return
    if action == "audience" and len(parts) == 4:
        mode, audience = parts[2], parts[3]
        if mode not in {"targeted", "broadcast"} or audience not in {"users", "groups", "both"}:
            await query.answer("अमान्य विकल्प", show_alert=True)
            return
        await query.answer()
        if mode == "targeted":
            await query.edit_message_text(
                "🗺️ *राज्य चुनें*\nउस राज्य को चुने रखने वाले recipients को ही यह delivery जाएगी।",
                reply_markup=_state_keyboard(audience), parse_mode="Markdown",
            )
        else:
            draft = context.user_data.get(DRAFT_KEY)
            if draft and draft.get("content_ready"):
                draft["mode"] = mode
                draft["audience"] = audience
                service: DeliveryService = context.application.bot_data["delivery_service"]
                recipients = await service.audience_preview_details(audience, None)
                button = draft.get("payload", {}).get("inline_button", {})
                await query.edit_message_text(
                    "📋 Broadcast preview\n\n"
                    f"Type: {draft['content_type']}\nAudience: {audience}\n"
                    f"Recipients: {len(recipients)}\n"
                    f"Button: {button.get('text', '—')}\nURL: {button.get('url', '—')}\n\n"
                    "Confirm दबाने के बाद ही broadcast जाएगी।",
                    reply_markup=_confirm_keyboard(),
                )
            else:
                await query.edit_message_text(
                    "📣 *Broadcast content type चुनें*\nयह सभी चुने हुए recipients को जाएगा।",
                    reply_markup=_content_keyboard(mode, audience, None), parse_mode="Markdown",
                )
        return
    if action == "statepage" and len(parts) == 4 and parts[2] in {"users", "groups", "both"} and parts[3].isdigit():
        audience, page = parts[2], int(parts[3])
        await query.answer()
        await query.edit_message_text(
            f"🗺️ *राज्य चुनें*\nराज्य सूची: {page + 1}/{state_page_count()}",
            reply_markup=_state_keyboard(audience, page), parse_mode="Markdown",
        )
        return
    if action == "state" and len(parts) >= 4:
        audience, state = parts[2], ":".join(parts[3:])
        if audience not in {"users", "groups", "both"} or state not in VALID_STATES:
            await query.answer("अमान्य राज्य", show_alert=True)
            return
        await query.answer()
        await query.edit_message_text(
            f"🎯 *{state} के लिए content type चुनें*", reply_markup=_content_keyboard("targeted", audience, state), parse_mode="Markdown"
        )
        return
    if action == "content" and len(parts) >= 6:
        mode, audience, state_token, content_type = parts[2], parts[3], parts[4], parts[5]
        if mode not in {"targeted", "broadcast"} or audience not in {"users", "groups", "both"} or content_type not in {"text", "poll", "photo", "video"}:
            await query.answer("अमान्य विकल्प", show_alert=True)
            return
        state = None if state_token == "all" else state_token
        if state and state not in VALID_STATES:
            await query.answer("अमान्य राज्य", show_alert=True)
            return
        context.user_data[DRAFT_KEY] = {"mode": mode, "audience": audience, "state": state, "content_type": content_type}
        await query.answer()
        prompts = {
            "text": "अब वह text message भेजें जिसे recipients को भेजना है।",
            "poll": "अब कोई existing Telegram MCQ quiz poll यहाँ forward करें।\nText format की जरूरत नहीं है।",
            "photo": "अब photo भेजें। आप optional caption भी जोड़ सकते हैं।",
            "video": "अब video भेजें। आप optional caption भी जोड़ सकते हैं।",
        }
        await query.edit_message_text("✍️ *Content तैयार करें*\n\n" + prompts[content_type], parse_mode="Markdown")
        return
    if action == "confirm":
        draft = context.user_data.get(DRAFT_KEY)
        if not draft:
            await query.answer("Draft समाप्त हो गया है। कृपया /deliver फिर से खोलें।", show_alert=True)
            return
        await query.answer("Delivery भेजी जा रही है…")
        service: DeliveryService = context.application.bot_data["delivery_service"]
        send_draft = {key: value for key, value in draft.items() if key != "content_ready"}
        summary = await service.send(created_by=query.from_user.id, **send_draft)
        context.user_data.pop(DRAFT_KEY, None)
        if summary.recipients == 0:
            await query.edit_message_text("कोई eligible recipient नहीं मिला। State या recipient type बदलकर फिर प्रयास करें।")
        else:
            await query.edit_message_text(
                f"✅ Delivery पूरी हुई।\nCampaign: {summary.campaign_id}\nRecipients: {summary.recipients}\nSent: {summary.sent}\nFailed: {summary.failed}"
            )
        return
    await query.answer("यह विकल्प उपलब्ध नहीं है।", show_alert=True)


async def delivery_content_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture delivery content, or delegate active bulk-MCQ intake to its state machine."""
    if context.user_data.get("bulk_import_draft"):
        from bot.handlers.bulk_import import bulk_content_handler
        await bulk_content_handler(update, context)
        return
    if not update.effective_user or not update.effective_message:
        return
    draft = context.user_data.get(DRAFT_KEY)
    if not draft:
        return
    if not _is_bot_admin(update.effective_user.id):
        context.user_data.pop(DRAFT_KEY, None)
        return
    message = update.effective_message
    content_type = draft["content_type"]
    payload: dict[str, object] = {}
    content_text: str | None = None
    if content_type == "text":
        if not message.text or message.text.startswith("/"):
            await message.reply_text("कृपया सामान्य text message भेजें।")
            return
        content_text = message.text
    elif content_type == "poll":
        if not message.poll:
            await message.reply_text("कृपया कोई existing Telegram MCQ quiz poll forward करें। Text format स्वीकार नहीं है।")
            return
        if message.poll.type != "quiz":
            await message.reply_text("कृपया MCQ quiz poll forward करें; साधारण poll स्वीकार नहीं है।")
            return
        payload = {
            "source_chat_id": message.chat_id,
            "source_message_id": message.message_id,
            "question": message.poll.question,
            "options": [option.text for option in message.poll.options],
            "correct_option": message.poll.correct_option_id,
        }
        content_text = message.poll.question
    elif content_type == "photo":
        if not message.photo:
            await message.reply_text("कृपया photo भेजें।")
            return
        payload = {"file_id": message.photo[-1].file_id}
        content_text = message.caption
    elif content_type == "video":
        if not message.video:
            await message.reply_text("कृपया video file भेजें।")
            return
        payload = {"file_id": message.video.file_id}
        content_text = message.caption
    else:
        context.user_data.pop(DRAFT_KEY, None)
        return

    draft["content_text"] = content_text
    draft["payload"] = payload
    service: DeliveryService = context.application.bot_data["delivery_service"]
    recipients = await service.audience_preview_details(draft["audience"], draft["state"])
    scope = draft["state"] or "सभी states"
    recipient_lines = [f"• {title} ({'user' if chat_type == 'private' else 'group'})" for _, title, chat_type in recipients[:12]]
    if len(recipients) > 12:
        recipient_lines.append(f"• … और {len(recipients) - 12} recipients")
    recipient_list = "\n".join(recipient_lines) if recipient_lines else "कोई eligible recipient नहीं मिला"
    poll_details = ""
    if content_type == "poll":
        poll_details = f"\n\n*Forwarded MCQ:*\n{content_text}\nOptions: {len(payload.get('options', []))}"
    await message.reply_text(
        f"📋 *Delivery preview*\n\nType: {content_type}\nMode: {draft['mode']}\nAudience: {draft['audience']}\nState: {scope}\nRecipients: {len(recipients)}{poll_details}\n\n*Recipients:*\n{recipient_list}\n\n"
        "Confirm दबाने के बाद ही delivery जाएगी।",
        reply_markup=_confirm_keyboard(), parse_mode="Markdown",
    )
