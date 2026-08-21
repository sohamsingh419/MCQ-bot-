from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import VALID_STATES, get_settings, subjects_for_state
from bot.database.repositories import Repository
from bot.handlers.start import INDIAN_STATES, STATE_PAGE_SIZE, state_page_count
from bot.services.source import ingest_source_document, safe_filename


def _state_keyboard(document_id: int, page: int = 0) -> InlineKeyboardMarkup:
    page = max(0, min(page, state_page_count() - 1))
    states = INDIAN_STATES[page * STATE_PAGE_SIZE:(page + 1) * STATE_PAGE_SIZE]
    rows: list[list[InlineKeyboardButton]] = []
    if page == 0:
        rows.append([InlineKeyboardButton("🇮🇳 पूरे भारत", callback_data=f"src:stateval:{document_id}:All India")])
    for index in range(0, len(states), 2):
        rows.append([
            InlineKeyboardButton(state, callback_data=f"src:stateval:{document_id}:{state}")
            for state in states[index:index + 2]
        ])
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(InlineKeyboardButton("⬅ पिछली सूची", callback_data=f"src:statepage:{document_id}:{page - 1}"))
    if page < state_page_count() - 1:
        navigation.append(InlineKeyboardButton("अगली सूची ➡", callback_data=f"src:statepage:{document_id}:{page + 1}"))
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(rows)


def _subject_keyboard(document_id: int, state: str) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(subject, callback_data=f"src:subject:{document_id}:{subject}")]
        for subject in subjects_for_state(state)
    ]
    rows.append([InlineKeyboardButton("❌ रद्द करें", callback_data=f"src:cancel:{document_id}")])
    return InlineKeyboardMarkup(rows)


def _is_configured_source_group(chat_id: int, settings) -> bool:
    return settings.source_group_id is not None and chat_id == settings.source_group_id


def _is_bot_admin(user_id: int, settings) -> bool:
    return user_id in settings.global_admin_ids


async def _authorized_source_uploader(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat = update.effective_chat
    user = update.effective_user
    settings = get_settings()
    return bool(
        chat and user and chat.type in {"group", "supergroup"}
        and _is_configured_source_group(chat.id, settings)
        and _is_bot_admin(user.id, settings)
    )


async def source_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    document = message.document if message else None
    if not message or not chat or not user or not document:
        return
    settings = get_settings()
    if chat.type not in {"group", "supergroup"} or not _is_configured_source_group(chat.id, settings):
        return
    if not _is_bot_admin(user.id, settings):
        await message.reply_text("यह source group केवल bot admins के लिए है।")
        return
    filename = safe_filename(document.file_name or "source.txt")
    size = int(document.file_size or 0)
    if size and size > settings.source_max_pdf_mb * 1024 * 1024:
        await message.reply_text(f"File बहुत बड़ी है। अधिकतम सीमा {settings.source_max_pdf_mb} MB है।")
        return
    root = Path(settings.source_storage_dir) / "documents" / str(chat.id)
    root.mkdir(parents=True, exist_ok=True)
    storage_path = root / f"{message.message_id}_{filename}"
    try:
        telegram_file = await context.bot.get_file(document.file_id)
        await telegram_file.download_to_drive(custom_path=str(storage_path))
        database = context.application.bot_data["database"]
        async with database.session_factory() as session:
            repo = Repository(session)
            source = await repo.create_source_document(
                telegram_file_id=document.file_id, telegram_chat_id=chat.id,
                telegram_message_id=message.message_id, uploaded_by=user.id,
                filename=filename, storage_path=str(storage_path),
            )
            await repo.commit()
            source_id = source.id
        await message.reply_text(
            f"📄 *{filename}* मिल गई है।\n\nपहले इसका क्षेत्र/state चुनें:",
            reply_markup=_state_keyboard(source_id), parse_mode="Markdown",
        )
    except Exception:
        storage_path.unlink(missing_ok=True)
        await message.reply_text("Document receive नहीं हो सका। कृपया readable PDF, TXT, DOCX, CSV, JSON, Markdown या RTF file भेजें।")


async def _process_and_notify(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    document_id: int,
    state: str,
    subject: str,
    progress_message_id: int | None = None,
) -> None:
    settings = get_settings()
    database = context.application.bot_data["database"]
    last_page = 0
    last_update = 0.0

    async def on_progress(page_number: int, total_pages: int, used_ocr: bool) -> None:
        nonlocal last_page, last_update
        if progress_message_id is None:
            return
        now = asyncio.get_running_loop().time()
        if page_number != total_pages and page_number - last_page < 10 and now - last_update < 15:
            return
        last_page = page_number
        last_update = now
        percent = int(page_number * 100 / max(total_pages, 1))
        mode = "OCR" if used_ocr else "text extraction"
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_message_id,
                text=(
                    f"⏳ Document indexing चल रही है…\n\n"
                    f"📄 Page {page_number}/{total_pages} ({percent}%)\n"
                    f"🔎 Current mode: {mode}"
                ),
            )
        except Exception:
            pass

    ok, text = await ingest_source_document(
        database,
        settings,
        document_id,
        state=state,
        subject=subject,
        progress_callback=on_progress,
    )
    prefix = "✅ " if ok else "⚠️ "
    if progress_message_id is not None:
        try:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_message_id,
                text=prefix + text,
            )
            return
        except Exception:
            pass
    await context.bot.send_message(chat_id=chat_id, text=prefix + text)


