#!/usr/bin/env python3
"""Export iRent's on-device models as the Core ML resources expected by iRentUserApp.

Run inside a dedicated Python environment on macOS. This script intentionally
does not change source models. It writes:
  frontend-user/iRentUserApp/Models/PlateDetector.mlpackage
  frontend-user/iRentUserApp/Models/PlateOCR.mlpackage
  frontend-user/iRentUserApp/Models/ViewClassifier.mlpackage

The iOS target must add the generated packages as resources. Before release run
the companion benchmark script on the same held-out photos used by Python.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
APP_MODELS = ROOT / "環節一_拍攝即時防呆" / "app_models"
QUALITY_BACKEND = ROOT / "環節一_拍攝即時防呆" / "quality_guard" / "backend"
DEFAULT_OUTPUT = ROOT / "frontend-user" / "iRentUserApp" / "Models"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-ocr", action="store_true")
    return parser.parse_args()


def export_detector(output: Path) -> None:
    from ultralytics import YOLO

    # nms=True is essential: Vision must receive VNRecognizedObjectObservation,
    # not raw YOLO tensors. The Swift app uses the top confidence result.
    model = YOLO(APP_MODELS / "detect" / "best.pt")
    result = model.export(format="coreml", imgsz=640, nms=True)
    source = Path(result)
    destination = output / "PlateDetector.mlpackage"
    if destination.exists():
        import shutil
        shutil.rmtree(destination)
    source.replace(destination)


def export_ocr(output: Path) -> None:
    """Convert the supplied ONNX OCR model through a traced PyTorch graph.

    coremltools does not guarantee direct ONNX conversion for every graph.
    onnx2torch keeps this step explicit and fails loudly on unsupported ops,
    rather than producing a silently altered OCR model.
    """
    import coremltools as ct
    import torch
    from onnx2torch import convert

    onnx_path = APP_MODELS / "ocr" / "cct_s_v2_global.onnx"
    model = convert(str(onnx_path)).eval()
    sample = torch.rand(1, 3, 64, 128)
    traced = torch.jit.trace(model, sample)
    converted = ct.convert(
        traced,
        inputs=[ct.ImageType(name="image", shape=sample.shape, scale=1 / 255.0)],
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.iOS18,
        compute_precision=ct.precision.FLOAT16,
    )
    converted.save(output / "PlateOCR.mlpackage")


def export_view_classifier(output: Path) -> None:
    import coremltools as ct
    import torch
    from torch import nn
    from torchvision import models

    checkpoint = torch.load(
        QUALITY_BACKEND / "app" / "models" / "view_classifier.pt",
        map_location="cpu",
        weights_only=True,
    )
    classes = list(checkpoint["classes"])
    if classes != ["左前", "右前", "左後", "右後"]:
        raise ValueError(f"Unexpected view-class order: {classes}")

    model = models.mobilenet_v2(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    class NormalizedClassifier(nn.Module):
        def __init__(self, classifier, mean, std):
            super().__init__()
            self.classifier = classifier
            self.register_buffer("mean", torch.tensor(mean).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor(std).view(1, 3, 1, 1))

        def forward(self, image):
            return self.classifier((image - self.mean) / self.std)

    # The Swift runtime reproduces the checkpoint's letterbox + normalization;
    # this model receives the same normalized 224×224 tensor.
    normalized_model = NormalizedClassifier(
        model, checkpoint["normalize_mean"], checkpoint["normalize_std"]
    ).eval()
    traced = torch.jit.trace(normalized_model, torch.rand(1, 3, 224, 224))
    converted = ct.convert(
        traced,
        inputs=[ct.ImageType(name="image", shape=(1, 3, 224, 224), scale=1 / 255.0)],
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.iOS18,
        compute_precision=ct.precision.FLOAT16,
    )
    converted.save(output / "ViewClassifier.mlpackage")


def main() -> None:
    args = parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    export_detector(args.output)
    if not args.skip_ocr:
        export_ocr(args.output)
    export_view_classifier(args.output)
    print(f"Generated Core ML packages in {args.output}")


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError as error:
        sys.exit(
            f"Missing conversion dependency: {error.name}. Install "
            "ultralytics, torch, torchvision, coremltools and onnx2torch first."
        )
