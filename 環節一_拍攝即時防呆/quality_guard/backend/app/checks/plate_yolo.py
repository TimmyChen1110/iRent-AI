"""Stage 2：車牌偵測 + 文字辨識（隊友的 YOLO 模型 + fast-plate-ocr）。

取代原本 `app/checks/plate.py` 的傳統 CV + pytesseract heuristic（實測文字
精確辨識率 0%）。邏輯搬自 `app_models/main.py`，但做了三件常駐服務必要的改造：

1. **不吃檔案路徑**：`detect_plate()` 直接吃 `np.ndarray`（BGR），不再需要先把
   上傳的照片寫到磁碟。
2. **模型只載入一次**：CLI 版本每次執行都 `YOLO(...)` / `LicensePlateRecognizer(...)`，
   在 FastAPI 裡那樣做等於每個 request 重載 11.5MB 模型。這裡改成 module-level
   單例 + `threading.Lock` 保護（uvicorn 預設 thread pool 會併發呼叫同步 endpoint）。
3. **不 print、不 sys.exit**：找不到車牌回傳 `None`，載入失敗丟例外由 API 層處理。

`PlateCandidate` 刻意保留 `box` / `text` / `confidence` / `score` 四個欄位，
讓 `framing.py`、`quality_rules.py` 不用大改；但 `confidence` 的刻度從
pytesseract 的 0-100 換成 fast-plate-ocr 的 0-1（見 config.py 註解）。
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

from app.config import (
    PLATE_DETECT_DEVICE,
    PLATE_DETECT_MODEL_PATH,
    PLATE_OCR_CONFIG_PATH,
    PLATE_OCR_DEVICE,
    PLATE_OCR_ONNX_PATH,
)

# 台灣車牌常見兩種排版，補上分隔線比較好讀（搬自 app_models/main.py）。
FOUR_DIGITS_TWO_LETTERS_RE = re.compile(r"^(\d{4})([A-Z]{2})$")
THREE_LETTERS_FOUR_DIGITS_RE = re.compile(r"^([A-Z]{3})(\d{4})$")
# fast-plate-ocr 會用 padding 字元把輸出補到固定長度，要先清掉。
NON_PLATE_CHAR_RE = re.compile(r"[^A-Z0-9]")


@dataclass
class PlateCandidate:
    box: tuple[int, int, int, int]  # (x1, y1, x2, y2)，原圖座標
    text: str  # 格式化後的車牌號碼，OCR 讀不出來時是空字串
    confidence: float  # OCR 平均字元機率，0-1
    score: float  # YOLO 偵測信心值，0-1
    char_confidences: list[float] = field(default_factory=list)


_detector = None
_recognizer = None
_detector_lock = threading.Lock()
_recognizer_lock = threading.Lock()
# ultralytics / onnxruntime 的 session 不保證 thread-safe，推論本身也上鎖。
# 單張圖片推論 ~50-200ms，黑客松 demo 的併發量下序列化不會是瓶頸；真的要
# 提高吞吐量應該是開多個 worker process，而不是拿掉這把鎖。
_inference_lock = threading.Lock()


def _require(path: Path, what: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(
            f"{what} 不存在：{path}\n"
            f"請確認 app_models/ 的模型檔有跟著 repo 一起拉下來，或用 app/config.py "
            f"註解裡的環境變數指到正確位置。"
        )
    return path


def get_detector():
    """回傳共用的 YOLO 車牌偵測模型（第一次呼叫時載入）。"""
    global _detector
    if _detector is None:
        with _detector_lock:
            if _detector is None:
                from ultralytics import YOLO  # 匯入成本高，延遲到真的要用時再付

                _detector = YOLO(str(_require(PLATE_DETECT_MODEL_PATH, "YOLO 車牌偵測模型")))
    return _detector


def get_recognizer():
    """回傳共用的 fast-plate-ocr 辨識器（第一次呼叫時載入）。"""
    global _recognizer
    if _recognizer is None:
        with _recognizer_lock:
            if _recognizer is None:
                from fast_plate_ocr import LicensePlateRecognizer

                _recognizer = LicensePlateRecognizer(
                    device=PLATE_OCR_DEVICE,
                    onnx_model_path=str(_require(PLATE_OCR_ONNX_PATH, "OCR ONNX 模型")),
                    plate_config_path=str(_require(PLATE_OCR_CONFIG_PATH, "OCR plate config")),
                )
    return _recognizer


def warmup() -> None:
    """FastAPI startup 時呼叫：把兩個模型都載入，讓第一個 request 不用等載入。"""
    get_detector()
    get_recognizer()


def _clamp(value: float, lower: int, upper: int) -> int:
    return max(lower, min(int(round(value)), upper))


def _padded_xyxy(
    xyxy: tuple[float, float, float, float],
    image_width: int,
    image_height: int,
    padding: float,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = xyxy
    pad_x = (x2 - x1) * padding
    pad_y = (y2 - y1) * padding

    left = _clamp(x1 - pad_x, 0, image_width - 1)
    top = _clamp(y1 - pad_y, 0, image_height - 1)
    right = _clamp(x2 + pad_x, left + 1, image_width)
    bottom = _clamp(y2 + pad_y, top + 1, image_height)
    return left, top, right, bottom


def format_plate_number(plate: str) -> str:
    """把 OCR 原始輸出清成車牌號碼；認得出台灣排版就補上分隔線。"""
    plate = NON_PLATE_CHAR_RE.sub("", (plate or "").strip().upper())

    match = FOUR_DIGITS_TWO_LETTERS_RE.fullmatch(plate)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    match = THREE_LETTERS_FOUR_DIGITS_RE.fullmatch(plate)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    return plate


def plate_character_count(text: str) -> int:
    """車牌的有效字元數，不算 format_plate_number 補上的分隔線。

    長度檢查一律走這個函式，不要直接 len(candidate.text)——那會把 "RCG-2235" 算成
    8 碼。
    """
    return len(NON_PLATE_CHAR_RE.sub("", (text or "").upper()))


def detect_plate_boxes(
    image_bgr: np.ndarray,
    min_conf: float,
    imgsz: int,
    padding: float,
) -> list[tuple[tuple[int, int, int, int], float]]:
    """回傳 [(bbox, yolo_conf), ...]，依信心值由高到低排序。"""
    detector = get_detector()
    height, width = image_bgr.shape[:2]

    with _inference_lock:
        results = detector.predict(
            source=image_bgr,
            conf=min_conf,
            imgsz=imgsz,
            device=PLATE_DETECT_DEVICE,
            save=False,
            verbose=False,
        )
    if not results:
        return []

    boxes = results[0].boxes
    if boxes is None or len(boxes) == 0:
        return []

    detections = []
    for box in boxes:
        conf = float(box.conf[0]) if box.conf is not None else 0.0
        xyxy = tuple(float(v) for v in box.xyxy[0].tolist())
        detections.append((_padded_xyxy(xyxy, width, height, padding), conf))

    detections.sort(key=lambda item: item[1], reverse=True)
    return detections


def read_plate_text(plate_crop_bgr: np.ndarray) -> tuple[str, float, list[float]]:
    """對已裁好的車牌小圖跑 OCR，回傳 (格式化文字, 平均字元機率, 每字元機率)。"""
    if plate_crop_bgr.size == 0:
        return "", 0.0, []

    recognizer = get_recognizer()
    crop_rgb = cv2.cvtColor(plate_crop_bgr, cv2.COLOR_BGR2RGB)

    with _inference_lock:
        predictions = recognizer.run([crop_rgb], return_confidence=True)
    if not predictions:
        return "", 0.0, []

    prediction = predictions[0]
    text = format_plate_number(prediction.plate)

    char_probs = getattr(prediction, "char_probs", None)
    if char_probs is None:
        return text, 0.0, []
    probs = [float(p) for p in np.asarray(char_probs).ravel().tolist()]
    mean_conf = float(np.mean(probs)) if probs else 0.0
    return text, mean_conf, probs


def detect_plate(
    image_bgr: np.ndarray,
    min_conf: float = 0.25,
    imgsz: int = 640,
    padding: float = 0.08,
) -> Optional[PlateCandidate]:
    """偵測信心值最高的車牌並讀出文字；沒偵測到任何車牌回傳 None。

    注意「沒偵測到車牌」與「偵測到但讀不出文字」是兩件事：後者仍會回傳
    `PlateCandidate`（`text` 可能是空字串、`confidence` 偏低），由
    `quality_rules.py` 決定要不要因為讀不出文字而擋關。
    """
    detections = detect_plate_boxes(image_bgr, min_conf=min_conf, imgsz=imgsz, padding=padding)
    if not detections:
        return None

    box, yolo_conf = detections[0]
    x1, y1, x2, y2 = box
    crop = image_bgr[y1:y2, x1:x2]
    text, ocr_conf, char_probs = read_plate_text(crop)

    return PlateCandidate(
        box=box,
        text=text,
        confidence=ocr_conf,
        score=yolo_conf,
        char_confidences=char_probs,
    )
