# Sử dụng Python 3.11
FROM python:3.11-slim

# Đặt thư mục làm việc
WORKDIR /app

# Copy file requirements và cài đặt dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code
COPY . .

# Lệnh chạy bot
CMD ["python", "tele_fb_monitor1.py"]
