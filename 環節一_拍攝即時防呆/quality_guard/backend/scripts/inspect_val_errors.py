"""把 val set 裡目前模型判斷錯誤的照片挑出來,複製到 dataset/val_errors/ 方便人工審核。

用法:
    cd backend && ../.venv/bin/python scripts/inspect_val_errors.py
"""
import shutil
from pathlib import Path

import torch
from torch import nn
from torchvision import datasets, models, transforms

ROOT = Path(__file__).resolve().parent.parent.parent
DATASET_DIR = ROOT / "dataset"
MODEL_PATH = Path(__file__).resolve().parent.parent / "app" / "models" / "view_classifier.pt"
ERRORS_DIR = DATASET_DIR / "val_errors"


def build_model(num_classes: int) -> nn.Module:
    model = models.mobilenet_v2(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def main() -> None:
    checkpoint = torch.load(MODEL_PATH, map_location="cpu")
    classes = checkpoint["classes"]
    image_size = checkpoint["image_size"]
    mean = checkpoint["normalize_mean"]
    std = checkpoint["normalize_std"]

    val_tf = transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])
    val_ds = datasets.ImageFolder(DATASET_DIR / "val", transform=val_tf)
    assert val_ds.classes == classes, f"類別順序不一致: {val_ds.classes} vs {classes}"

    model = build_model(num_classes=len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    if ERRORS_DIR.exists():
        shutil.rmtree(ERRORS_DIR)
    ERRORS_DIR.mkdir(parents=True)

    errors = []
    with torch.no_grad():
        for (path, true_idx), (image, _) in zip(val_ds.samples, val_ds):
            logits = model(image.unsqueeze(0))
            probs = torch.softmax(logits, dim=1)[0]
            pred_idx = int(probs.argmax())
            confidence = float(probs[pred_idx])

            if pred_idx != true_idx:
                true_label = classes[true_idx]
                pred_label = classes[pred_idx]
                src = Path(path)
                dst_name = f"真實={true_label}_預測={pred_label}_信心={confidence:.2f}__{src.name}"
                dst = ERRORS_DIR / dst_name
                shutil.copy2(src, dst)
                errors.append((src, true_label, pred_label, confidence))

    print(f"val set 共 {len(val_ds)} 張, 判斷錯誤 {len(errors)} 張\n")
    for src, true_label, pred_label, confidence in errors:
        print(f"  真實={true_label}  預測={pred_label}  信心={confidence:.2f}  來源={src}")

    print(f"\n已複製到: {ERRORS_DIR}（檔名已標明 真實/預測/信心，可以直接開資料夾用 Finder/預覽逐張看)")


if __name__ == "__main__":
    main()
