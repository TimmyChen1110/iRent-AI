#!/usr/bin/env python3
import argparse
from pathlib import Path

import cv2
from ultralytics import YOLO


def parse_args():
    parser = argparse.ArgumentParser(description="Crop license plates detected by YOLO.")
    parser.add_argument(
        "--model",
        default="best.pt",
        help="Path to the YOLO .pt model.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Image path, folder path, glob, video path, stream URL, or camera index such as 0.",
    )
    parser.add_argument(
        "--output",
        default="runs/plate_crops",
        help="Directory to save cropped plate images.",
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=0.25,
        help="Confidence threshold.",
    )
    parser.add_argument(
        "--imgsz",
        type=int,
        default=640,
        help="Inference image size.",
    )
    parser.add_argument(
        "--padding",
        type=float,
        default=0.08,
        help="Extra crop padding as a ratio of box width/height.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Inference device, such as cpu, mps, or 0 for CUDA GPU.",
    )
    parser.add_argument(
        "--half",
        action="store_true",
        help="Use FP16 inference when supported by the selected device.",
    )
    parser.add_argument(
        "--save-empty",
        action="store_true",
        help="Save a text file listing inputs where no plate was detected.",
    )
    return parser.parse_args()


def clamp(value, lower, upper):
    return max(lower, min(value, upper))


def padded_xyxy(box, image_width, image_height, padding):
    x1, y1, x2, y2 = box.xyxy[0].tolist()
    box_width = x2 - x1
    box_height = y2 - y1
    pad_x = box_width * padding
    pad_y = box_height * padding

    left = int(clamp(round(x1 - pad_x), 0, image_width - 1))
    top = int(clamp(round(y1 - pad_y), 0, image_height - 1))
    right = int(clamp(round(x2 + pad_x), left + 1, image_width))
    bottom = int(clamp(round(y2 + pad_y), top + 1, image_height))
    return left, top, right, bottom


def source_stem(result_path, fallback, frame_index):
    if result_path:
        path = Path(result_path)
        if path.name:
            return path.stem
    return f"{Path(str(fallback)).stem or 'frame'}_{frame_index:06d}"


def main():
    args = parse_args()
    model_path = Path(args.model)
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    model = YOLO(str(model_path))
    predict_kwargs = {
        "source": args.source,
        "conf": args.conf,
        "imgsz": args.imgsz,
        "device": args.device,
        "save": False,
        "stream": True,
        "verbose": False,
    }
    if args.half:
        predict_kwargs["half"] = True

    results = model.predict(**predict_kwargs)

    empty_sources = []
    total_crops = 0

    for frame_index, result in enumerate(results, start=1):
        image = result.orig_img
        if image is None:
            continue

        boxes = result.boxes
        source_name = Path(result.path).name if result.path else str(args.source)
        if boxes is None or len(boxes) == 0:
            print(f"{source_name}: 0 plate(s)")
            empty_sources.append(source_name)
            continue

        height, width = image.shape[:2]
        stem = source_stem(result.path, args.source, frame_index)
        saved_for_source = 0

        for plate_index, box in enumerate(boxes, start=1):
            left, top, right, bottom = padded_xyxy(box, width, height, args.padding)
            crop = image[top:bottom, left:right]
            if crop.size == 0:
                continue

            confidence = float(box.conf[0]) if box.conf is not None else 0.0
            crop_name = f"{stem}_plate{plate_index:02d}_conf{confidence:.3f}.jpg"
            crop_path = output_dir / crop_name
            cv2.imwrite(str(crop_path), crop)
            saved_for_source += 1
            total_crops += 1

        print(f"{source_name}: saved {saved_for_source} crop(s)")

    if args.save_empty and empty_sources:
        empty_path = output_dir / "no_plate_detected.txt"
        empty_path.write_text("\n".join(empty_sources) + "\n", encoding="utf-8")

    print(f"Done. Saved {total_crops} crop(s) to {output_dir}")


if __name__ == "__main__":
    main()
