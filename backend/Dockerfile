# iRent 車況判讀 backend — 單一容器（FastAPI + 判定 pipeline + 整備中心前端）
# build context = repo 根目錄（docker-compose.yml 已設定）；前端在第一階段以 node 建置後複製進 image。
#
# 紅線：此服務目前為單 replica（背景判讀是行內 thread + 全域鎖，
#       免費層 Gemini RPM 8）。水平擴展前必須先接真正的佇列。

# ---- 階段 1：整備中心前端（frontend-admin → backend/app/static/ops） ----
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY frontend-admin/package.json frontend-admin/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend-admin/ ./
# vite.config 的 outDir 是 ../backend/app/static/ops；在容器內改用 --outDir 輸出到固定位置
RUN npx tsc -b && npx vite build --outDir /fe-dist --emptyOutDir

# ---- 階段 2：backend ----
FROM python:3.13-slim

# opencv-python-headless / pillow-heif 的系統依賴。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# 前端 build 產物（覆蓋 repo 內過渡期進版控的那份，確保與程式碼一致）
COPY --from=frontend /fe-dist ./app/static/ops

# 執行期可設定路徑：預設指向容器內 volume 掛載點（見 docker-compose.yml）
ENV IRENT_UPLOAD_DIR=/data/uploads \
    IRENT_LIVE_SIGNALS=/data/shadow_signals_live.jsonl \
    IRENT_SCRATCH_DIR=/data/scratch \
    IRENT_DB_PATH=/data/decisions.sqlite3 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# server.py 於 import 時執行 prompt 凍結檢查（prompts/ 缺檔即拒絕啟動）。
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
