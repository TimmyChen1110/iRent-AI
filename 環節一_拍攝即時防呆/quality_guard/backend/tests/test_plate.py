"""Stage 2：YOLO 車牌偵測 + fast-plate-ocr 文字辨識。

取代舊的傳統 CV + pytesseract 測試（那版連 fixture 圖都已經不在 repo 裡）。
"""

import cv2
import pytest

from app.checks.plate_yolo import detect_plate, format_plate_number
from validation.parse_filename import normalize_plate_text, parse_filename


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("rcg2235", "RCG-2235"),  # 3 英文 + 4 數字
        ("1234AB", "1234-AB"),  # 4 數字 + 2 英文
        ("  rcg-2235 ", "RCG-2235"),  # 前後空白與既有分隔線都要正規化
        ("AB12", "AB12"),  # 認不出排版就原樣回傳，不亂補分隔線
        ("", ""),
    ],
)
def test_format_plate_number(raw, expected):
    assert format_plate_number(raw) == expected


def test_detect_plate_reads_known_plate(plate_models_available, sample_left_rear_photo):
    if not plate_models_available:
        pytest.skip("車牌偵測/OCR 模型檔不存在（見 app/config.py 的路徑說明）")

    image = cv2.imread(str(sample_left_rear_photo))
    assert image is not None, f"讀不到測試照片：{sample_left_rear_photo}"

    candidate = detect_plate(image)
    assert candidate is not None, "這張照片車牌清楚，應該要偵測得到"

    x1, y1, x2, y2 = candidate.box
    assert x2 > x1 and y2 > y1
    assert 0 <= x1 and 0 <= y1
    assert x2 <= image.shape[1] and y2 <= image.shape[0]
    assert 0.0 <= candidate.score <= 1.0
    assert 0.0 <= candidate.confidence <= 1.0

    ground_truth = parse_filename(sample_left_rear_photo)
    assert ground_truth is not None
    assert normalize_plate_text(candidate.text) == ground_truth.plate_text


def test_detect_plate_returns_none_on_blank_image(plate_models_available):
    if not plate_models_available:
        pytest.skip("車牌偵測/OCR 模型檔不存在")

    import numpy as np

    blank = np.full((720, 1280, 3), 128, dtype=np.uint8)
    assert detect_plate(blank) is None
