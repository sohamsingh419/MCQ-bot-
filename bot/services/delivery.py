"""Reliable, auditable dispatch for admin-targeted content and broadcasts."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Forbidden, RetryAfter, TelegramError

from bot.database.database import Database
from bot.database.repositories import Repository


@dataclass(frozen=True)
class DeliverySummary:
    campaign_id: int
    recipients: int
    sent: int
    failed: int


class DeliveryService:
    """Sends one manually composed item per eligible chat with durable per-chat receipts."""

    def __init__(self, bot: Bot, database: Database) -> None:
        self.bot = bot
        self.database = database

    async def audience_preview(self, audience: str, state: str | None = None) -> list[int]:
        async with self.database.session_factory() as session:
            return await Repository(session).audience_chat_ids(audience, state)

    async def audience_preview_details(self, audience: str, state: str | None = None) -> list[tuple[int, str, str]]:
        async with self.database.session_factory() as session:
            return await Repository(session).audience_chat_summaries(audience, state)

    async def send(
        self, *, created_by: int, mode: str, audience: str, state: str | None,
        content_type: str, content_text: str | None, payload: dict[str, Any],
    ) -> DeliverySummary:
        recipients = await self.audience_preview(audience, state)
        if not recipients:
            return DeliverySummary(campaign_id=0, recipients=0, sent=0, failed=0)

        async with self.database.session_factory() as session:
            repo = Repository(session)
            campaign = await repo.create_delivery_campaign(
                created_by=created_by, mode=mode, audience=audience, state=state,
                content_type=content_type, content_text=content_text, payload=payload,
                recipient_count=len(recipients),
            )
            receipts = await repo.create_delivery_receipts(campaign.id, recipients)
            await repo.commit()
            campaign_id = campaign.id
            receipt_ids = [(receipt.id, receipt.chat_id) for receipt in receipts]

        sent = 0
        failed = 0
        for receipt_id, chat_id in receipt_ids:
            try:
                message_id = await self._send_one(chat_id, content_type, content_text, payload)
                status, error = "sent", None
                sent += 1
            except (Forbidden, TelegramError) as exc:
                status, error, message_id = "failed", str(exc), None
                failed += 1
            async with self.database.session_factory() as session:
                repo = Repository(session)
                await repo.update_delivery_receipt(
                    receipt_id, status=status, telegram_message_id=message_id, error=error
                )
                await repo.commit()
            await asyncio.sleep(0.06)

        async with self.database.session_factory() as session:
            repo = Repository(session)
            await repo.complete_delivery_campaign(campaign_id, sent_count=sent, failed_count=failed)
            await repo.commit()
        return DeliverySummary(campaign_id=campaign_id, recipients=len(recipients), sent=sent, failed=failed)

    async def _send_one(self, chat_id: int, content_type: str, content_text: str | None, payload: dict[str, Any]) -> int:
        button = payload.get("inline_button")
        reply_markup = None
        if isinstance(button, dict) and button.get("text") and button.get("url"):
            reply_markup = InlineKeyboardMarkup([[
                InlineKeyboardButton(str(button["text"]), url=str(button["url"]))
            ]])
        try:
            if content_type == "text":
                kwargs = {"chat_id": chat_id, "text": content_text or ""}
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                message = await self.bot.send_message(**kwargs)
            elif content_type == "poll":
                # copyMessage preserves the original poll content without the
                # Telegram "Forwarded from" header or original sender identity.
                kwargs = {
                    "chat_id": chat_id,
                    "from_chat_id": int(payload["source_chat_id"]),
                    "message_id": int(payload["source_message_id"]),
                }
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                message = await self.bot.copy_message(**kwargs)
            elif content_type == "video":
                kwargs = {"chat_id": chat_id, "video": str(payload["file_id"]), "caption": content_text or None}
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                message = await self.bot.send_video(**kwargs)
            elif content_type == "photo":
                kwargs = {"chat_id": chat_id, "photo": str(payload["file_id"]), "caption": content_text or None}
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                message = await self.bot.send_photo(**kwargs)
            else:
                raise TelegramError("Unsupported delivery content type")
            return message.message_id
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            return await self._send_one(chat_id, content_type, content_text, payload)
