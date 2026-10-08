# 模擬租還車 Demo（定位找車 → 租車 → 還車資訊 → 拍照 AI 檢測 → 還車完成）— 開發報告

日期：2026-10-09。本輪把既有的 iOS 拍攝防呆、照片上傳與後端 AI 比對 pipeline，整合成一條可現場操作的 End-to-End 流程。
**所有車輛、位置、里程皆為模擬資料**（後端 `demo_vehicles.simulated=1`，UI 標示「模擬車輛」），不是真實 iRent 車隊。

## 1. 已完成的功能

| Phase | 內容 | 位置 |
|---|---|---|
| 1 定位授權 | App 啟動先顯示定位用途說明 → 請求「使用期間」權限 → GPS 座標顯示於地圖；拒絕／失敗／逾時（15 s）可「手動選擇位置」（拖地圖或預設地點）。定位只存記憶體 | `LocationService.swift`、`LocationPermissionView.swift` |
| 2 模擬車輛與車牌 | 後端登記兩台模擬車（二活周邊固定座標）：`SIM-RCG-2235`（資料集真車，Core ML 可辨識，還車走**真實 Gemini pipeline**）、`SIM-ABC-1234`（比賽示範固定劇本，UI 明確標示「非真實 AI 判定」）。地圖點車 → 卡片（車型／車牌／位置／距離／油量／里程／狀態）→「詳細資訊」頁 →「開始租車」。車牌辨識測試資料集見 `backend/tools/plate_test_set/` | `rental_sessions.py`、`FindCarView.swift`、`VehicleDetailView.swift` |
| 3 租車與還車資訊 | 開始租車＝建立 Session（記錄開始時間、車牌、起始位置、起始里程）；租用中頁顯示車輛資訊、開始時間、即時計時；「我要還車」→ 還車資訊確認頁（車牌、開始／還車時間、總使用時間、起始／結束里程、總行駛里程、還車位置），結束里程由前後端雙重驗證 ≥ 起始里程 | `ReturnInfoView.swift`、`ContentView.swift`（ActiveRentalView） |
| 4 還車拍照與 AI | 完全沿用既有拍攝清單／Core ML 防呆／上傳（`POST /v1/mobile-inspections/photos`）與後端 `rental_inspections.run_analysis`（Gemini Flash 快篩 → Pro 級聯；車內整潔）。新增 AI 檢測結果頁：逐角度比對、車內整潔、車牌比對、已轉人工複核的異常、判定來源；失敗可「重新檢測」或「重新拍攝」 | `InspectionResultView.swift` |
| 5 狀態判別 | 後端 Session 狀態機（下方），App 每次開啟以後端為準恢復畫面；重複租車 409、順序跳轉 409、檢測完成 ≠ 還車完成（需 `confirm-return`）；照片車牌與租借車牌比對：一致／手動輸入／不一致（使用者確認）→ 後兩者標記需人工確認，不判成功 | `rental_sessions.py`、`RentalStore.phase(for:)` |

### Session 狀態機（後端驗證）

```
AVAILABLE ─開始租車→ PICKUP_INSPECTION ─取車照齊（後端驗證）→ RENTED ─我要還車→ RETURN_INITIATED
  ─確認還車資訊（結束里程 ≥ 起始）→ PHOTO_INSPECTION ─還車照齊、AI 完成→ INSPECTION_COMPLETED ─確認還車→ RETURNED（車輛回 AVAILABLE、里程更新）
                                                      └─AI 失敗→ INSPECTION_FAILED ─重新檢測／重新拍攝→ PHOTO_INSPECTION
```

`PICKUP_INSPECTION` 是規格之外新增的一步：既有 AI 是「取車照 vs 還車照」比對，沒有取車基準就無法判定新損，所以開始租車後先拍取車照。

## 2. 修改與新增的檔案

