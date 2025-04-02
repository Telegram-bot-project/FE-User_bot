# User Bot

Bot Telegram dùng để tương tác với người dùng và tích hợp RAG model.

## Cấu trúc

Bot này cung cấp các chức năng sau:
- Trả lời câu hỏi bằng RAG model
- Hiển thị thông tin sự kiện
- Hiển thị các câu hỏi thường gặp (FAQ)
- Cung cấp menu truy cập nhanh

## Biến môi trường cần thiết

- `TELEGRAM_BOT_TOKEN`: Token của bot Telegram từ BotFather
- `API_MONGO_URL`: URL của MongoDB API
- `API_RAG_URL`: URL của RAG API

## Triển khai lên Render

### Bước 1: Đăng ký tài khoản Render

Truy cập [Render](https://render.com) và đăng ký tài khoản nếu chưa có.

### Bước 2: Tạo Web Service mới

1. Đăng nhập vào Render và nhấp vào "New +"
2. Chọn "Web Service"
3. Kết nối với kho GitHub của bạn hoặc tải lên trực tiếp

### Bước 3: Cấu hình Web Service

1. **Tên**: Đặt tên cho service (ví dụ: telegram-user-bot)
2. **Runtime**: Chọn Docker
3. **Root Directory**: Chỉ định đường dẫn tới thư mục `telegram/user_bot`
4. **Build Command**: Để trống (sử dụng Dockerfile)
5. **Start Command**: Để trống (sử dụng CMD trong Dockerfile)

### Bước 4: Thiết lập biến môi trường

Trong mục "Environment", thêm các biến sau:

- `TELEGRAM_BOT_TOKEN`: Token của bot Telegram từ BotFather
- `API_MONGO_URL`: URL của MongoDB API 
- `API_RAG_URL`: URL của RAG API

### Bước 5: Chọn plan và triển khai

1. Chọn plan phù hợp (có thể sử dụng Free plan cho testing)
2. Nhấp "Create Web Service"

## Lưu ý quan trọng

- Đảm bảo API_MONGO_URL và API_RAG_URL có thể truy cập từ internet
- Free plan của Render sẽ tạm ngừng hoạt động sau 15 phút không có traffic, làm chậm phản hồi đầu tiên
- Kiểm tra logs trên Render nếu bot không hoạt động
- Nếu gặp lỗi "health check failed", kiểm tra lại cấu hình để đảm bảo server HTTP lắng nghe trên cổng đúng 