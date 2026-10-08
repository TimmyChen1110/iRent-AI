"""模擬租還車 Session API（/v1/rental-sessions）——iOS App 用。

  GET  /v1/rental-sessions/vehicles                       模擬車輛清單（地圖用；含狀態、里程、位置、AI 來源）
  GET  /v1/rental-sessions/vehicles/{vehicle_id}          單一車輛
  GET  /v1/rental-sessions/vehicles/{vehicle_id}/photos   Demo Vehicle Registry：借車前／還車後照片、OCR、配對驗證
  POST /v1/rental-sessions/{session_id}/preload/{stage}   Preloaded Demo（模式 B）：預載 pickup / return 照片
  GET  /v1/rental-sessions/active                         目前進行中的 Session（單使用者 Demo；App 重新整理後恢復狀態用）
  POST /v1/rental-sessions                                開始租車 → PICKUP_INSPECTION（車輛 → RENTED）
  GET  /v1/rental-sessions/{session_id}                   Session 狀態（含租約照片完整度、分析狀態）
  POST /v1/rental-sessions/{session_id}/pickup/complete   取車照齊（後端驗證）→ RENTED
  POST /v1/rental-sessions/{session_id}/return/initiate   我要還車 → RETURN_INITIATED
  POST /v1/rental-sessions/{session_id}/return/info       確認還車資訊（結束里程 ≥ 起始里程）→ PHOTO_INSPECTION
  GET  /v1/rental-sessions/{session_id}/inspection        AI 檢測結果（逐角度、車內、車牌比對、AI 來源）
  POST /v1/rental-sessions/{session_id}/inspection/retry  檢測失敗 → 重新檢測（reanalyze）或重新拍攝（retake）
  POST /v1/rental-sessions/{session_id}/confirm-return    檢測完成 → 確認還車 → RETURNED（車輛 → AVAILABLE）
  POST /v1/rental-sessions/{session_id}/cancel            尚未開始用車時取消
  POST /v1/rental-sessions/reset                          Demo 重置（只在 DEMO_MODE）
  POST /v1/rental-sessions/vehicles/{vehicle_id}/reset    Demo 測試車輛重設（category=demo；展示者在 App 內可用）
  GET  /photos/demo/{name}                                Demo 車輛示意圖（server.py 轉接到 demo_assets/）

照片上傳不在這裡：沿用既有 POST /v1/mobile-inspections/photos（rental_id = session.rental_id）。
"""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import rental_sessions as rs

router = APIRouter(prefix="/v1/rental-sessions", tags=["rental-sessions"])


class Location(BaseModel):
    lat: float
    lng: float
    source: str = Field("gps", description="gps | manual")


class CreateSessionIn(BaseModel):
    vehicle_id: str
    user_location: Location | None = None


class ReturnInitiateIn(BaseModel):
    user_location: Location | None = None


class ReturnInfoIn(BaseModel):
    end_odometer_km: int
    return_location: Location | None = None


class RetryIn(BaseModel):
    mode: str = Field("reanalyze", description="reanalyze | retake")


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except rs.SessionError as e:
        raise HTTPException(e.status, e.detail) from e


@router.get("/vehicles")
def vehicles():
    return {"vehicles": rs.list_vehicles(), "simulated": True,
            "note": "模擬車輛資料（非真實 iRent 車隊），位置為固定座標。"}


@router.post("/vehicles/{vehicle_id}/reset")
def vehicle_reset(vehicle_id: str):
    """Demo 測試車輛重設（只允許 category=demo；不需 DEMO_MODE）：封存進行中 Session、車輛回 AVAILABLE。"""
    return _wrap(rs.reset_vehicle, vehicle_id)


@router.get("/vehicles/{vehicle_id}/photos")
def vehicle_photos(vehicle_id: str):
    """Demo Vehicle Registry：登記車輛的借車前／還車後照片（資料集）、車牌辨識、配對驗證。沒有登記 → 404。"""
    import demo_vehicle_registry as registry   # noqa: PLC0415
    v = rs.get_vehicle(vehicle_id)
    if v is None:
        raise HTTPException(404, "unknown vehicle_id")
    plate = (v.get("details") or {}).get("registry_plate")
    photos = registry.vehicle_photos(plate) if plate else None
    if photos is None:
        raise HTTPException(404, "此車輛沒有登記的 Demo 照片（只能即時拍攝）")
    return {"vehicle_id": vehicle_id, **photos}


@router.get("/vehicles/{vehicle_id}")
def vehicle(vehicle_id: str):
    v = rs.get_vehicle(vehicle_id)
    if v is None:
        raise HTTPException(404, "unknown vehicle_id")
    return v


@router.get("/active")
def active():
    return {"session": rs.active_session()}


@router.post("", status_code=201)
def create(body: CreateSessionIn):
    return _wrap(rs.create_session, body.vehicle_id, body.user_location.model_dump() if body.user_location else None)


@router.post("/reset")
def reset():
    if os.environ.get("DEMO_MODE", "").lower() not in ("1", "true", "yes"):
        raise HTTPException(404)
    return rs.reset_all()


@router.get("/{session_id}")
def get(session_id: str):
    return _wrap(rs.get_session, session_id)


@router.post("/{session_id}/pickup/complete")
def pickup_complete(session_id: str):
    return _wrap(rs.complete_pickup, session_id)


@router.post("/{session_id}/return/initiate")
def return_initiate(session_id: str, body: ReturnInitiateIn | None = None):
    loc = body.user_location.model_dump() if body and body.user_location else None
    return _wrap(rs.initiate_return, session_id, loc)


@router.post("/{session_id}/return/info")
def return_info(session_id: str, body: ReturnInfoIn):
    loc = body.return_location.model_dump() if body.return_location else None
    return _wrap(rs.confirm_return_info, session_id, body.end_odometer_km, loc)


@router.post("/{session_id}/preload/{stage}")
def preload(session_id: str, stage: str):
    """Preloaded Demo（模式 B）：用 Registry 的借車前（pickup）／還車後（return）照片取代即時拍攝；AI pipeline 相同。"""
    return _wrap(rs.preload_photos, session_id, stage)


@router.get("/{session_id}/inspection")
def inspection(session_id: str):
    return _wrap(rs.inspection_result, session_id)


@router.post("/{session_id}/inspection/retry")
def inspection_retry(session_id: str, body: RetryIn | None = None):
    return _wrap(rs.retry_inspection, session_id, (body.mode if body else "reanalyze"))


@router.post("/{session_id}/confirm-return")
def confirm_return(session_id: str):
    return _wrap(rs.confirm_return, session_id)


@router.post("/{session_id}/cancel")
def cancel(session_id: str):
    return _wrap(rs.cancel_session, session_id)