**後端（`backend/`）**
- 新增 `app/rental_sessions.py`：模擬車輛 + Session 領域層（SQLite 表 `demo_vehicles`、`rental_sessions`，與既有 DB 同檔）。
- 新增 `app/rental_sessions_api.py`：`/v1/rental-sessions/*`。
- `app/server.py`：掛載 router、啟動登記模擬車輛、demo health 加 Session 資訊。
- `app/user_capture_api.py`：新增選填欄位 `plate_confirmation`（ocr／manual／user_confirmed_mismatch）；預設行為不變（車牌不符仍 422）。
- `app/rental_inspections.py`：新增 `clear_return_stage()`（重新拍攝還車照）。
- 新增 `tests/test_rental_sessions.py`（18 條）；新增 `tools/build_plate_test_set.py` 與 `tools/plate_test_set/`。

**iOS（`frontend-user/irent-app/irent-app/`）**
- 新增 `Services/RentalSessionService.swift`、`Services/LocationService.swift`、`Views/LocationPermissionView.swift`、`Views/VehicleDetailView.swift`、`Views/ReturnInfoView.swift`、`Views/InspectionResultView.swift`。
- 改寫 `Models.swift`（Session／車輛／檢測結果模型、後端狀態 → 畫面階段、狀態恢復）、`Views/FindCarView.swift`（車輛改由後端提供、真實定位、開始租車／取消）、`ContentView.swift`（新階段、租用中計時、還車完成摘要、設定頁）。
- `Views/CaptureView.swift`、`Services/OnDeviceRecognitionService.swift`、`Services/CaptureValidator.swift`、`Services/InspectionSyncService.swift`：OCR 失敗可手動輸入車牌、OCR 與租約不符可由使用者確認後送人工複核。
- `DemoFleet.swift`：只剩後備位置與示意路線；`irent_appApp.swift` 注入 `LocationService`；`project.pbxproj` 新增定位權限說明字串。

## 3. 前後端整合方式

- App 只「請求」轉換（`POST .../pickup/complete`、`/return/initiate`、`/return/info`、`/confirm-return`），後端檢查租約照片完整度與狀態順序後才改狀態。
- 照片上傳仍用既有端點，`rental_id` 來自 Session；AI 分析由既有背景執行緒完成，Session 在每次讀取時由租約的 `ANALYSIS_COMPLETE / ANALYSIS_FAILED` 推導 `INSPECTION_COMPLETED / INSPECTION_FAILED`。
- App 開啟時 `GET /v1/rental-sessions/{saved id}`（沒有就 `/active`）恢復畫面；後端已重置（404）則回到找車。
- 模擬租約在管理者端 `/ops` 檢查紀錄照常出現（`demo=true`），案件走同一條裁決／任務路徑。

## 4. 車牌辨識與 AI 檢測流程

- 車牌：裝置端 Core ML（PlateDetector → PlateOCR）比對租借車牌；讀不到 → 可手動輸入（須等於租借車牌，標記 `manual`）；讀到別台 → 使用者可確認同一台車（標記 `user_confirmed_mismatch`）。後端 `plate_check` 匯總 MATCH／MANUAL／MISMATCH，後兩者 `review_required=true`，App 顯示「需人工確認」。
- AI：`rental_inspections._real_analysis()`（Gemini Flash → Pro 級聯 + 車內整潔）不變；只有 `SIM-ABC-1234` 走 `demo_inspection_fixture` 固定劇本，App／API 都以 `ai_source=demo_fixture` 標示「非真實 AI 判定」。
- 測試資料集：`backend/tools/plate_test_set/manifest.json`（35 張，Core ML 27 張與預期一致、4 張讀錯、2 張讀不到、2 張無標籤）。

## 5. 本機啟動與操作

