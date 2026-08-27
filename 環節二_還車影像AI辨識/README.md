# 環節二：還車影像 AI 辨識（本次主要交付）

> 目標：運用 AI 辨識使用者上傳的還車圖片——(1) 新車損偵測與異常預警 (2) 車內整潔三級分類（髒汙/普通/乾淨）(3) 後台預警與通知機制。

## 成果摘要（全部來自真實營運照片實測）

| 項目 | 結果 |
|---|---|
| 車損偵測（141 組借/還配對） | 對照原始索賠標籤：快篩 81% → Pro 級聯 **Recall 85.7% / 誤報 3.3%**（系統對外指標）；對照逐圖人工重標（n=138，排除 3 組無法判定）：Recall 95.5% / 誤報 0%——差距來自 4 筆「未索賠」樣本實為真車損 |
| 標籤噪音發現 | 4 筆「未索賠」樣本證實為真實車損——AI 抓到人工漏掉的求償機會 |
| 車內整潔（80 張真實車內照） | **70% 車內照欄位實為車外照**（photo_ok 誠實回報＋人工抽驗證實）；真車內 24 張：乾淨 20/普通 1/髒汙 3，Pro 複核翻轉救回快篩漏判 |
| 視覺標註 | 損傷/髒污以座標框圈出 + 中文說明（annotate_damage.py / Dashboard 疊加層） |
| 自動分流 KPI | 自動放行 83%・自動預警 15.6%・**需人工複核僅 1.4%**（analyze_autopass.py） |
| Image Quality Gate | 純 CV 攔模糊/過暗/過曝，282 張攔 9.2%——含人工也無法複驗的 RDZ-0187（quality_gate.py） |
| 部位定位 | 護照 59 筆損傷歸到 17 類固定部位（part_tagger.py）；**前後保險桿占 76%**（熱點分析第一手數據） |
| Cleanliness Score | AI 盤點問題（11 類×3 級）→ 程式端加權計分 0–100，可解釋可調（cleanliness_score.py） |
| Photo-chain | 跨訂單車況鏈（photo_chain.py）：掃 15 台多訂單車即抓到 **RDE-0180 跨單新損**（右後保險桿刮痕，3 票一致＋人工證實，未在索賠清單）——責任精準回溯到訂單 #47353795 |
| 現場實測入口 | **任意照片即時判定，不綁資料集**：CLI `judge_photos.py 借照 還照`（或 `--interior 車內照`）＋ 監理台「現場實測」分頁拖拉上傳——跑完整鏈路 Quality Gate → Flash 快篩 → 臨界升級 Pro 多數決 → 視覺標註，單案約 3–60 秒 |
| 成本 | 原型 $0（Gemini 免費額度）；全量上線估 NT$1,200／日 |

## 內容

- `SETUP.md` — **環境安裝、驗證指令與常見問題（第一次接手請先看這份）**
- `requirements.txt` — 執行環境依賴（Python 3.12/3.13）
- `tests/` — 判定骨幹回歸測試（`python -m pytest tests/ -q`，39 項，零 API 成本）
- `pipeline/` — 全部程式與評測結果（用法見 SETUP.md）
  - `results_config.py` — 判定結果檔的單一事實來源；Dashboard／標註／護照／KPI 一律讀同一份
- `dashboard/` — 複核後台原始碼：`dashboard_shell.html`（UI 模板）+ `build_dashboard.py`（一鍵組裝單檔版）+ `server.py`（server 版）
  - **單檔版**：直接雙擊 `irent-review-dashboard.html`，零依賴離線可用（demo 保底）
  - **Server 版**：`uvicorn server:app --host 0.0.0.0 --port 8000` → http://localhost:8000
    ——複核決策存 SQLite 全隊共享（5 秒自動同步）、照片由 server 供圖、「AI 重判」按鈕現場呼叫 Gemini、
    「現場實測」分頁：拖拉任意借/還照（或車內照）→ `POST /api/judge` 即時跑完整鏈路並回標註圖
    （上傳照片只落暫存目錄，判定後即刪除，不進 repo），判定結果可一鍵**存入案件佇列**
    （縮圖存 SQLite 全隊共享）→ 出現在「案件複核」分頁走人工複核——現場判定到複核閉環；
    品質檢核秒回分段顯示；內建區網 QR，評審手機掃碼即開、現場拍現場判。
    依賴見 `requirements.txt`（`pip install -r requirements.txt`）；資料含車牌照片，僅限 localhost／隊內區網
