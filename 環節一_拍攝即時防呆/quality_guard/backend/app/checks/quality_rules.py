"""四階段拍照防呆 pipeline（見 `../../整合計畫_四階段辨識.md`）。

    Stage 0  基本可讀性：解碼、解析度、整張有沒有內容   → IMAGE_INVALID / LOW_RESOLUTION
    Stage 1  影像品質：模糊、亮度（純 CV，很快）
             **預設只計算不擋關**，結果標註在第 1 關的結論裡供參考
             （要擋關把 config 的 stage1_blocks_on_* 打開）
    Stage 2  車牌偵測 + OCR（YOLO + fast-plate-ocr）   → PLATE_NOT_FOUND / TOO_FAR / TOO_CLOSE
                                                        / PLATE_TEXT_UNREADABLE
    Stage 3  視角分類（MobileNetV2 四分類）            → WRONG_VIEW
    Stage 4  分類信心值防線                            → UNCERTAIN_VIEW

**闖關式**：前一關沒過就不跑下一關，沒跑到的關卡在 `stages` 裡是 `skipped`、
在 debug 裡是 `None`。對外的三關（`stages` 欄位）是把內部階段合併過的：

    Stage 0 + Stage 1 → readability（基本可讀性）
    Stage 2           → plate（車牌偵測）
    Stage 3 + Stage 4 → view（四角辨識）

車牌沒抓到時要不要仍然報角度，是 `QualityThresholds.run_view_stage_when_plate_missing`
的取捨（預設 False＝闖關；設 True 時實測沒抓到車牌的照片角度仍有 91.4% 正確率）。

**stage 內部不提早結束**：Stage 1 的模糊與亮度各自獨立、互不影響，一次跑完
一起回報，使用者才不用重拍兩次才知道兩個問題。

Stage 3/4 的順序刻意跟整合計畫的編號相反：先看信心值再看是否符合
`required_view`。低信心時說「拍錯角度」是在拿模型的不確定性當事實去指控使用者，
回「無法確認角度，請重新拍攝」誠實得多。

Tier A（車外/車內）heuristic 維持 advisory、不擋關：對已知全部是「車外」的
285 張真實照片誤判率 28.8%（見 README 已知限制）。
"""

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np

from app.checks.blur import compute_blur_score, is_blurry
from app.checks.brightness import BrightnessStats, brightness_verdict, compute_brightness_stats
from app.checks.framing import FramingResult, estimate_framing
from app.checks.orientation import resolve_upright
from app.checks.plate_yolo import PlateCandidate, detect_plate, plate_character_count
from app.checks.view import ExteriorInteriorResult, classify_exterior_interior
from app.checks.view_classifier import ViewClassification, classify_corner
from app.config import DEFAULT_THRESHOLDS, QualityThresholds
from app.view_taxonomy import RequiredView, is_exterior, required_view_for_class_name

# 對外顯示的三個關卡：id、顯示名稱、屬於這一關的錯誤碼。
# 順序就是闖關順序，前一關沒過後面就是 skipped。
STAGE_DEFINITIONS: list[tuple[str, str, frozenset[str]]] = [
    ("readability", "基本可讀性", frozenset({
        "IMAGE_INVALID", "LOW_RESOLUTION", "IMAGE_BLURRY", "TOO_DARK", "TOO_BRIGHT",
    })),
    ("plate", "車牌偵測", frozenset({
        "PLATE_NOT_FOUND", "TOO_FAR", "TOO_CLOSE", "PLATE_TEXT_UNREADABLE",
        "PLATE_INCOMPLETE",
    })),
    ("view", "四角辨識", frozenset({"WRONG_VIEW", "UNCERTAIN_VIEW"})),
]

# 內部階段名稱 → 對外關卡 id
_INTERNAL_STAGE_TO_PUBLIC = {
    "stage0_readability": "readability",
    "stage1_image_quality": "readability",
    "stage2_plate": "plate",
    "stage3_view": "view",
    "stage4_view_confidence": "view",
}

