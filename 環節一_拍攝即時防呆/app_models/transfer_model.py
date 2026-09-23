#!/usr/bin/env python3
"""Convert the iRent plate detector and OCR models to Core ML."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


APP_MODELS = Path(__file__).resolve().parent
DEFAULT_OUTPUT = APP_MODELS / "coreml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export best.pt and cct_s_v2_global.onnx as .mlpackage files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory for the generated Core ML packages.",
    )
    parser.add_argument(
        "--skip-detector",
        action="store_true",
        help="Only convert the OCR model.",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Only convert the YOLO detector.",
    )
    return parser.parse_args()


def replace_package(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def export_detector(output: Path) -> None:
    from ultralytics import YOLO

    source_model = APP_MODELS / "detect" / "best.pt"
    destination = output / "PlateDetector.mlpackage"
    model = YOLO(str(source_model))
    exported_path = Path(model.export(format="coreml", imgsz=640, nms=True))
    replace_package(destination)
    exported_path.replace(destination)


def export_ocr(output: Path) -> None:
    import coremltools as ct
    import torch
    from torch import nn
    from onnx2torch import convert

    source_model = APP_MODELS / "ocr" / "cct_s_v2_global.onnx"
    destination = output / "PlateOCR.mlpackage"

    # Core ML image inputs are NCHW; the ONNX graph declares images as NHWC.
    onnx_model = convert(str(source_model)).eval()

    class NchwInputModel(nn.Module):
        def __init__(self, model: nn.Module):
            super().__init__()
            self.model = model

        def forward(self, image: torch.Tensor):
            return self.model(image.permute(0, 2, 3, 1))

    model = NchwInputModel(onnx_model).eval()
    sample = torch.rand(1, 3, 64, 128)
    traced_model = torch.jit.trace(model, sample, strict=False)
    converted_model = ct.convert(
        traced_model,
        inputs=[
            ct.ImageType(
                name="image",
                shape=sample.shape,
                scale=1.0 / 255.0,
                color_layout=ct.colorlayout.RGB,
            )
        ],
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.iOS16,
    )
    replace_package(destination)
    converted_model.save(str(destination))


def main() -> None:
    args = parse_args()
    if args.skip_detector and args.skip_ocr:
        raise ValueError("At least one of detector or OCR must be enabled.")

    args.output.mkdir(parents=True, exist_ok=True)
    if not args.skip_detector:
        export_detector(args.output)
    if not args.skip_ocr:
        export_ocr(args.output)
    print(f"Generated Core ML packages in {args.output}")


if __name__ == "__main__":
    main()