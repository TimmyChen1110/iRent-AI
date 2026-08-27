# iRent 智能車況管家 — 還車影像 AI 辨識系統

運用 AI 辨識使用者上傳的還車照片：比對借／還車影像偵測**新增車損**、判定**車內整潔程度**（髒汙/普通/乾淨），異常時觸發**後台預警與人工複核**，優化租還車體驗與營運效率。

> ⚠️ 本 repo 為私有：含 iRent 營運照片（車牌可見）與比賽提供之非公開資料，請勿轉公開或外流。

## 核心成果（全部來自真實營運照片實測）

| 指標 | 數值 |
|---|---|
| 車損偵測（141 組全量，對照**原始索賠標籤**） | 快篩 Recall 81% → Pro 級聯 **85.7%**、誤報 3.3% ← 系統對外指標 |
| 同一批結果對照**逐圖人工重標**（排除 3 組無法判定，n=138） | Recall 95.5%（21/22）、誤報 0% ← 說明「4 筆 FP 其實是真車損、原標籤有噪音」|
| 標籤噪音發現 | 4 筆「未索賠」樣本經放大複驗證實為真實新損（AI 抓到人工漏掉的車損） |
| 車內整潔（80 張 Blob 真實車內照） | 乾淨 21／普通 56／髒汙 3（3.75% 檢出，人工抽驗確認） |
| API 成本 | $0（Gemini 免費額度）；全量上線估 NT$1,200／日 |

關鍵工程發現：76% 照片帶未套用的 EXIF 旋轉（轉正 +10pp recall）；傳統 CV 差異偵測（ORB+SSIM）被實測推翻（手持照對齊成功率僅 45%），架構因此修正為 **VLM 模型級聯**（Flash 全量快篩 → 疑似案件升級 Pro 三票多數決）。

## 專案結構（對應比賽三環節）

```
├── 環節一_拍攝即時防呆/          # 拍照當下的品質檢核（規劃中，見資料夾 README）
├── 環節二_還車影像AI辨識/        # ★ 本次主要交付
│   ├── pipeline/                # 辨識與評測程式
│   │   ├── build_pairs.py       # 檔名解析 → 借/還配對（120 負 + 21 正）
│   │   ├── run_eval_gemini.py   # 車損判定評測（EXIF 轉正、few-shot、還2、斷點續跑）
│   │   ├── run_cascade.py       # Pro 級聯複核（低信心/無法比對升級、多數決）
│   │   ├── classify_interior.py # F2 車內整潔三級分類（Blob 下載 80 張實測）
│   │   ├── annotate_damage.py   # 損傷/髒污視覺標註（紅框+中文說明）
│   │   ├── batch_annotate.py    # Dashboard 標註框批次產生
│   │   ├── analyze_eval.py      # 混淆矩陣 / FP·FN 個案 / 門檻掃描
│   │   ├── cv_prefilter.py      # 傳統 CV 方案（實測後推翻，保留為證據）
│   │   ├── relabels.json        # 141 組逐圖重標結果（含二次複驗依據）
│   │   └── eval_results_*.json  # 各輪評測完整結果
│   └── Timmy_Project_Report/    # 簡報（presentation.pptx）、講稿、Demo script、Q&A
├── 環節三_營運通知與整備/        # 複核後台已具雛形，流程設計中（見資料夾 README）
└── iRent - 運用 AI 打造 iRent 智能車況管家…/   # 共用原始資料集
    ├── 沒有進行索賠/            # 負樣本：30 台車 × 4 方位借/還配對（240 張）
    ├── 進行索賠資料/            # 正樣本：28 台車爭議方位配對（53 張）
    ├── 車外車內照片上傳清單.xlsx  # 真實上傳 log：27,367 筆 / 4,820 單
    └── 取車/還車流程圖.png
```

## 快速開始

> 完整安裝步驟、驗證指令與常見問題見 **[環節二_還車影像AI辨識/SETUP.md](環節二_還車影像AI辨識/SETUP.md)**。
> Python 需 **3.12 或 3.13**（3.14 上 opencv / pillow-heif 無 wheel）。

```bash
cd 環節二_還車影像AI辨識
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "你的GEMINI_KEY" > pipeline/.gemini_key   # 金鑰已被 .gitignore 排除

# 驗證安裝（零 API 成本）
python -m pytest tests/ -q                      # 39 passed
python pipeline/quality_gate.py                 # 282 張檢核，攔下 26 張（9.2%）

cd pipeline
python3 build_pairs.py                          # 建立借/還配對
python3 run_eval_gemini.py --model gemini-3.7-flash --tag v3 --fewshot --include-alt
python3 run_cascade.py eval_results_gemini_37_flash_v3.json   # Pro 級聯複核
python3 classify_interior.py                    # F2 車內整潔分類
python3 judge_photos.py 借車照.jpg 還車照.jpg     # 現場實測：任意照片即時判定（--interior 車內照）
```

免費額度建議 `--rpm 8` 節流；中斷可直接重跑（斷點續跑）。

## 線上交付物（私有 Artifact）

- 系統架構設計文件 v1.5：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo（38 個真實案例、一鍵複核）：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
