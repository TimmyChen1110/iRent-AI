#!/usr/bin/env python3
"""
Run fast-plate-ocr on cropped license-plate images.

Examples:
  python run_ocr.py test/assets/test_plate_1.png
  python run_ocr.py runs/plate_crops --model cct-xs-v2-global-model
  python run_ocr.py plate.jpg --onnx-model model.onnx --plate-config plate_config.yaml
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from fast_plate_ocr import LicensePlateRecognizer, PlatePrediction


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recognize text from cropped license-plate images.",
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Cropped plate image, or a folder containing cropped plate images.",
    )
    parser.add_argument(
        "--model",
        default="cct-s-v2-global-model",
        help="Hub OCR model name. Ignored when --onnx-model and --plate-config are provided.",
    )
    parser.add_argument(
        "--onnx-model",
        type=Path,
        help="Path to a custom exported ONNX OCR model.",
    )
    parser.add_argument(
        "--plate-config",
        type=Path,
        help="Path to the matching plate_config.yaml for --onnx-model.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
        help="Inference device. Use cpu on Mac unless you have a supported ONNX CUDA setup.",
    )
    parser.add_argument(
        "--no-confidence",
        action="store_true",
        help="Hide character confidence output.",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        help="Optional CSV path for batch results.",
    )
    return parser.parse_args()


def collect_images(source: Path) -> list[Path]:
    if source.is_file():
        if source.suffix.lower() not in IMAGE_EXTENSIONS:
            raise ValueError(f"Unsupported image extension: {source.suffix}")
        return [source]

    if not source.is_dir():
        raise FileNotFoundError(f"Source not found: {source}")

    images = sorted(
        path
        for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )
    if not images:
        raise FileNotFoundError(f"No supported images found in: {source}")
    return images


def create_recognizer(args: argparse.Namespace) -> LicensePlateRecognizer:
    if args.onnx_model or args.plate_config:
        if not args.onnx_model or not args.plate_config:
            raise ValueError("Use --onnx-model and --plate-config together.")
        return LicensePlateRecognizer(
            device=args.device,
            onnx_model_path=args.onnx_model,
            plate_config_path=args.plate_config,
        )

    return LicensePlateRecognizer(args.model, device=args.device)


def confidence_text(prediction: PlatePrediction) -> str:
    if prediction.char_probs is None:
        return ""
    return ",".join(f"{prob:.3f}" for prob in prediction.char_probs.tolist())


def print_result(path: Path, prediction: PlatePrediction, show_confidence: bool) -> None:
    parts = [f"{path}: {prediction.plate}"]
    if prediction.region:
        parts.append(f"region={prediction.region}")
    if show_confidence and prediction.char_probs is not None:
        avg_conf = float(prediction.char_probs.mean())
        parts.append(f"avg_conf={avg_conf:.3f}")
        parts.append(f"char_conf=[{confidence_text(prediction)}]")
    print(" | ".join(parts))


def write_csv(path: Path, rows: list[tuple[Path, PlatePrediction]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(["image", "plate", "region", "region_prob", "char_probs"])
        for image_path, prediction in rows:
            writer.writerow(
                [
                    str(image_path),
                    prediction.plate,
                    prediction.region or "",
                    "" if prediction.region_prob is None else f"{prediction.region_prob:.6f}",
                    confidence_text(prediction),
                ]
            )


def main() -> None:
    args = parse_args()
    images = collect_images(args.source)
    recognizer = create_recognizer(args)
    show_confidence = not args.no_confidence

    predictions = recognizer.run(
        [str(path) for path in images],
        return_confidence=show_confidence,
    )
    rows = list(zip(images, predictions, strict=True))

    for image_path, prediction in rows:
        print_result(image_path, prediction, show_confidence)

    if args.output_csv:
        write_csv(args.output_csv, rows)
        print(f"CSV saved: {args.output_csv}")


if __name__ == "__main__":
    main()
