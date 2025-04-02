FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
# Ensure latest installation and force reinstall to avoid cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --force-reinstall -r requirements.txt

COPY user_bot.py .
COPY start.sh .
RUN chmod +x start.sh

# Create mock file to avoid errors when .env is not present
RUN touch .env

# Network port (for Render health check)
ENV PORT=10000
EXPOSE ${PORT}

# Use startup script
CMD ["./start.sh"] 