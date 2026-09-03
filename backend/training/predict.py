#!/usr/bin/env python3
"""用訓好的分類器對單張還車照做推論。

⚠️ 目前權重僅由 138 筆樣本（22 正）訓出，交叉驗證 ROC-AUC 僅 0.59
   （隨機 = 0.50），**遠不如現行 VLM 級聯的 100% Recall**。
   本腳本的用途是打通「訓練 → 推論 → 部署」的路，不是取代 judge_photos.py。
   等監理台累積到數千筆標籤後重訓，再評估是否接入主流程。

用法：python3 predict.py 還車照.jpg
      python3 predict.py 照片.jpg --threshold 0.3
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
CKPT = HERE / "damage_classifier.pt"


def load(ckpt_path=CKPT):
    if not ckpt_path.exists():
        sys.exit(f"找不到權重 {ckpt_path}——請先跑 train_classifier.py --export")
    from torchvision import models, transforms
    import torch.nn as nn
    ck = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    m = models.resnet18()
    m.fc = nn.Linear(m.fc.in_features, 1)
    m.load_state_dict(ck["state_dict"])
    m.eval()
    size = ck["img_size"]
    tf = transforms.Compose([
        transforms.Resize(int(size * 1.14)),
        transforms.CenterCrop(size),
        transforms.ToTensor(),
        transforms.Normalize(ck["mean"], ck["std"]),
    ])
    return m, tf, ck


def predict(path, model=None, tf=None, ck=None):
    if model is None:
        model, tf, ck = load()
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")   # EXIF 必轉正
    with torch.no_grad():
        p = torch.sigmoid(model(tf(im).unsqueeze(0))).item()
    return p, ck


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--threshold", type=float, default=0.3,
                    help="判為有車損的機率門檻（交叉驗證最佳 recall 點約 0.3）")
    args = ap.parse_args()

    t0 = time.time()
    prob, ck = predict(args.photo)
    print(json.dumps({
        "photo": args.photo,
        "damage_probability": round(prob, 4),
        "predicted": "damage" if prob >= args.threshold else "clean",
        "threshold": args.threshold,
        "elapsed_ms": round((time.time() - t0) * 1000, 1),
        "model": {"arch": ck["arch"], "trained_on": ck["trained_on"]},
        "warning": ck["warning"],
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
