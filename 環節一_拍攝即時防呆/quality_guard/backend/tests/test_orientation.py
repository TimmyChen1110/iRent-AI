"""方向防護網（app/checks/orientation.py）。

幾何與挑選邏輯不需要模型檔；真的要跑偵測的案例會在缺模型時 skip。
"""

import cv2
import numpy as np
import pytest

from app.checks.orientation import _plate_quality, resolve_upright, rotate_bgr
from app.checks.plate_yolo import PlateCandidate
from app.config import DEFAULT_THRESHOLDS

VALID_LENGTHS = frozenset({7})


def _asymmetric_image() -> np.ndarray:
    """四個角都不一樣的圖，旋轉後才分得出來轉對沒有。"""
    image = np.zeros((60, 100, 3), dtype=np.uint8)
    image[:30, :50] = (255, 0, 0)
    image[:30, 50:] = (0, 255, 0)
    image[30:, :50] = (0, 0, 255)
    image[30:, 50:] = (255, 255, 0)
    return image


def test_rotate_0_度回傳同一個陣列不複製():
    image = _asymmetric_image()
    assert rotate_bgr(image, 0) is image


@pytest.mark.parametrize("rotation", [90, 270])
def test_rotate_90_與_270_會交換寬高(rotation):
    image = _asymmetric_image()
    rotated = rotate_bgr(image, rotation)
    assert rotated.shape[:2] == image.shape[:2][::-1]


def test_rotate_90_再_270_回到原圖():
    image = _asymmetric_image()
    assert np.array_equal(rotate_bgr(rotate_bgr(image, 90), 270), image)


def test_rotate_180_兩次回到原圖():
    image = _asymmetric_image()
    assert np.array_equal(rotate_bgr(rotate_bgr(image, 180), 180), image)


def test_rotate_不支援的角度直接報錯():
    with pytest.raises(ValueError, match="0/90/180/270"):
        rotate_bgr(_asymmetric_image(), 45)


def _candidate(text: str, confidence: float) -> PlateCandidate:
    return PlateCandidate(box=(0, 0, 10, 10), text=text, confidence=confidence, score=0.9)


def test_合法字數優先於_ocr_信心值():
    """顛倒的車牌 OCR 也可能很有信心，所以先比字數合不合法。"""
    legal_but_unsure = _candidate("ABC-1234", 0.5)
    illegal_but_confident = _candidate("XY-999", 0.99)
    assert _plate_quality(legal_but_unsure, VALID_LENGTHS) > _plate_quality(
        illegal_but_confident, VALID_LENGTHS
    )


def test_字數同樣合法時才比信心值():
    assert _plate_quality(_candidate("ABC-1234", 0.9), VALID_LENGTHS) > _plate_quality(
        _candidate("XYZ-5678", 0.4), VALID_LENGTHS
    )


def test_沒偵測到車牌排在所有候選之後():
    assert _plate_quality(None, VALID_LENGTHS) < _plate_quality(_candidate("", 0.0), VALID_LENGTHS)


def test_偵測得到時不做任何旋轉探測(plate_models_available, sample_left_rear_photo):
    """正常照片走的是原本那條路：一次偵測、不旋轉、不多花錢。"""
    if not plate_models_available:
        pytest.skip("缺少車牌偵測/OCR 模型檔")

    image = cv2.imread(str(sample_left_rear_photo))
    result = resolve_upright(
        image,
        min_conf=DEFAULT_THRESHOLDS.plate_detect_min_conf,
        imgsz=DEFAULT_THRESHOLDS.plate_detect_imgsz,
        padding=DEFAULT_THRESHOLDS.plate_crop_padding,
        valid_lengths=DEFAULT_THRESHOLDS.plate_text_valid_lengths,
    )
    assert result.rotation == 0
    assert result.probed is False
    assert result.image_bgr is image
    assert result.plate is not None


def test_橫躺的照片會被轉正並讀回同一個車牌(plate_models_available, sample_left_rear_photo):
    """EXIF 被清掉、像素橫躺的照片：轉正後要讀回跟正立版本一樣的車牌號碼。"""
    if not plate_models_available:
        pytest.skip("缺少車牌偵測/OCR 模型檔")

    upright = cv2.imread(str(sample_left_rear_photo))
    kwargs = dict(
        min_conf=DEFAULT_THRESHOLDS.plate_detect_min_conf,
        imgsz=DEFAULT_THRESHOLDS.plate_detect_imgsz,
        padding=DEFAULT_THRESHOLDS.plate_crop_padding,
        valid_lengths=DEFAULT_THRESHOLDS.plate_text_valid_lengths,
    )
    expected = resolve_upright(upright, **kwargs).plate
    if expected is None or not expected.text:
        pytest.skip("這張樣本照片本身就讀不出車牌，測不到方向修正")

    sideways = rotate_bgr(upright, 90)
    result = resolve_upright(sideways, **kwargs)

    assert result.probed is True
    assert result.rotation == 270, "轉正需要的角度應該正好抵銷測試裡轉的 90 度"
    assert result.image_bgr.shape == upright.shape
    assert result.plate is not None
    assert result.plate.text == expected.text


def test_沒有車牌的照片維持原方向不亂轉(plate_models_available):
    """四個方向都測不到車牌時要保持原圖，讓 Stage 2 照常回 PLATE_NOT_FOUND。"""
    if not plate_models_available:
        pytest.skip("缺少車牌偵測/OCR 模型檔")

    noise = np.random.default_rng(7).integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    result = resolve_upright(
        noise,
        min_conf=DEFAULT_THRESHOLDS.plate_detect_min_conf,
        imgsz=DEFAULT_THRESHOLDS.plate_detect_imgsz,
        padding=DEFAULT_THRESHOLDS.plate_crop_padding,
        valid_lengths=DEFAULT_THRESHOLDS.plate_text_valid_lengths,
    )
    assert result.rotation == 0
    assert result.plate is None
    assert result.image_bgr is noise
