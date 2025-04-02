FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
# Đảm bảo cài đặt mới nhất và force reinstall để tránh cache
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --force-reinstall -r requirements.txt

COPY user_bot.py .
COPY start.sh .
RUN chmod +x start.sh

# Tạo tệp giả lập để tránh lỗi khi không có .env
RUN touch .env

# Cổng mạng (để Render có thể kiểm tra health check)
ENV PORT=10000
EXPOSE ${PORT}

# Sử dụng script khởi động
CMD ["./start.sh"] 