"""整合各項檢查，產出 pass/fail + 使用者提示文字（plan.md §7 規則）。

M4 更新：併入 framing.py（距離/太近太遠）與 view.py。framing 的門檻是用
validation/run_validation.py 對 285 張真實照片實測的車牌面積比例分布校準
（見 app/config.py 註解），屬於擋關規則。view.py 的 Tier A（車外/車內）
經同一份驗證資料測試，對已知全部是「車外」的 285 張真實照片誤判率高達
28.8%，遠低於 plan.md 設定的可擋關門檻，因此**不擋關**，只放在
debug 資訊裡供參考；Tier B（左右前後細分）則本來就設計成僅供提示。
"""

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.checks.blur import compute_blur_score, is_blurry
from app.checks.brightness import BrightnessStats, brightness_verdict, compute_brightness_stats
from app.checks.framing import FramingResult, estimate_framing
from app.checks.plate import PlateCandidate, detect_plate
from app.checks.view import CornerGuessResult, ExteriorInteriorResult, classify_exterior_interior, guess_corner_side
from app.config import DEFAULT_THRESHOLDS, QualityThresholds
from app.view_taxonomy import RequiredView, is_exterior

ERROR_MESSAGES = {
    "IMAGE_INVALID": "無法讀取照片，請重新拍攝",
    "LOW_RESOLUTION": "照片解析度過低，請使用較高畫質重新拍攝",
    "IMAGE_BLURRY": "照片模糊，請穩定手機後重新拍攝",
    "TOO_DARK": "照片太暗，請移到光線較充足處重新拍攝",
    "TOO_BRIGHT": "照片過曝，請避開強光反射後重新拍攝",
    "PLATE_NOT_FOUND": "未偵測到車牌，請讓車牌完整入鏡",
    "TOO_FAR": "距離太遠，請靠近一點，讓車牌看得更清楚",
    "TOO_CLOSE": "距離太近，請退後一點，讓車輛與車牌完整入鏡",
}


@dataclass
class QualityError:
    code: str
    message: str


@dataclass
class QualityResult:
    passed: bool
    quality_score: float
    required_view: RequiredView
    errors: list[QualityError] = field(default_factory=list)
    blur_score: Optional[float] = None
    brightness: Optional[BrightnessStats] = None
    plate_bbox: Optional[tuple[int, int, int, int]] = None
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    plate_area_ratio: Optional[float] = None
    elapsed_ms: Optional[float] = None
    # 以下為 advisory-only 資訊，不影響 passed/errors（見模組 docstring 說明原因）
    exterior_interior_guess: Optional[str] = None
    exterior_interior_confidence: Optional[float] = None
    corner_side_guess: Optional[str] = None
    front_rear_guess: Optional[str] = None


def run_quality_check(
    image_bgr: np.ndarray,
    required_view: RequiredView,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityResult:
    errors: list[QualityError] = []
    height, width = image_bgr.shape[:2]

    if width < thresholds.min_width_px or height < thresholds.min_height_px:
        errors.append(QualityError("LOW_RESOLUTION", ERROR_MESSAGES["LOW_RESOLUTION"]))

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)

    blur_score = compute_blur_score(gray)
    if is_blurry(blur_score, thresholds.blur_threshold):
        errors.append(QualityError("IMAGE_BLURRY", ERROR_MESSAGES["IMAGE_BLURRY"]))

    brightness_stats = compute_brightness_stats(gray)
    brightness_issue = brightness_verdict(
        brightness_stats,
        thresholds.brightness_min_mean,
        thresholds.brightness_max_mean,
        thresholds.brightness_max_dark_ratio,
        thresholds.brightness_max_bright_ratio,
    )
    if brightness_issue:
        errors.append(QualityError(brightness_issue, ERROR_MESSAGES[brightness_issue]))

    plate_candidate: Optional[PlateCandidate] = None
    plate_area_ratio: Optional[float] = None
    ext_int_result: Optional[ExteriorInteriorResult] = None
    corner_guess: Optional[CornerGuessResult] = None

    if is_exterior(required_view):
        plate_candidate = detect_plate(image_bgr, min_score=thresholds.plate_min_score)
        if plate_candidate is None:
            errors.append(QualityError("PLATE_NOT_FOUND", ERROR_MESSAGES["PLATE_NOT_FOUND"]))
        else:
            x1, y1, x2, y2 = plate_candidate.box
            plate_area_ratio = ((x2 - x1) * (y2 - y1)) / float(width * height)

        framing_result: FramingResult = estimate_framing(
            gray,
            plate_candidate.box if plate_candidate else None,
            width,
            height,
            thresholds.plate_area_ratio_min,
            thresholds.plate_area_ratio_max,
        )
        # 只有在車牌真的找到、且面積比例明確超出範圍時才擋關；找不到車牌
        # 時的「太近」猜測信心較低（見 framing.py 說明），只放進 debug，
        # 不重複疊加另一個擋關原因（PLATE_NOT_FOUND 已經擋過一次了）。
        if plate_candidate is not None and framing_result.verdict is not None:
            errors.append(QualityError(framing_result.verdict, ERROR_MESSAGES[framing_result.verdict]))

        ext_int_result = classify_exterior_interior(image_bgr)
        corner_guess = guess_corner_side(image_bgr, plate_candidate.box if plate_candidate else None)

    quality_score = _compute_quality_score(blur_score, brightness_stats, plate_candidate, thresholds)

    return QualityResult(
        passed=len(errors) == 0,
        quality_score=quality_score,
        required_view=required_view,
        errors=errors,
        blur_score=blur_score,
        brightness=brightness_stats,
        plate_bbox=plate_candidate.box if plate_candidate else None,
        plate_text=plate_candidate.text if plate_candidate else None,
        plate_confidence=plate_candidate.confidence if plate_candidate else None,
        plate_area_ratio=plate_area_ratio,
        exterior_interior_guess=ext_int_result.label if ext_int_result else None,
        exterior_interior_confidence=ext_int_result.confidence if ext_int_result else None,
        corner_side_guess=corner_guess.side if corner_guess else None,
        front_rear_guess=corner_guess.front_rear if corner_guess else None,
    )


def _compute_quality_score(
    blur_score: float,
    brightness_stats: BrightnessStats,
    plate_candidate: Optional[PlateCandidate],
    thresholds: QualityThresholds,
) -> float:
    blur_component = max(0.0, min(1.0, blur_score / (thresholds.blur_threshold * 2)))
    brightness_component = max(0.0, min(1.0, 1.0 - abs(brightness_stats.mean - 0.5) * 2))
    plate_component = 1.0 if plate_candidate is not None else 0.0
    return round((blur_component + brightness_component + plate_component) / 3, 3)
