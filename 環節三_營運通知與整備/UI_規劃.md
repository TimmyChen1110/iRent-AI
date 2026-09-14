# 環節三 管理者介面規劃（v2，僅規劃，尚未實作）

> 範圍：**營運／客服管理者使用的介面**（整備中心）。站點人員手機版與用戶端先不做。
> 協作邊界：Docker 由同事維護、PostgreSQL 由同事之後建立；環節三需要的 API **由本環節自己寫**，
> 以獨立 router 掛進既有 FastAPI，不改動監理台既有端點與 Demo 流程。
> 原則延續 DEMO.md：畫面只呈現真實發生的事，未接入的管道以「未接入」明示。

## 0. 現況盤點（可直接沿用）

| 已有 | 位置 | 說明 |
|---|---|---|
| 任務 API | `server.py` `GET/PATCH /api/tasks`、`POST /api/tasks/{id}/notify` | 狀態機 pending → in_progress → completed / cancelled，含 events |
| 資料表 | `tasks`、`task_events` | priority P1/P2/P3、assignee、notification_status |
| 通知管道 | `NOTIFICATION_WEBHOOK_URL` HTTP POST | 唯一管道；失敗可重發、冪等 |
| 三對象文案 | `pipeline/notify.py` | 只生成不發送，尚無端點 |
| 案件資料 | `/api/decisions`、`_case_snapshot()`、`/photos/*` | 借還照、AI 標註框、判定理由 |
| 健檢 / 重置 | `/api/demo/health`、`/api/demo/reset` | Demo 列 |
| 容器 | `backend/Dockerfile`（COPY 整個 backend/）、compose 單 replica、SQLite 在 `/data` volume | PR #2 換 Postgres，`DATABASE_URL` 注入 |
| 前端目錄 | `frontend-admin/` | 空佔位 |

## 1. 架構與協作邊界

```
frontend-admin/                 ← 本環節：Vite + React + TS，build 輸出到 backend/app/static/ops/
backend/app/ops_api.py          ← 本環節：APIRouter(prefix="/api/ops")，server.py 只加一行 include_router
backend/app/ops_db.py           ← 本環節：環節三自己的資料表建立 + 存取函式（薄薄一層，換 Postgres 只改這裡）
backend/app/server.py           ← 只加：include_router + StaticFiles 掛 /ops
backend/Dockerfile / compose    ← 同事的；只需請他加「build 前端」一段（或我們把 build 產物進版控，見 §7）
```

- **DB 相容策略**：新表 DDL 只用 SQLite / Postgres 都吃的型別（TEXT、INTEGER、時間存 ISO 字串）；SQL 走 `ops_db.py` 的函式，佔位符集中在一處，同事切 `DATABASE_URL` 時只換這個檔。
- **不碰既有表結構**：`tasks`、`task_events` 照用；新增欄位一律改為新表（例如 `task_meta`）避免與監理台衝突。
- **開發流程**：`make up` 起同事的容器（8000），Vite dev server 用 proxy 把 `/api`、`/photos` 轉到 8000；不需要本機 venv 也能開發前端。
- **時間**：所有 API 回傳 `server_time`，前端 SLA 倒數以此校正。

## 2. 設計系統

### 2.1 色彩（品牌：藍為主、黃為點綴）

| Token | 值 | 用途 |
|---|---|---|
| `--brand` | #3764CA | 主要按鈕、選中、連結、焦點環 |
| `--brand-deep` | #002153 | 側欄底、標題、KPI 數字 |
| `--accent` | #EFCB37 | **僅**未讀圓點、「新」標記、SLA 即將逾時；占比 <10% |
| `--bg` | #F7F9FC | 頁面底 |
| `--surface` | #FFFFFF | 卡片、側板 |
| `--ink` / `--ink-2` | #1A2138 / #5B6478 | 正文 / 次要 |
| `--line` | #E3E8F1 | 分隔線 |

語意色獨立：`--p1` #D93B3B、`--p2` #E58A1F、`--p3` #6B7A90、`--ok` #1F9D55。狀態一律「色 + 圖示 + 文字」。

### 2.2 排版與間距

- 字體 `-apple-system, "PingFang TC", "Noto Sans TC"`；車牌、時間、數字用 `ui-monospace` + `tabular-nums`。
- 字級 11 / 13 / 15 / 17 / 22 / 28；4pt 網格；卡片圓角 14、按鈕 10、chip 999；陰影極淡，層次靠底色與 1px 線。