ERROR_MESSAGES = {
    "IMAGE_INVALID": "無法讀取照片，請重新拍攝",
    "LOW_RESOLUTION": "照片解析度過低，請使用較高畫質重新拍攝",
    "IMAGE_BLURRY": "照片模糊，請穩定手機後重新拍攝",
    "TOO_DARK": "照片太暗，請移到光線較充足處重新拍攝",
    "TOO_BRIGHT": "照片過曝，請避開強光反射後重新拍攝",
    "PLATE_NOT_FOUND": "未偵測到車牌，請讓車牌完整入鏡",
    "TOO_FAR": "距離太遠，請靠近一點，讓車牌看得更清楚",
    "TOO_CLOSE": "距離太近，請退後一點，讓車輛與車牌完整入鏡",
    "PLATE_TEXT_UNREADABLE": "車牌字看不清楚，請靠近一點或穩定手機後重新拍攝",
    "PLATE_INCOMPLETE": "車牌可能只拍到一半，請讓完整車牌入鏡後重新拍攝",
    "WRONG_VIEW": "拍攝角度不符，請依指定角度重新拍攝",
    "UNCERTAIN_VIEW": "無法確認拍攝角度，請退後一點、讓整台車完整入鏡後重新拍攝",
}


@dataclass
class QualityError:
    code: str
    message: str


@dataclass
class StageOutcome:
    id: str
    name: str
    status: str  # "passed" | "failed" | "skipped"
    errors: list[QualityError] = field(default_factory=list)
    summary: Optional[str] = None  # 這一關的一句話結論，給前端直接顯示


@dataclass
class QualityResult:
    passed: bool
    quality_score: float
    required_view: Optional[RequiredView]
    errors: list[QualityError] = field(default_factory=list)
    stages_run: list[str] = field(default_factory=list)
    stages: list[StageOutcome] = field(default_factory=list)
    image_width: Optional[int] = None
    image_height: Optional[int] = None
    # 方向防護網實際套用的逆時針角度（0 = 原圖就是正的，見 orientation.py）。
    # 不是 0 的時候，plate_bbox 與 image_width/height 都是「轉正後」的座標系，
    # 前端要畫框就得先把預覽圖轉同樣的角度。
    orientation_rotation: int = 0

    # Stage 1（預設不擋關，只計算）
    blur_score: Optional[float] = None
    brightness: Optional[BrightnessStats] = None
    # 不擋關但值得讓使用者知道的觀察，例如「偏暗」「偏模糊」
    stage1_advisories: list[str] = field(default_factory=list)

    # Stage 2
    plate_bbox: Optional[tuple[int, int, int, int]] = None
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None  # OCR 平均字元機率 0-1
    plate_detect_confidence: Optional[float] = None  # YOLO 偵測信心值 0-1
    plate_area_ratio: Optional[float] = None

    # Stage 3/4。view_label / view_probabilities 已翻譯成 iRent 命名
    # （見 view_taxonomy.VIEW_CLASS_NAME_TO_REQUIRED_VIEW，車頭兩類會左右對調）；
    # view_model_label 保留模型原始輸出，方便對照 debug。
    view_label: Optional[str] = None
    view_model_label: Optional[str] = None
    view_confidence: Optional[float] = None
    view_probabilities: Optional[list[tuple[str, float]]] = None

    # advisory-only，不影響 passed
    exterior_interior_guess: Optional[str] = None
    exterior_interior_confidence: Optional[float] = None

    elapsed_ms: Optional[float] = None


