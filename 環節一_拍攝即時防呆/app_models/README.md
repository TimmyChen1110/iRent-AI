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
