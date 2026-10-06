# iRent 智能車況管家 — 還車影像 AI 辨識系統

運用 AI 辨識使用者上傳的還車照片：比對借／還車影像偵測**新增車損**、判定**車內整潔程度**（髒汙/普通/乾淨），異常時觸發**後台預警與人工複核**，優化租還車體驗與營運效率。

> ⚠️ 本 repo 為私有：含 iRent 營運照片（車牌可見）與比賽提供之非公開資料，請勿轉公開或外流。

## 核心成果（全部來自真實營運照片實測）

| 指標 | 數值 |
|---|---|
| 車損偵測（141 組全量，對照**原始索賠標籤**） | 快篩 Recall 81% → Pro 級聯 **85.7%**、誤報 3.3% ← 系統對外指標 |
| 同一批結果對照**逐圖人工重標**（排除 4 組無法判定，n=137） | Recall 100%（19/19）、誤報 0.85%（1/118）、精確度 95% ← 說明「帳面 4 筆 FP 中 2 筆其實是真車損、原標籤有噪音」|
| 標籤噪音發現 | 原記 4 筆「未索賠」實為真損，2026-08-30 用戶逐圖複核後確認 2 筆（AI 抓到人工漏登的車損）；另 1 筆為 AI 誤報、1 筆借車照覆蓋不足不可比 |
| 車內整潔（80 張 Blob 候選影像） | `photo_ok` 檢查（模型判斷）：24 張通過、56 張未通過（人工抽驗 3 張未通過案例，3 張皆為車外照）；級聯模型對通過檢查的 24 張分類結果：乾淨 20／普通 1／髒汙 3 |
| API 成本 | 尚未完成正式成本驗證，暫不作量化宣稱（正式計價與帳單核對列為後續工作） |

關鍵工程發現：76% 照片帶未套用的 EXIF 旋轉（轉正 +10pp recall）；傳統 CV 差異偵測（ORB+SSIM）被實測推翻（手持照對齊成功率僅 45%），架構因此修正為 **VLM 模型級聯**（Flash 全量快篩 → 疑似案件改用 Pro 模型複核）。

## 專案結構

程式已由比賽的「環節」目錄收斂為可部署的 `backend/`（重構規劃見
[後端服務化重構規劃.md](後端服務化重構規劃.md)）。環節一/二/三 目錄改為只存文件。

