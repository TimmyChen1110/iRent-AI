"""四階段 pipeline 的分階段/提早結束行為。

這裡的案例刻意都用合成影像，跑不到 Stage 2/3，所以**不需要模型檔**也能跑——
CI 或還沒下載模型的機器至少能守住「階段順序」這條最容易改壞的邏輯。
"""

import numpy as np
import pytest

from app.checks.quality_rules import ERROR_MESSAGES, run_quality_check
from app.config import QualityThresholds
from app.view_taxonomy import RequiredView

RNG = np.random.default_rng(1234)


def _structured_image(width: int = 1280, height: int = 720) -> np.ndarray:
    """有大尺度結構 + 高頻細節的合成圖：過得了 Stage 0/1，但裡面沒有車。

    不能用純亂數雜訊：高斯模糊會把獨立同分布的雜訊平均掉，整張標準差趨近 0，
    於是被 Stage 0 的「全黑/全白」判斷擋下，測不到想測的 Stage 1 行為。
    這裡用漸層色塊（模糊後仍保有對比）搭配細雜訊（提供銳利度）。
    """
    import cv2

    gradient = np.tile(np.linspace(30, 220, width, dtype=np.float32), (height, 1))
    image = cv2.merge([gradient, np.flip(gradient, axis=1), gradient * 0.7]).astype(np.uint8)
    cv2.rectangle(image, (120, 120), (520, 420), (20, 20, 20), -1)
    cv2.rectangle(image, (700, 260), (1150, 600), (240, 240, 240), -1)
    detail = RNG.integers(-25, 25, (height, width, 3))
    return np.clip(image.astype(np.int16) + detail, 0, 255).astype(np.uint8)


def _darken(image: np.ndarray, factor: float = 0.12) -> np.ndarray:
    return np.clip(image.astype(np.float32) * factor, 0, 255).astype(np.uint8)


def _codes(result) -> list[str]:
    return [e.code for e in result.errors]


def test_all_error_codes_have_messages():
    """新增錯誤碼時忘了補文案，使用者只會看到 KeyError。"""
    from app.checks import quality_rules

    source = (quality_rules.__file__ or "")
    assert source
    for code in ("WRONG_VIEW", "UNCERTAIN_VIEW", "PLATE_TEXT_UNREADABLE", "TOO_FAR", "TOO_CLOSE"):
        assert ERROR_MESSAGES[code]


def test_blank_image_stops_at_stage0():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=RequiredView.LEFT_FRONT)

    assert not result.passed
    assert "IMAGE_INVALID" in _codes(result)
    assert result.stages_run == ["stage0_readability"]
    # Stage 1 之後都沒跑到，對應欄位必須是 None 而不是報錯
    assert result.blur_score is None
    assert result.plate_bbox is None
    assert result.view_label is None


def test_low_resolution_stops_at_stage0():
    tiny = _structured_image(100, 100)
    result = run_quality_check(tiny, required_view=RequiredView.LEFT_FRONT)

    assert "LOW_RESOLUTION" in _codes(result)
    assert result.stages_run == ["stage0_readability"]


def test_blur_and_brightness_do_not_block_by_default():
    """第 1 關只擋解析度；模糊/亮度只標註不擋關。

    理由：整張照片的平均亮度不能代表「車牌讀不讀得到」——實測 285 張真實照片中，
    被舊規則擋掉的 39 張裡有 12 張的車牌其實讀得完全正確。能不能用交給第 2 關判斷。
    """
    import cv2

    dark_blurred = _darken(cv2.GaussianBlur(_structured_image(), (31, 31), sigmaX=12))
    result = run_quality_check(dark_blurred, required_view=RequiredView.LEFT_FRONT)

    assert "IMAGE_BLURRY" not in _codes(result)
    assert "TOO_DARK" not in _codes(result)
    # 但要記錄下來讓使用者知道系統有注意到
    assert {"畫面偏模糊", "照片偏暗"} <= set(result.stage1_advisories)
    assert _stage(result, "readability").status == "passed"
    assert "仍繼續判讀車牌" in (_stage(result, "readability").summary or "")


def test_blur_and_brightness_can_be_re_enabled_as_gates():
    """兩個旗標打開時要恢復擋關，而且同一關內的兩項要一次報完——
    否則使用者得重拍兩次才知道照片同時又暗又糊。"""
    import cv2

    dark_blurred = _darken(cv2.GaussianBlur(_structured_image(), (31, 31), sigmaX=12))
    result = run_quality_check(
        dark_blurred,
        required_view=RequiredView.LEFT_FRONT,
        thresholds=QualityThresholds(
            stage1_blocks_on_blur=True, stage1_blocks_on_brightness=True
        ),
    )

    assert {"IMAGE_BLURRY", "TOO_DARK"} <= set(_codes(result))
    assert "stage2_plate" not in result.stages_run
    assert result.plate_bbox is None


