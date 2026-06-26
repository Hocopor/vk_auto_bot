import asyncio
import logging

from vkbottle import API
from vkbottle.bot import Bot

from app.bot.handlers import register_handlers
from app.bot.worker import worker_loop
from app.core.config import settings
from app.core.db import async_session_maker
from app.core.services import app_settings as app_settings_service

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Как часто супервизор перечитывает VK-токен из БД, чтобы подхватить смену
# настроек в админке без ручного перезапуска службы.
RELOAD_INTERVAL_SEC = 10


async def _load_vk_token() -> str | None:
    """VK-токен: сначала из БД (админка), затем из .env как fallback. None если нет."""
    try:
        async with async_session_maker() as session:
            token = await app_settings_service.get_setting(
                session, app_settings_service.KEY_VK_TOKEN
            )
    except Exception:
        logger.exception("Не удалось прочитать VK-токен из БД, пробую .env")
        token = None
    return token or settings.vk_token or None


async def _run_bot(token: str) -> None:
    """Polling + воркер для данного токена. Отменяется супервизором при смене токена."""
    bot = Bot(token=token)
    upload_api = API(token=token)
    register_handlers(bot, upload_api)
    logger.info("Starting VK bot (Long Poll) + worker...")
    worker_task = asyncio.create_task(worker_loop(bot))
    try:
        await bot.run_polling()
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass
        # Закрыть HTTP-сессию vkbottle, чтобы не копить соединения при пересоздании.
        try:
            await bot.api.http_client.close()
        except Exception:
            pass
        try:
            await upload_api.http_client.close()
        except Exception:
            pass


async def _stop_task(task: asyncio.Task) -> None:
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _amain() -> None:
    """Супервизор: следит за VK-токеном в БД и (пере)запускает polling при его смене.

    Благодаря этому ввод/смена токена в админке `/settings` подхватывается
    автоматически (в течение ~RELOAD_INTERVAL_SEC секунд), без `systemctl restart`.
    """
    current_token: str | None = None
    bot_task: asyncio.Task | None = None
    logger.info(
        "Bot supervisor started (авто-подхват VK-токена, интервал=%sс)",
        RELOAD_INTERVAL_SEC,
    )
    try:
        while True:
            token = await _load_vk_token()

            # Polling упал сам (невалидный токен / сетевой сбой) — сбросим состояние,
            # чтобы пересоздать его на этой же итерации.
            if bot_task is not None and bot_task.done():
                exc = bot_task.exception()
                if exc is not None:
                    logger.error("Polling завершился с ошибкой: %r — пересоздаю", exc)
                bot_task = None
                current_token = None

            # Токен изменился (в т.ч. появился впервые или был очищен) — перезапуск.
            if token != current_token:
                if bot_task is not None:
                    logger.info("VK-токен изменился — перезапуск polling")
                    await _stop_task(bot_task)
                    bot_task = None
                current_token = token
                if token:
                    bot_task = asyncio.create_task(_run_bot(token))
                else:
                    logger.warning(
                        "VK-токен не задан — бот ждёт ввода в админке /settings..."
                    )

            await asyncio.sleep(RELOAD_INTERVAL_SEC)
    finally:
        if bot_task is not None:
            await _stop_task(bot_task)


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
