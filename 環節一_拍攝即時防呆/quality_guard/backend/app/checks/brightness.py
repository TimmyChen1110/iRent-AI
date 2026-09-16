"""亮度檢查（plan.md §5.2）：平均亮度、標準差、過暗/過曝像素比例。"""

from dataclasses import dataclass
from typing import Literal

import numpy as np

DARK_PIXEL_THRESHOLD = 40  # 0-255 灰階值，低於此視為過暗像素
BRIGHT_PIXEL_THRESHOLD = 235  # 0-255 灰階值，高於此視為過曝像素


@dataclass
class BrightnessStats:
    mean: float  # 0-1 常態化平均亮度
    std: float  # 0-1 常態化標準差
    dark_ratio: float  # 過暗像素比例
    bright_ratio: float  # 過曝像素比例


def compute_brightness_stats(gray: np.ndarray) -> BrightnessStats:
    mean = float(np.mean(gray)) / 255.0
    std = float(np.std(gray)) / 255.0
    dark_ratio = float(np.mean(gray < DARK_PIXEL_THRESHOLD))
    bright_ratio = float(np.mean(gray > BRIGHT_PIXEL_THRESHOLD))
    return BrightnessStats(mean=mean, std=std, dark_ratio=dark_ratio, bright_ratio=bright_ratio)


def brightness_verdict(
    stats: BrightnessStats,
    min_mean: float,
    max_mean: float,
    max_dark_ratio: float,
    max_bright_ratio: float,
) -> Literal["TOO_DARK", "TOO_BRIGHT"] | None:
    if stats.mean < min_mean or stats.dark_ratio > max_dark_ratio:
        return "TOO_DARK"
    if stats.mean > max_mean or stats.bright_ratio > max_bright_ratio:
        return "TOO_BRIGHT"
    return None
