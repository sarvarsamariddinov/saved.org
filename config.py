import os
import re
import shutil
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Token
# SECURITY: token must come from the environment only. Never hardcode a real
# token in source code — if this file is ever shared/leaked, the token is
# compromised. Set BOT_TOKEN in your environment or a .env-style secret store.
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

# Bot Username & Caption Branding
BOT_USERNAME: str = "VideoSavvedBot"
MEDIA_CAPTION: str = "⚡ Скачивай видео легко — @VideoSavvedBot"

# Telegram Bot API standard upload limit (50 MB)
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

# URL Regular Expressions
YOUTUBE_REGEX: re.Pattern = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtube\.com/(?:watch\?v=|embed/|v/|shorts/|live/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)

# Optional non-YouTube URL detection
URL_REGEX: re.Pattern = re.compile(
    r"(https?://(?:www\.)?[-a-zA-Z0-9@:%._+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b[-a-zA-Z0-9()@:%_+.~#?&/=]*)",
    re.IGNORECASE,
)

# Temporary session folder prefix
TEMP_DIR_PREFIX: str = "tg_media_pipeline_"

# Standard User-Agent mimicking a modern browser
USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0.0.0 Safari/537.36"
)

# FFmpeg Executable check
FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")

# aria2c external downloader (optional) - gives multi-connection segmented
# downloads for progressive (non-fragmented) media formats.
ARIA2C_PATH: str = os.getenv("ARIA2C_PATH", "aria2c")

# Number of parallel connections aria2c opens per download.
ARIA2C_CONNECTIONS: int = int(os.getenv("ARIA2C_CONNECTIONS", "16"))

# How many downloads can run truly in parallel across all users at once.
# This backs the asyncio default executor used by asyncio.to_thread().
MAX_PARALLEL_DOWNLOADS: int = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "24"))

_FFMPEG_AVAILABLE_CACHE: Optional[bool] = None
_ARIA2C_AVAILABLE_CACHE: Optional[bool] = None


def _setup_ffmpeg_path() -> None:
    """Ensure ffmpeg is in PATH, utilizing imageio_ffmpeg if installed."""
    if shutil.which("ffmpeg") is None:
        try:
            import imageio_ffmpeg
            exe = imageio_ffmpeg.get_ffmpeg_exe()
            if exe and os.path.exists(exe):
                ffmpeg_dir = os.path.dirname(exe)
                target = os.path.join(ffmpeg_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
                if not os.path.exists(target):
                    shutil.copyfile(exe, target)
                if ffmpeg_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        except Exception:
            pass


_setup_ffmpeg_path()


def is_ffmpeg_available() -> bool:
    """Check if ffmpeg executable is installed and available in PATH.

    Result is cached after the first call: shutil.which() hits the
    filesystem/PATH every time, and this is checked on every single
    download, so caching removes that repeated I/O from the hot path.
    """
    global _FFMPEG_AVAILABLE_CACHE
    if _FFMPEG_AVAILABLE_CACHE is None:
        _FFMPEG_AVAILABLE_CACHE = shutil.which(FFMPEG_PATH) is not None
    return _FFMPEG_AVAILABLE_CACHE


def is_aria2c_available() -> bool:
    """Check if aria2c is installed and available in PATH (cached)."""
    global _ARIA2C_AVAILABLE_CACHE
    if _ARIA2C_AVAILABLE_CACHE is None:
        _ARIA2C_AVAILABLE_CACHE = shutil.which(ARIA2C_PATH) is not None
    return _ARIA2C_AVAILABLE_CACHE
