FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies including FFmpeg, aria2 (multi-connection
# downloader used by yt-dlp for faster progressive-file downloads) and
# ca-certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    aria2 \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Run the bot
CMD ["python", "main.py"]
