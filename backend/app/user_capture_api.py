"""Mobile user-app photo ingestion.

This router persists evidence produced by on-device Core ML. It deliberately never
imports or runs the server-side detection, OCR, or view-classification models.

  POST /v1/mobile-inspections/photos                     上傳一張照片（冪等；既有欄位全部保留）
  GET  /v1/mobile-inspections/rentals/{rental_id}        App 端狀態（收到幾張、分析中／完成；不回傳判定內容）
  POST /v1/mobile-inspections/rentals/{rental_id}/restart 示範租約重新開始（只允許 demo 租約）
  GET  /photos/mobile/{path}                             供管理者端讀 App 上傳的照片

照片落地後交給 rental_inspections.ingest_photo()：建立／更新 Rental、Inspection、
InspectionPhoto，齊 5 張自動建立 Pickup Baseline 或觸發還車 AI 比對（背景執行）。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

import demo_inspection_fixture
import paths
import rental_inspections as ri

router = APIRouter(tags=["mobile-inspections"])

VALID_STAGES = set(ri.STAGE_TO_TYPE)
VALID_VIEWS = set(ri.ALL_ANGLES)
VALID_VALIDATION_MODES = {"coreml", "demo"}
VALID_PLATE_CONFIRMATIONS = {"ocr", "manual", "user_confirmed_mismatch"}


def _normalise_plate(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _resolve_view(view: str, angle: str | None) -> str:
    """沿用 ViewClassifier 的中文命名；也接受規格代號（FRONT_LEFT…／INTERIOR）。"""
    if view in VALID_VIEWS:
        return view
    code = (angle or view or "").upper()
    if code in ri.CODE_TO_ANGLE:
        return ri.CODE_TO_ANGLE[code]
    raise HTTPException(422, "view must be one of 左前、右前、左後、右後、車內")


@router.post("/v1/mobile-inspections/photos", status_code=201)
async def submit_photo(
    rental_id: str = Form(...),
    car_id: str = Form(...),
    expected_plate: str = Form(...),
    stage: str = Form(...),
    view: str = Form(...),
    recognized_plate: str = Form(...),
    image_sha256: str = Form(...),
    captured_at: str = Form(...),
    local_result_json: str = Form(...),
    photo: UploadFile = File(...),
    # ---- 以下為本輪新增的選填欄位（舊版 App 不帶也能上傳） ----
    photo_id: str | None = Form(None),            # App 端 UUID：PendingUploadSync 重試不重複建檔
    vehicle_id: str | None = Form(None),          # 同 car_id；規格命名
    inspection_type: str | None = Form(None),     # PICKUP | RETURN（同 stage；規格命名）
    photo_category: str | None = Form(None),      # exterior | interior
    angle: str | None = Form(None),               # FRONT_LEFT … INTERIOR（同 view；規格命名）
    validation_mode: str | None = Form(None),     # coreml（預設）| demo
    plate_confirmation: str | None = Form(None),  # ocr（預設）| manual（OCR 失敗、使用者手動輸入）| user_confirmed_mismatch（OCR 與租約不符、使用者確認同一台車 → 待人工複核）
):
    if inspection_type and stage not in VALID_STAGES:
        stage = ri.TYPE_TO_STAGE.get(inspection_type.upper(), stage)
    if stage not in VALID_STAGES:
        raise HTTPException(422, "stage must be pickup or return")
    view = _resolve_view(view, angle)
    if photo_category and photo_category != ri.photo_category_for(view):
        raise HTTPException(422, "photo_category does not match view")
    mode = (validation_mode or "coreml").lower()
    if mode not in VALID_VALIDATION_MODES:
        raise HTTPException(422, "validation_mode must be coreml or demo")

    rental = ri.get_rental(rental_id)
    if rental is None:
        raise HTTPException(404, "unknown rental_id")
    if mode == "demo" and not rental["demo"]:
        raise HTTPException(422, "demo validation is only accepted for demo rentals")
    registered_plate = rental["plate"]
    if _normalise_plate(expected_plate) != _normalise_plate(registered_plate):
        raise HTTPException(422, "expected_plate does not match the rental")
    confirmation = (plate_confirmation or "ocr").lower()
    if confirmation not in VALID_PLATE_CONFIRMATIONS:
        raise HTTPException(422, "plate_confirmation must be ocr, manual or user_confirmed_mismatch")
    plate_mismatch = view != ri.INTERIOR_ANGLE and _normalise_plate(recognized_plate) != _normalise_plate(registered_plate)
    if plate_mismatch and confirmation != "user_confirmed_mismatch":
        # 預設守門不變：車牌不符一律拒收。只有使用者明確確認「同一台車」才收下，並在 validation 留下記號待人工複核。
        raise HTTPException(422, "recognized_plate does not match the rental")

    try:
        local_result = json.loads(local_result_json)
    except json.JSONDecodeError as error:
        raise HTTPException(422, "local_result_json must be valid JSON") from error
    if local_result.get("passed") is not True:
        raise HTTPException(422, "only on-device-passed photos are accepted")

    data = await photo.read()
    actual_hash = hashlib.sha256(data).hexdigest()
    if actual_hash != image_sha256:
        raise HTTPException(422, "image_sha256 does not match file content")

    suffix = Path(photo.filename or "photo.jpg").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".heic"}:
        raise HTTPException(415, "unsupported image format")

    upload_directory = ri.upload_root() / rental_id / stage
    upload_directory.mkdir(parents=True, exist_ok=True)
    stored_path = upload_directory / f"{view}-{image_sha256[:16]}{suffix}"
    if not stored_path.exists():
        stored_path.write_bytes(data)

    local_result.setdefault("validationMode", mode)
    if confirmation != "ocr":
        local_result["plateSource"] = confirmation
        local_result["plateText"] = recognized_plate
    try:
        ingest = ri.ingest_photo(
            rental_id=rental_id, stage=stage, view=view, image_sha256=image_sha256, captured_at=captured_at,
            storage_path=str(stored_path), local_result=local_result, photo_id=photo_id,
            validation_mode=mode, source="mobile")
    except ri.IngestError as e:
        raise HTTPException(e.status, e.detail) from e

    return {
        "rental_id": rental_id,
        "vehicle_id": vehicle_id or car_id,
        "stage": stage,
        "inspection_type": ingest["inspection_type"],
        "view": view,
        "angle": ri.ANGLE_CODES[view],
        "photo_category": ri.photo_category_for(view),
        "image_sha256": image_sha256,
        "photo_id": ingest["photo_id"],
        "deduplicated": ingest["deduplicated"],
        "plate_confirmation": confirmation,
        "plate_mismatch": plate_mismatch,
        "rental_status": ingest["rental_status"],
        "completeness": ingest["completeness"],
        "triggered": ingest["triggered"],
    }


@router.get("/v1/mobile-inspections/rentals/{rental_id}")
def rental_status(rental_id: str):
    status = ri.app_status(rental_id)
    if status is None:
        raise HTTPException(404, "unknown rental_id")
    return status


@router.post("/v1/mobile-inspections/rentals/{rental_id}/restart")
def restart_rental(rental_id: str):
    """示範租約重新開始：清掉這筆租約的檢查紀錄與衍生案件／任務，讓 App 可以從取車重演。"""
    try:
        cleared = ri.restart_rental(rental_id)
    except ri.IngestError as e:
        raise HTTPException(e.status, e.detail) from e
    from server import reset_case_state  # noqa: PLC0415  與 Demo 重置同一條清理路徑
    reset_case_state(cleared["cleared_cases"])
    return cleared


@router.get("/photos/mobile/{rel_path:path}")
def mobile_photo(rel_path: str):
    target = ri.resolve_mobile_photo(rel_path)
    if target is None:
        raise HTTPException(404)
    return FileResponse(target)


# 舊常數保留給既有測試／文件參考；實際登記改由 rental_inspections.ensure_registered_rentals()
DEMO_RENTAL_PLATES = {r["rental_id"]: r["plate"] for r in demo_inspection_fixture.REGISTERED_RENTALS}
UPLOAD_ROOT = paths.UPLOAD_DIR / ri.MOBILE_UPLOAD_DIRNAME
