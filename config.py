import os
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
MEDIA_CAPTION: str = "⚡ Ovoz 2x kuchaytirildi — @VideoSavvedBot"

# Telegram Bot API standard upload limit (50 MB)
MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024

# Temporary session folder prefix
TEMP_DIR_PREFIX: str = "tg_audio_pipeline_"

# FFmpeg Executable check
FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "ffmpeg")

# How many audio boost processes can run in parallel
MAX_PARALLEL_DOWNLOADS: int = int(os.getenv("MAX_PARALLEL_DOWNLOADS", "24"))

_FFMPEG_AVAILABLE_CACHE: Optional[bool] = None


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
