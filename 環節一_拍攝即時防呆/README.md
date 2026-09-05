# 環節一：拍攝端即時防呆介入

> 目標：在用戶透過 iRent App 上傳照片的**當下**，即時判斷照片品質——有沒有拍對位置、模糊、未拍攝到車牌、拍攝角度不對、太遠太近、太髒等。

## 狀態：兩條 prototype 各自開發中，尚未整合

- **`quality_guard/`**：拍照即時防呆 API（FastAPI，模糊/亮度/構圖/車牌位置檢查），車牌偵測目前用傳統 CV + Tesseract，文字辨識精確率待改善。細節見 [quality_guard/backend/README.md](quality_guard/backend/README.md)。
- **`app_models/`**：YOLO 車牌偵測 + fast-plate-ocr 辨識 pipeline，準確度預期優於 `quality_guard` 目前的車牌 OCR。細節見 [app_models/README.md](app_models/README.md)。

兩者尚未接線——後續整合方向可能是把 `quality_guard/backend/app/checks/plate.py` 換成呼叫 `app_models` 的偵測/辨識模型。

## 原規劃背景（環節二實測數據證明其必要性）

環節二對真實營運照片的實測，量化了「不防呆」的代價：

| 實測發現 | 數據 | 來源 |
|---|---|---|
| 後方照片漏拍率 | 左後 24.6%／右後 29.9% | 上傳清單 27,367 筆分析 |
| EXIF 方向錯置 | 76% 照片帶未套用的旋轉標記 | 282 張照片檢查 |
| 拍錯側／未覆蓋損傷部位 | 141 組重標中 3 組因此無法比對，且為僅有的漏抓來源 | relabels.json |
| 分類錯置 | 車內照欄位混入車外照（官方欄位自註「常有誤」） | 車內照抽樣實測 |

**結論：環節二辨識系統的極限不在模型，而在照片品質——防呆前移到拍攝端是整條 pipeline 的治本之道。**

## 可直接沿用的既有資產（來自環節二 pipeline）

- **EXIF 方向轉正 + 模糊/曝光檢核**：`環節二/pipeline/run_eval_gemini.py` 的 `prep_image()` 與 cv_prefilter 的 Laplacian 模糊度檢測，可直接移植 App 端
- **角度/方位校驗**：VLM 判定 `angle_match` 的 prompt 邏輯（「這張是不是左前方？」），可改為拍攝當下的即時檢核
- **車牌偵測**：照片中車牌是否入鏡、是否可辨識

## 設計方向

1. **端側輕量檢核**（不需網路）：模糊度、曝光、方向——拍完 0.1 秒內提示重拍
2. **雲端快速校驗**（Flash 級 VLM，單張 <2 秒）：方位正確性、車牌入鏡、距離適中、覆蓋完整
3. **UI 引導**：取景框疊加車輛輪廓引導線；不合格即時跳提示「請退後一步重拍左後方」，而非事後才發現無圖可比
