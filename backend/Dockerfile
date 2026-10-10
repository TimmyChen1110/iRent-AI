# iRent 車況判讀 backend — 單一容器（FastAPI + 判定 pipeline + 整備中心前端）
# build context = repo 根目錄（docker-compose.yml 已設定）；前端在第一階段以 node 建置後複製進 image。
#
# 紅線：此服務目前為單 replica（背景判讀是行內 thread + 全域鎖，
#       免費層 Gemini RPM 8）。水平擴展前必須先接真正的佇列。

# ---- 階段 1：整備中心前端（fleet-ops-center → 靜態匯出 → backend/app/static/ops） ----
FROM node:22-alpine AS frontend
WORKDIR /fe
COPY fleet-ops-center/package.json fleet-ops-center/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY fleet-ops-center/ ./
# Next.js output: export（basePath /ops）；產物在 out/
RUN NEXT_OUTPUT=export NEXT_TELEMETRY_DISABLED=1 npm run build

# ---- 階段 2：backend ----
FROM python:3.13-slim

# 影像處理的系統依賴與中文標註字型（Linux 沒有 macOS 的 STHeiti）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
# 前端 build 產物（覆蓋 repo 內過渡期進版控的那份，確保與程式碼一致）
COPY --from=frontend /fe/out ./app/static/ops
RUN chmod +x /app/docker-entrypoint.sh

# python:3.13-slim 已含 /usr/share/zoneinfo；不在 source COPY 後重複 apt upgrade。
# 任務時間以現場時區的 ISO 字串儲存與顯示。
ENV TZ=Asia/Taipei

# 執行期可設定路徑：預設指向容器內 volume 掛載點（見 docker-compose.yml）
ENV IRENT_UPLOAD_DIR=/data/uploads \
    IRENT_LIVE_SIGNALS=/data/shadow_signals_live.jsonl \
    IRENT_SCRATCH_DIR=/data/scratch \
    IRENT_DB_PATH=/data/decisions.sqlite3 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

# server.py 於 import 時執行 prompt 凍結檢查（prompts/ 缺檔即拒絕啟動）。
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8000"]
