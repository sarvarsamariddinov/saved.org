# Production-Ready Telegram Media Downloader Bot

A high-concurrency, asynchronous Telegram bot built with **Python 3.11+**, **aiogram 3.x**, **yt-dlp**, and **FFmpeg**.

## ✨ Features
- **Multi-Platform Support**: YouTube, Instagram (Reels/Posts), TikTok, Pinterest, Facebook, and all platforms supported by `yt-dlp`.
- **Non-Blocking Asynchronous Design**: Blocking disk, network, and FFmpeg tasks are offloaded to asynchronous worker threads using `asyncio.to_thread`.
- **YouTube Interactive Flow**: Sends an inline keyboard with:
  - 📹 **Video**: Downloads 720p/best MP4 under 50MB.
  - 🎵 **Zvuk (Audio Boosted)**: Extracts audio and applies a `volume=2.0` boost filter via FFmpeg into a 192k MP3 file with artist/title tags.
- **Strict Resource Cleanup**: Isolated temporary session directories in `tempfile.gettempdir()` cleaned up in `finally` blocks to prevent disk leaks.
- **50 MB Telegram Bot API Limit Enforcement**: Gracefully detects and prevents uploads exceeding Telegram's file limit.

---

## 📁 Architecture

```
├── config.py          # Tokens, limits, regex patterns, headers
├── downloader.py      # Non-blocking yt-dlp & FFmpeg wrappers with session isolation
├── handlers.py        # Aiogram 3.x routers, message filters, and callbacks
├── main.py            # Bot initialization, dispatcher, and polling entry point
└── requirements.txt   # Python dependencies
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

*(Ensure [FFmpeg](https://ffmpeg.org/) is installed and accessible in your system `PATH` for audio boosting).*

### 2. Configure Environment (Required)
```bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# On Windows PowerShell:
# $env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
```
> ⚠️ `BOT_TOKEN` no longer has a hardcoded fallback. The bot will refuse to
> start without it (see `main.py`). If a real token was ever committed to
> source control or shared as a file, revoke it via @BotFather (`/revoke`)
> and generate a new one — a token in source code is a leaked secret the
> moment the file leaves your machine.

### Optional performance tuning env vars
```bash
export MAX_PARALLEL_DOWNLOADS=24   # concurrent downloads across all users
export ARIA2C_CONNECTIONS=16       # connections per file when aria2c is installed
```
Install `aria2` (already added to `Dockerfile`/`Aptfile`) to enable
multi-connection segmented downloads for Instagram/TikTok/Pinterest/Facebook
links — this is the single biggest speed win for non-YouTube sources, since
those are usually one progressive file rather than fragmented DASH streams.

### 3. Run the Bot
```bash
python main.py
```
