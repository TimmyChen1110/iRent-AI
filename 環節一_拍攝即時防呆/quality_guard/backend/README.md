# iRent Photo Quality Guard — 任務一 Prototype

拍照即時防呆：使用者拍完一張車輛照片後，1 秒內回傳合格/不合格 + 具體重拍原因。
完整背景與設計決策見上層目錄 `irent_photo_quality_guard_plan.md` 與
`/Users/huxiangrui/.claude/plans/irent-distributed-pnueli.md`。

## 快速開始

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 啟動 API
.venv/bin/uvicorn app.main:app --reload --port 8000

# 另開一個終端機跑測試
.venv/bin/python -m pytest tests/ -v
```

前端 demo（純靜態檔案，任何方式 serve 都可以，例如）：

```bash
cd frontend
python3 -m http.server 5500
# 瀏覽器開 http://localhost:5500，記得後端要先跑在 8000
```

## 目前準確率（對 285 張真實照片實測，見 `validation/reports/validation_run_20260804_183414.json`）

| 指標 | 數值 |
|---|---|
| 車牌偵測率（找到疑似車牌區域） | 81.1%（左前 85.7% / 右前 83.1% / 左後 78.3% / 右後 76.5%） |
| 整體 pass 率 | 73.3% |
| 車牌文字精確辨識率 | 0.0%（見下方限制說明） |
| 模糊檢查：真實合格照片誤擋率 / 合成模糊照片攔截率 | 0.0% / 100% |
| 亮度（太暗）：誤擋率 / 攔截率 | 5.0% / 100% |
| 亮度（過曝）：誤擋率 / 攔截率 | 0.0% / 80% |
| 單張處理耗時 | 中位數 273ms，p90 862ms，最大 1788ms |

開發過程中實測發現並修正了兩個會嚴重拖低準確率的 bug（過程見 git 歷史/對話紀錄）：
1. `checks/plate.py` 評分公式原本讓 tesseract 對 1~2 個字元的雜訊小區塊給出的偏高信心值主導排序，導致真正車牌形狀的候選框常常輸給雜訊——加了最小尺寸過濾、OCR 信心值依文字長度打折、拉高幾何形狀權重後，車牌偵測率從 53.3% 提升到 81.1%。
2. `checks/framing.py` 原本有一個「候選框是否貼到畫面邊界」的太近判斷，實測對 285 張真實照片會誤判其中 71 張（24.9%）——因為 3/4 角落構圖下車牌本來就常偏向畫面一側，加上候選框本身的 padding 會被裁到邊界，這個訊號太不可靠，已經拿掉，只保留車牌面積比例這個有校準過的訊號。

## 已知限制（誠實揭露，demo 時要主動說明）

- **OCR 文字辨識準確率極低（近 0%）**：偵測到「哪裡有車牌」的定位準確率已校準到約 8 成，但用 tesseract 讀出的車牌文字幾乎不可信，只能當作輔助顯示資訊，不能拿來做車牌比對。目前的 pass/fail 判斷只依賴「有沒有偵測到疑似車牌區域」，不依賴文字讀對。
- **室內視角（前車內/後車內）完全沒有本地驗證資料**：`raw_data` 的 293 張真實照片全部是外部 4 角落視角，室內視角只做模糊/亮度檢查，車牌相關檢查一律略過，實際效果未經驗證。
- **左右前後角落細分判斷（Tier B）與車外/車內判斷（Tier A）都只是 advisory**：不會擋關。Tier A 經驗證發現對已知全是「車外」的真實照片會誤判 28.8%，遠不足以拿來擋關，所以只放在 API 回傳的 `debug` 欄位供參考。
- **單張處理耗時中位數約 0.27 秒，但 p90 可達 0.86 秒**，個別大圖甚至接近 1.8 秒，尚未完全達到 plan.md §11 訂的 <1 秒目標，仍有優化空間（例如降低 4x 放大倍率或用更小的 ROI）。

## 驗證方法

```bash
.venv/bin/python -m validation.run_validation
```

會對 `raw_data/沒有進行索賠` + `raw_data/進行索賠資料` 裡 285 張有效標註的
真實照片跑一次完整管線（排除「車況回報」等無關檔案），並對其中 40 張抽樣
做模糊/調暗/調亮/中心裁切放大的合成劣化注入，輸出：

- `validation/reports/validation_run_<timestamp>.csv` — 每張照片的詳細結果
- `validation/reports/validation_run_<timestamp>.json` — 彙總指標

門檻值（`app/config.py`）就是用這份報表的實測分布校準出來的，不是憑空設定。
如果之後改動 `app/checks/` 底下任何演算法，建議重跑一次這個驗證，用真實資料
確認準確率有沒有退步。

## 選用：擴充驗證集

```bash
.venv/bin/python -m scripts.scrape_azure_blobs --per-category 20
```

⚠️ 這支腳本要手動執行，見腳本內文件字串的完整說明（含資料曝露疑慮）。
預設只抓一小批（每類別 20 張），要擴充到 50~100 張要自己加大 `--per-category`。

## 目錄結構

```
app/
  main.py            FastAPI app，POST /api/photo-quality/check
  schemas.py          API 的 Pydantic 請求/回應模型
  config.py            品質檢查門檻值（已用真實資料校準）
  view_taxonomy.py    左前/右前/左後/右後/前車內/後車內 六分類
  checks/
    blur.py            模糊檢查
    brightness.py      亮度檢查
    plate.py           車牌偵測 + OCR（改寫自車牌 OCR 測試/licence_plate_test.py）
    framing.py         遠近/太近太遠判斷
    view.py            車外/車內、左右前後判斷（advisory only）
    quality_rules.py   整合以上所有檢查
validation/
  parse_filename.py    從 raw_data 檔名解析真值
  run_validation.py    跑真實照片 + 合成劣化，輸出準確率報表
scripts/
  scrape_azure_blobs.py  選用的小規模資料擴充腳本
tests/                  pytest 單元測試
```
