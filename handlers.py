import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    FSInputFile,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

from config import MAX_FILE_SIZE_BYTES, MEDIA_CAPTION
from downloader import (
    DownloadError,
    FileSizeExceededError,
    MediaResult,
    boost_audio_file_async,
    cleanup_session_dir,
    create_temp_session_dir,
)

logger = logging.getLogger(__name__)

router = Router(name="audio_router")

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac", ".opus", ".oga", ".wma"
}


def _is_audio_document(doc) -> bool:
    if not doc:
        return False
    if doc.mime_type and doc.mime_type.startswith("audio/"):
        return True
    if doc.file_name:
        suffix = Path(doc.file_name).suffix.lower()
        if suffix in SUPPORTED_AUDIO_EXTENSIONS:
            return True
    return False


@router.message(CommandStart())
async def handle_start_command(message: Message):
    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men audio va MP3 fayllar ovozini 2 barobar kuchaytirib (boost qilib) beruvchi tezyurar botman.\n\n"
        "🎵 <b>Menga istalgan audio yoki MP3 fayl yuboring!</b>"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    help_text = (
        "💡 <b>Qo'llanma:</b>\n\n"
        "1. Menga audio, musiqa yoki ovozli xabar (voice) yuboring.\n"
        "2. Men uning ovozini balandlashtirib, 192k MP3 formatida qaytaraman (🎶 belgisi ko'rinadi).\n"
        "3. 50 MB gacha bo'lgan fayllar qo'llab-quvvatlanadi."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


@router.message(F.audio | F.voice | (F.document.func(_is_audio_document)))
async def handle_audio_message(message: Message):
    status_msg = await message.answer("🎶")
    session_dir = create_temp_session_dir()
    try:
        file_obj = None
        orig_filename = "audio.mp3"
        title = "Audio"
        performer = "Unknown Artist"
        duration = None
        file_size = None

        if message.audio:
            file_obj = message.audio
            orig_filename = message.audio.file_name or "audio.mp3"
            title = message.audio.title or Path(orig_filename).stem or "Audio"
            performer = message.audio.performer or "Unknown Artist"
            duration = message.audio.duration
            file_size = message.audio.file_size
        elif message.voice:
            file_obj = message.voice
            orig_filename = "voice.ogg"
            title = "Ovozli xabar"
            performer = "Telegram Voice"
            duration = message.voice.duration
            file_size = message.voice.file_size
        elif message.document:
            file_obj = message.document
            orig_filename = message.document.file_name or "audio.mp3"
            title = Path(orig_filename).stem or "Audio"
            performer = "Unknown Artist"
            duration = None
            file_size = message.document.file_size

        if not file_obj:
            await status_msg.edit_text("❌ Yaroqli audio fayl topilmadi.")
            return

        if file_size and file_size > MAX_FILE_SIZE_BYTES:
            raise FileSizeExceededError("Fayl hajmi 50 MB dan katta.")

        if not message.bot:
            raise DownloadError("Bot obyekti mavjud emas.")

        ext = Path(orig_filename).suffix or ".mp3"
        raw_input_path = session_dir / f"input_raw{ext}"

        await message.bot.download(file_obj, destination=raw_input_path)

        if not raw_input_path.exists() or raw_input_path.stat().st_size == 0:
            raise DownloadError("Fayl yuklab olinmadi.")

        if raw_input_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise FileSizeExceededError("Fayl hajmi 50 MB dan katta.")

        result: MediaResult = await boost_audio_file_async(
            input_path=raw_input_path,
            output_dir=session_dir,
            title=title,
            performer=performer,
            duration=duration,
        )

        out_stem = Path(orig_filename).stem
        out_filename = f"{out_stem}_boosted.mp3"
        input_file = FSInputFile(path=result.file_path, filename=out_filename)

        async with ChatActionSender(
            bot=message.bot,
            chat_id=message.chat.id,
            action=ChatAction.UPLOAD_VOICE,
        ):
            await message.answer_audio(
                audio=input_file,
                title=result.title,
                performer=result.performer or "Unknown Artist",
                duration=result.duration,
                caption=MEDIA_CAPTION,
                parse_mode=ParseMode.HTML,
            )

        await status_msg.delete()
    except FileSizeExceededError:
        await status_msg.edit_text("❌ Fayl hajmi 50 MB dan katta.")
    except DownloadError as e:
        await status_msg.edit_text(f"❌ {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in audio boost handler: {e}")
        await status_msg.edit_text("❌ Audio faylini qayta ishlashda xatolik yuz berdi.")
    finally:
        cleanup_session_dir(session_dir)


@router.message()
async def handle_other_messages(message: Message):
    await message.answer(
        "🎵 <b>Ovozini kuchaytirish uchun menga audio yoki MP3 fayl yuboring!</b>",
        parse_mode=ParseMode.HTML,
    )
