# iRent 智能車況管家 - 第一階段建置方案

## 1. 專題聚焦

本階段聚焦於 iRent 租還車流程中的「即時反饋」與「拍照防呆」。

目標是在使用者拍照或上傳照片的當下，即時判斷照片是否符合後續 AI 判讀與營運審核需求，避免不合格照片進入後台流程。

主要要解決的問題包含：

- 照片模糊
- 未拍到車牌
- 拍攝角度錯誤
- 距離太遠或太近
- 拍錯車輛位置
- 車輛未完整入鏡
- 照片太暗或過曝
- 車牌或車身被遮擋

## 2. 核心目標

建立一個 `Photo Quality Guard`，在使用者拍照或上傳前完成照片品質檢查，並提供明確的重拍提示。

使用者流程：

```text
開啟拍照頁
-> 系統顯示指定拍攝角度
-> 使用者拍照
-> AI 即時檢查照片品質
-> 合格：允許送出
-> 不合格：顯示具體原因與重拍指引
```

## 3. 第一階段檢查項目

| 檢查項目 | 判斷方式 | 建議技術 |
|---|---|---|
| 照片模糊 | Laplacian variance 模糊分數 | OpenCV |
| 太暗或過曝 | 平均亮度、亮度直方圖、過曝比例 | OpenCV |
| 車輛是否入鏡 | 偵測車輛 bounding box | YOLO |
| 車牌是否出現 | 偵測車牌 bounding box | YOLO / OpenCV |
| 車牌是否可讀 | OCR 信心分數、車牌格式檢查 | Tesseract / EasyOCR / PaddleOCR |
| 拍攝距離是否合理 | 車輛或車牌 bbox 面積比例 | OpenCV |
| 角度是否正確 | 視角分類，例如 front / rear / side / interior | Image classifier / CLIP |
| 是否拍錯位置 | 比對 required_view 與 detected_view | Rule engine |
| 是否裁切或遮擋 | bbox 是否貼邊、車牌是否完整 | OpenCV |

## 4. 建議系統架構

```text
Mobile App / Web App
    |
    | 拍照 preview / 上傳照片
    v
Photo Quality Guard API
    |
    |-- Basic Quality Check
    |     |-- blur check
    |     |-- brightness check
    |     |-- resolution check
    |
    |-- Vehicle Detection
    |     |-- detect car
    |     |-- check car size / position
    |
    |-- Plate Detection
    |     |-- detect license plate bbox
    |     |-- OCR plate text
    |     |-- check OCR confidence
    |
    |-- Viewpoint Validation
    |     |-- front / rear / left / right / interior
    |     |-- compare with required step
    |
    |-- Rule Engine
          |-- produce pass / fail
          |-- produce user-facing hint
```

## 5. MVP 功能範圍

第一版建議優先完成以下 5 個功能：

### 5.1 模糊檢查

使用 OpenCV 計算 Laplacian variance。

```python
blur_score = cv2.Laplacian(gray, cv2.CV_64F).var()
```

若分數低於門檻，判斷為照片模糊。

使用者提示：

```text
照片模糊，請穩定手機後重新拍攝
```

### 5.2 亮度檢查

檢查照片是否太暗或過曝。

可使用：

- 平均亮度
- 亮度標準差
- 過暗像素比例
- 過曝像素比例

使用者提示：

```text
照片太暗，請移到光線較充足處重新拍攝
```

或：

```text
照片過曝，請避開強光反射後重新拍攝
```

### 5.3 車牌偵測

檢查照片中是否出現車牌。

Prototype 階段可使用：

- OpenCV 影像處理
- Tesseract OCR

正式版本建議使用：

- YOLO 車牌偵測模型
- OCR 模型輔助確認車牌文字

使用者提示：

```text
未偵測到車牌，請讓車牌完整入鏡
```

### 5.4 車輛是否入鏡

使用物件偵測模型確認畫面中是否有車輛。

判斷條件：

- 是否偵測到車輛
- 車輛 bbox 是否太小
- 車輛 bbox 是否貼近畫面邊界
- 車輛是否被裁切

使用者提示：

```text
未偵測到車輛，請對準車輛重新拍攝
```

或：

```text
車輛未完整入鏡，請退後一點重新拍攝
```

### 5.5 拍攝角度防呆

每個拍攝步驟應指定 `required_view`。

例如：

```text
front
rear
left
right
interior
```

系統需判斷使用者實際拍攝角度 `detected_view` 是否符合指定步驟。

若不符合，阻擋送出並提示重拍。

使用者提示：

```text
拍攝角度不正確，請拍攝車頭正面
```

## 6. API 設計

### 6.1 照片品質檢查 API

```http
POST /api/photo-quality/check
```

Request：

```json
{
  "rental_id": "R123456",
  "car_id": "ABC-1234",
  "required_view": "front",
  "image_base64": "..."
}
```

Response：

```json
{
  "passed": false,
  "quality_score": 0.62,
  "required_view": "front",
  "detected_view": "front",
  "plate_text": null,
  "errors": [
    {
      "code": "PLATE_NOT_FOUND",
      "message": "未偵測到車牌，請靠近車頭並讓車牌完整入鏡"
    },
    {
      "code": "IMAGE_BLURRY",
      "message": "照片模糊，請穩定手機後重新拍攝"
    }
  ],
  "debug": {
    "blur_score": 83.2,
    "brightness_score": 0.71,
    "vehicle_bbox": [20, 40, 310, 210],
    "plate_bbox": null
  }
}
```