### 2.3 動效（Apple design 原則）

| 原則 | 落地 |
|---|---|
| 即時回應 | 狀態變更樂觀更新：按「開始處理」卡片立刻移欄，失敗彈回並提示 |
| 承接速度／可中斷 | 側板、卡片移動用 spring（`motion` 套件，stiffness 400 / damping 30 量級），中途可反向 |
| 有意義的動效 | 新事件從頂部滑入，2 秒後只留黃點；完成卡片淡出 |
| 尊重使用者 | `prefers-reduced-motion` 降為 150ms 淡入淡出 |

## 3. 資訊架構（管理者）

```
/ops
├── /inbox        通知中心（首頁）：事件流 + KPI
├── /board        整備看板：三欄 Kanban + SLA
├── /tasks/:id    任務詳情：摘要 / 證據 / 通知 / 歷程（桌機為右側板，可分享 URL）
├── /people       人員與班表：整備組別、可指派名單（取代寫死的 ASSIGNEES）
└── /settings     通知設定：管道狀態、SLA 門檻、測試發送
```

左側固定導覽（深藍底），頂列：全域搜尋（車牌／案件 ID）、連線狀態（即時／輪詢中／離線）、Demo 模式標記。

### 3.1 通知中心 `/inbox`

- KPI 三張：待處理任務、P1 未開工、通知失敗。點擊即套用篩選。
- 篩選 chips：全部／P1／P2／P3／未讀／通知失敗／今日。
- 事件列：優先級色條、車牌、事件類型（新車損任務／新髒汙任務／通知失敗／SLA 逾時／任務完成）、相對時間、通知狀態、黃色未讀點。點開右側任務詳情；「全部標為已讀」。
- 資料：`GET /api/ops/events`（分頁）+ `GET /api/ops/events/stream`（SSE）；SSE 斷線退回 5 秒輪詢並顯示狀態。
- 已讀狀態存 server（`event_reads` 表），全隊共享。

### 3.2 整備看板 `/board`

- 三欄：待處理／處理中／已完成（已取消併入已完成欄，灰階）。已完成預設只顯示今日。
- 卡片：車牌、類型 chip、P 級、標題、負責人縮寫、建立時間、**SLA 倒數**、通知狀態一行。
- 操作：拖曳換欄（drop 即 PATCH），保留按鈕；指派為 popover 選人（名單來自 `/api/ops/people`）。
- 排序：P1 置頂 → 逾時 → 建立時間；Demo 模式示範案例置頂（沿用既有 DEMO_IDS 邏輯，讀 `/api/demo/health`）。
- 篩選列：類型（維修／清潔）、負責人、只看逾時。

### 3.3 任務詳情 `/tasks/:id`

1. **摘要**：車牌、類型、P 級、狀態、負責人、SLA、建立／完成時間；主要動作依狀態只露一個。
2. **證據**：借／還照並排 + AI 標註框（重用監理台繪框邏輯，資料來自 `_case_snapshot`）；髒汙案單張 + 整潔分數；「在監理台開啟」連結。
3. **通知**：
   - 三 tab：用戶通知／客服摘要／派工單，來源 `notify.py`；顯示 grounding 檢核結果；文案可手動修改後再發。
   - 「生成文案」按鈕（呼叫 Gemini，結果快取於 `task_drafts`），Demo 前可預先生成。
   - 每則文案「發送」+ 管道選單：Webhook（可用）／LINE／簡訊（灰階「未接入」）。
   - 發送紀錄（`notification_log`）：時間、對象、管道、結果、重發。
4. **歷程**：`task_events` 時間軸（建立 → 通知 → 指派 → 開工 → 完成），加備註輸入（寫入 `task_events` event=note）。

### 3.4 人員與班表 `/people`

- 組別列表（維修組 A/B、清潔組 A/B…）與成員、是否在班；可新增／停用。
- 取代前端寫死的 `ASSIGNEES`；監理台暫不改，仍用舊名單（名單值相容）。

### 3.5 通知設定 `/settings`

- 管道卡片：Webhook（已設定／未設定，來自 `/api/demo/health` 或新的 `/api/ops/channels`）、LINE、簡訊（未接入）。「發送測試」按鈕只對 Webhook 可用。
- SLA 門檻：P1 5 分、P2 4 小時、P3 當日，可調（存 `ops_settings`）。
- 全部只讀不到金鑰；URL 一律不回傳前端。

