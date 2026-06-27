from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.models import AppSetting

KEY_VK_TOKEN = "vk_token"
KEY_VK_GROUP_ID = "vk_group_id"
KEY_ADMIN_TITLE = "admin_title"
KEY_WINNERS_TAB_ENABLED = "winners_tab_enabled"
KEY_RECEIPT_MAX_AGE_DAYS = "receipt_max_age_days"
KEY_AUTOCONFIRM_WITHOUT_DATE = "autoconfirm_without_date"

SECRET_KEYS = {KEY_VK_TOKEN}


async def get_setting(session: AsyncSession, key: str) -> str | None:
    """Прочитать настройку. Секретные ключи расшифровываются. None если пусто/нет."""
    row = await session.get(AppSetting, key)
    if row is None or not row.value:
        return None
    if key in SECRET_KEYS:
        try:
            return crypto.decrypt(row.value)
        except Exception:
            return None
    return row.value


async def set_setting(session: AsyncSession, key: str, value: str | None) -> None:
    """Записать настройку (flush; commit на вызывающем). Пусто/None → None (очистка).
    Секретные ключи шифруются."""
    if value is None or value.strip() == "":
        stored = None
    elif key in SECRET_KEYS:
        stored = crypto.encrypt(value.strip())
    else:
        stored = value.strip()
    row = await session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=stored))
    else:
        row.value = stored
    await session.flush()


async def is_set(session: AsyncSession, key: str) -> bool:
    row = await session.get(AppSetting, key)
    return bool(row and row.value)
