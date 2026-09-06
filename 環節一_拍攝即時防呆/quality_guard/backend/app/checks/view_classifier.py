"""Stage 3：四角視角分類（左前/右前/左後/右後），MobileNetV2 transfer learning。

取代 `app/checks/view.py` 裡 Tier B 的 heuristic 猜測（那版靠車牌在畫面的左右
位置 + 尾燈紅色比例，沒有訓練資料支撐）。模型載入與前處理跟
`scripts/classify_tool.py` 完全一致——**前處理只要跟訓練時差一點，準確率就會
無聲無息地掉**，所以 Resize(256) → CenterCrop(image_size) 這組順序不要「順手優化」
成直接 resize 成 224x224。

checkpoint 不是單純的 state_dict，是一個 dict（見 `整合計畫_四階段辨識.md`）：
    classes / image_size / normalize_mean / normalize_std / state_dict
類別順序以 checkpoint 內的 `classes` 為準，不要在程式裡硬編碼順序。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from app.config import VIEW_CLASSIFIER_PATH


@dataclass
class ViewClassification:
    label: str  # checkpoint["classes"] 其中之一，例如「左前」
    confidence: float  # top-1 機率，0-1
    probabilities: list[tuple[str, float]]  # 全部類別的機率，由高到低


class _LoadedClassifier:
    def __init__(self, model, transform, classes: list[str]):
        self.model = model
        self.transform = transform
        self.classes = classes


_classifier: Optional[_LoadedClassifier] = None
_load_lock = threading.Lock()
# torch 的 forward 在 CPU 上是 thread-safe 的，但為了跟 plate_yolo 一致、
# 也避免之後換到 GPU 時踩到 stream 共用問題，推論一樣序列化。
_inference_lock = threading.Lock()


def _build_model(num_classes: int):
    from torch import nn
    from torchvision import models

    model = models.mobilenet_v2(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def _load() -> _LoadedClassifier:
    import torch
    from torchvision import transforms

    if not VIEW_CLASSIFIER_PATH.exists():
        raise FileNotFoundError(
            f"視角分類模型不存在：{VIEW_CLASSIFIER_PATH}\n"
            f"可用 scripts/train_view_classifier.py 重新訓練，或用環境變數 "
            f"IRENT_VIEW_CLASSIFIER 指到既有的 .pt。"
        )

    # weights_only=True：checkpoint 裡只有 tensor 與基本型別，不需要
    # 反序列化任意 python 物件，關掉可以避免載入不明 .pt 時的執行風險。
    checkpoint = torch.load(VIEW_CLASSIFIER_PATH, map_location="cpu", weights_only=True)
    classes = list(checkpoint["classes"])
    image_size = checkpoint["image_size"]

    transform = transforms.Compose(
        [
            transforms.Resize(256),
            transforms.CenterCrop(image_size),
            transforms.ToTensor(),
            transforms.Normalize(checkpoint["normalize_mean"], checkpoint["normalize_std"]),
        ]
    )

    model = _build_model(len(classes))
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()

    return _LoadedClassifier(model=model, transform=transform, classes=classes)


def get_classifier() -> _LoadedClassifier:
    global _classifier
    if _classifier is None:
        with _load_lock:
            if _classifier is None:
                _classifier = _load()
    return _classifier


def warmup() -> None:
    """FastAPI startup 時呼叫，避免第一個 request 才付模型載入成本。"""
    get_classifier()


def get_classes() -> list[str]:
    return list(get_classifier().classes)


def classify_corner(image_bgr: np.ndarray) -> ViewClassification:
    """把整張照片分成左前/右前/左後/右後其中一類。"""
    import torch
    from PIL import Image

    loaded = get_classifier()
    # OpenCV 是 BGR、torchvision 的 Normalize 參數是 ImageNet RGB 順序，
    # 少轉這一步不會報錯但會系統性影響預測，是很容易漏掉的坑。
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    tensor = loaded.transform(Image.fromarray(image_rgb)).unsqueeze(0)

    with _inference_lock, torch.no_grad():
        probs = torch.softmax(loaded.model(tensor), dim=1)[0]

    ranked = sorted(
        ((label, float(prob)) for label, prob in zip(loaded.classes, probs.tolist())),
        key=lambda item: item[1],
        reverse=True,
    )
    return ViewClassification(label=ranked[0][0], confidence=ranked[0][1], probabilities=ranked)