```bash
cd backend/app && DEMO_MODE=true ../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000   # GEMINI_API_KEY 走 環節二/.env 或環境變數
```
iOS：Xcode 開 `frontend-user/irent-app`，模擬器或真機執行；設定 → API Base URL 填 `http://<Mac 區網 IP>:8000`（模擬器可用 `http://127.0.0.1:8000`）。
模擬器定位：`xcrun simctl location booted set 25.0175,121.5340`。流程：允許定位 → 地圖點 RCG-2235 或 ABC-1234 → 開始租車 → 我已抵達 → 取車拍 5 張 → 開始租借 → 我要還車 → 輸入結束里程 → 還車拍 5 張 → 完成拍攝 → 看 AI 結果 → 確認還車 → 完成。重演：設定 →「重新開始 Demo」。

## 6. 測試結果

| 測試 | 結果 |
|---|---|
| 後端 pytest 全套（含新增 18 條：完整流程 fixture／pipeline(mock)、無 key 失敗→重新檢測→重新拍攝、重複租車、順序跳轉、里程驗證、取消、狀態恢復、手動車牌、車牌不一致、Demo 重置、管理者端整合） | 434 passed |
| 真實 Gemini pipeline（`SIM-RCG-2235`，資料集借／還照）經 API 走完 | 56 秒完成：4 角 NO_NEW_DAMAGE／EXISTING_DAMAGE、車牌 MATCH、整體 PASSED；車內照判 UNREADABLE（選用的資料集「車內」照實為車外照，誠實回報） |
| iOS 編譯（iPhone 17 模擬器） | BUILD SUCCEEDED |
| iOS 各階段畫面（以 API 推進狀態、重開 App 恢復）：定位／地圖與兩台車／前往車輛／租用中計時／還車資訊／還車拍攝／AI 結果（fixture 標示）／還車完成 | 全部正確渲染，截圖已檢視 |
| 定位遭拒 | 顯示「前往設定開啟定位」與「手動選擇位置」 |
| 頁面重新整理與狀態恢復 | 每個階段 terminate → relaunch 後皆回到正確畫面（後端狀態為準） |

**未以實機操作驗證的部分**：模擬器沒有相機、本機也沒有 UI 自動化工具，所以「在 App 內實際點按鈕 → 拍照 → 上傳」這段只靠既有程式路徑（本輪未改上傳邏輯）與編譯通過；手動輸入車牌／車牌不一致確認的 UI 需在真機用真實 Core ML 操作確認。

## 7. 仍使用 Mock／模擬資料的部分

- 模擬車輛（車牌、車型、位置、里程、油量）、車輛圖片（RCG-2235 用資料集取車照；ABC-1234 用資料集佔位照並標示）。
- 結束里程由使用者輸入或「填入模擬里程」；步行路線為示意折線。
- `SIM-ABC-1234` 的 AI 結果為示範固定劇本；拍攝防呆 Demo 模式為固定劇本（設定頁可關閉改走真實 Core ML）。
- 無車門、計費、合約；Stonk API 未串接（只有可匯出的測試資料）。

## 8. 後續可改善

- 真機跑一輪真實 Core ML + Gemini（含手動車牌／不一致確認）並補 XCUITest。
- 車內照 UNREADABLE 時在 App 提示補拍；Session 完成後把還車位置回寫車輛位置。
- 多使用者／多裝置（目前 `/active` 假設單使用者 Demo）；Session 過期與逾時取消。
- 接 Stonk API 時把 `manifest.json` 轉成對方格式。


---

## 附錄 A（2026-10-09）：固定 Demo 測試車輛 RFY-1753

不受使用者定位／距離限制、不論 GPS 授權成功或失敗都能從首頁進入的展示用車輛。

**資料（單一來源：`backend/app/rental_sessions.py` 的 `SIM_VEHICLES`，`category="demo"`，`vehicle_id=demo-rfy-1753`）**

