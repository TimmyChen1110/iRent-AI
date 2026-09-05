"""品質檢查門檻值。

這裡的初始值是合理預設，會在 M3（validation/run_validation.py 對 293 張真實
照片 + 合成劣化跑過一輪後）依實際分數分布校準，不是最終值。
"""

from dataclasses import dataclass


@dataclass
class QualityThresholds:
    blur_threshold: float = 100.0

    brightness_min_mean: float = 0.25
    brightness_max_mean: float = 0.85
    brightness_max_dark_ratio: float = 0.55
    brightness_max_bright_ratio: float = 0.35

    plate_min_score: float = 25.0
    plate_min_confidence: float = 30.0

    # 車牌 bbox 面積佔整張圖片面積的比例，用來近似遠近判斷。
    # 數值取自 validation/run_validation.py 對 285 張真實照片的實測分布
    # （偵測到車牌的樣本中面積比例 p2≈0.0007，p99≈0.09）：min 設在 p2
    # 附近，讓現有真實合格照片的誤擋率控制在 ~2%；max 留在實測最大值
    # 之上，避免誤擋合法的近距離合格照片。
    plate_area_ratio_min: float = 0.0007  # 低於此比例視為太遠
    plate_area_ratio_max: float = 0.12  # 高於此比例視為太近/裁切

    min_width_px: int = 480
    min_height_px: int = 270


DEFAULT_THRESHOLDS = QualityThresholds()