async def source_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.message is None or not query.data or not query.data.startswith("src:"):
        return
    chat = query.message.chat
    settings = get_settings()
    if chat.type not in {"group", "supergroup"} or not _is_configured_source_group(chat.id, settings) or not _is_bot_admin(query.from_user.id, settings):
        await query.answer("केवल configured source group के bot admins यह काम कर सकते हैं।", show_alert=True)
        return
    parts = query.data.split(":", 3)
    action = parts[1] if len(parts) > 1 else ""
    document_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    value = parts[3] if len(parts) > 3 else ""
    database = context.application.bot_data["database"]
    if not document_id:
        await query.answer("Invalid source document.", show_alert=True)
        return
    if action == "statepage" and value.isdigit():
        await query.answer()
        await query.edit_message_reply_markup(reply_markup=_state_keyboard(document_id, int(value)))
        return
    if action == "stateval" and value in VALID_STATES:
        async with database.session_factory() as session:
            repo = Repository(session)
            document = await repo.update_source_document(document_id, state=value)
            await repo.commit()
        await query.answer("State सेव हो गया।")
        await query.edit_message_text(
            f"📄 {document.filename}\n\nअब subject चुनें:",
            reply_markup=_subject_keyboard(document_id, value),
        )
        return
    if action == "subject" and value in subjects_for_state((await _document_state(database, document_id)) or "General"):
        state = await _document_state(database, document_id)
        async with database.session_factory() as session:
            repo = Repository(session)
            document = await repo.update_source_document(document_id, subject=value, status="queued")
            filename = document.filename
            await repo.commit()
        await query.answer("Subject सेव हो गया। Document indexing शुरू हो रही है।")
        await query.edit_message_text(f"⏳ {filename}\n\nDocument पढ़ा जा रहा है और source index बन रहा है…")
        context.application.create_task(
            _process_and_notify(
                context,
                chat.id,
                document_id,
                state or "General",
                value,
                progress_message_id=query.message.message_id,
            )
        )
        return
    if action == "cancel":
        async with database.session_factory() as session:
            repo = Repository(session)
            await repo.update_source_document(document_id, status="cancelled")
            await repo.commit()
        await query.answer("Source upload रद्द कर दिया गया।")
        await query.edit_message_text("Source upload रद्द कर दिया गया है।")
        return
    await query.answer("यह source action उपलब्ध नहीं है।", show_alert=True)


async def _document_state(database, document_id: int) -> str | None:
    async with database.session_factory() as session:
        repo = Repository(session)
        document = await repo.get_source_document(document_id)
        return document.state if document else None


async def sources_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat or not update.effective_user or not update.effective_message:
        return
    settings = get_settings()
    if (
        update.effective_chat.type not in {"group", "supergroup"}
        or not _is_configured_source_group(update.effective_chat.id, settings)
        or not _is_bot_admin(update.effective_user.id, settings)
    ):
        await update.effective_message.reply_text("यह command केवल configured source group के bot admins के लिए है।")
        return
    state = None
    database = context.application.bot_data["database"]
    async with database.session_factory() as session:
        repo = Repository(session)
        documents = await repo.source_document_summaries(state=state)
    if not documents:
        await update.effective_message.reply_text("अभी कोई source PDF indexed नहीं है।")
        return
    lines = ["📚 Source Bank:\n"]
    for item in documents:
        lines.append(f"{item.id}. {item.filename} — {item.state or 'pending'} / {item.subject or 'pending'} / {item.status} / {item.chunk_count} sections")
    await update.effective_message.reply_text("\n".join(lines[:21]))
