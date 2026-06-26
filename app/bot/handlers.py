"""Тонкая vkbottle-обвязка: получает события Long Poll, делегирует логику в dialog.py."""

import logging
import os

import aiohttp
from vkbottle import PhotoMessageUploader
from vkbottle.bot import Bot, Message

from app.bot import dialog
from app.core.config import settings
from app.core.db import async_session_maker
from app.core.placeholders import render
from app.core.services import public_table
from app.core.services.participants import upsert_participant
from app.ocr import parse as ocr_parse
from app.ocr import recognize as ocr_recognize

logger = logging.getLogger(__name__)


async def _download(url: str) -> bytes:
    """Скачивает содержимое вложения (фото/документ) по URL."""
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.get(url) as resp:
            resp.raise_for_status()
            return await resp.read()


def _ext_from_url(url: str, default: str = "jpg") -> str:
    """Извлекает расширение файла из URL (до query-параметров)."""
    path = url.split("?", 1)[0]
    _, _, tail = path.rpartition(".")
    if tail and len(tail) <= 5 and tail.isalnum():
        return tail
    return default


async def _extract_receipt_attachment(message: Message) -> tuple[str, str] | None:
    """Возвращает (url, ext) первого вложения-чека (фото или документ), либо None."""
    attachments = message.attachments or []
    for att in attachments:
        photo = getattr(att, "photo", None)
        if photo is not None and photo.sizes:
            biggest = max(photo.sizes, key=lambda s: s.width or 0)
            return biggest.url, _ext_from_url(biggest.url)
        doc = getattr(att, "doc", None)
        if doc is not None:
            ext = doc.ext or _ext_from_url(doc.url)
            return doc.url, ext
    return None


def _resolve_sheet_url(event) -> str:
    if event.google_sheet_url:
        from app.sheets.sync import reader_url

        try:
            return reader_url(event.google_sheet_url)
        except Exception:
            logger.exception(
                "reader_url failed for event %s, fallback to public table", event.id
            )
    return public_table.public_table_url(event.id)


async def _build_ctx(event, numbers=None) -> dict:
    """Контекст для рендеринга плейсхолдеров в текстах события."""
    ctx: dict = {
        "event_name": event.name,
        "price": event.price,
        "sheet_url": _resolve_sheet_url(event),
    }
    if numbers is not None:
        from app.core.placeholders import format_numbers

        ctx["numbers"] = format_numbers(numbers)
        ctx["count"] = len(numbers)
    return ctx


async def _get_vk_identity(message: Message) -> tuple[str | None, str | None]:
    """Пытается получить имя/ссылку пользователя ВК. Не критично при ошибке."""
    user_id = message.from_id
    vk_name = None
    vk_link = f"https://vk.com/id{user_id}"
    try:
        users = await message.ctx_api.users.get(user_ids=[user_id])
        if users:
            u = users[0]
            vk_name = f"{u.first_name} {u.last_name}"
    except Exception:
        logger.exception("Failed to fetch VK user info for user_id=%s", user_id)
    return vk_name, vk_link


def register_handlers(bot: Bot) -> None:
    """Регистрирует обработчики Long Poll событий на переданном экземпляре Bot."""

    @bot.on.message()
    async def on_message(message: Message) -> None:
        try:
            await _handle_message(bot, message)
        except Exception:
            logger.exception("Unhandled error while processing message from_id=%s", message.from_id)


async def _handle_message(bot: Bot, message: Message) -> None:
    user_id = message.from_id
    vk_name, vk_link = await _get_vk_identity(message)

    async with async_session_maker() as session:
        attachment_info = await _extract_receipt_attachment(message)

        if attachment_info is not None:
            await _handle_receipt(bot, message, session, user_id, vk_name, vk_link, attachment_info)
        else:
            await _handle_keyword(bot, message, session, user_id, vk_name, vk_link)

        await session.commit()


async def _handle_receipt(
    bot: Bot,
    message: Message,
    session,
    user_id: int,
    vk_name: str | None,
    vk_link: str | None,
    attachment_info: tuple[str, str],
) -> None:
    event = await dialog.resolve_event_for_receipt(session, user_id)
    if event is None:
        return  # нет активного диалога — бот молчит

    url, ext = attachment_info
    content = await _download(url)
    receipt_hash = dialog.compute_receipt_hash(content)

    os.makedirs(settings.receipts_dir, exist_ok=True)
    file_name = f"{event.id}_{user_id}_{receipt_hash[:12]}.{ext}"
    file_path = os.path.join(settings.receipts_dir, file_name)
    with open(file_path, "wb") as f:
        f.write(content)

    is_dup = await dialog.is_duplicate_receipt(session, event.id, receipt_hash)

    ocr_amount = None
    ocr_raw = None
    recipient_found = False
    if ocr_recognize.tesseract_available():
        try:
            ocr_raw = await ocr_recognize.recognize_text(file_path)
            parsed = ocr_parse.parse_receipt(ocr_raw, event.expected_recipient)
            ocr_amount = parsed["amount"]
            recipient_found = parsed["recipient_found"]
        except Exception:
            logger.exception("OCR failed for file_path=%s", file_path)

    purchase = await dialog.process_receipt(
        session,
        event=event,
        vk_user_id=user_id,
        vk_name=vk_name,
        vk_link=vk_link,
        message_text=message.text or "",
        receipt_file_path=file_path,
        receipt_hash=receipt_hash,
        ocr_amount=ocr_amount,
        ocr_raw_text=ocr_raw,
        recipient_found=recipient_found,
        is_duplicate=is_dup,
    )

    if event.send_receipt_received:
        ctx = await _build_ctx(event)
        await message.answer(render(event.msg_receipt_received, ctx))
    # Присвоение номеров и финальное уведомление — отдельный воркер (этап 2.7).
    _ = purchase


async def _handle_keyword(
    bot: Bot,
    message: Message,
    session,
    user_id: int,
    vk_name: str | None,
    vk_link: str | None,
) -> None:
    event = await dialog.find_matching_event(session, message.text or "")
    if event is None:
        return  # ни одно событие не подошло — бот молчит

    await upsert_participant(session, event.id, user_id, vk_name=vk_name, vk_link=vk_link)
    await dialog.set_dialog(session, user_id, event.id)

    text = render(event.msg_instruction, await _build_ctx(event)) if event.send_instruction else ""

    # QR прикрепляем «по возможности»: если у токена нет права «Фотографии»
    # (VK API Error 15) или upload падает по иной причине — инструкция всё равно
    # должна дойти до участника. Иначе бот молчит и кажется «нерабочим».
    attachment = None
    if event.send_qr and event.qr_image_path and os.path.exists(event.qr_image_path):
        try:
            uploader = PhotoMessageUploader(bot.api)
            attachment = await uploader.upload(file_source=event.qr_image_path)
        except Exception:
            logger.exception(
                "Не удалось загрузить QR (event_id=%s) — шлю инструкцию без картинки. "
                "Проверьте, что у VK-токена сообщества включено право «Фотографии».",
                event.id,
            )

    if text or attachment:
        await message.answer(text, attachment=attachment)
