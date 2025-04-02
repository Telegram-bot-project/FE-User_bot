#!/bin/bash

# Đảm bảo script crash khi có lỗi
set -e

# Hiển thị phiên bản Python
python --version

# Kiểm tra biến môi trường
if [ -z "$TELEGRAM_BOT_TOKEN" ]; then
    echo "Error: TELEGRAM_BOT_TOKEN is not set"
    exit 1
fi

if [ -z "$API_MONGO_URL" ]; then
    echo "Error: API_MONGO_URL is not set"
    exit 1
fi

if [ -z "$API_RAG_URL" ]; then
    echo "Error: API_RAG_URL is not set"
    exit 1
fi

# Đặt PORT mặc định nếu không có
if [ -z "$PORT" ]; then
    export PORT=10000
    echo "PORT not set, defaulting to $PORT"
fi

# Khởi động bot
echo "Starting Telegram User Bot..."
exec python user_bot.py 