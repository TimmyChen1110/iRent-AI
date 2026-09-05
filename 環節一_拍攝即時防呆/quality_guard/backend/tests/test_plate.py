from pathlib import Path

import cv2

from app.checks.plate import detect_plate

FIXTURE_IMAGE = (
    Path(__file__).resolve().parents[2]
    / "車牌 OCR 測試"
    / "2019_Toyota_Corolla_Altis_(front).jpg"
)


def test_detect_plate_on_known_fixture():
    image = cv2.imread(str(FIXTURE_IMAGE))
    assert image is not None, f"cannot read fixture image: {FIXTURE_IMAGE}"

    candidate = detect_plate(image)

    assert candidate is not None, "expected a plate candidate to be found"
    x1, y1, x2, y2 = candidate.box
    assert x2 > x1 and y2 > y1
    # 車牌位置理論上落在畫面下半部
    height = image.shape[0]
    assert (y1 + y2) / 2 > height * 0.4
