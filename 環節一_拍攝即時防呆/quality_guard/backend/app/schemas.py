"""FastAPI request/response 模型（改自 irent_photo_quality_guard_plan.md §6.1）。"""

from typing import Optional

from pydantic import BaseModel, Field

from app.view_taxonomy import RequiredView


class PhotoQualityCheckRequest(BaseModel):
    rental_id: Optional[str] = None
    car_id: Optional[str] = None
    required_view: RequiredView
    image_base64: str


class QualityErrorResponse(BaseModel):
    code: str
    message: str


class BrightnessDebug(BaseModel):
    mean: float
    std: float
    dark_ratio: float
    bright_ratio: float


class DebugInfo(BaseModel):
    blur_score: Optional[float] = None
    brightness: Optional[BrightnessDebug] = None
    plate_bbox: Optional[tuple[int, int, int, int]] = None
    plate_area_ratio: Optional[float] = None
    # advisory only，不影響 passed（見 app/checks/quality_rules.py 說明）
    exterior_interior_guess: Optional[str] = None
    exterior_interior_confidence: Optional[float] = None
    corner_side_guess: Optional[str] = None
    front_rear_guess: Optional[str] = None
    elapsed_ms: float


class PhotoQualityCheckResponse(BaseModel):
    passed: bool
    quality_score: float = Field(ge=0, le=1)
    required_view: RequiredView
    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None
    errors: list[QualityErrorResponse]
    debug: DebugInfo
