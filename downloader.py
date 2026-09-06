import asyncio
import html
import logging
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yt_dlp

from config import (
    ARIA2C_CONNECTIONS,
    FFMPEG_PATH,
    MAX_FILE_SIZE_BYTES,
    PINTEREST_REGEX,
    TEMP_DIR_PREFIX,
    USER_AGENT,
    is_aria2c_available,
    is_ffmpeg_available,
)

logger = logging.getLogger(__name__)


class MediaType(str, Enum):
    VIDEO = "video"
    PHOTO = "photo"
    AUDIO = "audio"
    DOCUMENT = "document"


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
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            },
            "instagram": {
                "api": ["web", "graphql"],
            },
        },
    }

    if not is_ffmpeg_available():
        opts["prefer_ffmpeg"] = False

    # Use aria2c for progressive (non-DASH) downloads when available: it opens
    # multiple TCP connections per file (segmented download), which is much
    # faster than a single-connection HTTP GET for Instagram/TikTok/Pinterest/
    # Facebook links (these are typically one progressive mp4, so
    # concurrent_fragment_downloads above never kicks in for them).
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
    if suffix in [".mp4", ".mov", ".mkv", ".webm", ".avi", ".flv"]:
        return MediaType.VIDEO
    elif suffix in [".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]:
        return MediaType.PHOTO
    elif suffix in [".mp3", ".m4a", ".ogg", ".wav", ".aac", ".flac", ".opus"]:
        return MediaType.AUDIO
    return MediaType.DOCUMENT


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


def _download_direct_image(image_url: str, output_dir: Path, fallback_title: str = "Pinterest Image") -> MediaResult:
    """Fast streaming download for direct images."""
    req = urllib.request.Request(
        image_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.pinterest.com/",
        },
    )
    ext = ".jpg"
    if ".png" in image_url.lower():
        ext = ".png"
    elif ".webp" in image_url.lower():
        ext = ".webp"
    elif ".gif" in image_url.lower():
        ext = ".gif"

    output_file = output_dir / f"image_{abs(hash(image_url))}{ext}"
    with urllib.request.urlopen(req, timeout=15) as resp, open(output_file, "wb") as out_f:
        # Larger copy buffer reduces syscall overhead for bigger images.
        shutil.copyfileobj(resp, out_f, length=256 * 1024)

    if not output_file.exists() or output_file.stat().st_size == 0:
        raise DownloadError("Rasm yuklab olinmadi.")

    if output_file.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise FileSizeExceededError("Fayl hajmi 50MB dan oshib ketdi.")

    return MediaResult(
        media_type=MediaType.PHOTO,
        file_path=output_file,
        title=fallback_title,
    )


