"""車牌偵測與 OCR。

改寫自 `車牌 OCR 測試/licence_plate_test.py` 的 prototype，泛化重點：

- 拿掉檔案層級的 IMAGE_PATH/OUTPUT_PATH 與 main() 腳本入口，改成可匯入的
  `detect_plate()` 函式。
- 拿掉原本的 `front_plate_location_score`（車牌在畫面左下角才加分）：
  這是針對單一「車頭正面」測試圖的過擬合項，對右前/右後這種車牌會出現在
  右側或偏中的照片是錯的，會系統性地壓低右側車牌候選框的分數。
- HSV 白色車牌偵測原本用 `white_mask[:, int(width * 0.4):] = 0` 把畫面
  右側 60% 直接歸零（等於只搜尋左下角），改成只保留「下半部」的限制，
  讓右前/右後照片的車牌也能被這條路徑偵測到。
"""

from dataclasses import dataclass
import re

import cv2
import numpy as np
import pytesseract


@dataclass
class PlateCandidate:
    box: tuple[int, int, int, int]  # (x1, y1, x2, y2) in original image coordinates
    text: str
    confidence: float
    score: float


def clean_plate_text(text: str) -> str:
    text = text.upper()
    text = re.sub(r"[^A-Z0-9-]", "", text)
    return text


def preprocess_for_ocr(plate_bgr: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(plate_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    gray = cv2.bilateralFilter(gray, 7, 35, 35)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binary = cv2.copyMakeBorder(binary, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    return binary


def ocr_plate(plate_bgr: np.ndarray) -> tuple[str, float]:
    config = (
        "--oem 3 --psm 7 "
        "-c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-"
    )

    try:
        data = pytesseract.image_to_data(
            preprocess_for_ocr(plate_bgr),
            config=config,
            output_type=pytesseract.Output.DICT,
        )
    except pytesseract.TesseractNotFoundError:
        return "", 0.0

    words = []
    confidences = []
    for text, conf in zip(data["text"], data["conf"]):
        text = clean_plate_text(text)
        if not text:
            continue
        try:
            conf_value = float(conf)
        except ValueError:
            conf_value = -1.0
        if conf_value >= 0:
            words.append(text)
            confidences.append(conf_value)

    plate_text = clean_plate_text("".join(words))
    confidence = float(np.mean(confidences)) if confidences else 0.0
    return plate_text, confidence


def find_plate_candidates(image_bgr: np.ndarray) -> list[PlateCandidate]:
    height, width = image_bgr.shape[:2]
    scale = 4
    resized = cv2.resize(image_bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)

    # 車牌通常是淺底深字；black-hat 可以凸顯白底上的深色字元與外框。
    blackhat_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, blackhat_kernel)

    grad_x = cv2.Sobel(blackhat, cv2.CV_32F, 1, 0, ksize=-1)
    grad_x = np.absolute(grad_x)
    min_value, max_value = np.min(grad_x), np.max(grad_x)
    if max_value > min_value:
        grad_x = 255 * ((grad_x - min_value) / (max_value - min_value))
    grad_x = grad_x.astype("uint8")

    close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 7))
    closed = cv2.morphologyEx(grad_x, cv2.MORPH_CLOSE, close_kernel)
    _, thresh = cv2.threshold(closed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    thresh = cv2.erode(thresh, None, iterations=1)
    thresh = cv2.dilate(thresh, None, iterations=2)

    candidates: list[PlateCandidate] = []

    scaled_height, scaled_width = resized.shape[:2]
    image_area = scaled_width * scaled_height

    def add_candidate(x, y, w, h, source_bonus=0.0):
        aspect_ratio = w / float(h)
        area_ratio = (w * h) / float(image_area)

        pad_x = int(w * 0.18)
        pad_y = int(h * 0.25)
        x1 = max((x - pad_x) // scale, 0)
        y1 = max((y - pad_y) // scale, 0)
        x2 = min((x + w + pad_x) // scale, width)
        y2 = min((y + h + pad_y) // scale, height)

        crop = image_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return

        # 台灣車牌至少 6 個字元；候選框小到不可能容納完整車牌時直接捨棄，
        # 避免雜訊小區塊靠 tesseract 對單一字元的偏高信心值勝出（實測發現
        # 這是真實資料集裡準確率偏低的主因：真車牌區塊常因整串 OCR
        # 信心值偏低而輸給雜訊區塊裡一兩個字元的高信心誤判）。
        if (x2 - x1) < 30:
            return

        text, ocr_confidence = ocr_plate(crop)
        crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        crop_edges = cv2.Canny(crop_gray, 80, 180)
        edge_density = cv2.countNonZero(crop_edges) / float(crop_edges.size)

        # 車牌文字通常是 6~7 碼；OCR 讀到的字元數太少時，即使單字信心值
        # 很高也不太可信，用長度係數大幅壓低其對總分的貢獻——實測發現
        # 雜訊區塊常被 tesseract 對單一字元給出偏高信心值，若不壓低，
        # 會系統性地贏過真正車牌形狀但整串信心值較低的候選框。
        length_factor = min(1.0, len(text) / 5.0)

        # 幾何形狀（長寬比、面積）是比 OCR 信心值更可靠的「這是不是車牌」
        # 訊號，所以權重要夠高，OCR 只當作候選框之間的輔助排序依據。
        geometry_score = area_ratio * 4000 + max(0, 6.0 - abs(aspect_ratio - 2.2)) * 3
        ocr_score = ocr_confidence * length_factor * 0.4 + (
            30 if re.fullmatch(r"[A-Z0-9]{2,4}-?[A-Z0-9]{2,4}", text) else 0
        )
        score = ocr_score + geometry_score + edge_density * 20 + source_bonus

        candidates.append(
            PlateCandidate(
                box=(x1, y1, x2, y2),
                text=text,
                confidence=ocr_confidence,
                score=score,
            )
        )

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / float(h)
        area_ratio = (w * h) / float(image_area)

        if not (2.0 <= aspect_ratio <= 6.5):
            continue
        if not (0.001 <= area_ratio <= 0.08):
            continue
        if y < scaled_height * 0.55:
            continue

        add_candidate(x, y, w, h)

    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    white_mask = cv2.inRange(hsv, (0, 0, 160), (180, 80, 255))
    # 車牌一定落在畫面下半部，但左右兩側都要搜尋（原 prototype 只搜左下角，
    # 對右前/右後照片會系統性漏掉車牌）。
    white_mask[: int(height * 0.45), :] = 0
    white_contours, _ = cv2.findContours(white_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in white_contours:
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = w / float(h)
        area = w * h
        if not (0.8 <= aspect_ratio <= 5.5):
            continue
        if not (80 <= area <= 3500):
            continue
        center_y = (y + h / 2) / height
        if not (0.58 <= center_y <= 0.82):
            continue
        add_candidate(x * scale, y * scale, w * scale, h * scale, source_bonus=8.0)

    return sorted(candidates, key=lambda item: item.score, reverse=True)


def detect_plate(image_bgr: np.ndarray, min_score: float = 5.0) -> PlateCandidate | None:
    """回傳分數最高且達門檻的車牌候選框，找不到則回傳 None。"""
    candidates = find_plate_candidates(image_bgr)
    if not candidates:
        return None
    best = candidates[0]
    if best.score < min_score:
        return None
    return best