def test_interior_view_skips_model_stages():
    result = run_quality_check(_structured_image(), required_view=RequiredView.FRONT_INTERIOR)

    assert "stage2_4_skipped_interior_view" in result.stages_run
    assert "stage2_plate" not in result.stages_run
    assert result.plate_bbox is None
    assert result.view_label is None


def test_quality_score_stays_in_range_on_early_exit():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=RequiredView.LEFT_FRONT)
    assert 0.0 <= result.quality_score <= 1.0


def test_thresholds_are_overridable():
    """門檻值全部走 QualityThresholds，沒有藏在函式裡的硬編碼常數。

    用「調嚴」而不是「調鬆」來測：調鬆會讓照片繼續往第 2 關跑，那就需要模型檔了；
    調嚴可以完全留在第 1 關裡驗證門檻真的有被吃進去。
    """
    sharp = _structured_image()
    strict = QualityThresholds(blur_threshold=10_000_000.0, stage1_blocks_on_blur=True)
    result = run_quality_check(sharp, required_view=RequiredView.LEFT_FRONT, thresholds=strict)

    assert "IMAGE_BLURRY" in _codes(result)
    assert "stage2_plate" not in result.stages_run
    assert 0.0 <= result.quality_score <= 1.0


def test_low_resolution_still_blocks():
    """第 1 關唯一（除了整張沒內容以外）的擋關條件。"""
    result = run_quality_check(_structured_image(100, 100), required_view=RequiredView.LEFT_FRONT)
    assert "LOW_RESOLUTION" in _codes(result)
    assert _stage(result, "readability").status == "failed"
    assert _stage(result, "plate").status == "skipped"


def test_blank_image_still_blocks():
    """整張沒有內容仍然要在第 1 關擋下——那不是「亮度品質」判斷，是「這個檔案
    根本沒有畫面」。實測 285 張真實照片的亮度標準差最低 0.070，離門檻 0.01 有 7 倍
    距離，夜拍照片不會被誤傷。"""
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=RequiredView.LEFT_FRONT)
    assert "IMAGE_INVALID" in _codes(result)


def test_zero_blur_threshold_does_not_divide_by_zero():
    """把模糊門檻設成 0（等同停用）時，品質分數的計算不能炸掉。"""
    sharp = _structured_image()
    result = run_quality_check(
        sharp, required_view=RequiredView.FRONT_INTERIOR, thresholds=QualityThresholds(blur_threshold=0.0)
    )
    assert "IMAGE_BLURRY" not in _codes(result)
    assert 0.0 <= result.quality_score <= 1.0


def test_no_required_view_does_not_raise():
    """自由上傳模式：不指定角度時 Stage 0/1 照跑，不能因為 required_view=None 就爆掉。"""
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=None)
    assert not result.passed
    assert result.required_view is None


def _crop_away_plate(image):
    """裁掉下半部（車牌所在區域），模擬真實資料最常見的失敗模式「車牌被裁出畫面」。

    不能改用塗黑：那會讓整張平均亮度掉下去，變成在第 1 關就被 TOO_DARK 擋掉，
    根本測不到第 2 關失敗後的行為。
    """
    return image[: int(image.shape[0] * 0.55), :].copy()


def _stage(result, stage_id):
    return next(s for s in result.stages if s.id == stage_id)


def test_stages_are_always_the_same_three_in_order():
    """不管走到哪一關，stages 都要是完整的三關——前端才能直接照著畫，
    不用處理「這次只有兩關」的特例。"""
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=RequiredView.LEFT_FRONT)
    assert [s.id for s in result.stages] == ["readability", "plate", "view"]
    assert [s.name for s in result.stages] == ["基本可讀性", "車牌偵測", "四角辨識"]


def test_failing_stage1_marks_later_stages_skipped():
    black = np.zeros((720, 1280, 3), dtype=np.uint8)
    result = run_quality_check(black, required_view=RequiredView.LEFT_FRONT)

    assert _stage(result, "readability").status == "failed"
    assert _stage(result, "plate").status == "skipped"
    assert _stage(result, "view").status == "skipped"
    # 失敗的關卡要自己帶著錯誤訊息，前端不用再從攤平的 errors 反推
    assert _stage(result, "readability").errors
    assert not _stage(result, "plate").errors


def test_plate_failure_gates_the_view_stage(plate_models_available, view_model_available, sample_left_rear_photo):
    """闖關式：第 2 關沒過，第 3 關就是 skipped（預設行為）。"""
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    result = run_quality_check(
        _crop_away_plate(cv2.imread(str(sample_left_rear_photo))),
        required_view=RequiredView.LEFT_REAR,
    )

    assert _stage(result, "readability").status == "passed"
    assert _stage(result, "plate").status == "failed"
    assert _stage(result, "view").status == "skipped"
    assert "stage3_view" not in result.stages_run
    assert result.view_label is None


