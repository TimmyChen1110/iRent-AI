"""Tier A：車外 vs 車內的粗略判斷（advisory only，不擋關）。

原本這支還有 Tier B（左前/右前/左後/右後 的 heuristic 猜測），四階段整合後
已由訓練好的分類模型取代，見 `app/checks/view_classifier.py`。

Tier A 保留但**維持不擋關**：本地 293 張真實樣本裡沒有任何一張「車內」照片
（`grep -c 車內` = 0），無法離線驗證；而且對已知全部是「車外」的 285 張照片
誤判率高達 28.8%。只放在 API 的 debug 欄位供參考，demo 時要誠實說明這個限制。
"""

from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np

ExteriorInterior = Literal["exterior", "interior"]


@dataclass
class ExteriorInteriorResult:
    label: ExteriorInterior
    confidence: float


def classify_exterior_interior(image_bgr: np.ndarray) -> ExteriorInteriorResult:
    """粗略啟發式：室外照片通常有較高的色彩飽和度變化跟較大範圍的高亮
    區域（天空、反光地面）；室內照片色調較均勻、偏中性色。這項沒有真實
    室內樣本可以校準，門檻刻意保守，預設傾向判斷為 exterior，只有在
    訊號非常明確時才給高信心的 interior 判斷。
    """
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1].astype(np.float32) / 255.0
    value = hsv[:, :, 2].astype(np.float32) / 255.0

    bright_sky_like_ratio = float(np.mean((value > 0.75) & (saturation < 0.25)))
    saturation_std = float(np.std(saturation))

    # 室外場景常有大面積偏白/偏亮且低飽和度的天空或反光路面；
    # 室內照片這個比例通常低很多。
    if bright_sky_like_ratio > 0.12 or saturation_std > 0.22:
        return ExteriorInteriorResult(label="exterior", confidence=0.55)

    return ExteriorInteriorResult(label="interior", confidence=0.35)
