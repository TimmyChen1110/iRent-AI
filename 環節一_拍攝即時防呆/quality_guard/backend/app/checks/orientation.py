"""方向防護網：EXIF 不可靠時，用車牌偵測器判斷照片該不該轉 90 度。

## 什麼時候會用到（以及什麼時候用不到）

大多數情況根本不會觸發。`cv2.imdecode`（`app/main.py` 解碼上傳照片用的）**會**
自動套用 EXIF Orientation，實測 40/40 張 EXIF=6 的直拍照片解出來跟
`ImageOps.exif_transpose` 逐像素相同。所以正常的手機上傳走完 EXIF 就已經是正立的。

這支模組要擋的是 EXIF 靠不住的情況：照片被某些上傳流程或通訊軟體重新編碼、
EXIF 旗標被清掉、但像素沒有跟著轉正。這時圖會橫躺著進 pipeline，而後果不是
「準確率掉一點」而是**整條 pipeline 直接死掉**——車牌偵測器只見過正立車牌，
橫躺時幾乎完全測不到，使用者拿到「未偵測到車牌，請重拍」，然後怎麼重拍都一樣。

## 判斷方法：兩段式

方向有兩個自由度，各自要用不同的訊號，因為沒有任何單一訊號能同時判斷兩者。

**第一段（要不要轉 90 度）用 YOLO 車牌偵測的信心值。** 車牌是扁長方形，偵測器
只在正立車牌上訓練過，圖橫躺時測不到。實測 98 張 val：

    橫躺輸入，判出「需要轉」      79/80 = 0.988
    正立輸入，誤判成「需要轉」     1/87 = 0.011

**第二段（順時針還是逆時針）用 OCR。** 90° 與 270° 差 180 度，兩邊 YOLO 都測得到
車牌、信心值幾乎一樣（例如 0.86 vs 0.88），因為它只是在找一塊高對比矩形，分不出
上下顛倒。但 OCR 分得出來：顛倒的車牌讀不出合法的 7 碼。沿用
`plate_text_valid_lengths` 與 `plate_ocr_min_confidence` 這兩個已經用 285 張真實
照片校準過的門檻當判準，實測 73/79 = 0.924。

**不能用的方法**：拿視角分類器自己的 top-1 信心值去挑方向。實測只有 59.2% 猜對，
而且套下去準確率從 0.990 掉到 0.745。原因是第一/二版模型有 51% 的訓練樣本是
橫躺的（見 `view_preprocess.py`），對兩種方向都很有信心，信心值裡不含方向資訊。

## 刻意不處理的情況

**上下顛倒（180°）不判。** 圖 180° 顛倒時 YOLO 照樣測得到車牌，所以 0° 這一關會
直接通過、不會進到探測。要抓它得對每張照片都多跑一次 OCR 比對，成本加在 100% 的
請求上、只為了處理幾乎不會發生的情況（手機要上下顛倒拿著拍）。目前的行為是
OCR 讀不出來 → `PLATE_TEXT_UNREADABLE` → 要求重拍，是誤擋而不是靜默給錯答案，
可以接受。

**四個方向都測不到車牌的照片不判。** 這些在闖關流程裡本來就會被 Stage 2 擋成
`PLATE_NOT_FOUND`、根本走不到視角分類（`run_view_stage_when_plate_missing`
預設 False），不需要為它們決定方向。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np

from app.checks.plate_yolo import PlateCandidate, detect_plate, plate_character_count

# 逆時針角度 → cv2.rotate 的旗標。原圖要轉這麼多度才會正立。
_ROTATION_FLAGS = {
    90: cv2.ROTATE_90_COUNTERCLOCKWISE,
    180: cv2.ROTATE_180,
    270: cv2.ROTATE_90_CLOCKWISE,
}

# 探測順序：橫躺的照片不是順轉就是逆轉 90 度。
_PROBE_ROTATIONS = (90, 270)


@dataclass
class OrientationResult:
    """`resolve_upright()` 的結果。

    `image_bgr` 一律是「應該拿去跑後面所有階段」的那張圖：不需要旋轉時就是傳進來
    的原圖本身（不複製），需要時是轉正後的新陣列。`plate` 是在 `image_bgr` 這個
    座標系底下偵測到的車牌，Stage 2 直接拿去用、不用重跑一次偵測。
    """

    image_bgr: np.ndarray
    rotation: int  # 已套用的逆時針角度，0 代表原圖就是正的
    plate: Optional[PlateCandidate]
    probed: bool  # 有沒有真的跑過旋轉探測（沒跑代表第一次偵測就成功）


def rotate_bgr(image_bgr: np.ndarray, rotation: int) -> np.ndarray:
    """逆時針旋轉 0/90/180/270 度。0 度直接回傳原陣列，不做多餘的複製。"""
    if rotation == 0:
        return image_bgr
    if rotation not in _ROTATION_FLAGS:
        raise ValueError(f"只支援 0/90/180/270 度，收到 {rotation}")
    return cv2.rotate(image_bgr, _ROTATION_FLAGS[rotation])


def _plate_quality(plate: Optional[PlateCandidate], valid_lengths: frozenset[int]) -> tuple[int, float]:
    """比較兩個方向誰比較像正立：先看讀不讀得出合法車牌，再比 OCR 信心值。

    先比「合法字數」而不是直接比信心值，是因為顛倒的車牌 OCR 也可能給出不低的
    平均字元機率（它對每個字元都很有信心，只是讀出來的是別的字）；字數合不合法
    才是比較硬的訊號。
    """
    if plate is None:
        return (-1, 0.0)
    legal = int(plate_character_count(plate.text) in valid_lengths)
    return (legal, plate.confidence)


def resolve_upright(
    image_bgr: np.ndarray,
    min_conf: float,
    imgsz: int,
    padding: float,
    valid_lengths: frozenset[int],
) -> OrientationResult:
    """偵測車牌；測不到就試著把圖轉正再測一次。

    正常路徑只跑一次偵測（跟沒有這支模組時一樣），只有第一次測不到才會多付
    最多兩次偵測的成本（imgsz=960 約 47ms/次）。
    """

    def _detect(image: np.ndarray) -> Optional[PlateCandidate]:
        return detect_plate(image, min_conf=min_conf, imgsz=imgsz, padding=padding)

    plate = _detect(image_bgr)
    if plate is not None:
        return OrientationResult(image_bgr=image_bgr, rotation=0, plate=plate, probed=False)

    candidates: list[tuple[tuple[int, float], int, np.ndarray, PlateCandidate]] = []
    for rotation in _PROBE_ROTATIONS:
        rotated = rotate_bgr(image_bgr, rotation)
        found = _detect(rotated)
        if found is not None:
            candidates.append((_plate_quality(found, valid_lengths), rotation, rotated, found))

    if not candidates:
        # 哪個方向都找不到車牌：維持原圖，讓 Stage 2 照常回 PLATE_NOT_FOUND。
        return OrientationResult(image_bgr=image_bgr, rotation=0, plate=None, probed=True)

    _, rotation, rotated, found = max(candidates, key=lambda item: item[0])
    return OrientationResult(image_bgr=rotated, rotation=rotation, plate=found, probed=True)
