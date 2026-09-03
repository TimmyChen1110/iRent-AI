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
│   ├── app/                     # 監理台 server 與 API（原 dashboard/）
│   │   ├── server.py            # FastAPI app：監理台頁面 + 複核/判讀 API + 現場實測
│   │   ├── inspections_api.py   # 非同步判讀 API（/v1/inspections）
│   │   ├── review_api.py        # 複核介面 API（/v1/review）
│   │   ├── build_dashboard.py   # 單檔版監理台組裝
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
│   ├── tests/                   # 判定骨幹回歸測試（262 項，零 API 成本）
│   ├── training/                # 自訓 CV 模型流程驗證（不接主流程）
│   ├── Dockerfile / requirements.txt / requirements-dev.txt
├── docker-compose.yml           # backend + (PR#2) postgres
├── .env.example                 # GEMINI_API_KEY 等
├── frontend-user/               # 使用者前端（待開工，見 IDEAS 提案②車況收據）
├── frontend-admin/              # 後台前端（暫由 backend server-render，日後拆 SPA）
├── 環節一/二/三_*/              # 比賽文件（README / SETUP / 隊友須知 / 簡報）
└── iRent - 運用 AI 打造 iRent 智能車況管家…/   # 共用原始資料集
    ├── 沒有進行索賠/            # 負樣本：30 台車 × 4 方位借/還配對（240 張）
    ├── 進行索賠資料/            # 正樣本：28 台車爭議方位配對（53 張）
    ├── 車外車內照片上傳清單.xlsx  # 真實上傳 log：27,367 筆 / 4,820 單
    └── 取車/還車流程圖.png
```

## 快速開始

> 完整安裝步驟、驗證指令與常見問題見 **[環節二_還車影像AI辨識/SETUP.md](環節二_還車影像AI辨識/SETUP.md)**。
> Python 需 **3.12 或 3.13**（3.14 上 opencv / pillow-heif 無 wheel）。

### 本機開發

```bash
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt              # runtime + 測試/訓練
export GEMINI_API_KEY=你的KEY                    # 或寫進 backend/.env（Docker 用 repo 根 .env）

# 驗證安裝（零 API 成本）
python -m pytest tests/ -q                       # 262 passed
python pipeline/quality_gate.py                  # 282 張檢核，攔下 26 張（9.2%）

python pipeline/build_pairs.py                   # 建立借/還配對
python pipeline/run_eval_gemini.py --model gemini-3.7-flash --tag v3 --fewshot --include-alt
python pipeline/run_cascade.py pipeline/eval_results_gemini_37_flash_v3.json
python pipeline/classify_interior.py             # F2 車內整潔分類
python pipeline/judge_photos.py 借.jpg 還.jpg     # 現場實測（--interior 車內照）

# 監理台
cd app && uvicorn server:app --host 0.0.0.0 --port 8000
```

### Docker

```bash
make up        # 確保 colima 在跑 → 建 .env → build → 背景起 → http://localhost:8000
make logs      # 看 backend log
make down      # 停（留 volume 資料）        make help   全部指令
```

macOS 需先有容器 runtime（`brew install colima docker docker-compose`）；`make up` 會自動 `colima start`。
手動等價：`cp .env.example .env && docker compose up --build -d`。
資料集照片不進 image，`docker-compose.yml` 已把資料夾唯讀掛進容器（見 `IRENT_DATASET_ROOT`）。

免費額度建議 `--rpm 8` 節流；中斷可直接重跑（斷點續跑）。

> ⚠️ 單容器、單 replica、無認證機制 → 僅限本機／內網，禁止對公網開放。

## 線上交付物（私有 Artifact）

- 系統架構設計文件 v2.0（2026-08-29 同步）：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo（38 個真實案例、一鍵複核）：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