## 4. SLA 規則

以 `created_at` 與 `server_time` 計算開工期限（P1 5 分、P2 4 小時、P3 當日 23:59）。剩餘 <20% 黃底；逾時紅字「逾時 N 分」並在通知中心產生一則 `sla_overdue` 事件（由後端每分鐘掃描一次，簡單 thread；容器單 replica 所以安全）。

## 5. 自寫 API（`/api/ops`，全部本環節負責）

| 方法 | 路徑 | 用途 | 讀寫表 |
|---|---|---|---|
| GET | `/events?since=&priority=&unread=&limit=` | 事件流分頁 | `ops_events`, `event_reads` |
| GET | `/events/stream` | SSE；每 15 秒心跳 | 記憶體佇列 + `ops_events` |
| POST | `/events/read` `{ids|all}` | 標已讀 | `event_reads` |
| GET | `/summary` | KPI（待處理、P1 未開工、通知失敗、逾時） | `tasks`, `notification_log` |
| GET | `/tasks?...` | 包裝既有 `/api/tasks`，加 `sla_due_at`、`overdue`、`server_time` | `tasks` |
| GET | `/tasks/{id}` | 任務 + 案件快照（照片 URL、標註框、AI 理由）+ 草稿 + 發送紀錄 | 多表 |
| PATCH | `/tasks/{id}` | 轉呼叫既有狀態機邏輯（不重寫規則），加 `note` | `tasks`, `task_events` |
| POST | `/tasks/{id}/drafts` | 呼叫 `notify.py` 生成三對象文案並快取；`?force=1` 重生 | `task_drafts` |
| PUT | `/tasks/{id}/drafts/{audience}` | 人工修改文案 | `task_drafts` |
| POST | `/tasks/{id}/send` `{audience, channel}` | 發送；webhook 實發，其他管道回 501 並記錄 `unsupported` | `notification_log`, `task_events` |
| GET | `/people`、POST/PATCH `/people/{id}` | 組別與成員 | `ops_people` |
| GET/PUT | `/settings` | SLA 門檻等 | `ops_settings` |
| GET | `/channels` | 各管道是否設定（布林，不含 URL） | env |

事件產生點：既有 confirm 建任務、通知結果、PATCH 狀態變更、SLA 掃描。為不改動 `server.py` 主邏輯，先用「輪詢 `task_events` 的增量」產生 `ops_events`（每 2 秒），之後再視情況改成直接寫入。

## 6. 新資料表（SQLite / Postgres 相容 DDL 草稿）

```sql
ops_events(id INTEGER PK, at TEXT, type TEXT, task_id INTEGER, case_id TEXT, priority TEXT, payload TEXT)
event_reads(event_id INTEGER, reader TEXT, at TEXT, PK(event_id, reader))
task_drafts(task_id INTEGER, audience TEXT, content TEXT, grounding_ok INTEGER, grounding_notes TEXT,
            generated_at TEXT, edited_at TEXT, PK(task_id, audience))
notification_log(id INTEGER PK, task_id INTEGER, audience TEXT, channel TEXT, status TEXT,
                 detail TEXT, at TEXT)
ops_people(id INTEGER PK, group_name TEXT, name TEXT, active INTEGER, created_at TEXT)
ops_settings(key TEXT PK, value TEXT)
```

`reader` 暫以前端選擇的身分名稱（無登入）；日後接帳號再改。

## 7. 分期

1. **Phase 1（骨架，可 Demo）**：前端專案 + tokens、通知中心（輪詢）、看板重製、任務詳情摘要／證據／歷程、SLA 倒數；後端 `ops_api.py` 的 summary / tasks / events（輪詢版）/ people / settings；`/ops` 靜態掛載。
2. **Phase 2（通知閉環）**：SSE、文案生成與編輯、多管道發送紀錄、SLA 掃描與逾時事件、通知設定頁。
3. **Phase 3**：Postgres 切換配合（`ops_db.py` 換驅動）、站點手機版、派單鎖定。

**Docker 配合事項**（需與同事確認一項即可）：Dockerfile 加 node 多階段 build 前端，或我們把 `backend/app/static/ops/` 的 build 產物進版控。建議前者；過渡期先用後者不擋人。

## 8. 已決定（2026-09-14）

