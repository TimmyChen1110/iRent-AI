"""Mobile user-app photo ingestion.

This router persists evidence produced by on-device Core ML. It deliberately never
imports or runs the server-side detection, OCR, or view-classification models.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

import paths

router = APIRouter(prefix="/v1/mobile-inspections", tags=["mobile-inspections"])

VALID_STAGES = {"pickup", "return"}
VALID_VIEWS = {"左前", "右前", "左後", "右後"}

# Demo-only rental registry. Replace this lookup with the rental service before
# production; clients do not get to choose the expected plate.
DEMO_RENTAL_PLATES = {"demo-rental-001": "RCG-2235"}


def _normalise_plate(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _db() -> sqlite3.Connection:
    connection = sqlite3.connect(paths.DB_PATH)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS mobile_photo_submissions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rental_id TEXT NOT NULL,
            car_id TEXT NOT NULL,
            stage TEXT NOT NULL,
            view TEXT NOT NULL,
            expected_plate TEXT NOT NULL,
            recognized_plate TEXT NOT NULL,
            image_sha256 TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            local_result_json TEXT NOT NULL,
            model_versions_json TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            received_at TEXT NOT NULL,
            UNIQUE(rental_id, stage, view, image_sha256)
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_mobile_submission_rental "
        "ON mobile_photo_submissions(rental_id, stage)"
    )
    return connection


@router.post("/photos", status_code=201)
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
):
    if stage not in VALID_STAGES:
        raise HTTPException(422, "stage must be pickup or return")
    if view not in VALID_VIEWS:
        raise HTTPException(422, "view must be one of 左前、右前、左後、右後")

    registered_plate = DEMO_RENTAL_PLATES.get(rental_id)
    if registered_plate is None:
        raise HTTPException(404, "unknown rental_id")
    if _normalise_plate(expected_plate) != _normalise_plate(registered_plate):
        raise HTTPException(422, "expected_plate does not match the rental")
    if _normalise_plate(recognized_plate) != _normalise_plate(registered_plate):
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

    upload_directory = paths.UPLOAD_DIR / "mobile-inspections" / rental_id / stage
    upload_directory.mkdir(parents=True, exist_ok=True)
    stored_path = upload_directory / f"{view}-{image_sha256[:16]}{suffix}"
    if not stored_path.exists():
        stored_path.write_bytes(data)

    model_versions = local_result.get("modelVersions", {})
    connection = _db()
    try:
        connection.execute(
            """INSERT OR IGNORE INTO mobile_photo_submissions(
                rental_id, car_id, stage, view, expected_plate, recognized_plate,
                image_sha256, captured_at, local_result_json, model_versions_json,
                stored_path, received_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rental_id, car_id, stage, view, registered_plate, recognized_plate,
                image_sha256, captured_at, json.dumps(local_result, ensure_ascii=False),
                json.dumps(model_versions, ensure_ascii=False), str(stored_path),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        duplicate = connection.total_changes == 0
        connection.commit()
    finally:
        connection.close()

    return {
        "rental_id": rental_id,
        "stage": stage,
        "view": view,
        "image_sha256": image_sha256,
        "deduplicated": duplicate,
    }
