# Telegram Audio & MP3 Volume Booster Bot

A high-concurrency, asynchronous Telegram bot built with **Python 3.11+**, **aiogram 3.x**, and **FFmpeg**.

## ✨ Features
- **Audio & MP3 Volume Boost**: Boosts the volume of any audio, music, voice message, or audio file sent by the user (`volume=2.0`, 192k MP3).
- **Supports All Common Formats**: MP3, M4A, WAV, OGG, FLAC, AAC, OPUS, OGA, WMA, and Telegram Voice messages.
- **Non-Blocking Asynchronous Design**: FFmpeg processing is offloaded to worker threads via `asyncio.to_thread` with a tunable thread pool.
- **Strict Resource Cleanup**: Isolated temporary session directories in `tempfile.gettempdir()` cleaned up in `finally` blocks to prevent disk leaks.
- **50 MB Telegram Bot API Limit Enforcement**: Gracefully detects and prevents uploads exceeding Telegram's file limit.

---

## 📁 Architecture

```
├── config.py          # Tokens, limits, executable paths
├── downloader.py      # Non-blocking FFmpeg audio booster wrapper
├── handlers.py        # Aiogram 3.x router and audio handlers
├── main.py            # Bot initialization, dispatcher, and polling entry point
└── requirements.txt   # Python dependencies
```

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

*(Ensure [FFmpeg](https://ffmpeg.org/) is installed and accessible in your system `PATH`).*

### 2. Configure Environment (Required)
```bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
# On Windows PowerShell:
# $env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
```

### 3. Run the Bot
```bash
python main.py
```
