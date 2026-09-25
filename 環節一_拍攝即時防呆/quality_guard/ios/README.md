# 環節一 iOS App — PhotoQualityGuard（Phase 2）

Native SwiftUI App（iOS 17+，無第三方套件），把 `../frontend/` 的 Web prototype 移植成真正的 iPhone App。
`../frontend/` 保留為 UI/UX prototype 與 Web demo。

## 執行步驟

1. 啟動 FastAPI（另一個終端機）：

   ```bash
   cd 環節一_拍攝即時防呆/quality_guard/backend
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```

2. 用 Xcode 打開 `PhotoQualityGuard/PhotoQualityGuard.xcodeproj`（double click 這個檔案）。
3. 上方 Scheme 選 `PhotoQualityGuard`，裝置選任一 iPhone Simulator（例如 iPhone 17）。
4. 按 ▶ Run（⌘R）。
5. 先把測試照片加進 Simulator 相簿（把 JPG 拖進 Simulator 視窗，或）：

   ```bash
   xcrun simctl addmedia booted "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率/沒有進行索賠/RCG2235左後 借.jpg"
   ```

6. App 內按「從相簿選擇」→ 選那張照片 → 自動送檢 → 應顯示「照片檢查通過」與車牌 RCG-2235。
   再點角度 chip「右前」→ 同一張自動重跑 → 應顯示「需要重新拍攝」（拍攝角度不符）。

## 實體 iPhone

Simulator 的 `127.0.0.1` 是 Mac；實體機的 `127.0.0.1` 是手機自己。二選一：

- 改 `PhotoQualityGuard/Services/AppConfig.swift` 的 `developmentBaseURL` 為 Mac 的區網 IP，例如 `http://192.168.1.23:8000`。
- 或在 Xcode Scheme → Run → Arguments → Environment Variables 加 `PQG_API_BASE_URL=http://192.168.1.23:8000`。

FastAPI 要用 `--host 0.0.0.0` 啟動；手機與 Mac 同一個 Wi-Fi。`Info.plist` 只開了 `NSAllowsLocalNetworking`（區網 HTTP），沒有 `NSAllowsArbitraryLoads`。

## 測試

```bash
cd 環節一_拍攝即時防呆/quality_guard/ios/PhotoQualityGuard
# 單元測試（後端有跑才會執行 live API 測試，否則自動 skip）
TEST_RUNNER_PQG_API_BASE_URL=http://127.0.0.1:8000 xcodebuild test \
  -project PhotoQualityGuard.xcodeproj -scheme PhotoQualityGuard \
  -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:PhotoQualityGuardTests
# UI 測試（先 addmedia，見上）
TEST_RUNNER_PQG_API_BASE_URL=http://127.0.0.1:8000 xcodebuild test \
  -project PhotoQualityGuard.xcodeproj -scheme PhotoQualityGuard \
  -destination 'platform=iOS Simulator,name=iPhone 17' -only-testing:PhotoQualityGuardUITests
```

## 結構

```
PhotoQualityGuard/
├── PhotoQualityGuardApp.swift
├── Info.plist                      相機／相簿／區網權限文案 + ATS 區網例外
├── Models/                         對應 backend schemas.py 的 Codable
│   ├── RequiredView.swift          rawValue = backend 中文值（左前/右前/左後/右後/前車內/後車內）
│   ├── PhotoQualityRequest.swift   nil 的 required_view 不會出現在 JSON
│   ├── StageResult.swift
│   └── PhotoQualityResponse.swift  含 DebugInfo、ViewProbability、ERROR hint 文案
├── Services/
│   ├── AppConfig.swift             API base URL（PQG_API_BASE_URL 可覆寫）
│   ├── PhotoQualityAPI.swift       URLSession + async/await，POST /api/photo-quality/check
│   └── ImagePreparation.swift      EXIF 轉正、JPEG、純 base64；不縮圖
├── ViewModels/PhotoQualityViewModel.swift   狀態機 idle/analyzing/result/failed + Task 取消
├── Views/
│   ├── PhotoCaptureView.swift      首頁
│   ├── PhotoPreviewView.swift      深色相機區、取景框、角度 pill
│   ├── AnalysisLoadingView.swift   loading overlay
│   ├── CameraPicker.swift          UIImagePickerController（Phase 3 才換 AVFoundation）
│   ├── ResultView.swift            PASS/FAIL 卡、API error 卡、技術細節
│   ├── StageResultCard.swift       三關卡片、車牌 hero、角度 hero、機率條
│   └── PlateOverlayImage.swift     bbox overlay（aspectFit + letterbox + orientation_rotation）
├── Components/                     AngleSelector、AppButton、StatusIcon、QualityScoreBadge、WarningPill
└── Theme/AppTheme.swift            色票、spacing、radius
```
