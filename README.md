# Production-Ready Telegram YouTube Downloader Bot

A high-concurrency, asynchronous Telegram bot built with **Python 3.11+**, **aiogram 3.x**, **yt-dlp**, and **FFmpeg**.

## ✨ Features
- **YouTube Video & Audio Extraction**: Dedicated support for YouTube videos and Shorts.
- **Interactive Format Selection**: Sends an inline keyboard with:
  - 📹 **Video**: Downloads best quality up to 720p (MP4 format under 50MB).
  - 🎵 **Zvuk (Boosted)**: Extracts audio and applies a `volume=2.0` boost filter via FFmpeg into a 192k MP3 with artist and title tags.
- **Non-Blocking Asynchronous Design**: Blocking disk, network, and FFmpeg tasks are offloaded to worker threads via `asyncio.to_thread` with a tunable thread pool.
- **Strict Resource Cleanup**: Isolated temporary session directories in `tempfile.gettempdir()` cleaned up in `finally` blocks to prevent disk leaks.
- **50 MB Telegram Bot API Limit Enforcement**: Gracefully detects and prevents uploads exceeding Telegram's file limit.

---

## 📁 Architecture

```
├── config.py          # Tokens, limits, regex patterns, executable paths
├── downloader.py      # Non-blocking yt-dlp & FFmpeg wrappers with session isolation
├── handlers.py        # Aiogram 3.x routers, YouTube filters, and callbacks
├── main.py            # Bot initialization, dispatcher, and polling entry point
└── requirements.txt   # Python dependencies
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

*(Ensure [FFmpeg](https://ffmpeg.org/) is installed and accessible in your system `PATH` for video remuxing and audio boosting).*

### 2. Configure Environment (Required)
```bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# On Windows PowerShell:
# $env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
```
> ⚠️ `BOT_TOKEN` must be set via environment variable or `.env` file.

### Optional Performance Tuning
```bash
export MAX_PARALLEL_DOWNLOADS=24   # concurrent downloads across all users
export ARIA2C_CONNECTIONS=16       # connections per file when aria2c is installed
```

### 3. Run the Bot
```bash
python main.py
```