- `pipeline/export_training_labels.py` — **訓練標籤匯出**（見下節）
- `artifacts/` — 線上文件備份（架構設計 HTML）
- `Timmy_Project_Report/` — 14 頁簡報 pptx、逐頁講稿、Demo script、Q&A

## 訓練標籤累積機制（為日後自訓模型鋪路）

VLM API 判定準確、上線快，但長期而言自訓模型才是成本與延遲的解方。
問題在於自訓模型需要大量人工標註資料——而**監理台的複核作業本身就在產生這批資料**。

每一次人工裁決（確認車損／駁回誤報）都會 append 一筆 `decision_events`，存下：

| 欄位 | 內容 |
|---|---|
| `label` | 人工真值（confirm=1／reject=0／retake=NULL 不表態） |
| `ai_found` / `agreed` | AI 當時的判定，以及是否與人工一致 |
| `photos` | 照片絕對路徑（訓練時據此讀圖） |
| `boxes` | AI 標註框 box_2d |
| `assessment` | AI 完整判定含理由 |
| `note` | 稽核員備註（難例說明） |

**稽核員本來就要看這些照片，所以這批標籤的邊際成本是零。**
資料表刻意 append-only：改判、復原的歷程本身就是難例訊號，覆蓋掉就永遠救不回來。

```bash
# 查看累積現況（監理台統計列也會即時顯示）
curl localhost:8000/api/labels/stats

# 匯出訓練資料集
python3 pipeline/export_training_labels.py                  # JSONL
python3 pipeline/export_training_labels.py --format coco     # COCO 偵測格式
python3 pipeline/export_training_labels.py --disagreed-only  # 只要 AI 判錯的（難例挖掘）
```

以本資料集流量估算（4,820 單／日 × 4 方位 ≈ 19,280 組／日），
車損率 0.5% 時約 **52 天**即可累積 5,000 個正樣本，達偵測模型訓練門檻。

> ⚠️ 匯出的 `box_2d` 由 VLM 產生、人工僅確認「有無車損」而非框的精確度。
> 正式訓練偵測模型前建議先人工修框，或當作弱監督（weak supervision）使用。
> 「有無車損」二分類則可直接使用。

## 自訓 CV 模型（流程驗證）

`training/` 打通了「監理台標籤 → 訓練 → 評估 → 推論」整條路，並誠實量測現況：

| 指標 | 自訓 ResNet18 | 現行 VLM 級聯 |
|---|---|---|
| ROC-AUC（5-fold 車輛分組交叉驗證） | **0.594**（隨機 = 0.50） | — |
| Recall / FPR | 45.5% / 22.4% | **95.5% / 0%** |

**結論：現階段 VLM 完勝，自訓模型不應接入主流程。**
瓶頸是資料量（僅 22 個正樣本）而非程式——ablation 顯示凍結 backbone 的
linear probe（0.611）反而略優於全微調（0.594），是典型過擬合。

等監理台累積到數千筆標籤後，同一支腳本可直接重跑。詳見 [training/README.md](training/README.md)。



- 系統架構設計文件：https://claude.ai/code/artifact/ab616929-dda5-47a6-9324-8cb6d022c6d2
- 複核後台 Demo：https://claude.ai/code/artifact/ea7e3f69-18d6-4e5d-bbc2-2d6dd4025058