def _scrape_pinterest_image_fallback(url: str, output_dir: Path) -> MediaResult:
    """Fast fallback scraper for Pinterest static photo pins."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html_content = response.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.error(f"Error requesting Pinterest page: {e}")
        raise DownloadError("Pinterest sahifasini ochib bo'lmadi.")

    og_image_match = re.search(r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)
    og_title_match = re.search(r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']', html_content, re.IGNORECASE)

    title = "Pinterest Media"
    if og_title_match:
        title = html.unescape(og_title_match.group(1))

    img_url: Optional[str] = None
    if og_image_match:
        img_url = og_image_match.group(1)

    if not img_url:
        pinimg_matches = re.findall(r'https://i\.pinimg\.com/[^"\'\s<>]+', html_content)
        if pinimg_matches:
            img_url = pinimg_matches[0]

    if not img_url:
        raise DownloadError("Pinterest rasmi topilmadi.")

    high_res_url = re.sub(r'/(?:736x|564x|474x|236x)/', '/originals/', img_url)

    try:
        return _download_direct_image(high_res_url, output_dir, fallback_title=title)
    except Exception:
        return _download_direct_image(img_url, output_dir, fallback_title=title)


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
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web"],
            },
        },
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
            logger.warning(f"Fast extraction note for {url}: {e}")
            return {"title": "Media", "duration": 0}


def _sync_download_generic(url: str, output_dir: Path) -> MediaResult:
    """High-speed media download for general URLs."""
    is_pinterest = bool(PINTEREST_REGEX.search(url))
    opts = _get_base_ydl_opts(output_dir)

    if is_ffmpeg_available():
        # Prefer direct single stream first for zero-remux instant download
        opts.update({
            "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": "mp4",
                }
            ],
        })
    else:
        opts.update({
            "format": "best[ext=mp4]/best",
            "prefer_ffmpeg": False,
        })

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True) or {}
            file_path = _find_downloaded_file(output_dir)

            if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                raise FileSizeExceededError("Fayl hajmi 50MB dan oshib ketdi.")

            media_type = _detect_media_type_from_file(file_path)
            title = info.get("title") or "Media"

            return MediaResult(
                media_type=media_type,
                file_path=file_path,
                title=title,
                duration=info.get("duration"),
            )
    except FileSizeExceededError:
        raise
    except Exception as ydl_err:
        err_msg = str(ydl_err)
        if is_pinterest or "no video formats" in err_msg.lower():
            try:
                return _scrape_pinterest_image_fallback(url, output_dir)
            except Exception as scrape_err:
                logger.error(f"Pinterest fallback error: {scrape_err}")
                raise DownloadError("Pinterest media faylini yuklab bo'lmadi.")

        raise DownloadError("Media faylini yuklab olishda xatolik yuz berdi.")


def _sync_download_youtube_video(video_id: str, output_dir: Path) -> MediaResult:
    """High-speed YouTube video download."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = _get_base_ydl_opts(output_dir)

    if is_ffmpeg_available():
        opts.update({
            "format": (
                "best[height<=720][ext=mp4]/"
                "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                "bestvideo[height<=720]+bestaudio/"
                "best"
            ),
            "merge_output_format": "mp4",
            "postprocessors": [
                {
                    "key": "FFmpegVideoRemuxer",
                    "preferedformat": "mp4",
                }
            ],
        })
    else:
        opts.update({
            "format": "best[height<=720][ext=mp4]/best[ext=mp4]/best",
            "prefer_ffmpeg": False,
        })

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True) or {}
            file_path = _find_downloaded_file(output_dir, target_ext="mp4" if is_ffmpeg_available() else None)

            if file_path.stat().st_size > MAX_FILE_SIZE_BYTES:
                raise FileSizeExceededError("Video hajmi 50MB dan oshib ketdi.")

            return MediaResult(
                media_type=MediaType.VIDEO,
                file_path=file_path,
                title=info.get("title") or "YouTube Video",
                duration=info.get("duration"),
            )
        except FileSizeExceededError:
            raise
        except Exception as e:
            logger.error(f"Error downloading YouTube video {video_id}: {e}")
            raise DownloadError("YouTube videosini yuklashda xatolik yuz berdi.")


def _sync_download_and_boost_audio(video_id: str, output_dir: Path) -> MediaResult:
    """High-speed YouTube audio download and boost."""
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
            logger.error(f"Error extracting audio for {video_id}: {e}")
            raise DownloadError("Audioni yuklab olishda xatolik yuz berdi.")

    title = info.get("title") or "YouTube Audio"
    uploader = info.get("uploader") or info.get("channel") or "Unknown Artist"
    duration = info.get("duration")

    if not is_ffmpeg_available():
        if input_audio.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise FileSizeExceededError("Audio hajmi 50MB dan oshib ketdi.")
        return MediaResult(
            media_type=MediaType.AUDIO,
            file_path=input_audio,
            title=title,
            performer=uploader,
            duration=duration,
        )

    output_mp3 = output_dir / f"{video_id}_boosted.mp3"
    ffmpeg_cmd = [
        FFMPEG_PATH,
        "-y",
        "-i", str(input_audio),
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
            timeout=60,
        )
    except Exception:
        if input_audio.stat().st_size > MAX_FILE_SIZE_BYTES:
            raise FileSizeExceededError("Audio hajmi 50MB dan oshib ketdi.")
        return MediaResult(
            media_type=MediaType.AUDIO,
            file_path=input_audio,
            title=title,
            performer=uploader,
            duration=duration,
        )

    if not output_mp3.exists() or output_mp3.stat().st_size == 0:
        raise DownloadError("Audio fayli yaratilmadi.")

    if output_mp3.stat().st_size > MAX_FILE_SIZE_BYTES:
        raise FileSizeExceededError("Audio hajmi 50MB dan oshib ketdi.")

    return MediaResult(
        media_type=MediaType.AUDIO,
        file_path=output_mp3,
        title=title,
        performer=uploader,
        duration=duration,
    )


# ------------------- Non-Blocking Async Public API ------------------- #

async def extract_info_async(url: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_sync_extract_info, url)


async def download_generic_media_async(url: str, output_dir: Path) -> MediaResult:
    return await asyncio.to_thread(_sync_download_generic, url, output_dir)


async def download_youtube_video_async(video_id: str, output_dir: Path) -> MediaResult:
    return await asyncio.to_thread(_sync_download_youtube_video, video_id, output_dir)


async def download_youtube_audio_boosted_async(video_id: str, output_dir: Path) -> MediaResult:
    return await asyncio.to_thread(_sync_download_and_boost_audio, video_id, output_dir)


def create_temp_session_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix=TEMP_DIR_PREFIX))


def cleanup_session_dir(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except Exception as e:
        logger.warning(f"Failed to cleanup directory {path}: {e}")
