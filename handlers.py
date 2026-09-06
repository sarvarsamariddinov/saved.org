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

from config import MEDIA_CAPTION, URL_REGEX, YOUTUBE_REGEX, is_ffmpeg_available
from downloader import (
    DownloadError,
    FileSizeExceededError,
    MediaResult,
    MediaType,
    cleanup_session_dir,
    create_temp_session_dir,
    download_generic_media_async,
    download_youtube_audio_boosted_async,
    download_youtube_video_async,
    extract_info_async,
)

logger = logging.getLogger(__name__)

router = Router(name="media_router")


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
        "Men har qanday ijtimoiy tarmoqdan (Instagram, TikTok, Pinterest, YouTube, Facebook) "
        "video, rasm va audio yuklab beruvchi tezyurar botman.\n\n"
        "🚀 <b>Menga shunchaki media havolasini yuboring!</b>"
    )
    await message.answer(welcome_text, parse_mode=ParseMode.HTML)


@router.message(Command("help"))
async def handle_help_command(message: Message):
    help_text = (
        "💡 <b>Qo'llanma:</b>\n\n"
        "1. <b>Instagram, TikTok, Pinterest, Facebook:</b> Havolani yuboring — bot to'g'ridan-to'g'ri yuklab beradi.\n"
        "2. <b>YouTube:</b> Havolani yuboring va <b>Video</b> yoki <b>Zvuk (Boosted)</b> tugmasini bosing.\n"
        "3. 50 MB gacha bo'lgan fayllar qo'llab-quvvatlanadi."
    )
    await message.answer(help_text, parse_mode=ParseMode.HTML)


@router.message(F.text.regexp(URL_REGEX))
async def handle_url_message(message: Message):
    text = message.text or ""
    url_match = URL_REGEX.search(text)
    if not url_match:
        return

    url = url_match.group(0)

    # 1. YouTube Interception
    yt_match = YOUTUBE_REGEX.search(url)
    if yt_match:
        video_id = yt_match.group(1)
        status_msg = await message.answer("⏳")
        try:
            info = await extract_info_async(f"https://www.youtube.com/watch?v={video_id}")
            title = _clean_title(info.get("title", "YouTube Media"))
            duration = info.get("duration", 0)
            mins, secs = divmod(duration, 60)
            duration_str = f"{mins}:{secs:02d}" if duration else "Noma'lum"

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
        except Exception:
            await status_msg.edit_text(
                "🎬 <b>YouTube Media</b>\n\nFormatni tanlang:",
                reply_markup=get_youtube_keyboard(video_id),
                parse_mode=ParseMode.HTML,
            )
        return

    # 2. General Media Handling (Instagram, TikTok, Pinterest, Facebook, etc.)
    status_msg = await message.answer("⏳")
    session_dir = create_temp_session_dir()

    try:
        async with ChatActionSender(bot=message.bot, chat_id=message.chat.id, action=ChatAction.UPLOAD_DOCUMENT):
            result: MediaResult = await download_generic_media_async(url, session_dir)
            input_file = FSInputFile(path=result.file_path, filename=result.file_path.name)
            caption = MEDIA_CAPTION

            if result.media_type == MediaType.VIDEO:
                await message.answer_video(
                    video=input_file,
                    caption=caption,
                    duration=result.duration,
                    parse_mode=ParseMode.HTML,
                )
            elif result.media_type == MediaType.PHOTO:
                await message.answer_photo(
                    photo=input_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            elif result.media_type == MediaType.AUDIO:
                await message.answer_audio(
                    audio=input_file,
                    caption=caption,
                    duration=result.duration,
                    title=result.title,
                    performer=result.performer,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await message.answer_document(
                    document=input_file,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )

        await status_msg.delete()
    except FileSizeExceededError:
        await status_msg.edit_text("❌ Fayl hajmi 50 MB dan katta.")
    except DownloadError as e:
        await status_msg.edit_text(f"❌ {e}")
    except Exception as e:
        logger.exception(f"Unexpected error handling URL {url}: {e}")
        await status_msg.edit_text("❌ Yuklab olishning imkoni bo'lmadi.")
    finally:
        cleanup_session_dir(session_dir)


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
