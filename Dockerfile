# --- Dockerfile tối giản & ổn định cho bot Telegram ---
FROM python:3.11-slim

# (không bắt buộc) set timezone cho log dễ đọc
ENV TZ=Asia/Ho_Chi_Minh \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Cài deps hệ thống tối thiểu (unzip, ca-certificates giúp httpx/requests)
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      tzdata \
    && rm -rf /var/lib/apt/lists/*

# Cài python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY . .

# Chạy bot (đúng tên file chính của bạn)
CMD ["python", "tele_fb_monitor1.py"]