## 7. 判斷規則設計

### 7.1 模糊

```text
if blur_score < blur_threshold:
    fail IMAGE_BLURRY
```

提示：

```text
照片模糊，請重新拍攝
```

### 7.2 未偵測到車輛

```text
if vehicle_bbox is None:
    fail VEHICLE_NOT_FOUND
```

提示：

```text
未偵測到車輛，請對準車輛拍攝
```

### 7.3 未偵測到車牌

```text
if required_view in ["front", "rear"] and plate_bbox is None:
    fail PLATE_NOT_FOUND
```

提示：

```text
未拍到車牌，請讓車牌完整入鏡
```

### 7.4 距離太遠

```text
if vehicle_bbox_area_ratio < min_vehicle_area_ratio:
    fail TOO_FAR
```

提示：

```text
距離太遠，請靠近一點
```

### 7.5 距離太近

```text
if vehicle_bbox touches image boundary:
    fail TOO_CLOSE_OR_CROPPED
```

提示：

```text
距離太近，請退後一點，讓車輛完整入鏡
```

### 7.6 拍攝角度錯誤

```text
if detected_view != required_view:
    fail WRONG_VIEW
```

提示：

```text
拍攝角度不正確，請依照畫面指示重新拍攝
```

## 8. 技術選型

### 8.1 Prototype

適合黑客松初期快速驗證。

```text
Python
OpenCV
Tesseract / pytesseract
FastAPI
```

### 8.2 正式版本

適合提高辨識穩定性與擴充後續車損、髒污判斷。

```text
YOLOv8 / YOLOv11：車輛與車牌偵測
OpenCV：模糊、亮度、裁切、角度分析
OCR：Tesseract / EasyOCR / PaddleOCR
FastAPI：AI 檢查服務
PostgreSQL：檢查紀錄與結果儲存
S3 / GCS：照片儲存
React Native / Flutter：App 端即時提示
```

## 9. 資料與標註計畫

### 9.1 需要收集的照片類型

- 合格車頭照
- 合格車尾照
- 合格左側照
- 合格右側照
- 合格車內照
- 模糊照
- 太暗照
- 過曝照
- 太近照
- 太遠照
- 未拍到車牌照
- 角度錯誤照
- 車輛被裁切照
- 車牌被遮擋照

### 9.2 標註欄位

```json
{
  "image_id": "001.jpg",
  "required_view": "front",
  "is_valid": false,
  "failure_reasons": ["BLURRY", "PLATE_NOT_FOUND"],
  "vehicle_bbox": [20, 40, 310, 210],
  "plate_bbox": null,
  "plate_text": "ABC-1234"
}
```

## 10. 建置時程

### 第 1 週：Prototype

- 建立 OpenCV 品質檢查
- 完成模糊、亮度、解析度判斷
- 串接 Tesseract OCR
- 建立單張圖片檢查 API
- 輸出 pass / fail 與錯誤原因

### 第 2 週：車輛與車牌偵測

- 導入 YOLO 車輛偵測
- 導入車牌偵測模型
- 建立 bbox 與距離判斷規則
- 輸出 bounding box debug 圖

### 第 3 週：拍攝角度防呆

- 建立 front / rear / side / interior 分類器
- 加入 `required_view` 驗證
- 設計 App 端錯誤提示文案
- 串接前端拍照流程

### 第 4 週：Demo 與成效驗證

- 建立測試資料集
- 統計 pass / fail 準確率
- 計算誤擋率與漏放率
- 完成前端 demo 流程
- 準備黑客松展示用案例

## 11. 評估指標

| 指標 | 目標 |
|---|---|
| 模糊照片攔截率 | > 90% |
| 未拍到車牌攔截率 | > 90% |
| 角度錯誤攔截率 | > 85% |
| 合格照片誤擋率 | < 10% |
| 單張照片判斷時間 | < 1 秒 |
| 使用者重拍成功率 | > 80% |
| 後台人工審核量 | 降低 30% 以上 |

## 12. Demo 呈現重點

Demo 可以設計成一個拍照檢查畫面。

畫面包含：

- 即時車輛框線
- 即時車牌框線
- 照片品質分數
- 合格 / 不合格結果
- 錯誤原因
- 重拍提示

提示範例：

```text
請靠近一點
請將車牌置中
照片模糊，請重新拍攝
拍攝角度錯誤，請拍攝車頭正面
車輛未完整入鏡，請退後一點
```

## 13. 第一階段交付物

- `Photo Quality Guard` 架構圖
- 照片品質檢查 API
- OpenCV 基礎品質檢查模組
- 車輛與車牌偵測 prototype
- 拍攝角度防呆規則
- 前端即時提示 demo
- 測試資料集與評估報告

## 14. 後續擴充方向

第一階段完成後，可接續文件中的第二、第三環節：

- 車身新車損偵測
- 車內整潔程度分類
- 異常預警分級
- 客服與營運後台通知
- 車輛清潔與整備派工流程
- 租還車照片與歷史車況比對
