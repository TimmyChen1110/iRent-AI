# 環節二：還車影像 AI 辨識（本次主要交付）

> 目標：運用 AI 辨識使用者上傳的還車圖片——(1) 新車損偵測與異常預警 (2) 車內整潔三級分類（髒汙/普通/乾淨）(3) 後台預警與通知機制。

## 成果摘要（全部來自真實營運照片實測）

| 項目 | 結果 |
|---|---|
| 車損偵測（141 組借/還配對） | 快篩 81% → Pro 級聯 Recall 85.7%；逐圖重標後可判定 138 組 **Recall 95.5%、誤報 0%** |
| 標籤噪音發現 | 4 筆「未索賠」樣本證實為真實車損——AI 抓到人工漏掉的求償機會 |
| 車內整潔（80 張真實車內照） | **70% 車內照欄位實為車外照**（photo_ok 誠實回報＋人工抽驗證實）；真車內 24 張：乾淨 20/普通 1/髒汙 3，Pro 複核翻轉救回快篩漏判 |
| 視覺標註 | 損傷/髒污以座標框圈出 + 中文說明（annotate_damage.py / Dashboard 疊加層） |
| 自動分流 KPI | 自動放行 83%・自動預警 15.6%・**需人工複核僅 1.4%**（analyze_autopass.py） |
| Image Quality Gate | 純 CV 攔模糊/過暗/過曝，282 張攔 9.2%——含人工也無法複驗的 RDZ-0187（quality_gate.py） |
| 部位定位 | 護照 59 筆損傷歸到 17 類固定部位（part_tagger.py）；**前後保險桿占 76%**（熱點分析第一手數據） |
| Cleanliness Score | AI 盤點問題（11 類×3 級）→ 程式端加權計分 0–100，可解釋可調（cleanliness_score.py） |
| Photo-chain | 跨訂單車況鏈（photo_chain.py）：掃 15 台多訂單車即抓到 **RDE-0180 跨單新損**（右後保險桿刮痕，3 票一致＋人工證實，未在索賠清單）——責任精準回溯到訂單 #47353795 |
| 成本 | 原型 $0（Gemini 免費額度）；全量上線估 NT$1,200／日 |

## 內容

- `pipeline/` — 全部程式與評測結果（用法見根目錄 README「快速開始」）
- `dashboard/` — 複核後台原始碼：`dashboard_shell.html`（UI 模板）+ `build_dashboard.py`（一鍵組裝）
- `artifacts/` — 線上文件備份（架構設計 HTML）
- `Timmy_Project_Report/` — 14 頁簡報 pptx、逐頁講稿、Demo script、Q&A

## 線上交付物

- 系統架構設計文件：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
