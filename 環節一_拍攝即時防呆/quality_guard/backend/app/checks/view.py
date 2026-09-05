"""角度/視角判斷（plan.md §5.5/§7.6），分兩層：

Tier A（車外 vs 車內）：當作安全網，可以擋關；但因為本地 293 張真實樣本
裡沒有任何一張「車內」照片（`grep -c 車內` = 0），這項準確率在本階段
無法離線驗證，demo 時要誠實說明這個限制。

Tier B（左前/右前/左後/右後 4 個角落之間的細分判斷）：僅供參考提示，
不擋送出——因為完全沒有訓練資料，強行擋關容易誤判真正合格的照片。
是否要把 Tier B 升級成擋關規則，要看 validation/run_validation.py 對
293 張真實照片的角落猜測準確率是否穩定超過 ~70%。
"""

from dataclasses import dataclass
from typing import Literal, Optional

import cv2
import numpy as np

ExteriorInterior = Literal["exterior", "interior"]
CornerSide = Literal["left", "right"]
FrontRear = Literal["front", "rear"]


@dataclass
class ExteriorInteriorResult:
    label: ExteriorInterior
    confidence: float


@dataclass
class CornerGuessResult:
    side: Optional[CornerSide]
    side_confidence: float
    front_rear: Optional[FrontRear]
    front_rear_confidence: float


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


def guess_corner_side(
    image_bgr: np.ndarray,
    plate_bbox: Optional[tuple[int, int, int, int]],
) -> CornerGuessResult:
    """僅供參考的左右/前後猜測，不擋送出。用車牌在畫面中的左右位置，加上
    車牌旁邊色調（頭燈偏白/尾燈偏紅）輔助判斷。"""
    if plate_bbox is None:
        return CornerGuessResult(side=None, side_confidence=0.0, front_rear=None, front_rear_confidence=0.0)

    height, width = image_bgr.shape[:2]
    x1, y1, x2, y2 = plate_bbox
    center_x = (x1 + x2) / 2.0 / width

    side: Optional[CornerSide] = "left" if center_x < 0.5 else "right"
    side_confidence = min(1.0, abs(center_x - 0.5) * 2)

    pad = int((x2 - x1) * 1.5)
    region_x1 = max(0, x1 - pad)
    region_x2 = min(width, x2 + pad)
    region_y1 = max(0, y1 - int((y2 - y1) * 1.5))
    region_y2 = min(height, y2)
    region = image_bgr[region_y1:region_y2, region_x1:region_x2]

    front_rear: Optional[FrontRear] = None
    front_rear_confidence = 0.0
    if region.size > 0:
        hsv_region = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
        red_mask = (
            ((hsv_region[:, :, 0] < 10) | (hsv_region[:, :, 0] > 170))
            & (hsv_region[:, :, 1] > 80)
            & (hsv_region[:, :, 2] > 60)
        )
        red_ratio = float(np.mean(red_mask))
        if red_ratio > 0.08:
            front_rear = "rear"
            front_rear_confidence = min(1.0, red_ratio * 4)
        else:
            front_rear = "front"
            front_rear_confidence = 0.3

    return CornerGuessResult(
        side=side,
        side_confidence=side_confidence,
        front_rear=front_rear,
        front_rear_confidence=front_rear_confidence,
    )