1. **技術棧**：Vite + React + TypeScript + motion。
2. **身分**：無登入，前端選身分（介面標明「未驗證身分」）；帳號與登入等 PostgreSQL 與帳號表就位後再做。
3. **文案**：Demo 前對示範案例預生成三對象文案並快取；保留「重新生成」按鈕供現場即時展示。重置 Demo 時保留快取。
4. **Docker**：過渡期把前端 build 產物進版控（`backend/app/static/ops/`）讓第一期能動；之後 Dockerfile 多階段 build 與 compose 調整由本環節自行維護，不依賴同事排程。

## 9. 進度

- **Phase 1 完成（2026-09-14）**：`frontend-admin/`（Vite + React + TS + motion）、`backend/app/ops_api.py` + `ops_db.py`、`/ops` 靜態掛載、通知中心（5 秒輪詢）、看板（拖曳 + 樂觀更新）、任務詳情側板、人員、通知設定、SLA 倒數與逾時事件、`tests/test_ops.py` 15 項。
  - 與規劃差異：`/tasks/{id}/drafts`、`/send` 與 SSE 未做（Phase 2）；任務詳情「通知」區先顯示 Phase 2 說明與既有 webhook 狀態。
- **Phase 2 完成（2026-09-14）**：SSE `GET /api/ops/events/stream`（斷線退回輪詢、10 秒重連、新事件底部提示）；三對象文案 `GET/POST /api/ops/cases/{case_id}/drafts`（呼叫 `notify.py`，**以 case_id 快取**，重置 Demo 不清）、`PUT .../drafts/{audience}` 人工編輯；`POST /api/ops/tasks/{id}/send`（webhook 實發、line/sms 記 unsupported、寫 `notification_log` 與歷程）；`POST /api/ops/settings/test` 測試通知；通知設定頁 Demo 模式「預生成文案」。`tests/test_ops.py` 24 項。
  - 與規劃差異：文案改以案件為鍵（原規劃 `task_drafts` 以任務為鍵），因內容取決於 AI 判定且要在 confirm 前預生成。
- **Phase 3 部分完成（2026-09-14）**：
  - 車輛派單狀態頁 `/fleet` + `GET/PATCH /api/ops/fleet`：有未完成任務或手動鎖定 → 整備中不可派，完成自動解除；AI 標記未複核者標「待確認」。**模擬狀態，未與派單系統串接**，頁面上明示。
  - 營運洞察頁 `/insights` + `GET /api/ops/insights`：還車時段分布（`pipeline/build_ops_insights.py` 離線彙整真實上傳 log 4,820 單，單日）、整備中位開工／完工時間（即時）、車輛事件排行（任務＋索賠）、車內整潔分布（離線，n=24）。每張圖標口徑與 n，附數值表。
  - 站點人員手機版 `/ops/m`（同日）：選組別 → 我的任務（指派給我＋未指派）→ 接單開工 → 拍完工照（`POST /api/ops/tasks/{id}/photos`，EXIF 轉正、縮圖、存 `IRENT_UPLOAD_DIR/ops_task_photos/`）→ 完工（前端要求至少一張完工照）。完工照顯示於任務詳情，日後可作下一次借車基準照。
  - Dockerfile 改多階段（node 建前端 → python），compose 的 build context 改為 repo 根、根目錄 `.dockerignore`；repo 內 `backend/app/static/ops/` 仍保留供本機 uvicorn 直接使用。
  - `ops_db.py` 方言層：`DATABASE_URL` 為 postgres 時以 psycopg 連線、`?`→`%s`、AUTOINCREMENT→SERIAL；**Postgres 未實測**（本機無 Postgres），等同事的 PR #2 一起驗證。
  - **流程修正（2026-09-14 下午）**：Demo 重置後孤兒事件／紀錄／完工照自動清除；手機版接單防搶單（`expected_assignee`，409）；完工照規則改由後端守門（`server.TASK_COMPLETE_GUARD`，監理台與手機版同一條；清潔預設必附、維修選填、設定頁可調）；系統推播 payload 加 `kind=system_event` 與 `url`（需 `PUBLIC_BASE_URL`）；SLA 逾時自動升級推播（`kind=escalation`，可關）；通知中心預設「需要行動」；任務詳情深連結監理台 `/#case=<id>`；依任務類型預設指派（只做一次）；完工照作基準照 `GET /api/ops/cars/{car}/baseline`；洞察頁加「人工裁決 vs AI 一致率」趨勢。
  - 待做：Postgres 實測、登入與身分驗證、派單系統真實串接、環節二判讀流程實際取用基準照。
