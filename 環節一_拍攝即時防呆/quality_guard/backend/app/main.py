"""iRent Photo Quality Guard API（plan.md §6.1）。

啟動：
    cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
"""

import base64
import binascii
import time

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.checks.quality_rules import ERROR_MESSAGES, run_quality_check
from app.config import DEFAULT_THRESHOLDS
from app.schemas import (
    BrightnessDebug,
    DebugInfo,
    PhotoQualityCheckRequest,
    PhotoQualityCheckResponse,
    QualityErrorResponse,
)

app = FastAPI(title="iRent Photo Quality Guard")

# Demo 用網頁前端跟 API 不同來源（file:// 或 http.server 另開的埠），
# 黑客松 demo 直接全開，正式環境要收斂成白名單。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decode_base64_image(image_base64: str) -> np.ndarray | None:
    try:
        if "," in image_base64 and image_base64.strip().startswith("data:"):
            image_base64 = image_base64.split(",", 1)[1]
        raw_bytes = base64.b64decode(image_base64, validate=True)
    except (binascii.Error, ValueError):
        return None

    buffer = np.frombuffer(raw_bytes, dtype=np.uint8)
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    return image


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.post("/api/photo-quality/check", response_model=PhotoQualityCheckResponse)
def check_photo_quality(request: PhotoQualityCheckRequest) -> PhotoQualityCheckResponse:
    start = time.perf_counter()
    image = _decode_base64_image(request.image_base64)

    if image is None:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return PhotoQualityCheckResponse(
            passed=False,
            quality_score=0.0,
            required_view=request.required_view,
            plate_text=None,
            plate_confidence=None,
            errors=[QualityErrorResponse(code="IMAGE_INVALID", message=ERROR_MESSAGES["IMAGE_INVALID"])],
            debug=DebugInfo(elapsed_ms=round(elapsed_ms, 1)),
        )

    result = run_quality_check(image, required_view=request.required_view, thresholds=DEFAULT_THRESHOLDS)
    elapsed_ms = (time.perf_counter() - start) * 1000

    brightness_debug = None
    if result.brightness is not None:
        brightness_debug = BrightnessDebug(
            mean=result.brightness.mean,
            std=result.brightness.std,
            dark_ratio=result.brightness.dark_ratio,
            bright_ratio=result.brightness.bright_ratio,
        )

    return PhotoQualityCheckResponse(
        passed=result.passed,
        quality_score=result.quality_score,
        required_view=result.required_view,
        plate_text=result.plate_text,
        plate_confidence=result.plate_confidence,
        errors=[QualityErrorResponse(code=e.code, message=e.message) for e in result.errors],
        debug=DebugInfo(
            blur_score=result.blur_score,
            brightness=brightness_debug,
            plate_bbox=result.plate_bbox,
            plate_area_ratio=result.plate_area_ratio,
            exterior_interior_guess=result.exterior_interior_guess,
            exterior_interior_confidence=result.exterior_interior_confidence,
            corner_side_guess=result.corner_side_guess,
            front_rear_guess=result.front_rear_guess,
            elapsed_ms=round(elapsed_ms, 1),
        ),
    )
