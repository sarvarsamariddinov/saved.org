import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

import yt_dlp

from config import (
    ARIA2C_CONNECTIONS,
    FFMPEG_PATH,
    MAX_FILE_SIZE_BYTES,
    TEMP_DIR_PREFIX,
    USER_AGENT,
    is_aria2c_available,
    is_ffmpeg_available,
)

logger = logging.getLogger(__name__)


class MediaType(str, Enum):
    VIDEO = "video"
    AUDIO = "audio"


@dataclass
class MediaResult:
    media_type: MediaType
    file_path: Path
    title: str
    duration: Optional[int] = None
    performer: Optional[str] = None
    caption: Optional[str] = None


class DownloadError(Exception):
    """Custom exception raised when download or extraction fails."""
    pass


class FileSizeExceededError(DownloadError):
    """Custom exception raised when downloaded file exceeds 50MB."""
    pass


def _get_base_ydl_opts(output_dir: Path) -> Dict[str, Any]:
    """High-speed, optimized options for yt-dlp extractor."""
    opts: Dict[str, Any] = {
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "max_filesize": MAX_FILE_SIZE_BYTES,
        "http_headers": {
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
        },
        # High speed concurrency optimizations
        "check_formats": False,
        "concurrent_fragment_downloads": 24,
        "buffersize": 1024 * 1024,
        "http_chunk_size": 10485760,
        "socket_timeout": 15,
        "retries": 3,
        "fragment_retries": 3,
        "nocheckcertificate": True,
    }

    if not is_ffmpeg_available():
        opts["prefer_ffmpeg"] = False

    if is_aria2c_available():
        opts["external_downloader"] = "aria2c"
        opts["external_downloader_args"] = {
            "aria2c": [
                "-x", str(ARIA2C_CONNECTIONS),
                "-s", str(ARIA2C_CONNECTIONS),
                "-k", "1M",
                "--summary-interval=0",
                "--console-log-level=warn",
            ]
        }

    # Automatically load cookies.txt if present
    cookies_file = Path("cookies.txt")
    if cookies_file.exists():
        opts["cookiefile"] = str(cookies_file.resolve())

    return opts


def _detect_media_type_from_file(file_path: Path) -> MediaType:
    """Classifies media type based on file extension."""
    suffix = file_path.suffix.lower()
    if suffix in [".mp3", ".m4a", ".ogg", ".wav", ".aac", ".flac", ".opus"]:
        return MediaType.AUDIO
    return MediaType.VIDEO


def _find_downloaded_file(output_dir: Path, target_ext: Optional[str] = None) -> Path:
    """Finds the primary downloaded media file in the specified directory."""
    files = list(output_dir.iterdir())
    if not files:
        raise DownloadError("Fayl yuklab olinmadi.")

    if target_ext:
        for f in files:
            if f.is_file() and f.suffix.lower() == f".{target_ext.lower()}":
                return f

    valid_files = [
        f for f in files
        if f.is_file() and not f.name.endswith((".part", ".ytdl", ".temp", ".aria2"))
    ]
    if not valid_files:
        raise DownloadError("Fayl to'liq yuklab olinmadi.")

    return max(valid_files, key=lambda f: f.stat().st_size)


