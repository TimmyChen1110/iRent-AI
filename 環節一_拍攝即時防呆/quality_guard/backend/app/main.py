"""iRent Photo Quality Guard API — 四階段拍照防呆。

啟動：
    cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

三個模型（YOLO 車牌偵測、fast-plate-ocr、MobileNetV2 視角分類）在
lifespan startup 時載入一次；CLI 版本那種「每次呼叫重新載入」的寫法搬進常駐
服務會讓每個 request 多付 ~11.5MB 的模型載入成本。
"""

import base64
import binascii
import logging
import time
from contextlib import asynccontextmanager

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.checks import plate_yolo, view_classifier
from app.checks.quality_rules import ERROR_MESSAGES, QualityResult, run_quality_check
from app.config import DEFAULT_THRESHOLDS
from app.schemas import (
    BrightnessDebug,
    DebugInfo,
    PhotoQualityCheckRequest,
    PhotoQualityCheckResponse,
    QualityErrorResponse,
    StageResult,
    ViewProbability,
)
from app.view_taxonomy import validate_classifier_classes

logger = logging.getLogger(__name__)

# 模型載入狀態：/healthz 會回報，方便前端/維運知道是「還在暖機」還是「掛了」。
_model_status: dict[str, str] = {"plate": "not_loaded", "view": "not_loaded"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 載入失敗不讓整個服務起不來——Stage 0/1 的純 CV 檢查不需要模型，仍然可用；
    # 缺哪個模型會在 /healthz 顯示，打 check API 時該 stage 會回 500 而不是靜默放行。
    try:
        plate_yolo.warmup()
        _model_status["plate"] = "ready"
    except Exception as exc:
        _model_status["plate"] = f"failed: {exc}"
        logger.exception("車牌偵測/OCR 模型載入失敗")

    try:
        view_classifier.warmup()
        validate_classifier_classes(view_classifier.get_classes())
        _model_status["view"] = "ready"
    except Exception as exc:
        _model_status["view"] = f"failed: {exc}"
        logger.exception("視角分類模型載入失敗")

    yield


app = FastAPI(title="iRent Photo Quality Guard", lifespan=lifespan)

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
    return cv2.imdecode(buffer, cv2.IMREAD_COLOR)


@app.get("/healthz")
def healthz():
    ready = all(status == "ready" for status in _model_status.values())
    return {"status": "ok" if ready else "degraded", "models": dict(_model_status)}


@app.post("/api/photo-quality/check", response_model=PhotoQualityCheckResponse)
def check_photo_quality(request: PhotoQualityCheckRequest) -> PhotoQualityCheckResponse:
    start = time.perf_counter()
    image = _decode_base64_image(request.image_base64)

    if image is None:
        return PhotoQualityCheckResponse(
            passed=False,
            quality_score=0.0,
            required_view=request.required_view,
            stages=[
                StageResult(
                    id="readability",
                    name="基本可讀性",
                    status="failed",
                    errors=[
                        QualityErrorResponse(
                            code="IMAGE_INVALID", message=ERROR_MESSAGES["IMAGE_INVALID"]
                        )
                    ],
                    summary="檔案無法解碼成圖片",
                ),
                StageResult(id="plate", name="車牌偵測", status="skipped", summary="前一關沒過，尚未執行"),
                StageResult(id="view", name="四角辨識", status="skipped", summary="前一關沒過，尚未執行"),
            ],
            errors=[
                QualityErrorResponse(code="IMAGE_INVALID", message=ERROR_MESSAGES["IMAGE_INVALID"])
            ],
            debug=DebugInfo(
                stages_run=["stage0_readability"],
                elapsed_ms=round((time.perf_counter() - start) * 1000, 1),
            ),
        )

    result = run_quality_check(
        image, required_view=request.required_view, thresholds=DEFAULT_THRESHOLDS
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    return _to_response(result, elapsed_ms)


def _to_response(result: QualityResult, elapsed_ms: float) -> PhotoQualityCheckResponse:
    brightness_debug = None
    if result.brightness is not None:
        brightness_debug = BrightnessDebug(
            mean=result.brightness.mean,
            std=result.brightness.std,
            dark_ratio=result.brightness.dark_ratio,
            bright_ratio=result.brightness.bright_ratio,
        )

    view_probabilities = None
    if result.view_probabilities is not None:
        view_probabilities = [
            ViewProbability(label=label, probability=probability)
            for label, probability in result.view_probabilities
        ]

    return PhotoQualityCheckResponse(
        passed=result.passed,
        quality_score=result.quality_score,
        required_view=result.required_view,
        plate_text=result.plate_text,
        plate_confidence=result.plate_confidence,
        detected_view=result.view_label,
        view_confidence=result.view_confidence,
        stages=[
            StageResult(
                id=stage.id,
                name=stage.name,
                status=stage.status,
                errors=[QualityErrorResponse(code=e.code, message=e.message) for e in stage.errors],
                summary=stage.summary,
            )
            for stage in result.stages
        ],
        errors=[QualityErrorResponse(code=e.code, message=e.message) for e in result.errors],
        debug=DebugInfo(
            stages_run=result.stages_run,
            orientation_rotation=result.orientation_rotation,
            blur_score=result.blur_score,
            brightness=brightness_debug,
            stage1_advisories=result.stage1_advisories,
            plate_bbox=result.plate_bbox,
            plate_area_ratio=result.plate_area_ratio,
            plate_detect_confidence=result.plate_detect_confidence,
            view_model_label=result.view_model_label,
            view_probabilities=view_probabilities,
            exterior_interior_guess=result.exterior_interior_guess,
            exterior_interior_confidence=result.exterior_interior_confidence,
            elapsed_ms=round(elapsed_ms, 1),
        ),
    )
