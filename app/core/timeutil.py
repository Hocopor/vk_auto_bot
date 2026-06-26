"""Утилиты для работы с таймзоной отображения (Europe/Moscow по умолчанию).

В БД даты хранятся в UTC (DateTime(timezone=True)). Админка показывает и
принимает время в локальной таймзоне заказчика (settings.display_timezone),
чтобы «Начало = сейчас» по МСК не означало «бот молчит 3 часа» из-за
наивного сравнения с UTC.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

try:
    LOCAL_TZ = ZoneInfo(settings.display_timezone)
except Exception:
    LOCAL_TZ = ZoneInfo("Europe/Moscow")


def parse_local_datetime(value: str | None) -> datetime | None:
    """Парсит значение из <input type="datetime-local"> как локальное время и
    возвращает aware datetime в UTC. Пустая строка/None -> None."""
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    dt = dt.replace(tzinfo=LOCAL_TZ)
    return dt.astimezone(timezone.utc)


def to_local(dt: datetime | None) -> datetime | None:
    """Конвертирует aware (или наивный, считая его UTC) datetime в локальную TZ."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def format_local_input(dt: datetime | None) -> str:
    """Форматирует datetime для value атрибута <input type="datetime-local">."""
    local = to_local(dt)
    if local is None:
        return ""
    return local.strftime("%Y-%m-%dT%H:%M")
