"""FastAPI request/response 模型。

四階段整合後的改動（見 `../../整合計畫_四階段辨識.md`）：
- `required_view` 改成可選。不給的話 API 只辨識並回報角度，不做 WRONG_VIEW 擋關，
  對應前端「隨手上傳一張照片，告訴我這是哪個角度」的用法。
- 舊的 `corner_side_guess` / `front_rear_guess`（heuristic 拆成左右 + 前後兩欄）
  拿掉，換成分類模型直接輸出的 `detected_view` + `view_confidence` + 完整機率分布。
"""

from typing import Optional

from pydantic import BaseModel, Field

from app.view_taxonomy import RequiredView


class PhotoQualityCheckRequest(BaseModel):
    rental_id: Optional[str] = None
    car_id: Optional[str] = None
    # None = 不指定角度，只辨識不擋關（見模組 docstring）
    required_view: Optional[RequiredView] = None
    image_base64: str


class QualityErrorResponse(BaseModel):
    code: str
    message: str


class StageResult(BaseModel):
    """對外的一個關卡結果（闖關流程用）。

    前端直接照 `stages` 的順序畫三張卡片，不用自己從錯誤碼反推是哪一關失敗。
    """

    id: str  # readability | plate | view
    name: str  # 顯示名稱，例如「車牌偵測」
    status: str  # passed | failed | skipped
    errors: list["QualityErrorResponse"] = Field(default_factory=list)
    summary: Optional[str] = None  # 一句話結論


class BrightnessDebug(BaseModel):
    mean: float
    std: float
    dark_ratio: float
    bright_ratio: float


class ViewProbability(BaseModel):
    label: str
    probability: float


class DebugInfo(BaseModel):
    # 實際跑到的 stage（提早結束時後面的 stage 不會出現，對應欄位是 None）
    stages_run: list[str] = Field(default_factory=list)

    blur_score: Optional[float] = None
    brightness: Optional[BrightnessDebug] = None
    # 第 1 關注意到但不擋關的觀察，例如「照片偏暗」
    stage1_advisories: list[str] = Field(default_factory=list)

    plate_bbox: Optional[tuple[int, int, int, int]] = None
    plate_area_ratio: Optional[float] = None
    plate_detect_confidence: Optional[float] = None  # YOLO 偵測信心值 0-1

    # 模型原始輸出的類別字串（車頭兩類跟 iRent 命名左右相反，見 view_taxonomy.py）
    view_model_label: Optional[str] = None
    view_probabilities: Optional[list[ViewProbability]] = None

    # advisory only，不影響 passed（見 app/checks/view.py 說明）
    exterior_interior_guess: Optional[str] = None
    exterior_interior_confidence: Optional[float] = None

    elapsed_ms: float


class PhotoQualityCheckResponse(BaseModel):
    passed: bool
    quality_score: float = Field(ge=0, le=1)
    required_view: Optional[RequiredView] = None

    plate_text: Optional[str] = None
    plate_confidence: Optional[float] = None  # OCR 平均字元機率 0-1

    detected_view: Optional[str] = None  # 判定的角度，iRent 命名，例如「左前」
    view_confidence: Optional[float] = None  # top-1 機率 0-1

    # 三個關卡的結果，依闖關順序排列
    stages: list[StageResult] = Field(default_factory=list)
    # 所有關卡的錯誤攤平在一起（保留舊介面；分關卡的版本在 stages 裡）
    errors: list[QualityErrorResponse]
    debug: DebugInfo
