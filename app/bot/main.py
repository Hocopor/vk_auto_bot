import asyncio
import logging

from vkbottle.bot import Bot

from app.core.config import settings
from app.bot.handlers import register_handlers
from app.bot.worker import worker_loop

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=settings.vk_token)
register_handlers(bot)


async def _amain() -> None:
    logger.info("Starting VK bot (Long Poll) + worker...")
    asyncio.create_task(worker_loop(bot))
    await bot.run_polling()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
