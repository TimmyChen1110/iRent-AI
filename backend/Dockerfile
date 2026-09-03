# iRent 車況判讀 backend — 單一容器（FastAPI + 判定 pipeline）
# build context = backend/    ；  docker compose build 會自動帶入
#
# 紅線：此服務目前為單 replica（背景判讀是行內 thread + 全域鎖，
#       免費層 Gemini RPM 8）。水平擴展前必須先接真正的佇列。
FROM python:3.13-slim

# opencv-python-headless / pillow-heif 的系統依賴。
# 兩者的 manylinux wheel 多半已內含所需 .so，但 libglib2.0-0 仍常被 cv2 動態連結。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 執行期可設定路徑：預設指向容器內 volume 掛載點（見 docker-compose.yml）
ENV IRENT_UPLOAD_DIR=/data/uploads \
    IRENT_LIVE_SIGNALS=/data/shadow_signals_live.jsonl \
    IRENT_SCRATCH_DIR=/data/scratch \
    IRENT_DB_PATH=/data/decisions.sqlite3 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# server.py 於 import 時執行 prompt 凍結檢查（prompts/ 缺檔即拒絕啟動）。
# 模組路徑 app.server：WORKDIR /app 下 app/ 為隱式命名空間套件。
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
