import asyncio
import logging
import socket
import sys
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramNetworkError

from config import (
    BOT_TOKEN,
    MAX_PARALLEL_DOWNLOADS,
    is_ffmpeg_available,
    is_js_runtime_available,
)
from handlers import router as media_router

# Force line buffering for immediate log output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def create_bot_session() -> AiohttpSession:
    """
    Creates an AiohttpSession configured with socket.AF_INET (IPv4).
    Fixes Windows WinError 121 semaphore timeouts when connecting to api.telegram.org.
    """
    session = AiohttpSession()
    session._connector_init["family"] = socket.AF_INET
    session._connector_init["ttl_dns_cache"] = 300
    # Bigger connection pool so many simultaneous uploads/replies to Telegram
    # don't queue up behind each other on a single connector.
    session._connector_init["limit"] = 100
    session._connector_init["limit_per_host"] = 0
    return session


def boost_thread_pool() -> None:
    """
    Every blocking call (yt-dlp extraction/download, ffmpeg, urllib) runs via
    asyncio.to_thread(), which uses the loop's *default* executor. Python's
    default executor caps out at min(32, cpu_count + 4) workers - on small
    VPS/containers (1-2 vCPU) that can be as low as 5-6 threads, so several
    users sending links at the same time end up queued behind each other
    even though the bottleneck is network I/O, not CPU. Raising this lets
    that many downloads actually run concurrently.
    """
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(max_workers=MAX_PARALLEL_DOWNLOADS, thread_name_prefix="media_dl")
    )


async def run_bot() -> None:
    """Initializes and runs the bot with automatic network reconnection."""
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN is not defined. Please set BOT_TOKEN environment variable.")
        sys.exit(1)

    if is_js_runtime_available():
        logger.info("JavaScript runtime found - YouTube extraction should work.")
    else:
        logger.critical(
            "Hech qanday JavaScript runtime (deno/node/bun/qjs) topilmadi! "
            "YouTube ISHLAMAYDI. Dockerfile orqali deno o'rnatilganini "
            "tekshiring yoki qo'lda o'rnating: "
            "curl -fsSL https://deno.land/install.sh | sh"
        )

    if not is_ffmpeg_available():
        logger.warning("FFmpeg topilmadi. Video remuxing va audio boost ishlamaydi.")

    boost_thread_pool()

    logger.info("Initializing Bot with IPv4 optimized network session...")
    bot = Bot(
        token=BOT_TOKEN,
        session=create_bot_session(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()

    # Include handler routers
    dp.include_router(media_router)

    # Reconnection loop for network resilience
    while True:
        try:
            logger.info("Connecting to Telegram Bot API...")
            await bot.delete_webhook(drop_pending_updates=True)
            logger.info("Bot started polling successfully.")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
            break
        except TelegramNetworkError as net_err:
            logger.warning(f"Network error connecting to Telegram API: {net_err}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Unexpected error in polling loop: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        finally:
            await bot.session.close()


async def main() -> None:
    await run_bot()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped by user.")
