# Dùng Python 3.11
FROM python:3.11-slim

# Cài các gói phụ thuộc cơ bản
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Tạo thư mục làm việc
WORKDIR /app

# Copy requirements và cài đặt
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ code vào container
COPY . .

# Chạy bot
CMD ["python", "tele_fb_monitor1.py"]
