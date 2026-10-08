# License Plate Recognition App Models

This folder contains a local license-plate recognition pipeline:

1. Detect the license plate from an original image with YOLO.
2. Crop the detected plate in memory.
3. Recognize the plate text with fast-plate-ocr.
4. Print the plate number.

The main entry point is `main.py`.

## Folder Structure

```text
app_models/
  requirements.txt
  main.py
  detect/
    best.pt
    crop_plate.py
  ocr/
    cct_s_v2_global.onnx
    cct_s_v2_global_plate_config.yaml
    run_ocr.py
```

## Requirements

- Python 3.10 or newer
- macOS, Linux, or Windows
- Python packages listed in `requirements.txt`

## Setup

Run these commands from the project folder that contains `app_models`.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r app_models/requirements.txt
```

If the project already includes a prepared `.venv`, activate it instead:

```bash
source .venv/bin/activate
```

## Recognize From Original Image

Use `main.py` when the input is the original photo, not a cropped plate.

```bash
python app_models/main.py path/to/image.jpg
```

Example output:

```text
RDB-6729
```

Only the plate number is printed to stdout. The cropped plate image is passed to OCR in memory and is not saved to disk.

## Multiple Plates In One Image

By default, only the highest-confidence YOLO detection is recognized.

To print every detected plate, one plate per line:

```bash
python app_models/main.py path/to/image.jpg --all
```

## Useful Options

```bash
python app_models/main.py path/to/image.jpg --conf 0.25 --imgsz 640
```

- `--conf`: YOLO detection confidence threshold. Default is `0.25`.
- `--imgsz`: YOLO input image size. Default is `640`.
- `--padding`: extra crop padding around the detected plate. Default is `0.08`.
- `--detect-device`: YOLO device, for example `cpu`, `mps`, or `0`.
- `--ocr-device`: OCR device, one of `cpu`, `cuda`, or `auto`. Default is `cpu`.

Apple Silicon example:

```bash
python app_models/main.py path/to/image.jpg --detect-device mps --ocr-device cpu
```

## Test Detection Only

Use this if you only want to verify the YOLO crop result.

```bash
python app_models/detect/crop_plate.py \
  --source path/to/image.jpg \
  --model app_models/detect/best.pt \
  --output runs/plate_crops \
  --conf 0.25 \
  --imgsz 640
```

This command saves cropped plate images to `runs/plate_crops`.

## Test OCR Only

Use this if you already have cropped plate images.

```bash
python app_models/ocr/run_ocr.py runs/plate_crops \
  --onnx-model app_models/ocr/cct_s_v2_global.onnx \
  --plate-config app_models/ocr/cct_s_v2_global_plate_config.yaml \
  --device cpu
```

## Exit Behavior

- Success: prints plate number and exits with code `0`.
- No plate detected: prints `No plate detected.` to stderr and exits with code `2`.
- Runtime error: prints the error message to stderr and exits with code `1`.

## Notes For App Integration

- The current Python pipeline is intended for local validation and backend-style integration.
- For a mobile offline app, the same pipeline should be ported as:
  - mobile detector model
  - in-memory plate crop
  - mobile OCR runtime
  - plate text output
- Validate accuracy and latency on the target phone before release.

## Core ML 偵測驗證與照片方向

照片的儲存像素可能是橫向，但 EXIF 方向標記要求旋轉後才是正向。
OpenCV 讀取照片時通常會套用 EXIF；`UIImage.cgImage` 則不會自動套用
`UIImage.imageOrientation`。因此，相同檔案若直接把原始 `CGImage` 交給
Vision，模型實際看到的方向會與 Python 不同。

App 的 `OnDeviceRecognitionService` 會先依 `UIImage.imageOrientation`
旋轉／鏡像照片，再讓偵測、車牌裁切、OCR 與視角分類共用正向像素。
不能只替 Vision 傳入方向卻繼續裁切原始像素，否則車牌裁切座標會不一致。

在 macOS 上，從包含 `app_models` 的資料夾執行以下驗證。需要 Xcode
Command Line Tools，不需要 Python 的 Core ML 原生套件：

```bash
swift app_models/scripts/validate_coreml_detector.swift \
  app_models/coreml/PlateDetector.mlpackage \
  app_models/1.jpg
```

驗證程式會列印 EXIF 方向、正向圖片尺寸與信心分數。加入
`--ignore-orientation` 可重現忽略方向的結果；加入 `--cpu-only` 可比較 CPU。
對 `1.jpg`（EXIF=6），既有模型在忽略方向時無偵測，轉正後可偵測車牌，
信心約 0.89，門檻維持 0.25。這是 Mac 的偵測驗證，仍需在目標 iPhone
驗證完整辨識流程。

App 使用 Vision 物件偵測輸出，偵測模型應使用 `nms=True` 匯出。
直接 `torch.jit.trace`／`ct.convert` 的原始張量輸出需要另外實作解碼與 NMS，
不能直接替換目前的 Vision 偵測模型。

## Core ML 偵測＋OCR 測試

驗證程式支援 `--ocr`，會將最高信心的車牌框加上 8% padding，裁切正向照片，
再依 OCR 模型的輸入尺寸縮放。提供的 CCT OCR 使用 RGB 128×64，輸出為
10 個字元位置的機率；程式依設定中的字母表解碼並略過 `_`。

```bash
swift app_models/scripts/validate_coreml_detector.swift \
  app_models/coreml/PlateDetector.mlpackage \
  app_models/1.jpg \
  --ocr app_models/coreml/PlateOCR.mlpackage \
  --expect-plate RCG-2235 \
  --save-crop /tmp/plate_crop.png
```

- `--ocr`：指定 Core ML OCR 模型，支援 `.mlpackage` 或 `.mlmodelc`。
- `--expect-plate`：可選，驗證文字是否符合預期，忽略大小寫與連字號。
- `--save-crop`：可選，儲存裁切 PNG 供檢查；不會自動建立父資料夾。
- `--cpu-only`：可選，偵測與 OCR 都只用 CPU。

換成其他照片時，移除 `--expect-plate` 或改成該張照片的正確車牌。
`1.jpg` 的修正版 Core ML OCR 實測輸出 `RCG-2235`，與同一裁切圖的 ONNX
結果一致。測試程式列印的 OCR 信心是非 padding 字元機率的平均值。

OCR ONNX 圖內已包含除以 255 的正規化，所以 OCR 匯出的 `ImageType`
必須使用 `scale=1.0`。原本額外設定 `scale=1/255` 會重複正規化，導致 OCR
無法辨識；`transfer_model.py` 已修正，`scripts/export_coreml.py` 共用此匯出函式。
既有的舊 OCR 套件需要重新匯出。只重新匯出 OCR：

```bash
python app_models/transfer_model.py --skip-detector --skip-view
```
