import html
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.chat_action import ChatActionSender

from config import MAX_FILE_SIZE_BYTES, MEDIA_CAPTION, URL_REGEX, YOUTUBE_REGEX
from downloader import (
    DownloadError,
    FileSizeExceededError,
    MediaResult,
    MediaType,
    boost_audio_file_async,
    cleanup_session_dir,
    create_temp_session_dir,
    download_youtube_audio_boosted_async,
    download_youtube_video_async,
    extract_info_async,
)

logger = logging.getLogger(__name__)

router = Router(name="media_router")

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


def get_youtube_keyboard(video_id: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(
                text="📹 Video",
                callback_data=f"yt_vid:{video_id}",
            ),
            InlineKeyboardButton(
                text="🎵 Zvuk (Boosted)",
                callback_data=f"yt_aud:{video_id}",
            ),
        ]
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def _clean_title(title: str, max_len: int = 60) -> str:
    escaped = html.escape(title or "Media")
    if len(escaped) > max_len:
        return escaped[:max_len] + "..."
    return escaped


@router.message(CommandStart())
async def handle_start_command(message: Message):
    welcome_text = (
        "👋 <b>Assalomu alaykum!</b>\n\n"
        "Men YouTube'dan video va audio yuklab beruvchi hamda audio fayllar ovozini kuchaytiruvchi tezyurar botman.\n\n"
        "🚀 <b>Imkoniyatlar:</b>\n"
        "• YouTube video yoki shorts havolasini yuboring (yuklashda ⏳ ko'rinadi)\n"
        "• Audio/MP3 fayl yuboring — ovozini balandlashtirib qaytaraman (ishlov berishda 🎶 ko'rinadi)"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    help_text = (
        "💡 <b>Qo'llanma:</b>\n\n"
        "1. <b>YouTube:</b> Havolani yuboring va <b>📹 Video</b> yoki <b>🎵 Zvuk (Boosted)</b> tugmasini bosing (⏳ ko'rinadi).\n"
        "2. <b>Audio kuchaytirish:</b> Audio/mp3 fayl yuboring — men ovozini balandlashtirib qaytaraman (🎶 belgisi ko'rinadi).\n"
        "3. 50 MB gacha bo'lgan fayllar qo'llab-quvvatlanadi."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(YOUTUBE_REGEX))
async def handle_youtube_message(message: Message):
    text = message.text or ""
    yt_match = YOUTUBE_REGEX.search(text)
    if not yt_match:
        return

    video_id = yt_match.group(1)
    status_msg = await message.answer("⏳")
    try:
        info = await extract_info_async(f"https://www.youtube.com/watch?v={video_id}")
        title = _clean_title(info.get("title") or "YouTube Media")
        raw_dur = info.get("duration")
        duration = int(raw_dur) if raw_dur is not None else 0
        mins, secs = divmod(duration, 60)
        duration_str = f"{mins}:{secs:02d}" if duration > 0 else "Noma'lum"

        prompt_text = (
            f"🎬 <b>{title}</b>\n"
            f"⏱ <code>{duration_str}</code>\n\n"
            f"Formatni tanlang:"
        )
        await status_msg.edit_text(
            prompt_text,
            reply_markup=get_youtube_keyboard(video_id),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(f"Error handling youtube message for {video_id}: {e}")
        await status_msg.edit_text(
            "🎬 <b>YouTube Media</b>\n\nFormatni tanlang:",
            reply_markup=get_youtube_keyboard(video_id),
            parse_mode=ParseMode.HTML,
        )


@router.message(F.text.regexp(URL_REGEX))
async def handle_non_youtube_url(message: Message):
    await message.answer("❌ Faqat YouTube havolalarini qabul qilaman.")


@router.callback_query(F.data.startswith("yt_vid:"))
async def handle_youtube_video_callback(callback: CallbackQuery):
    video_id = callback.data.split("yt_vid:")[1]
    message = callback.message

    await callback.answer("⏳")
    if isinstance(message, Message):
        await message.edit_text("⏳")

    session_dir = create_temp_session_dir()
    try:
        async with ChatActionSender(bot=callback.bot, chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VIDEO):
            result: MediaResult = await download_youtube_video_async(video_id, session_dir)
            input_file = FSInputFile(path=result.file_path, filename=f"{video_id}.mp4")

            await callback.message.answer_video(
                video=input_file,
                caption=MEDIA_CAPTION,
                duration=result.duration,
                parse_mode=ParseMode.HTML,
            )

        if isinstance(message, Message):
            await message.delete()
    except FileSizeExceededError:
        if isinstance(message, Message):
            await message.edit_text("❌ Video hajmi 50 MB dan katta.")
    except DownloadError as e:
        if isinstance(message, Message):
            await message.edit_text(f"❌ {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in YouTube video callback {video_id}: {e}")
        if isinstance(message, Message):
            await message.edit_text("❌ Yuklab bo'lmadi.")
    finally:
        cleanup_session_dir(session_dir)


@router.callback_query(F.data.startswith("yt_aud:"))
async def handle_youtube_audio_callback(callback: CallbackQuery):
    video_id = callback.data.split("yt_aud:")[1]
    message = callback.message

    await callback.answer("⏳")
    if isinstance(message, Message):
        await message.edit_text("⏳")

    session_dir = create_temp_session_dir()
    try:
        async with ChatActionSender(bot=callback.bot, chat_id=callback.message.chat.id, action=ChatAction.UPLOAD_VOICE):
            result: MediaResult = await download_youtube_audio_boosted_async(video_id, session_dir)
            input_file = FSInputFile(path=result.file_path, filename=f"{video_id}.mp3")

            await callback.message.answer_audio(
                audio=input_file,
                title=result.title,
                performer=result.performer or "Unknown Artist",
                duration=result.duration,
                caption=MEDIA_CAPTION,
                parse_mode=ParseMode.HTML,
            )

        if isinstance(message, Message):
            await message.delete()
    except FileSizeExceededError:
        if isinstance(message, Message):
            await message.edit_text("❌ Audio hajmi 50 MB dan katta.")
    except DownloadError as e:
        if isinstance(message, Message):
            await message.edit_text(f"❌ {e}")
    except Exception as e:
        logger.exception(f"Unexpected error in YouTube audio callback {video_id}: {e}")
        if isinstance(message, Message):
            await message.edit_text("❌ Yuklab bo'lmadi.")
    finally:
        cleanup_session_dir(session_dir)


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
