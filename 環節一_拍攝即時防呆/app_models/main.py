#!/usr/bin/env python3
"""
Detect a license plate from an original image and recognize its text.

The plate crop is passed to OCR in memory and is not saved to disk.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import cv2
from fast_plate_ocr import LicensePlateRecognizer
from ultralytics import YOLO


APP_MODELS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_MODELS_DIR.parent
DEFAULT_DETECT_MODEL = APP_MODELS_DIR / "detect" / "best.pt"
DEFAULT_OCR_ONNX_MODEL = APP_MODELS_DIR / "ocr" / "cct_s_v2_global.onnx"
DEFAULT_LOCAL_PLATE_CONFIG = APP_MODELS_DIR / "ocr" / "cct_s_v2_global_plate_config.yaml"
DEFAULT_REPO_PLATE_CONFIG = PROJECT_ROOT / "fast-plate-ocr" / "config" / "latin_plate_config_v2.yaml"
DEFAULT_PLATE_CONFIG = (
    DEFAULT_LOCAL_PLATE_CONFIG if DEFAULT_LOCAL_PLATE_CONFIG.exists() else DEFAULT_REPO_PLATE_CONFIG
)
FOUR_DIGITS_TWO_LETTERS_RE = re.compile(r"^(\d{4})([A-Z]{2})$")
THREE_LETTERS_FOUR_DIGITS_RE = re.compile(r"^([A-Z]{3})(\d{4})$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Detect a plate in an original image and print the recognized plate number.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Original image path.",
    )
    parser.add_argument(
        "--detect-model",
        type=Path,
        default=DEFAULT_DETECT_MODEL,
        help="YOLO license-plate detection model path.",
    )
    parser.add_argument(
        "--ocr-onnx-model",
        type=Path,
        default=DEFAULT_OCR_ONNX_MODEL,
        help="Local fast-plate-ocr ONNX model path.",
    )
    parser.add_argument(
        "--plate-config",
        type=Path,
        default=DEFAULT_PLATE_CONFIG,
        help="Plate config YAML matching the OCR ONNX model.",
    )
    parser.add_argument(
        "--ocr-model",
        default="cct-s-v2-global-model",
        help="Hub OCR model name used only when local ONNX/config files are unavailable.",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="YOLO confidence threshold.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="YOLO inference image size.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.08,
        help="Extra crop padding as a ratio of detected box width/height.",
    )
    parser.add_argument(
        "--detect-device",
        default=None,
        help="YOLO device, such as cpu, mps, or 0 for CUDA.",
    )
    parser.add_argument(
        "--ocr-device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
        help="OCR inference device.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Print all detected plate numbers, one per line. Default prints only the highest-confidence detection.",
    )
    return parser.parse_args()


def clamp(value: float, lower: int, upper: int) -> int:
    return max(lower, min(int(round(value)), upper))


def padded_xyxy(box, image_width: int, image_height: int, padding: float) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box.xyxy[0].tolist()
    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = box_width * padding
    pad_y = box_height * padding

    left = clamp(x1 - pad_x, 0, image_width - 1)
    top = clamp(y1 - pad_y, 0, image_height - 1)
    right = clamp(x2 + pad_x, left + 1, image_width)
    bottom = clamp(y2 + pad_y, top + 1, image_height)
    return left, top, right, bottom


def format_plate_number(plate: str) -> str:
    plate = plate.strip().upper()

    match = FOUR_DIGITS_TWO_LETTERS_RE.fullmatch(plate)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = THREE_LETTERS_FOUR_DIGITS_RE.fullmatch(plate)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    return plate


def create_recognizer(args: argparse.Namespace) -> LicensePlateRecognizer:
    if args.ocr_onnx_model.exists() and args.plate_config.exists():
        return LicensePlateRecognizer(
            device=args.ocr_device,
            onnx_model_path=args.ocr_onnx_model,
            plate_config_path=args.plate_config,
        )

    return LicensePlateRecognizer(args.ocr_model, device=args.ocr_device)


def detect_plate_crops(args: argparse.Namespace) -> list:
    if not args.source.exists():
        raise FileNotFoundError(f"Source image not found: {args.source}")
    if not args.detect_model.exists():
        raise FileNotFoundError(f"Detection model not found: {args.detect_model}")

    detector = YOLO(str(args.detect_model))
    results = detector.predict(
        source=str(args.source),
        conf=args.conf,
        imgsz=args.imgsz,
        device=args.detect_device,
        save=False,
        verbose=False,
    )
    if not results:
        return []

    result = results[0]
    image = result.orig_img
    boxes = result.boxes
    if image is None or boxes is None or len(boxes) == 0:
        return []

    height, width = image.shape[:2]
    sorted_boxes = sorted(boxes, key=lambda box: float(box.conf[0]), reverse=True)
    if not args.all:
        sorted_boxes = sorted_boxes[:1]

    crops = []
    for box in sorted_boxes:
        left, top, right, bottom = padded_xyxy(box, width, height, args.padding)
        crop_bgr = image[top:bottom, left:right]
        if crop_bgr.size == 0:
            continue
        crops.append(cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB))
    return crops


def main() -> int:
    args = parse_args()
    try:
        crops = detect_plate_crops(args)
        if not crops:
            print("No plate detected.", file=sys.stderr)
            return 2

        recognizer = create_recognizer(args)
        predictions = recognizer.run(crops, return_confidence=False)
        for prediction in predictions:
            if prediction.plate:
                print(format_plate_number(prediction.plate))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