def run_quality_check(
    image_bgr: np.ndarray,
    required_view: Optional[RequiredView] = None,
    thresholds: QualityThresholds = DEFAULT_THRESHOLDS,
) -> QualityResult:
    """跑完整四階段檢查。

    `required_view=None` 代表「不指定角度，只要辨識並回報角度」（前端的自由
    上傳模式）：Stage 3 照跑、照回傳結果，但不會因為角度不符而擋關，Stage 4
    的信心值防線仍然有效——角度連模型自己都不確定時，照片本身就不合格。
    """
    result = QualityResult(passed=False, quality_score=0.0, required_view=required_view)
    errors = result.errors

    # ---------- Stage 0：基本可讀性 ----------
    result.stages_run.append("stage0_readability")
    height, width = image_bgr.shape[:2]
    result.image_width, result.image_height = width, height
    if width < thresholds.min_width_px or height < thresholds.min_height_px:
        errors.append(_error("LOW_RESOLUTION"))

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    result.brightness = compute_brightness_stats(gray)
    # 全黑/全白：標準差幾乎為 0 表示整張沒有內容，後面所有模型都不用跑了。
    if result.brightness.std < 0.01:
        errors.append(_error("IMAGE_INVALID"))

    if errors:
        return _finalize(result, thresholds)

    # ---------- Stage 1：影像品質（模糊 + 亮度一起跑完再回報）----------
    result.stages_run.append("stage1_image_quality")
    result.blur_score = compute_blur_score(gray)
    blurry = is_blurry(result.blur_score, thresholds.blur_threshold)
    brightness_issue = brightness_verdict(
        result.brightness,
        thresholds.brightness_min_mean,
        thresholds.brightness_max_mean,
        thresholds.brightness_max_dark_ratio,
        thresholds.brightness_max_bright_ratio,
    )

    # 預設只記錄不擋關：整張照片的平均亮度不能代表「車牌讀不讀得到」——實測有
    # 12 張被舊規則擋掉的偏暗照片，車牌其實讀得完全正確（見 config.py 的說明）。
    # 能不能用，交給第 2 關實際去偵測車牌。
    if blurry:
        (errors.append(_error("IMAGE_BLURRY")) if thresholds.stage1_blocks_on_blur
         else result.stage1_advisories.append("畫面偏模糊"))
    if brightness_issue:
        note = "照片偏暗" if brightness_issue == "TOO_DARK" else "照片偏亮"
        (errors.append(_error(brightness_issue)) if thresholds.stage1_blocks_on_brightness
         else result.stage1_advisories.append(note))

    if errors:
        return _finalize(result, thresholds)

    # 車內視角沒有車牌可偵測、四角分類器也沒有對應類別，Stage 2-4 全部略過。
    # （已知限制：本地 293 張真實照片沒有任何一張車內照，這條路徑未經驗證。）
    if required_view is not None and not is_exterior(required_view):
        result.stages_run.append("stage2_4_skipped_interior_view")
        return _finalize(result, thresholds)

    # ---------- Stage 2：車牌偵測 + OCR ----------
    result.stages_run.append("stage2_plate")
    if thresholds.enable_orientation_probe:
        # 偵測不到車牌時會試著把圖轉正再測一次（見 orientation.py）。第一次就
        # 測到的話成本與直接呼叫 detect_plate 完全相同。
        oriented = resolve_upright(
            image_bgr,
            min_conf=thresholds.plate_detect_min_conf,
            imgsz=thresholds.plate_detect_imgsz,
            padding=thresholds.plate_crop_padding,
            valid_lengths=thresholds.plate_text_valid_lengths,
        )
        plate = oriented.plate
        if oriented.rotation:
            # 從這裡開始所有東西都活在「轉正後」的座標系：bbox、面積比例、
            # 送進視角分類器的圖都是。gray 與寬高必須跟著換，否則 framing 會拿
            # 轉正前的尺寸去除轉正後的 bbox 面積，比例直接算錯。
            image_bgr = oriented.image_bgr
            gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
            height, width = image_bgr.shape[:2]
            result.image_width, result.image_height = width, height
            result.orientation_rotation = oriented.rotation
    else:
        plate = detect_plate(
            image_bgr,
            min_conf=thresholds.plate_detect_min_conf,
            imgsz=thresholds.plate_detect_imgsz,
            padding=thresholds.plate_crop_padding,
        )

    if plate is None:
        # 找不到車牌時，用「大片平滑烤漆」訊號區分兩種失敗：貼太近拍局部特寫
        # （給得出具體動作：退後）vs 根本沒拍到車。兩種都擋關，但只回報一個
        # 錯誤碼——同時丟 PLATE_NOT_FOUND + TOO_CLOSE 只會讓使用者不知道要做什麼。
        framing = estimate_framing(
            gray, None, width, height,
            thresholds.plate_area_ratio_min, thresholds.plate_area_ratio_max,
        )
        errors.append(_error("TOO_CLOSE" if framing.verdict == "TOO_CLOSE" else "PLATE_NOT_FOUND"))
    else:
        _record_plate(result, plate, gray, width, height, thresholds, errors)

    # ---------- Stage 3：視角分類 ----------
    # 闖關式：車牌這一關沒過就不跑（可用 run_view_stage_when_plate_missing 改）。
    plate_stage_passed = not any(
        e.code in STAGE_DEFINITIONS[1][2] for e in errors
    )
    if plate_stage_passed or thresholds.run_view_stage_when_plate_missing:
        _classify_view(result, image_bgr, required_view, thresholds, errors)
    return _finalize(result, thresholds)


