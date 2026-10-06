# PRE-DEMO CHECKLIST — iOS App → Backend → AI → Incident → Fleet Command Center

現場出狀況先看 **[DEMO_RECOVERY.md](DEMO_RECOVERY.md)**。本文件是賽前準備與完整步驟。
所有指令皆為 repo 真實指令，在 repo 根目錄執行。

## 1. System Startup（依序）

```bash
# 0) 一次性：後端 Python 3.13 venv（3.14 無 opencv / pillow-heif wheel）
cd backend && python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..

# 1) 後端：一定本機 uvicorn、一定 0.0.0.0（iPhone 才連得到）、一定 DEMO_MODE=true
cd backend/app && DEMO_MODE=true ../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
#    選填：GEMINI_API_KEY（示範租約不需要）、NOTIFICATION_WEBHOOK_URL（python3 backend/tools/webhook_receiver.py）

# 2) 健檢（另一個終端）
curl -s http://localhost:8000/api/health            # {"status":"ok",...}
curl -s http://localhost:8000/api/ops/health | python3 -m json.tool | grep -A3 demo_rental   # status: ANALYSIS_COMPLETE

# 3) 管理者端：http://localhost:8000/ops → 「管理者 · admin」一鍵登入（admin / admin-demo）
#    前端已預先 build 進 backend/app/static/ops；改過 fleet-ops-center 才需要 cd fleet-ops-center && npm run build:ops

# 4) 重置 Demo：Admin 右上角頭像 → 「重置 Demo 案例」（或 curl -X POST -b <cookie> http://localhost:8000/api/demo/reset）

# 5) Mac 區網 IP
ipconfig getifaddr en0        # Wi-Fi；接 iPhone 熱點時通常是 172.20.10.x（若回空白，試 en1）
```

`--host 0.0.0.0` 只在 Demo 用：資料含真實車牌照片且無 TLS，僅限本機／內網（同既有 README 紅線）。

## 2. Network Setup（建議）

| 優先 | 方案 | 說明 |
|---|---|---|
| 1 | **iPhone 開個人熱點，Mac 連上熱點** | 不依賴場地 Wi-Fi、沒有 client isolation；Mac IP 用 `ipconfig getifaddr en0` 取得 |
| 2 | 自帶小型路由器 / 第二支手機熱點 | Mac 與 iPhone 都連同一個 |
| 3 | 場地 Wi-Fi | 常有 client isolation（裝置互連被擋），**不要當主方案**；賽前先用「測試連線」驗證 |

不要用 Docker（容器內網 IP 手機連不到）、關 VPN、Mac 防火牆若開著要允許 Python 接受連線（首次會跳提示）。

## 3. iPhone Configuration

1. Xcode 開 `frontend-user/irent-app/irent-app.xcodeproj` → 選真機 → Run（Team YQN2UV8J9M 自動簽章；新機器需在 iPhone 設定 › 一般 › VPN 與裝置管理 信任開發者）。
2. App 右上「設定」：
   - API Base URL：`http://<Mac 區網 IP>:8000`（可只打 `192.168.1.10:8000`，App 會自動補 `http://`；**不是 localhost**）
   - 按「測試連線」→ 必須看到 ✓
   - Demo 模式：開（固定驗證劇本；關掉則用真實 Core ML，需要真車 RCG-2235）
   - 租約：ABC-1234 · RNT-20261005-1842
3. 第一次拍照會跳「相機」權限 → 允許；第一次上傳會跳「區域網路」權限 → 允許。
4. 若之前跑過：設定 → 「重新開始 Demo」（同時清本機與後端這筆租約）。

## 4. 60-Second Preflight

```text
[ ] 後端在跑：curl -s http://localhost:8000/api/health 回 status ok
[ ] DEMO_MODE：/api/ops/health 的 demo_mode=true、demo_rental.status=ANALYSIS_COMPLETE
[ ] Admin 已登入，總覽看到 LIVE INCIDENT ABC-1234（右後車門 92% / 車內 88%）
[ ] Admin 右上已按「重置 Demo」一次
[ ] Mac 與 iPhone 同一網路（熱點），VPN 關
[ ] App 設定 API URL = http://<Mac IP>:8000，「測試連線」✓
[ ] App 設定「重新開始 Demo」已按（清單全部「待拍攝」、沒有「待上傳」）
[ ] iPhone 相機與區域網路權限皆已允許
[ ] iPhone 電量 / 螢幕不自動鎖定
[ ] Admin 右上角徽章「即時連線」或「輪詢中」（不是「離線」）
```

## 5. Full Demo Steps