```
├── backend/                     # ★ 可部署後端（FastAPI + 判定 pipeline，單容器）
│   ├── app/                     # FastAPI 入口與 API
│   │   ├── server.py            # FastAPI app：掛載各 router、/ops 靜態匯出、/photos 供圖、Demo 重置；/ 導向 /ops
│   │   ├── ops_api.py / ops_db.py # 環節三 整備中心 API（/api/ops）與資料層
│   │   ├── inspections_api.py   # 非同步判讀 API（/v1/inspections）
│   │   ├── user_capture_api.py  # iOS App 照片上傳（/v1/mobile-inspections）＋ 租約狀態／重新開始
│   │   ├── rental_inspections.py # ★ Rental → Pickup/Return Inspection → Photo → AI Comparison → Incident
│   │   ├── rental_inspections_api.py # 管理者 Inspection History（/api/ops/inspections）
│   │   ├── demo_inspection_fixture.py # 比賽示範租約固定劇本（唯一允許寫死結果的地方）
│   │   ├── body_regions.py      # AI 位置文字 → Digital Twin 區域 id（與前端 HotspotLocation 同一組）
│   │   ├── review_api.py        # 複核介面 API（/v1/review）
│   │   ├── build_dashboard.py   # 資料集示範案件的資料組裝（ops_api 用；舊單頁 UI 已退役）
│   │   └── paths.py             # 執行期可設定路徑與金鑰檢查（env 覆寫）
│   ├── pipeline/                # 辨識與評測程式（判定核心）
│   │   ├── build_pairs.py       # 檔名解析 → 借/還配對（120 負 + 21 正）
│   │   ├── run_eval_gemini.py   # 車損判定評測（EXIF 轉正、few-shot、還2、斷點續跑）
│   │   ├── run_cascade.py       # Pro 級聯複核（低信心/無法比對改用 Pro 判讀）
│   │   ├── classify_interior.py # F2 車內整潔三級分類（Blob 下載 80 張實測）
│   │   ├── judge_photos.py      # 現場實測：任意照片即時判定（CLI + API 共用函式）
│   │   ├── cv_prefilter.py      # 傳統 CV 方案（實測後推翻，保留為證據）
│   │   ├── prompts/             # 凍結的 prompt 檔 + MANIFEST（啟動時 sha256 比對）
│   │   ├── relabels.json        # 141 組逐圖重標結果（含二次複驗依據）
│   │   └── eval_results_*.json  # 各輪評測完整結果
│   ├── tests/                   # Backend 與環節三回歸測試（零 Gemini API 成本）
│   ├── training/                # 自訓 CV 模型流程驗證（不接主流程）
│   ├── Dockerfile / requirements.txt / requirements-dev.txt
├── docker-compose.yml           # backend + (PR#2) postgres
├── .env.example                 # GEMINI_API_KEY 等
├── frontend-user/irent-app/     # ★ 正式使用者 App（SwiftUI：Find a Car 3D 地圖 → 取車／還車拍攝 + 裝置端 Core ML 防呆 → 離線重送）
├── E2E_INSPECTION_FLOW.md       # ★ iOS → Backend → AI 比對 → Incident → 指揮中心 的端對端說明（Mermaid）
├── fleet-ops-center/            # ★ 正式管理者介面 Fleet Command Center（Next.js + 3D Digital Twin；npm run build:ops → backend/app/static/ops → /ops，/ops/m 為站點手機版；Docker 多階段自動 build）
├── 環節一/二/三_*/              # 比賽文件（README / SETUP / 隊友須知 / 簡報）
└── iRent - 運用 AI 打造 iRent 智能車況管家…/   # 共用原始資料集
    ├── 沒有進行索賠/            # 負樣本：30 台車 × 4 方位借/還配對（240 張）
    ├── 進行索賠資料/            # 正樣本：28 台車爭議方位配對（53 張）
    ├── 車外車內照片上傳清單.xlsx  # 真實上傳 log：27,367 筆 / 4,820 單
    └── 取車/還車流程圖.png
```

## 端對端流程（iOS App → Backend → Admin）

一筆租約 `RNT-20261005-1842`（ABC-1234）從既有 iOS App 的導引拍攝、Core ML 防呆、上傳，到後端建立 Pickup Baseline、還車後背景 AI 比對、自動建立車損／清潔案件，再到指揮中心的 Digital Twin、證據、AI 建議與整備任務——完整說明與 Demo 步驟見 **[E2E_INSPECTION_FLOW.md](E2E_INSPECTION_FLOW.md)**（含哪些是真實 pipeline、哪些是 deterministic demo fixture）。

## 快速開始

> 完整安裝步驟、驗證指令與常見問題見 **[環節二_還車影像AI辨識/SETUP.md](環節二_還車影像AI辨識/SETUP.md)**。
> Python 需 **3.12 或 3.13**（3.14 上 opencv / pillow-heif 無 wheel）。

### 本機開發

```bash
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt              # runtime + 測試/訓練
export GEMINI_API_KEY=你的KEY                    # 或寫進 backend/.env（Docker 用 repo 根 .env）
# 選填：整備任務即時通知（人工 confirm 建立任務後 POST JSON 到此 URL；見 .env.example）
# export NOTIFICATION_WEBHOOK_URL=http://127.0.0.1:9999/hook   # 本機測試：python3 tools/webhook_receiver.py

# 驗證安裝（零 API 成本）
python -m pytest tests/ -q                       # Backend 全套回歸
python pipeline/quality_gate.py                  # 282 張檢核，攔下 26 張（9.2%）

python pipeline/build_pairs.py                   # 建立借/還配對
python pipeline/run_eval_gemini.py --model gemini-3.7-flash --tag v3 --fewshot --include-alt
python pipeline/run_cascade.py pipeline/eval_results_gemini_37_flash_v3.json
python pipeline/classify_interior.py             # F2 車內整潔分類
python pipeline/judge_photos.py 借.jpg 還.jpg     # 現場實測（--interior 車內照）

# 後端（管理者介面 http://localhost:8000/ops；iPhone 連 http://<Mac 區網 IP>:8000）
cd app && DEMO_MODE=true uvicorn server:app --host 0.0.0.0 --port 8000
```