| 欄位 | 值 |
|---|---|
| 車牌／車款 | RFY-1753／TOYOTA ALTIS HYBRID |
| 車輛類型／乘坐人數／顏色 | 個人用車／5 人／白色 |
| 停車格 / 路段 | 67 |
| 租金／里程費 | NT$130 / 小時、NT$3.5 / 公里（示範數值） |
| 預估里程費／預估總金額 | NT$70／NT$200（示範數值，不串接計費、不產生費用） |
| 狀態／類別 | Available／Demo Vehicle |
| 圖片 | `/photos/demo/rfy-1753.png`：程式生成的白色轎車示意圖（`backend/app/demo_assets/`），UI 標示「非本車實拍」；沒有找到使用者提到的截圖檔，換圖只要覆蓋這個 PNG。車牌辨識測試素材另在 `backend/tools/plate_test_set/`，兩者不混用 |

**顯示邏輯（獨立於一般車輛）**
- API `GET /v1/rental-sessions/vehicles` 每台車帶 `category` / `is_demo_vehicle` / `details`；App 以 `SimVehicle.isDemo` 過濾出 Demo 車。
- 固定入口 `DemoVehicleEntry`（`Views/DemoVehicleEntry.swift`）：定位授權頁（含拒絕／逾時狀態）、地圖頁上方、設定頁都有；點擊開 `VehicleDetailView`（車牌、車型圖、車款、乘坐人數、狀態、停車格、租金／里程費、預估費用、「開始使用」、「重設 Demo」）。
- 地圖 marker 仍畫在固定示範位置（橘色 DEMO 標籤），卡片明說「不代表車輛真的在你附近」；一般車輛與 GPS 定位邏輯不變。
- 「開始使用」→ 建立 Session（租約 `RNT-DEMO-…`）→ 直接進取車檢查（不經「前往車輛」），之後租用中／還車資訊／還車拍照／AI 檢測／確認還車全部沿用既有流程；AI 走真實 Gemini pipeline。

**重設 Demo**：`POST /v1/rental-sessions/vehicles/demo-rfy-1753/reset`（只允許 `category=demo`，不需 `DEMO_MODE`）→ 進行中 Session 封存為 `ARCHIVED`、該租約檢查紀錄與衍生案件清掉、車輛回 AVAILABLE（里程保留）；不碰其他車輛與正式資料。App 在車輛詳細頁／設定頁按「重設 Demo」，會先跳確認視窗；若重設的是自己正在用的車，本機狀態一併清掉。每位展示者的 Session 是獨立紀錄，重設只封存該車進行中的 Session。

**啟動 Demo**：後端照常啟動（`DEMO_MODE=true` 非必要）；App 開啟 → 定位頁或地圖上點「Demo 測試車輛 — RFY-1753」→「開始使用」→ 取車拍 5 張 → 開始租借 → 我要還車 → 輸入結束里程 → 還車拍 5 張 → AI 檢測 → 確認還車；下一位展示者直接再租，或先「重設 Demo」。

**驗收結果（2026-10-09）**

| 項目 | 結果 |
|---|---|
| 後端 pytest（新增 5 條：資料與示範計費、示意圖供圖、完整流程走真實 pipeline（mock）後可再租、重設封存且不碰其他車／非 demo 車 403、舊資料庫自動補欄位） | 439 passed |
| 定位拒絕（`simctl privacy revoke location`） | 定位頁顯示「Demo 測試車輛 — RFY-1753」入口 |
| 定位在高雄（`simctl location set 22.6273,120.3014`） | 地圖頂部固定入口可見，可租借車輛數含 RFY-1753 |
| 定位在臺大 | 同上，且 marker 以橘色 DEMO 標籤顯示 |
| 以 API 推進 + 重開 App：開始使用 → 取車檢查（直接進入，不經前往車輛）→ 租用中（狀態 RENTED）→ 還車資訊 → 還車拍攝 → AI 檢測（真實 Gemini，120 秒：右後 NEW_DAMAGE、左後 EXISTING_DAMAGE、車牌 MATCH）→ 確認還車 → 車輛回 AVAILABLE | 全部通過，畫面截圖已檢視 |
| 第二位展示者重新租借 → 重設 Demo | Session 封存、車輛回 AVAILABLE，可再次租借 |
| 未驗證 | App 內實際點按「開始使用」「重設 Demo」與相機拍照（模擬器無相機、無 UI 自動化工具），僅編譯通過與程式路徑檢視 |