| # | 操作 | 預期 |
|---|---|---|
| 1 | App 取車檢查 → 左前 → 拍照 | 第一次：「照片需要重拍／畫面過於模糊」；重拍 → ✓ 畫面清晰／角度正確／車牌 ABC-1234／車輛完整 |
| 2 | 右前 → 左後 → 右後 → 車內 | 每張 ✓，列表顯示「已拍攝 · 已同步」 |
| 3 | 檢視並完成取車檢查 → 完成 | 「取車檢查完成」外觀 4/4、車內 1/1、車況基準 已建立 → 開始租借 |
| 4 | 開始還車 → 四角（右後第一次失敗 → 重拍）→ 車內 → 完成還車 | 「還車完成」車況檢查：分析中 → 已完成（約 2–5 秒）；App 不顯示任何車損判定 |
| 5 | Admin 總覽（不用重新整理） | 約 5 秒內 LIVE INCIDENT ABC-1234 · 還車 20:42 · AI 標記 2 件待裁決（實測 3.3 秒） |
| 6 | 檢查紀錄 → RNT-20261005-1842 | 右後 NEW_DAMAGE、右前 EXISTING_DAMAGE 不開案、左前／左後 NO_NEW_DAMAGE、車內 CLEANING_REQUIRED |
| 7 | 指揮中心 → 檢視台北 → ABC-1234 → 開啟數位分身 | 右後車門 hotspot 92% → 查看證據（取車右後 vs 還車右後，紅框） |
| 8 | 執行 AI 建議方案 | 暫停派單、建立維修 + 清潔任務 → 整備進行中 |
| 9 | 維修頁 / 清潔頁 → 開始 → 完工（清潔需完工照）→ 車輛恢復上線 | 台北地圖標記變回正常 |
| 10 | 右上 → 重置 Demo | 回到 seed 狀態，可重演 |

## 6. Failure Recovery
見 [DEMO_RECOVERY.md](DEMO_RECOVERY.md)。

## 7. Reset Procedure

- **Admin「重置 Demo」**（`POST /api/demo/reset`）：清兩個資料集示範案例 + 示範租約案件的裁決／任務／事件／通知／完工照；示範租約 **重新落地為固定劇本 + 固定照片（ANALYSIS_COMPLETE）**，App 上傳過的真照片會被佔位照取代。Admin 開著不用重整，下一輪輪詢（≤5 秒）即更新；在車輛頁按下時不會跳頁。
- **App「重新開始 Demo」**（`POST /v1/mobile-inspections/rentals/RNT-20261005-1842/restart`）：清本機照片、本機狀態、後端這筆租約的所有紀錄與衍生案件／任務 → 租約回 CREATED，Admin 這台車的事件消失（總覽主角退回資料集示範案 RCR-7661），等 App 再次完成還車才重新出現。App 進入取車清單且本機沒有照片時也會自動呼叫一次。
- 順序建議：上台前 Admin 重置 → App 重新開始 Demo → 開拍。

## 8. Real Device Manual QA（本機環境無法自動驗證，請在 iPhone 上逐項打勾）

```text
[ ] 全新安裝 → 取車 → 拍照 → 跳「相機」權限 → 允許 → 相機開啟、可拍
[ ] 相機權限拒絕 → 再按拍照 → 顯示「相機權限已關閉，請至設定…」，不閃退
[ ] 第一次上傳跳「區域網路」權限 → 允許 → 設定頁「測試連線」✓
[ ] http://<IP>:8000 真機可連（ATS 只開 NSAllowsLocalNetworking；若被擋，見「已知限制」）
[ ] 拍兩個不同角度 → 兩張都在清單、縮圖不同（檔名含角度與 UUID，不覆寫）
[ ] 關閉 Mac 後端 → 拍照 → 「目前無法連線，照片已保存…（待上傳）」→ 清單「待上傳 1 張」
[ ] 後端開回來 → 按「重試」或重開 App → 變「已同步」；後端 inspection_photos 只有一筆
[ ] 有待上傳時把 App 滑掉 → 重開 → 自動重送，不需重拍
[ ] 相機開著 → 切到背景 → 回來 → 相機可用，不黑屏
[ ] 上傳中切背景 → 回前景 → 仍會同步
[ ] 拍完鎖機 → 解鎖 → 狀態仍在
[ ] 取車完成後再上傳取車照（舊一輪殘留）→ 顯示「上傳被拒：…請先重新開始 Demo」且不再重試
[ ] 一輪完整 Demo 後，Admin 總覽 ≤5 秒出現 LIVE INCIDENT（不重整）
```

## 9. Known Limitations

- 分析是行內 thread；後端被 kill 會中斷，**啟動時自動重排**（已實作並測試），但需要有人重啟後端。
- ATS 用 `NSAllowsLocalNetworking`（區網 HTTP），未開 `NSAllowsArbitraryLoads`；是否覆蓋你場地的 IP 段 **未在真機驗證**。若真機連不上且錯誤是 ATS，臨時方案：Xcode → Info.plist 改為 `NSAllowsArbitraryLoads=YES`（Demo 限定，Production 用 HTTPS 並刪除整段 NSAppTransportSecurity）。
- 示範租約的固定劇本只對 `RNT-20261005-1842`；真實租約需要 GEMINI_API_KEY 與網路，失敗時變 ANALYSIS_FAILED（紀錄保留）。
- 模擬器沒有相機，只能「從相簿選擇」。
- Admin 登入 session 為 cookie；重整瀏覽器會回登入頁（一鍵登入即可）。
- 後端單 process、SQLite；不要同時開兩個 uvicorn 指向同一 DB。
