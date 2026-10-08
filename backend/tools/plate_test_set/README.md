# 車牌辨識測試資料集（給 Stonk／外部驗證）

`manifest.json` 由 `backend/tools/build_plate_test_set.py` 產生：每張照片的路徑、SHA-256、預期車牌（資料集檔名）、拍攝角度，
以及用 **與 iOS App 相同的 Core ML 模型**（環節一 `app_models/coreml/PlateDetector.mlpackage` + `PlateOCR.mlpackage`，macOS CPU 執行）跑出的辨識結果。

- 不假設 Stonk 的 API 規格：manifest 是自描述 JSON，之後依對方格式轉換即可。
- 匯出圖片：`python3 backend/tools/build_plate_test_set.py --copy-images <資料夾>`（會把圖片複製過去並在 manifest 記 `exported_file`）。
- 只列照片、不跑模型：`--no-recognize`。

## 2026-10-09 實測摘要（35 張）

| 項目 | 數量 |
|---|---|
| 辨識出車牌文字 | 33 |
| 與預期一致 | 27 |
| 與預期不一致（OCR 讀錯／少字） | 4 |
| 未偵測到車牌／OCR 讀不出字 | 2 |
| 無預期標籤（`2.jpg`、`3.jpg`，Core ML 讀為 RDG-8571、RDR-6350，待人工確認） | 2 |

模擬車輛 RCG-2235 的 8 張（4 方位 × 借／還）：6 張正確辨識（信心 ≥ 0.99），`右前 還` 未偵測到車牌、`右後 借` 偵測到框但 OCR 讀不出字——
App 端對這兩種情況會要求重拍，或讓使用者手動輸入車牌（標記為需人工確認）。

> ⚠️ 資料集照片為比賽提供的 iRent 營運照片（車牌可見、非公開），只可在隊內／評審範圍使用。`環節一/app_models/1~3.jpg` 為環節一自備測試照。