def _sync_extract_info(url: str) -> Dict[str, Any]:
    """Fast metadata extraction."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "http_headers": {"User-Agent": USER_AGENT},
        "socket_timeout": 10,
        "check_formats": False,
    }
    if not is_ffmpeg_available():
        opts["prefer_ffmpeg"] = False

    cookies_file = Path("cookies.txt")
    if cookies_file.exists():
        opts["cookiefile"] = str(cookies_file.resolve())

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            return ydl.sanitize_info(info) or {}
        except Exception as e:
            logger.exception(f"Fast extraction error for {url}: {e}")
            return {"title": "Media", "duration": 0}


def _sync_boost_audio_file(
    input_path: Path,
    output_dir: Path,
    title: str = "Audio",
    performer: str = "Unknown Artist",
    duration: Optional[int] = None,
) -> MediaResult:
    """Boosts audio volume using ffmpeg (volume=2.0, 192k mp3)."""
    if not is_ffmpeg_available():
        raise DownloadError("Audio ovozini balandlashtirish uchun FFmpeg mavjud emas.")

    if not input_path.exists() or input_path.stat().st_size == 0:
        raise DownloadError("Yaroqli audio fayl topilmadi.")

    if input_path.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise FileSizeExceededError("Audio hajmi 50MB dan oshib ketdi.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_mp3 = output_dir / f"{input_path.stem}_boosted.mp3"
    if output_mp3.resolve() == input_path.resolve():
        output_mp3 = output_dir / f"{input_path.stem}_boosted_out.mp3"

    ffmpeg_cmd = [
        FFMPEG_PATH,
        "-y",
        "-i", str(input_path),
        "-filter:a", "volume=2.0",
        "-vn",
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        str(output_mp3),
    ]

    try:
        subprocess.run(
            ffmpeg_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            timeout=120,
        )
    except subprocess.CalledProcessError as e:
        err_msg = e.stderr.decode(errors="ignore") if e.stderr else str(e)
        logger.exception(f"FFmpeg boosting error for {input_path}: {err_msg}")
        raise DownloadError("Audio faylini qayta ishlashda xatolik yuz berdi.")
    except Exception as e:
        logger.exception(f"Error boosting audio {input_path}: {e}")
        raise DownloadError("Audio faylini qayta ishlashda xatolik yuz berdi.")

    if not output_mp3.exists() or output_mp3.stat().st_size == 0:
        raise DownloadError("Audio fayli yaratilmadi.")

    if output_mp3.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise FileSizeExceededError("Audio hajmi 50MB dan oshib ketdi.")

    return MediaResult(
        media_type=MediaType.AUDIO,
        file_path=output_mp3,
        title=title,
        performer=performer,
        duration=int(duration) if duration is not None else None,
    )


def _sync_download_and_boost_audio(video_id: str, output_dir: Path) -> MediaResult:
    """High-speed YouTube audio download and boost reusing _sync_boost_audio_file."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    raw_audio_dir = output_dir / "raw"
    raw_audio_dir.mkdir(parents=True, exist_ok=True)

    opts = _get_base_ydl_opts(raw_audio_dir)
    opts.update({
        "format": "bestaudio/best",
    })

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True) or {}
            input_audio = _find_downloaded_file(raw_audio_dir)
        except Exception as e:
            logger.exception(f"Error extracting audio for {video_id}: {e}")
            raise DownloadError("Audioni yuklab olishda xatolik yuz berdi.")

    title = info.get("title") or "YouTube Audio"
    uploader = info.get("uploader") or info.get("channel") or "Unknown Artist"
    raw_dur = info.get("duration")
    duration = int(raw_dur) if raw_dur is not None else None

    # Directly reuse the proven boost function
    return _sync_boost_audio_file(
        input_path=input_audio,
        output_dir=output_dir,
        title=title,
        performer=uploader,
        duration=duration,
    )


# ------------------- Non-Blocking Async Public API ------------------- #

async def extract_info_async(url: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_sync_extract_info, url)


async def download_youtube_audio_boosted_async(video_id: str, output_dir: Path) -> MediaResult:
    return await asyncio.to_thread(_sync_download_and_boost_audio, video_id, output_dir)


async def boost_audio_file_async(
    input_path: Path,
    output_dir: Path,
    title: str = "Audio",
    performer: str = "Unknown Artist",
    duration: Optional[int] = None,
) -> MediaResult:
    return await asyncio.to_thread(
        _sync_boost_audio_file, input_path, output_dir, title, performer, duration
    )


def create_temp_session_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX))


def cleanup_session_dir(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to cleanup directory {path}: {e}")