## Demo Quick Start

這是本機／內網 Demo 啟動方式，不是 Production deployment guide。需要 Docker Compose；資料集照片不進 image，而是由 `docker-compose.yml` 唯讀掛載。

1. 建立環境檔並啟動：

   ```bash
   cp .env.example .env
   docker compose up --build -d
   ```

   若目前開發主機的 Docker CLI 因 buildx plugin 失敗，repository 不需修改，改用：

   ```bash
   DOCKER_BUILDKIT=0 docker compose build
   docker compose up -d
   ```

2. 確認服務健康：

   ```bash
   docker compose ps
   curl http://localhost:8000/api/health
   ```

   `backend` 應顯示 `healthy`，health API 應回 `status: ok`。若 `.env` 的 `IRENT_PORT` 有修改，網址也要改成相同 port。

3. 開啟管理者介面 <http://localhost:8000/ops>（根路徑 `/` 會自動導向這裡）。`DEMO_MODE=true` 且仍使用標準帳密時，登入頁會提供一鍵填入：

   - Admin：`admin / admin-demo`
   - Station Staff：`station / station-demo`

   這些弱帳密在 `DEMO_MODE=false` 時不會啟用或顯示。

4. 完整端對端示範見 [DEMO.md](DEMO.md)（Demo C：iOS App → 後端 AI 比對 → 指揮中心）。只想看管理者端：事件中心 → 固定示範案件 `RCR-7661-左後`（車損）或 `F2-RDE-0160-front`（車內髒汙）→ 查看證據 → 確認異常並建立任務 → 維修／清潔頁開始處理、上傳完工照、完工 → 車輛恢復上線。Demo 前或每輪結束後，在 /ops 右上角頭像按「重置 Demo 案例」；它只重置示範案件的裁決、任務、衍生事件與完工照，不影響 AI 固定結果及其他案件。

5. `GEMINI_API_KEY` 可留空。AI 重新判讀與通知文案生成會停用，但固定案例、Admin、Station、Task、SQLite、完工照與 baseline 流程仍可完整操作。`NOTIFICATION_WEBHOOK_URL` 也是選填；未設定會清楚顯示 Not configured，不會影響任務。LINE／SMS 尚未接入。

6. SQLite、session metadata 與 uploads 共用 `backend_data` named volume；普通 restart 或 `docker compose down` 不會遺失，只有 `docker compose down -v` 會刪除。管理者介面的瀏覽器 E2E 以 Playwright 針對 `/ops` 手動／腳本實測（舊版 frontend-admin 與其 e2e 已於 2026-10-06 移除）。

7. Demo 結束後停止容器（保留資料）：

   ```bash
   docker compose down
   ```

macOS 亦可用 `make up`、`make logs`、`make down`；`make up` 會啟動 Colima 並執行相同流程。

免費額度建議 `--rpm 8` 節流；中斷可直接重跑（斷點續跑）。

> ⚠️ 單容器、單 replica，且只有 Demo 帳密／session（無 MFA、分散式 rate limit、SSO；登入限流以來源 IP 計數，經反向代理時所有人共用同一個計數） → 僅限本機／內網，禁止對公網開放。

## 線上交付物（私有 Artifact）

- 系統架構設計文件 v2.0（2026-08-29 同步）：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo（38 個真實案例、一鍵複核）：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
