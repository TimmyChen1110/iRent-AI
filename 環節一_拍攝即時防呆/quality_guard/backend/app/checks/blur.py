"""模糊檢查（plan.md §5.1/§7.1）。"""

import cv2
import numpy as np


def compute_blur_score(gray: np.ndarray) -> float:
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def is_blurry(blur_score: float, threshold: float) -> bool:
    return blur_score < threshold
