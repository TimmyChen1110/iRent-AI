#!/usr/bin/env python3
"""Convert the iRent plate detector, OCR, and view classifier models to Core ML."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

APP_MODELS = Path(__file__).resolve().parent
QUALITY_BACKEND = APP_MODELS.parent / "quality_guard" / "backend"
DEFAULT_OUTPUT = APP_MODELS / "coreml"
VIEW_CLASS_ORDER = ["左前", "右前", "左後", "右後"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export best.pt, cct_s_v2_global.onnx, and view_classifier.pt to Core ML.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output directory for the generated Core ML packages.",
    )
    parser.add_argument("--skip-detector", action="store_true", help="Only convert OCR and view.")
    parser.add_argument("--skip-ocr", action="store_true", help="Only convert YOLO detector.")
    parser.add_argument("--skip-view", action="store_true", help="Skip the view classifier.")
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

    print("--> 匯出 PlateDetector (YOLO)...")
    model = YOLO(str(source_model))
    
    # 使用 ultralytics 匯出 (先嘗試更新後的標準導出)
    exported_path = Path(model.export(format="coreml", imgsz=640, nms=True))
    replace_package(destination)
    exported_path.replace(destination)
    print(f"PlateDetector 匯出完成: {destination}")


def export_ocr(output: Path) -> None:
    import coremltools as ct
    import torch
    from torch import nn
    from onnx2torch import convert

    source_model = APP_MODELS / "ocr" / "cct_s_v2_global.onnx"
    destination = output / "PlateOCR.mlpackage"

    print("--> 匯出 PlateOCR (CCT)...")
    # Core ML image inputs are NCHW; the ONNX graph declares images as NHWC.
    onnx_model = convert(str(source_model)).eval()

    class NchwInputModel(nn.Module):
        def __init__(self, model: nn.Module):
            super().__init__()
            self.model = model

        def forward(self, image: torch.Tensor):
            return self.model(image.permute(0, 2, 3, 1))

    model = NchwInputModel(onnx_model).eval()
    
    # fast-plate-ocr 的形狀: (Batch=1, C=3, H=64, W=128)
    # ONNX already divides uint8 RGB pixels by 255; preserve [0,255] here.
    sample = torch.randint(0, 256, (1, 3, 64, 128)).float()
    traced_model = torch.jit.trace(model, sample, strict=False)
    
    converted_model = ct.convert(
        traced_model,
        inputs=[
            # cct_s_v2_global.onnx 的圖內已含 rescaling(×1/255)，輸入是 0–255 的 uint8；
            # 這裡絕不能再給 scale=1/255，否則模型看到的是全黑影像、每個字槽都輸出 pad。
            ct.ImageType(
                name="image",
                shape=sample.shape,
                scale=1.0,
                color_layout=ct.colorlayout.RGB,
            )
        ],
        convert_to="mlprogram",
        minimum_deployment_target=ct.target.iOS16,
        # CCT transformer 在 iPhone Neural Engine 以 fp16 執行會輸出壞值（Mac 不會），固定 float32；
        # iOS 端同時把這個模型限制在 cpuAndGPU（見 OnDeviceRecognitionService）。
        compute_precision=ct.precision.FLOAT32,
    )
    replace_package(destination)
    converted_model.save(str(destination))
    print(f"PlateOCR 匯出完成: {destination}")


def export_view_classifier(output: Path) -> None:
    import coremltools as ct
    import torch
    from torch import nn
    from torchvision import models

    source_model = QUALITY_BACKEND / "app" / "models" / "view_classifier.pt"
    destination = output / "ViewClassifier.mlpackage"

    print("--> 匯出 ViewClassifier (MobileNetV2)...")
    checkpoint = torch.load(str(source_model), map_location="cpu", weights_only=True)
    classes = list(checkpoint["classes"])
    if set(classes) != set(VIEW_CLASS_ORDER) or len(classes) != len(VIEW_CLASS_ORDER):
        raise ValueError(f"Unexpected view-class order: {classes}")
    output_indices = [classes.index(label) for label in VIEW_CLASS_ORDER]

    model = models.mobilenet_v2(weights=None)
    model.classifier[-1] = nn.Linear(model.classifier[-1].in_features, len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    class NormalizedClassifier(nn.Module):
        def __init__(
            self,
            classifier: nn.Module,
            mean: list[float],
            std: list[float],
            output_indices: list[int],
        ):
            super().__init__()
            self.classifier = classifier
            self.register_buffer("mean", torch.tensor(mean).view(1, 3, 1, 1))
            self.register_buffer("std", torch.tensor(std).view(1, 3, 1, 1))
            self.register_buffer("output_indices", torch.tensor(output_indices))

        def forward(self, image: torch.Tensor):
            logits = self.classifier((image - self.mean) / self.std)
            return logits.index_select(1, self.output_indices)

    normalized_model = NormalizedClassifier(
        model,
        checkpoint["normalize_mean"],
        checkpoint["normalize_std"],
        output_indices,
    ).eval()
    sample = torch.rand(1, 3, 224, 224)
    traced_model = torch.jit.trace(normalized_model, sample)
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
    print(f"ViewClassifier 匯出完成: {destination}")


def main() -> None:
    args = parse_args()
    if args.skip_detector and args.skip_ocr and args.skip_view:
        raise ValueError("At least one model must be enabled.")

    args.output.mkdir(parents=True, exist_ok=True)
    if not args.skip_detector:
        export_detector(args.output)
    if not args.skip_ocr:
        export_ocr(args.output)
    if not args.skip_view:
        export_view_classifier(args.output)
    print(f"\n所有模型已產生至目錄: {args.output}")


if __name__ == "__main__":
    main()