---

## 附錄 B（2026-10-09）：專案照片盤點 → Demo 車輛 Registry → 預載照片 Demo（模式 B）

**盤點與分析**（`backend/tools/audit_demo_images.py`，報告 `DEMO_IMAGE_AUDIT.md`、候選 `DEMO_VEHICLE_CANDIDATES.md`、對應表 `backend/app/DEMO_IMAGE_MANIFEST.json`）
- 掃描 repo 內 2,325 張照片：資料集借／還 293、車內候選 80、環節一樣本 3、跨訂單還車照鏈 1,909、App 上傳副本 40。
- 品質用既有 `quality_gate.py`；車牌用與 App 相同的 Core ML 模型批次 OCR（讀不出標 UNREADABLE、與檔名不符標 MISMATCH，不猜）；借／還階段只採既有 `pairs.json`（資料集檔名）；可比對性用 AI `angle_match` 與人工 `relabels.json`。
- 配對驗證：兩張照片 OCR 都讀到檔名車牌 → VERIFIED；否則 Unverified Pair。

**選定**：主要影像辨識 Demo 車 **RDG-9853**（4 角借／還 VERIFIED、人工重標全 clean）；車損展示 **RFH-8122**（右後角 VERIFIED 且人工重標真實新損）；**RFY-1753** 保留但專案內沒有它的任何照片，只能即時拍攝（不虛構）。

**Demo Vehicle Registry**（`backend/app/demo_vehicle_registry.py`，單一資料來源）
- `GET /v1/rental-sessions/vehicles/{id}/photos`：Before／After 照片（走既有 `/photos/pair` 供圖、不複製、不含絕對路徑）、角度、品質、Core ML OCR、配對驗證、人工重標、車內佔位照說明。
- `POST /v1/rental-sessions/{sid}/preload/{pickup|return}`：模式 B，把登記照片灌進租約（`validation_mode=preloaded`、`source=demo_preload`），之後與即時拍攝走同一條 `rental_inspections` pipeline。
- 車內：資料集沒有同一租約的車內借／還照，預載用其他車輛的「乾淨」車內照當佔位，API／App 都標示 `interior_standin`（非本車）。

**App**
- 首頁（定位頁與地圖頂部）固定「Demo 測試車輛（3 台）」區塊：照片、車牌、車型（照片目視，標示資料集未記錄）、狀態、DEMO／「有借／還照片」標籤；不受定位與 GPS 授權影響，每次開啟都從後端載入。
- 車輛詳細頁：借車前／還車後照片列、逐角度配對驗證與人工重標、「開始使用」。
- 取車／還車拍攝頁：模式 A 即時拍攝（既有流程）或模式 B「使用預載照片」；預載後每張標示「預載 Demo 照片（資料集，非當下拍攝）」。
- 租用中頁顯示借車前車況照片；AI 結果頁標示照片來源。

**驗收（2026-10-09）**

| 項目 | 結果 |
|---|---|
| 後端 pytest（新增 5 條：Registry 照片集／三台 Demo 車／預載取車＋還車走同一 judge_pair／無照片車 404／manifest 缺檔仍可啟動） | 444 passed |
| 預載流程真實 Gemini（RDG-9853 借／還資料集照）：取車預載 → RENTED → 還車預載 → 40 秒 INSPECTION_COMPLETED → PASSED、車內 CLEAN、車牌 MATCH → 確認還車 → 車輛 AVAILABLE | 通過（畫面截圖已檢視） |
| 定位拒絕／定位在臺大：首頁都顯示 3 台 Demo 車 | 通過 |
| 拒絕定位、缺 manifest、無照片的 RFY-1753 | App 正常啟動；無照片車只提供模式 A |
| 未驗證 | App 內實際點按（模擬器無相機、無 UI 自動化）；chain_photos 的 OCR 批次於報告產出時仍在跑的部分以 NOT_RUN 標示 |
