import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import Participant

PHONE_RE = re.compile(r"(?:\+7|7|8)?[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")

_PUNCT_STRIP_RE = re.compile(r'^[\s,.;:!?"\'\-]+|[\s,.;:!?"\'\-]+$')
_WS_RE = re.compile(r"\s+")


def parse_phone(text: str) -> str | None:
    """Ищет телефон в тексте, возвращает нормализованный в формате +7XXXXXXXXXX."""
    if not text:
        return None
    m = PHONE_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) == 11 and digits[0] == "8":
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] != "7":
        return None
    return "+" + digits


def parse_name_and_phone(text: str) -> tuple[str | None, str | None]:
    """Разделяет текст на (имя, телефон)."""
    if not text:
        return None, None
    phone = parse_phone(text)
    name_part = text
    m = PHONE_RE.search(text)
    if m:
        name_part = text[: m.start()] + text[m.end():]
    name_part = _WS_RE.sub(" ", name_part).strip()
    name_part = _PUNCT_STRIP_RE.sub("", name_part).strip()
    name = name_part if name_part else None
    return name, phone


async def upsert_participant(
    session: AsyncSession,
    event_id: int,
    vk_user_id: int,
    vk_name: str | None = None,
    vk_link: str | None = None,
    provided_name: str | None = None,
    phone: str | None = None,
) -> Participant:
    """Создаёт или обновляет участника по (event_id, vk_user_id)."""
    result = await session.execute(
        select(Participant).where(
            Participant.event_id == event_id,
            Participant.vk_user_id == vk_user_id,
        )
    )
    participant = result.scalar_one_or_none()

    if participant is None:
        participant = Participant(
            event_id=event_id,
            vk_user_id=vk_user_id,
            vk_name=vk_name,
            vk_link=vk_link,
            provided_name=provided_name if provided_name else None,
            phone=phone if phone else None,
        )
        session.add(participant)
    else:
        if vk_name is not None:
            participant.vk_name = vk_name
        if vk_link is not None:
            participant.vk_link = vk_link
        if provided_name is not None and provided_name:
            participant.provided_name = provided_name
        if phone is not None and phone:
            participant.phone = phone

    await session.flush()
    return participant
