# 環境安裝與驗證

> 📁 **程式已搬到 repo 根的 `backend/`**（重構規劃見 `../後端服務化重構規劃.md`）。
> `pipeline/` → `backend/pipeline/`、`dashboard/` → `backend/app/`、
> `tests/` → `backend/tests/`。本文件的指令已更新為新路徑。

## 1. 建立虛擬環境

**Python 版本：請用 3.12 或 3.13。**
3.14 上 `opencv-python` / `pillow-heif` 尚無 wheel，安裝會失敗。

```bash
cd backend

python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # runtime + 測試/訓練/簡報
# 只要跑服務不跑測試：pip install -r requirements.txt
```

若有 [uv](https://github.com/astral-sh/uv)（快很多）：

```bash
uv venv --python 3.13 .venv
uv pip install -r requirements-dev.txt --python .venv/bin/python
```

## 2. 放入 API Key

Gemini API key（AI Studio 免費額度即可）擇一：

```bash
export GEMINI_API_KEY=your_key_here      # 方式 A：環境變數
echo "your_key_here" > pipeline/.gemini_key   # 方式 B：檔案（已在 .gitignore）
```

Docker 只需在 `.env` 設 `GEMINI_API_KEY`（`docker compose` 自動注入）。
server 端的金鑰檢查（`app/paths.py:gemini_key_available()`）環境變數與
`pipeline/.gemini_key` 檔擇一即可。

**沒有 key 也能跑**：`build_pairs.py`、`quality_gate.py`、`cv_prefilter.py`、
`analyze_autopass.py`、`analyze_eval.py`、`build_passport.py`、`app/build_dashboard.py`
與全部測試都是零 API 成本。只有實際判定（`judge_photos.py`、`run_eval_gemini.py`、
`classify_interior.py`、監理台的「AI 重判」與「現場實測」）需要 key。

## 3. 驗證安裝（零 API 成本，約 1 分鐘）

```bash
source .venv/bin/activate

# ① 測試套件——判定骨幹的回歸保護
python -m pytest tests/ -q
# 預期：262 passed

# ② 資料集配對
python pipeline/build_pairs.py
# 預期：negative_pairs 120 / positive_pairs 21（合計 141 組）

# ③ Quality Gate 全量
python pipeline/quality_gate.py
# 預期：282 張檢核，攔下 26 張（9.2%）

# ④ 自動分流 KPI
python pipeline/analyze_autopass.py
# 預期：自動放行 83.0%、自動預警 15.6%、人工複核 1.4%

# ⑤ 組裝監理台單檔版
python app/build_dashboard.py
# 預期：assembled ~5.0 MB → irent-review-dashboard.html / syntax all OK
#（語法檢查需要 node；沒裝 node 只會跳過檢查，HTML 仍會產出）
```

## 4. 啟動監理台

```bash
# 本機（venv）
source .venv/bin/activate
cd app
uvicorn server:app --host 0.0.0.0 --port 8000

# 或 Docker（在 repo 根）
cp .env.example .env && docker compose up --build
```

開 http://localhost:8000 。隊友連 `http://<你的區網IP>:8000`，
或用頁面內建的 QR 讓手機掃碼直開（`GET /api/qr` 會自動偵測區網 IP）。

> ⚠️ 資料含真實車牌照片，**僅限 localhost / 隊內區網，勿部署公網**。server 無認證機制。

**看 API 文件（Swagger UI）**：預設關閉。本機開發時加 `IRENT_ENABLE_DOCS=1`：
>
> ```bash
> IRENT_ENABLE_DOCS=1 uvicorn server:app --port 8000   # 本機
> # Docker：在 .env 取消註解 IRENT_ENABLE_DOCS=1 再 up
> ```
>
> 然後開 http://localhost:8000/docs （或 `/redoc`、`/openapi.json`）。共用／對外部署不要設此變數。

**保底方案**：`app/irent-review-dashboard.html` 是自包含單檔，
雙擊即開、零依賴、離線可用。單檔版沒有「現場實測」與「AI 重判」（需要 server 呼叫 Gemini），
其餘分頁功能完全相同。

Docker 執行期路徑由環境變數覆寫（見 `app/paths.py` 檔頭）：
`IRENT_UPLOAD_DIR`、`IRENT_LIVE_SIGNALS`、`IRENT_SCRATCH_DIR`、`IRENT_DB_PATH`——
`docker-compose.yml` 預設全部指向 `backend_data` volume。

## 5. 現場實測（需要 key）

```bash
source .venv/bin/activate

# 車損比對
python pipeline/judge_photos.py 借車照.jpg 還車照.jpg

# 車內整潔
python pipeline/judge_photos.py --interior 車內照.jpg

# 品質不合格仍強制判定
python pipeline/judge_photos.py 借.jpg 還.jpg --skip-gate
```

判定 JSON 走 stdout、進度走 stderr，方便 `> result.json` 導出。
標註圖存到 `pipeline/annotated/live_<檔名>_annotated.jpg`。
支援 iPhone HEIC（透過 `pillow-heif`）。

## 常見問題

| 症狀 | 原因與處理 |
|---|---|
| `ModuleNotFoundError: cv2` | 沒有 `source .venv/bin/activate`，或用系統 python 跑 |
| pip 安裝 opencv 失敗 | Python 版本是 3.14，改用 3.13 |
| `找不到 API key` | 設 `GEMINI_API_KEY` 或建立 `pipeline/.gemini_key` |
| 判定時 429 / 配額用盡 | 免費層 RPM 低，降 `--rpm`（預設 8）；腳本已內建退避重試與斷點續跑 |
| `複核模型 404` | Pro 模型該 key 不可用，程式會自動 fallback 回 Flash，不影響流程 |
| `syntax all OK` 沒出現 | 沒裝 node，僅跳過 JS 語法檢查，HTML 仍正常產出 |
