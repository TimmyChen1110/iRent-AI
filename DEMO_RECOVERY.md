# IF SOMETHING BREAKS ON STAGE（30–60 秒內查）

所有指令在 repo 根目錄執行。後端一律本機 uvicorn，不用 Docker。

```text
iPhone 上傳一直「待上傳」／「等待照片上傳」
→ 先看後端 log 有沒有任何來自手機 IP 的請求；一筆都沒有 = 被 Mac 防火牆擋（2026-10-06 實際踩到）
   系統設定 › 網路 › 防火牆 › 選項 → 把啟動 uvicorn 的那個 python 加進「允許連入」；或先關防火牆
   或改用已在允許清單的 miniconda python 啟動：
   cd backend/app && DEMO_MODE=true /opt/homebrew/Caskroom/miniconda/base/bin/python3.13 -m uvicorn server:app --host 0.0.0.0 --port 8000
→ iPhone 與 Mac 同一網路（建議 iPhone 個人熱點，Mac 連上去）；Mac 的 VPN（Tailscale 等）先關
→ Mac 區網 IP：ipconfig getifaddr en0   （熱點時通常是 172.20.10.x；用 en1 時換介面）
→ App 設定 → API Base URL = http://<那個IP>:8000 → 按「測試連線」看到 ✓
→ 回清單按「重試」，或關掉再開 App（PendingUploadSync 會自動重送）
→ iOS 跳「區域網路」權限 → 允許（設定 › iRent App › 區域網路）

App「上傳被拒：此租約的取車檢查已結束」
→ 上一輪沒清：App 設定 → 「重新開始 Demo」 → 重拍取車

相機黑畫面／不開
→ 設定 › 隱私權與安全性 › 相機 › irent-app 開啟；或 設定 › irent-app › 相機
→ 模擬器沒有相機：用「從相簿選擇」

Admin 看不到 ABC-1234 事件
→ curl -s http://localhost:8000/v1/mobile-inspections/rentals/RNT-20261005-1842 | python3 -m json.tool
     status=RETURN_IN_PROGRESS → 照片沒齊（看 return.missing），回 iPhone 補傳
     status=ANALYZING 超過 30 秒 → 重啟後端（啟動會自動重排分析）
     status=ANALYSIS_FAILED → 走 fixture：按 Admin 右上「重置 Demo」
     status=ANALYSIS_COMPLETE → 案件在：curl -s -b cookie http://localhost:8000/api/ops/cases?car=ABC-1234
→ Admin 右上角徽章顯示「離線」→ 後端掛了（見下）；顯示「輪詢中／即時連線」→ 等 5 秒
→ 最後才重新整理瀏覽器（會回到登入頁，demo 帳號一鍵登入）

後端掛掉 / 無回應
→ cd backend/app && DEMO_MODE=true ../.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8000
   （沒有 .venv 時：cd backend && python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt）
→ 啟動自動：登記租約、復原卡在分析中的租約、示範租約沒有照片時用固定劇本落地
→ 已收到的照片、基準、案件、任務都在 SQLite，不會消失

AI（Gemini）不可用
→ 示範租約 RNT-20261005-1842 永遠走固定劇本，不打 Gemini；其他租約會 ANALYSIS_FAILED 但紀錄保留
→ 不要現場改 code；App 預設 Demo 模式、後端 DEMO_MODE=true 即可

全部都掛（iPhone / 網路都不行）
→ 只要後端能起：Admin 右上 → 重置 Demo
→ 總覽直接是 LIVE INCIDENT ABC-1234（右後車門 92% / 車內 88%，固定照片）
→ 指揮中心 → 台北 → ABC-1234 → 數位分身 → 執行 AI 建議方案 → 維修／清潔完工 → 恢復上線
→ 這條路不需要 iPhone、不需要 Gemini、不需要網路
```
