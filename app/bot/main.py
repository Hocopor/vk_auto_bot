import asyncio
import logging

from vkbottle.bot import Bot

from app.bot.handlers import register_handlers
from app.bot.worker import worker_loop
from app.core.config import settings
from app.core.db import async_session_maker
from app.core.services import app_settings as app_settings_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _load_vk_token() -> str:
    """VK-токен: сначала из БД (админка), затем из .env как fallback."""
    try:
        async with async_session_maker() as session:
            token = await app_settings_service.get_setting(
                session, app_settings_service.KEY_VK_TOKEN
            )
    except Exception:
        logger.exception("Не удалось прочитать VK-токен из БД, пробую .env")
        token = None
    return token or settings.vk_token


async def _amain() -> None:
    token = await _load_vk_token()
    if not token:
        logger.error("VK-токен не задан ни в админке (БД), ни в .env — бот не запущен.")
        return
    bot = Bot(token=token)
    register_handlers(bot)
    logger.info("Starting VK bot (Long Poll) + worker...")
    asyncio.create_task(worker_loop(bot))
    await bot.run_polling()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