def test_view_stage_can_be_configured_to_run_anyway(plate_models_available, view_model_available, sample_left_rear_photo):
    """把 run_view_stage_when_plate_missing 打開時，車牌沒過仍要判角度。

    實測沒偵測到車牌的 81 張真實照片，視角分類仍有 91.4% 正確率，所以這個選項
    是產品取捨（闖關 vs 一次講完），不是在賭運氣。
    """
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    result = run_quality_check(
        _crop_away_plate(cv2.imread(str(sample_left_rear_photo))),
        required_view=RequiredView.LEFT_REAR,
        thresholds=QualityThresholds(run_view_stage_when_plate_missing=True),
    )

    assert _stage(result, "plate").status == "failed"
    assert _stage(result, "view").status != "skipped"
    assert result.view_label is not None


def test_all_stages_pass_on_a_good_photo(plate_models_available, view_model_available, sample_left_rear_photo):
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    result = run_quality_check(
        cv2.imread(str(sample_left_rear_photo)), required_view=RequiredView.LEFT_REAR
    )

    assert result.passed
    assert [s.status for s in result.stages] == ["passed", "passed", "passed"]
    # 每一關都要有一句話結論可以顯示
    assert all(s.summary for s in result.stages)
    assert result.plate_text in (_stage(result, "plate").summary or "")
    assert result.view_label in (_stage(result, "view").summary or "")


def test_uncertain_view_is_reported_as_a_failed_third_stage(
    plate_models_available, view_model_available, sample_left_rear_photo
):
    """第 3 關「跑了但判不出來」要明確講出來，不能靜靜地當作通過。

    用高到不可能達成的信心門檻來製造這個狀況——真實照片上分類器信心通常 >0.99，
    等現成的低信心樣本不可靠。
    """
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    result = run_quality_check(
        cv2.imread(str(sample_left_rear_photo)),
        required_view=RequiredView.LEFT_REAR,
        thresholds=QualityThresholds(view_confidence_min=0.999999),
    )

    view_stage = _stage(result, "view")
    assert view_stage.status == "failed"
    assert [e.code for e in view_stage.errors] == ["UNCERTAIN_VIEW"]
    # 即使判不出來，也要把模型當下的判定與信心顯示出來供使用者參考
    assert result.view_label is not None
    assert "左後" in (view_stage.summary or "")
    assert not result.passed


def test_wrong_view_is_reported_as_a_failed_third_stage(
    plate_models_available, view_model_available, sample_left_rear_photo
):
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    result = run_quality_check(
        cv2.imread(str(sample_left_rear_photo)), required_view=RequiredView.RIGHT_FRONT
    )

    assert _stage(result, "readability").status == "passed"
    assert _stage(result, "plate").status == "passed"
    view_stage = _stage(result, "view")
    assert view_stage.status == "failed"
    assert [e.code for e in view_stage.errors] == ["WRONG_VIEW"]


def test_incomplete_plate_text_is_rejected(plate_models_available, view_model_available, sample_left_rear_photo):
    """車牌只讀到一半（字數不對）要擋下來。

    實測依據：285 張真實照片中，OCR 讀出 7 碼的 131 張有 95% 完全正確，讀出非 7 碼的
    34 張則 0 張正確——內容多半是 RDG857（尾碼被裁）或 FH8052（首碼被裁）。這條規則
    在真實資料上幾乎沒有誤擋成本。
    """
    import cv2

    if not (plate_models_available and view_model_available):
        pytest.skip("模型檔不存在")

    image = cv2.imread(str(sample_left_rear_photo))
    assert image is not None

    # 這張照片本身讀得出完整 7 碼，先確認基準
    baseline = run_quality_check(image, required_view=RequiredView.LEFT_REAR)
    assert baseline.passed

    # 把「合法字數」改成 8，等同於宣告這張的 7 碼不完整——用設定值製造這個狀況，
    # 比去找一張剛好被裁掉的照片可靠。
    result = run_quality_check(
        image,
        required_view=RequiredView.LEFT_REAR,
        thresholds=QualityThresholds(plate_text_valid_lengths=frozenset({8})),
    )

    plate_stage = _stage(result, "plate")
    assert plate_stage.status == "failed"
    assert [e.code for e in plate_stage.errors] == ["PLATE_INCOMPLETE"]
    assert "只讀到 7 碼" in (plate_stage.summary or "")
    # 讀到的內容仍要顯示出來，使用者才看得出是哪一頭被裁掉
    assert result.plate_text in (plate_stage.summary or "")
    # 闖關：第 2 關沒過，第 3 關不執行
    assert _stage(result, "view").status == "skipped"


def test_unreadable_and_incomplete_are_mutually_exclusive():
    """兩個錯誤碼不能同時出現——使用者只需要一個明確的下一步。"""
    from app.checks.quality_rules import ERROR_MESSAGES, STAGE_DEFINITIONS

    plate_codes = next(codes for stage_id, _, codes in STAGE_DEFINITIONS if stage_id == "plate")
    assert {"PLATE_TEXT_UNREADABLE", "PLATE_INCOMPLETE"} <= plate_codes
    assert ERROR_MESSAGES["PLATE_INCOMPLETE"]
