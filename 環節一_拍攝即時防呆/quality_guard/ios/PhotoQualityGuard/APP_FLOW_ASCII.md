# PhotoQualityGuard App 流程與程式碼對照

> 範圍：本文件說明 iOS SwiftUI 客戶端。後端的實際模型實作不在此 Xcode 專案內；iOS 端會把照片送至 FastAPI，並依 API 回傳的三個關卡結果呈現畫面。

```text
+---------------------------------------------------------------+
| 1. App 啟動                                                   |
|    PhotoQualityGuardApp                                       |
|    WindowGroup -> PhotoCaptureView()                          |
+-------------------------------+-------------------------------+
                                |
                                v
+---------------------------------------------------------------+
| 2. 首頁：PhotoCaptureView                                     |
|    [拍攝角度 chips] [照片預覽] [開啟相機] [從相簿選擇] [清除] |
|                                                               |
|    初始狀態：AnalysisState.idle                               |
|    預覽區顯示「拍攝車況照片」引導                             |
+-------------------------------+-------------------------------+
                                |
            +-------------------+--------------------+
            |                                        |
            v                                        v
+--------------------------+          +--------------------------+
| 選擇拍攝角度             |          | 選擇照片來源             |
| 不指定 / 左前 / 右前 ... |          | 相機 / 相簿              |
+------------+-------------+          +------------+-------------+
             |                                     |
             v                                     v
+--------------------------+          +--------------------------+
| model.select(view:)      |          | CameraPicker             |
| - 記錄 requiredView      |          | UIImagePickerController  |
| - 若已有照片，自動重跑   |          +------------+-------------+
+--------------------------+                       |
                                        或          |
                                                     v
                                      +--------------------------+
                                      | PhotosPicker             |
                                      | 讀取 PhotosPickerItem    |
                                      +------------+-------------+
                                                   |
                                                   v
                                      +--------------------------+
                                      | model.didPick(image:)    |
                                      | - 取消舊 Task            |
                                      | - generation + 1         |
                                      +------------+-------------+
                                                   |
                                                   v
+---------------------------------------------------------------+
| 3. 背景圖片準備：ImagePreparation.prepare(image)              |
|    - 將 EXIF 方向真正畫入像素，輸出正立 UIImage               |
|    - HEIC／其他圖片重新編碼為 JPEG                            |
|    - 不縮圖，保留輸出 JPEG 的完整像素尺寸                     |
|    - JPEG -> 純 Base64（無 data:image 前綴）                  |
+-------------------------------+-------------------------------+
                                |
                    +-----------+-----------+
                    |                       |
                  失敗 v                       v 成功
+---------------------------+    +--------------------------------+
| 顯示「這張照片無法讀取」 |    | AnalysisState.analyzing(photo) |
+---------------------------+    | 預覽區覆蓋 Loading 畫面       |
                                 +---------------+----------------+
                                                 |
                                                 v
+---------------------------------------------------------------+
| 4. 呼叫後端                                                   |
|    POST {baseURL}/api/photo-quality/check                     |
|    Content-Type: application/json                             |
|                                                               |
|    Payload:                                                    |
|    {                                                          |
|      "image_base64": "<JPEG base64>",                       |
|      "required_view": "左前"  // 僅使用者有指定時才送出     |
|    }                                                          |
|                                                               |
|    預設開發網址：http://127.0.0.1:8000                        |
|    實機可用環境變數 PQG_API_BASE_URL 改為 Mac 區網 IP         |
+-------------------------------+-------------------------------+
                                |
                                v
+---------------------------------------------------------------+
| 5. 後端回傳的檢查關卡（iOS 根據回傳資料顯示）                 |
|                                                               |
|  readability -> plate -> view                                 |
|  基本可讀性      車牌辨識    拍攝角度                         |
|  - 有效圖片      - 車牌位置  - 偵測角度                       |
|  - 解析度        - OCR 文字  - 與 required_view 比對          |
|  - 模糊/明暗     - 過遠過近  - 回傳各角度機率                 |
|                                                               |
|  某關失敗時，後續關卡可被標記為 skipped。                     |
+-------------------------------+-------------------------------+
                                |
          +---------------------+---------------------+
          |                                           |
          v                                           v
+-------------------------------+       +-------------------------------+
| HTTP 2xx 且 JSON 解碼成功     |       | 逾時、斷線、非 2xx、JSON 解碼失敗 |
| state = result(photo,response)|       | state = failed(photo,failure) |
+---------------+---------------+       +---------------+---------------+
                |                                       |
                v                                       v
+-------------------------------+       +-------------------------------+
| 6A. ResultView                |       | 6B. AnalysisFailureView       |
| - 通過 / 需要重新拍攝         |       | - 顯示連線失敗提示             |
| - 品質分數                     |       | - 重新檢查 -> model.retry()   |
| - 三關結果 StageResultCard     |       | - 重新拍攝                     |
| - 車牌、bbox 框、角度與機率    |       | - 可展開 API/HTTP 錯誤細節    |
| - 重新拍攝 / 更換拍攝角度      |       +-------------------------------+
+-------------------------------+
```

