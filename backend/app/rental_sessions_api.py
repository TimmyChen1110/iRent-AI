"""模擬租還車 Session API（/v1/rental-sessions）——iOS App 用。

  GET  /v1/rental-sessions/vehicles                       模擬車輛清單（地圖用；含狀態、里程、位置、AI 來源）
  GET  /v1/rental-sessions/vehicles/{vehicle_id}          單一車輛
  GET  /v1/rental-sessions/vehicles/{vehicle_id}/records  車況紀錄（已驗證的借車前／還車後照片，無開發資訊）
  GET  /v1/rental-sessions/active                         目前進行中的 Session（單使用者 Demo；App 重新整理後恢復狀態用）
  POST /v1/rental-sessions                                開始租車 → PICKUP_INSPECTION（車輛 → RENTED）
  GET  /v1/rental-sessions/{session_id}                   Session 狀態（含租約照片完整度、分析狀態）
  POST /v1/rental-sessions/{session_id}/pickup/complete   取車照齊（後端驗證）→ RENTED
  POST /v1/rental-sessions/{session_id}/return/initiate   我要還車 → RETURN_INITIATED
  POST /v1/rental-sessions/{session_id}/return/cancel     撤回開始還車 → RENTED（尚無還車照片時）
  POST /v1/rental-sessions/{session_id}/photos/{stage}/finish  完成拍攝：車內照選填，沒拍即略過；還車外觀齊即開始 AI 分析
  POST /v1/rental-sessions/{session_id}/return/info       確認還車資訊（結束里程 ≥ 起始里程）→ PHOTO_INSPECTION
  GET  /v1/rental-sessions/{session_id}/inspection        AI 檢測結果（逐角度、車內、車牌比對、AI 來源）
  POST /v1/rental-sessions/{session_id}/inspection/retry  檢測失敗 → 重新檢測（reanalyze）或重新拍攝（retake）
  POST /v1/rental-sessions/{session_id}/confirm-return    檢測完成 → 確認還車 → RETURNED（車輛 → AVAILABLE）
  POST /v1/rental-sessions/{session_id}/cancel            尚未開始用車時取消

開發者功能（重設、預載照片、OCR／pipeline 細節）在 devtools_api（/api/ops/devtools，需管理者登入）。
照片上傳不在這裡：沿用既有 POST /v1/mobile-inspections/photos（rental_id = session.rental_id）。
"""
from __future__ import annotations

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
    """一般使用者車輛清單：置頂推薦（featured）在前，不受定位限制；只含產品資訊與服務說明。"""
    return {"vehicles": rs.list_vehicles(), "service_notice": rs.SERVICE_NOTICE}


@router.get("/vehicles/{vehicle_id}/records")
def vehicle_records(vehicle_id: str):
    """車況紀錄（一般使用者）：只有已確認屬於同一台車的借車前／還車後照片（url、角度、階段）；沒有紀錄回空陣列。"""
    import demo_vehicle_registry as registry   # noqa: PLC0415
    v = rs.get_vehicle(vehicle_id, internal=True)
    if v is None or v["visibility"] != "public":
        raise HTTPException(404, "unknown vehicle_id")
    plate = (v.get("details") or {}).get("registry_plate")
    return {"vehicle_id": vehicle_id, **registry.public_records(plate), "damage_records": rs.vehicle_damage_records(vehicle_id)}


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


@router.post("/{session_id}/photos/{stage}/finish")
def photos_finish(session_id: str, stage: str):
    """完成拍攝（stage=pickup|return）：車內照選填，沒拍就略過；還車外觀齊即開始 AI 分析。"""
    return _wrap(rs.finish_photos, session_id, stage)


@router.post("/{session_id}/return/cancel")
def return_cancel(session_id: str):
    """撤回開始還車 → RENTED（尚未上傳任何還車照片時才允許）。"""
    return _wrap(rs.cancel_return, session_id)


@router.post("/{session_id}/return/info")
def return_info(session_id: str, body: ReturnInfoIn):
    loc = body.return_location.model_dump() if body.return_location else None
    return _wrap(rs.confirm_return_info, session_id, body.end_odometer_km, loc)


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

