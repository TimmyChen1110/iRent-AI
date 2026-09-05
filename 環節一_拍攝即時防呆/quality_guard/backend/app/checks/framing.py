"""距離/構圖判斷（plan.md §5.4/§7.4/§7.5）。

沒有訓練資料可以做車輛偵測，所以近似做法是用車牌 bbox 的面積比例來判斷
遠近：車牌太小 -> 太遠；車牌太大（甚至貼邊）-> 太近。

如果完全偵測不到車牌，還要區分兩種情況：
  1. 車輛根本不在畫面裡（開錯照片/對錯方向）
  2. 貼近車身局部特寫，車牌被排除在畫面外（raw_data 裡真實觀察到的
     失敗模式，例如整張只拍到頭燈特寫）
第二種情況的畫面特徵是：有一大片平滑、低局部變異的光滑烤漆色塊佔滿畫面
（車身鈑金反光），用這個訊號輔助判斷「可能太近」。
"""

from dataclasses import dataclass
from typing import Literal, Optional

import cv2
import numpy as np

FramingVerdict = Literal["TOO_FAR", "TOO_CLOSE"]


@dataclass
class FramingResult:
    verdict: Optional[FramingVerdict]
    confidence: float  # 0-1，1 代表訊號很明確
    smooth_panel_ratio: Optional[float] = None  # 只有在找不到車牌時才計算


def _smooth_panel_ratio(gray: np.ndarray) -> float:
    """估計畫面中「大片平滑色塊」（例如貼近拍攝的烤漆、鈑金）所佔比例。

    做法：用小視窗算局部標準差，標準差很低的區域視為平滑色塊。
    """
    mean = cv2.blur(gray.astype(np.float32), (15, 15))
    mean_sq = cv2.blur((gray.astype(np.float32)) ** 2, (15, 15))
    local_var = np.clip(mean_sq - mean**2, 0, None)
    local_std = np.sqrt(local_var)
    smooth_mask = local_std < 6.0
    return float(np.mean(smooth_mask))


def estimate_framing(
    gray: np.ndarray,
    plate_bbox: Optional[tuple[int, int, int, int]],
    image_width: int,
    image_height: int,
    area_ratio_min: float,
    area_ratio_max: float,
    close_up_smooth_ratio_threshold: float = 0.55,
) -> FramingResult:
    if plate_bbox is not None:
        x1, y1, x2, y2 = plate_bbox
        area_ratio = ((x2 - x1) * (y2 - y1)) / float(image_width * image_height)

        # 原本還有一個「候選框是否貼到畫面邊界」的判斷，但實測對 285 張
        # 真實照片跑過一輪後發現：3/4 角落構圖下車牌本來就常常偏向畫面
        # 一側，加上候選框本身會加 padding 再被裁到畫面邊界，導致這個
        # 條件對將近 25% 的真實合格照片誤判 TOO_CLOSE，訊號太不可靠，
        # 拿掉了、只保留面積比例這個已用真實資料校準過的訊號。
        if area_ratio < area_ratio_min:
            return FramingResult(verdict="TOO_FAR", confidence=0.7)
        if area_ratio > area_ratio_max:
            return FramingResult(verdict="TOO_CLOSE", confidence=0.7)
        return FramingResult(verdict=None, confidence=0.9)

    # 找不到車牌：用平滑色塊比例輔助判斷是不是貼太近拍局部特寫
    smooth_ratio = _smooth_panel_ratio(gray)
    if smooth_ratio > close_up_smooth_ratio_threshold:
        return FramingResult(verdict="TOO_CLOSE", confidence=0.4, smooth_panel_ratio=smooth_ratio)

    return FramingResult(verdict=None, confidence=0.2, smooth_panel_ratio=smooth_ratio)