def _record_plate(
    result: QualityResult,
    plate: PlateCandidate,
    gray: np.ndarray,
    width: int,
    height: int,
    thresholds: QualityThresholds,
    errors: list[QualityError],
) -> None:
    result.plate_bbox = plate.box
    result.plate_text = plate.text or None
    result.plate_confidence = plate.confidence
    result.plate_detect_confidence = plate.score
    x1, y1, x2, y2 = plate.box
    result.plate_area_ratio = ((x2 - x1) * (y2 - y1)) / float(width * height)

    framing: FramingResult = estimate_framing(
        gray, plate.box, width, height,
        thresholds.plate_area_ratio_min, thresholds.plate_area_ratio_max,
    )
    if framing.verdict is not None:
        errors.append(_error(framing.verdict))

    # 偵測到車牌但字讀不出來 = 車牌區域太糊/太小/角度太斜，對使用者是可行動的
    # 提示。門檻待校準（見 config.py），刻意訂得寬鬆。
    #
    # 「讀不出來」與「只讀到一半」互斥、只報一個：兩個都丟出來使用者不知道要做什麼。
    # 完全讀不出字（含 OCR 高信心但輸出空字串的情況）歸類為讀不出來；讀得出字但
    # 字數不對，代表車牌被裁掉頭或尾，那是構圖問題，要講「請讓完整車牌入鏡」。
    character_count = plate_character_count(plate.text)
    if plate.confidence < thresholds.plate_ocr_min_confidence or character_count == 0:
        errors.append(_error("PLATE_TEXT_UNREADABLE"))
    elif character_count not in thresholds.plate_text_valid_lengths:
        errors.append(_error("PLATE_INCOMPLETE"))


def _classify_view(
    result: QualityResult,
    image_bgr: np.ndarray,
    required_view: Optional[RequiredView],
    thresholds: QualityThresholds,
    errors: list[QualityError],
) -> None:
    result.stages_run.append("stage3_view")
    classification: ViewClassification = classify_corner(image_bgr)
    predicted_view = required_view_for_class_name(classification.label)
    result.view_model_label = classification.label
    # 對外一律用 iRent 命名：required_view 是 App 指定的，使用者看到的角度提示
    # 必須跟 App 要求的角度是同一套詞，否則「需要左前、你拍的是左前」卻擋關。
    result.view_label = predicted_view.value if predicted_view else classification.label
    result.view_confidence = classification.confidence
    result.view_probabilities = [
        (
            translated.value if (translated := required_view_for_class_name(label)) else label,
            probability,
        )
        for label, probability in classification.probabilities
    ]

    ext_int: ExteriorInteriorResult = classify_exterior_interior(image_bgr)
    result.exterior_interior_guess = ext_int.label
    result.exterior_interior_confidence = ext_int.confidence

    # ---------- Stage 4：信心值防線（先於 WRONG_VIEW，見模組 docstring）----------
    result.stages_run.append("stage4_view_confidence")
    if classification.confidence < thresholds.view_confidence_min:
        errors.append(_error("UNCERTAIN_VIEW"))
    elif required_view is not None and predicted_view != required_view:
        errors.append(
            QualityError(
                "WRONG_VIEW",
                f"拍攝角度不符：需要「{required_view.value}」，"
                f"但這張看起來是「{result.view_label}」，請重新拍攝",
            )
        )


def _error(code: str) -> QualityError:
    return QualityError(code, ERROR_MESSAGES[code])


def _finalize(result: QualityResult, thresholds: QualityThresholds) -> QualityResult:
    result.passed = len(result.errors) == 0
    result.quality_score = _compute_quality_score(result, thresholds)
    result.stages = _build_stage_outcomes(result, thresholds)
    return result


