# Project Map — iRent 智能車況管家

**一句話**：運用 AI 辨識使用者上傳的還車照片，自動偵測新車損與車內髒汙，異常即時預警，優化租還車體驗與營運效率。

## 技術棧
| 層 | 技術 |
|---|---|
| 辨識引擎 | Gemini 3.7 Flash（快篩，實測引擎）＋ Pro 級模型（複核，規劃中）；Structured Output 強制 JSON Schema |
| 前處理 | Python + Pillow/OpenCV（EXIF 方向轉正、模糊/曝光檢核） |
| 評測 Pipeline | Python（ThreadPool 併發、RPM 節流、斷點續跑 JSONL） |
| 複核後台 | 監理台（FastAPI server 版：SQLite 全隊共享；另有單檔 HTML 版） |
| 整備中心（環節三） | React + Vite + motion SPA（`frontend-admin/` → `/ops`）；`/api/ops` FastAPI router；SSE 即時、SQLite（Postgres 方言層預留） |
| 資料來源 | 既有營運鏈路：iRent App → Azure Blob (carpic/) |

## 專案結構
```
iRent/
├── iRent - 運用 AI 打造 iRent 智能車況管家/   # 原始資料
│   ├── 沒有進行索賠/        # 負樣本：30 台車 × 4 方位借/還配對（240 張）
│   ├── 進行索賠資料/        # 正樣本：28 台車爭議方位配對（53 張，含 8 張車況回報特寫）
│   ├── 車外車內照片上傳清單.xlsx   # 真實上傳 log：27,367 筆 / 4,820 單 / 3,121 車
│   └── 取車/還車流程圖.png
├── backend/                 # FastAPI：監理台 + /api/ops 整備中心 API（ops_api.py / ops_db.py）
├── frontend-admin/          # 環節三 整備中心（含 /ops/m 站點手機版）
└── pipeline/
    ├── build_pairs.py       # 檔名解析 → 借/還配對（120 負 + 21 正）
    ├── cv_prefilter.py      # 傳統 CV 差異偵測（實測後推翻，保留為證據）
    ├── run_eval_gemini.py   # VLM 判定評測主程式（EXIF 轉正、節流、續跑）
    ├── analyze_eval.py      # 混淆矩陣 / FP·FN 個案 / 門檻掃描
    └── eval_results_v2_exif.json  # 141 組實測結果
```

## 核心數字
- 評測集：141 組借/還配對（21 索賠正樣本 + 120 未索賠負樣本）
- 實測（統一口徑並列）：對照原始索賠標籤 Recall 85.7%、誤報率 3.3%（n=141）；對照人工逐圖重標 Recall 100%、誤報率 0.85%（n=137，排除 4 組不可判定）
- 成本：原型驗證於免費額度完成；正式 API 成本估算尚未納入目前模型版本，不作量化宣稱

## 線上產出
- 架構設計文件（v1.1 實測版）：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
- 整備中心（需本機 server）：http://localhost:8000/ops ；站點手機版 http://localhost:8000/ops/m ；上台步驟見 repo 根 DEMO.md