## 狀態機與避免舊結果覆蓋

```text
AnalysisState

  idle
    |
    | didPick(image)
    v
  analyzing(PreparedPhoto)
    |                 |
    | API 成功         | API 失敗
    v                 v
  result(photo, response)     failed(photo, failure)

任何時候使用者：選新照片 / 改角度重跑 / 清除
    |
    v
cancelInFlight() + generation += 1
    |
    v
舊 Task 即使晚回傳，也因 generation 不同而不能更新 UI。
```

## 流程節點與程式碼對照

```text
流程節點                         對應檔案                                      關鍵型別 / 方法
-------------------------------  --------------------------------------------  ----------------------------------------------
App 進入點                       PhotoQualityGuard/PhotoQualityGuardApp.swift PhotoQualityGuardApp.body
首頁與畫面分流                   PhotoQualityGuard/Views/PhotoCaptureView.swift PhotoCaptureView.body / resultSection
拍攝角度選擇                     PhotoQualityGuard/Components/AngleSelector.swift AngleSelector / onSelect
角度資料與 API 值                PhotoQualityGuard/Models/RequiredView.swift  RequiredView.rawValue / isExterior
系統相機                         PhotoQualityGuard/Views/CameraPicker.swift   CameraPicker / didFinishPickingMediaWithInfo
系統相簿                         PhotoQualityGuard/Views/PhotoCaptureView.swift photosPicker / loadPickedPhoto(_:)
照片預覽與分析中遮罩             PhotoQualityGuard/Views/PhotoPreviewView.swift PhotoPreviewView
                                  PhotoQualityGuard/Views/AnalysisLoadingView.swift AnalysisLoadingView
ViewModel 狀態與使用者操作       PhotoQualityGuard/ViewModels/PhotoQualityViewModel.swift
                                                                            AnalysisState / didPick / select / retry / reset
圖片正規化、JPEG、Base64          PhotoQualityGuard/Services/ImagePreparation.swift ImagePreparation.prepare(_:)
API 基底網址與 60 秒逾時          PhotoQualityGuard/Services/AppConfig.swift   AppConfig.apiBaseURL / requestTimeout
HTTP POST 與錯誤分類              PhotoQualityGuard/Services/PhotoQualityAPI.swift PhotoQualityAPI.check(_:)
請求 JSON                        PhotoQualityGuard/Models/PhotoQualityRequest.swift PhotoQualityRequest
回應 JSON                        PhotoQualityGuard/Models/PhotoQualityResponse.swift PhotoQualityResponse / DebugInfo
三關結果資料                     PhotoQualityGuard/Models/StageResult.swift   StageResult / StageStatus
成功結果總畫面                   PhotoQualityGuard/Views/ResultView.swift     ResultView
每關卡片與使用者提示              PhotoQualityGuard/Views/StageResultCard.swift StageResultCard
車牌 bbox 疊圖                   PhotoQualityGuard/Views/PlateOverlayImage.swift PlateOverlayImage / PlateBoxGeometry
API 失敗畫面                     PhotoQualityGuard/Views/ResultView.swift     AnalysisFailureView
相機、相簿、本地網路權限          PhotoQualityGuard/Info.plist                 NSCameraUsageDescription 等
```

## 回應資料如何對應到 UI

```text
後端欄位                          iOS 顯示位置
-------------------------------  -------------------------------------------------
passed / quality_score            ResultView：總結、品質分數 badge
stages[]                          ResultView -> StageResultCard（三張關卡卡片）
stages[].errors                   StageResultCard：紅色錯誤與重拍提示
plate_text / plate_confidence     「辨識到車牌」與 OCR 信心值
debug.plate_bbox                  PlateOverlayImage：在原照片畫車牌框
detected_view / view_confidence   「判定角度」與信心值
debug.view_probabilities          ProbabilityBars：各拍攝角度機率條
debug.blur_score / brightness     TechnicalDetailsView（預設收合）
debug.elapsed_ms                  TechnicalDetailsView：後端處理耗時
```

## 目前功能邊界

```text
已實作：拍照或選相簿 -> 單張照片上傳 -> 等待後端 -> 顯示品質結果。

尚未實作：AVFoundation 相機即時預覽、逐幀即時推論、完全離線的 iPhone 端模型推論。
```
