#!/bin/bash

# Ensure script crashes on error
set -e

# Display Python version
python --version

# Check environment variables
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

# Set default PORT if not provided
if [ -z "$PORT" ]; then
    export PORT=10000
    echo "PORT not set, defaulting to $PORT"
fi

# Start the bot
echo "Starting Telegram User Bot..."
exec python user_bot.py 