def _build_stage_outcomes(result: QualityResult, thresholds: QualityThresholds) -> list[StageOutcome]:
    """把內部階段與錯誤碼整理成對外的三關結果。

    分三種狀態，前端就能直接畫闖關流程，不用自己從錯誤碼反推：
      passed  這一關跑過而且沒有錯誤
      failed  這一關跑過但有錯誤
      skipped 前一關沒過（或車內視角本來就不適用），根本沒跑
    """
    reached = {
        _INTERNAL_STAGE_TO_PUBLIC[name]
        for name in result.stages_run
        if name in _INTERNAL_STAGE_TO_PUBLIC
    }

    outcomes: list[StageOutcome] = []
    for stage_id, name, codes in STAGE_DEFINITIONS:
        stage_errors = [e for e in result.errors if e.code in codes]
        if stage_id not in reached:
            status = "skipped"
        elif stage_errors:
            status = "failed"
        else:
            status = "passed"
        outcomes.append(
            StageOutcome(
                id=stage_id,
                name=name,
                status=status,
                errors=stage_errors,
                summary=_stage_summary(stage_id, status, result, thresholds),
            )
        )
    return outcomes


def _stage_summary(
    stage_id: str, status: str, result: QualityResult, thresholds: QualityThresholds
) -> Optional[str]:
    """每一關給一句話結論。失敗原因走 errors，不在這裡重複。"""
    if status == "skipped":
        if "stage2_4_skipped_interior_view" in result.stages_run:
            return "車內視角不適用這一關"
        return "前一關沒過，尚未執行"

    if stage_id == "readability":
        parts = []
        if result.image_width and result.image_height:
            parts.append(f"解析度 {result.image_width}×{result.image_height}")
        if result.blur_score is not None:
            parts.append(f"清晰度 {result.blur_score:.0f}")
        if result.brightness is not None:
            parts.append(f"平均亮度 {result.brightness.mean * 100:.0f}%")
        summary = "・".join(parts) or None
        if summary and result.stage1_advisories:
            # 講清楚「有注意到，但不因此擋你」，不然使用者會困惑為什麼標了偏暗還算通過
            summary += f"（{'、'.join(result.stage1_advisories)}，仍繼續判讀車牌）"
        return summary

    if stage_id == "plate":
        if result.plate_text:
            # 字數不對時也要把讀到的內容秀出來——使用者看到「RDG857」才會意識到
            # 尾碼被裁掉了，比只說一句「請重拍」有用得多。
            count = plate_character_count(result.plate_text)
            parts = [f"辨識信心 {result.plate_confidence * 100:.1f}%"]
            if count not in thresholds.plate_text_valid_lengths:
                expected = "/".join(str(n) for n in sorted(thresholds.plate_text_valid_lengths))
                parts.insert(0, f"只讀到 {count} 碼，應為 {expected} 碼")
            return f"車牌 {result.plate_text}（{'・'.join(parts)}）"
        if result.plate_bbox is not None:
            return "有找到車牌位置，但讀不出號碼"
        return "畫面中沒有找到車牌"

    if stage_id == "view":
        if result.view_label and result.view_confidence is not None:
            return f"判定為「{result.view_label}」（判斷信心 {result.view_confidence * 100:.1f}%）"
        return "無法判斷拍攝角度"

    return None


def _compute_quality_score(result: QualityResult, thresholds: QualityThresholds) -> float:
    """0-1 的綜合品質分數，只當作參考顯示，不參與 pass/fail 判斷。

    四個成分各占 1/4：模糊、亮度、車牌（偵測 + OCR）、視角信心。提早結束時
    沒跑到的成分算 0——分數低本來就代表「這張照片沒走完整條檢查」。
    """
    # blur_threshold 可以被呼叫端調成 0（例如想停用模糊檢查），除以 0 會炸掉，
    # 所以用 max(..., 1e-6) 兜底：門檻為 0 時任何銳利度都算滿分，語意也合理。
    blur_component = (
        max(0.0, min(1.0, result.blur_score / max(thresholds.blur_threshold * 2, 1e-6)))
        if result.blur_score is not None
        else 0.0
    )
    brightness_component = (
        max(0.0, min(1.0, 1.0 - abs(result.brightness.mean - 0.5) * 2))
        if result.brightness is not None
        else 0.0
    )
    if result.plate_bbox is None:
        plate_component = 0.0
    else:
        # 偵測到就先給一半，剩下一半看 OCR 讀得多清楚。
        plate_component = 0.5 + 0.5 * max(0.0, min(1.0, result.plate_confidence or 0.0))
    view_component = result.view_confidence if result.view_confidence is not None else 0.0

    return round((blur_component + brightness_component + plate_component + view_component) / 4, 3)
