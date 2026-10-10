"""管理者後台（精簡版）唯讀 API：總覽統計、租還車紀錄（/api/ops/overview、/api/ops/rentals）。

資料全部取自既有資料表（rental_sessions、demo_vehicles、rentals、inspection_*、decisions、tasks），
不寫入、不另造資料。資料來源分類（data_source）：
  app      真實 App 租約：有租車 Session、且不是固定劇本 → 總覽統計與預設清單只算這一類
  fixture  固定劇本租約（demo_inspection_fixture，AI 結果為劇本、非真實判定）
  legacy   舊版 App 上傳流程（沒有 Session 的早期租約）
資料集離線評測案件（141 組配對、車內、照片鏈）不屬於 App 租還車流程，這裡不列。
與 /api/ops/* 其他路由一樣受 ops_auth 中介層保護（需登入）。
"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, HTTPException

import demo_inspection_fixture as fixture
import rental_inspections as ri
import rental_sessions as rs

router = APIRouter(prefix="/api/ops", tags=["ops-console"])

_ops = None   # ops_api 模組（bind 後借用 _attach_case_state 補裁決／任務狀態）


def bind(ops_api_module) -> None:
    global _ops
    _ops = ops_api_module


SESSION_STATE_LABELS = {
    "PICKUP_INSPECTION": "取車檢查中", "RENTED": "租用中", "RETURN_INITIATED": "還車中",
    "PHOTO_INSPECTION": "還車拍攝／AI 檢測中", "INSPECTION_COMPLETED": "檢測完成・待確認還車",
    "INSPECTION_FAILED": "AI 檢測失敗", "RETURNED": "已還車", "CANCELLED": "已取消", "ARCHIVED": "已封存（Demo 重設）",
}

REVIEW_STATES = ("capturing", "analyzing", "passed", "pending_review", "reviewed", "failed")


# ---------- 共用 ----------

def _sessions_by_rental() -> dict[str, dict]:
    with ri.db() as conn:
        if not ri._table_exists(conn, "rental_sessions"):
            return {}
        out = {}
        for r in ri.rows(conn.execute("SELECT * FROM rental_sessions ORDER BY created_at")):
            out[r["rental_id"]] = r      # 固定劇本租約會被多次重用：取最新一筆
    return out


def data_source(rental_id: str, sessions: dict[str, dict]) -> str:
    if fixture.is_demo_rental(rental_id):
        return "fixture"
    return "app" if rental_id in sessions else "legacy"


def _case_states(case_ids: set[str]) -> dict[str, dict]:
    if not case_ids or _ops is None:
        return {}
    return {c["case_id"]: c for c in _ops._attach_case_state(ri.ops_cases()) if c["case_id"] in case_ids}


def review_state(result: str, incidents: list[dict]) -> str:
    """AI 檢測與人工審核的狀態分類：檢測中／無異常／發現異常待審核／已審核／檢測失敗（還車照未齊＝拍攝中）。"""
    if result == "PENDING":
        return "capturing"
    if result == "ANALYZING":
        return "analyzing"
    if result == "FAILED":
        return "failed"
    if result == "PASSED":
        return "passed"
    return "pending_review" if any(i.get("review_status") in (None, "unreviewed") for i in incidents) else "reviewed"


def inspections_with_state() -> list[dict]:
    """既有 list_inspections（每筆租約的檢查摘要）＋ 案件裁決狀態 ＋ data_source ＋ review_state ＋ session_id。"""
    sessions = _sessions_by_rental()
    items = ri.list_inspections()
    states = _case_states({i["case_id"] for it in items for i in it["incidents"]})
    for it in items:
        for i in it["incidents"]:
            c = states.get(i["case_id"])
            i["review_status"] = c["review_status"] if c else "unreviewed"
            i["decision"] = c["decision"] if c else None
            i["tasks"] = c["tasks"] if c else []
        it["data_source"] = data_source(it["rental_id"], sessions)
        it["session_id"] = (sessions.get(it["rental_id"]) or {}).get("session_id")
        it["review_state"] = review_state(it["result"], it["incidents"])
    return items


def _photo_ocr(stage: str, rental_id: str, expected_plate: str) -> dict:
    """某階段每個角度最新一張照片的裝置端辨識結果（車牌、信心、角度、驗證模式）＋ 與租約車牌的比對摘要。"""
    with ri.db() as conn:
        photos = ri._latest_photos(conn, rental_id, ri.STAGE_TO_TYPE[stage])
    items, statuses = [], []
    for angle in ri.ALL_ANGLES:
        p = photos.get(angle)
        if not p:
            continue
        v = json.loads(p["validation_json"] or "{}")
        text, src = v.get("plateText"), v.get("plateSource") or "ocr"
        if angle == ri.INTERIOR_ANGLE:
            st = None
        elif src == "user_confirmed_mismatch" or (text and rs._normalise_plate(text) != rs._normalise_plate(expected_plate)):
            st = "MISMATCH"
        elif src == "manual":
            st = "MANUAL"
        elif text:
            st = "MATCH"
        else:
            st = "UNKNOWN"
        if st:
            statuses.append(st)
        items.append({"angle": angle, "angle_code": ri.ANGLE_CODES[angle], "url": ri.photo_url(p.get("storage_path")),
                      "plate_text": text, "plate_confidence": v.get("plateConfidence"), "plate_source": src,
                      "plate_status": st, "view": v.get("detectedView"), "view_confidence": v.get("viewConfidence"),
                      "validation_mode": p["validation_mode"], "captured_at": p["captured_at"]})
    overall = ("PENDING" if not statuses else "MISMATCH" if "MISMATCH" in statuses else "MANUAL" if "MANUAL" in statuses
               else "MATCH" if all(s == "MATCH" for s in statuses) else "UNKNOWN")
    return {"photos": items, "plate_status": overall,
            "plate_texts": sorted({i["plate_text"] for i in items if i["plate_text"]})}


def _today(ts: str | None) -> bool:
    return bool(ts) and ts[:10] == datetime.now().date().isoformat()


def _session_row(s: dict, insp: dict | None, sessions: dict[str, dict]) -> dict:
    src = data_source(s["rental_id"], sessions)
    pickup = _photo_ocr("pickup", s["rental_id"], s["vehicle"]["plate"])
    incidents = (insp or {}).get("incidents") or []
    return {
        "session_id": s["session_id"], "rental_id": s["rental_id"], "data_source": src,
        "plate": s["vehicle"]["plate"], "vehicle_id": s["vehicle"]["vehicle_id"], "model": s["vehicle"]["model"],
        "vehicle_category": s["vehicle"]["category"], "state": s["state"],
        "state_label": SESSION_STATE_LABELS.get(s["state"], s["state"]),
        "started_at": s["started_at"], "returned_at": s["returned_at"], "cancelled_at": s["cancelled_at"],
        "pickup_plate_status": pickup["plate_status"], "pickup_plate_texts": pickup["plate_texts"],
        "pickup_photos": len(pickup["photos"]), "return_photos": len((s.get("photos") or {}).get("RETURN") or []),
        "analysis": s["analysis"], "review_state": (insp or {}).get("review_state"),
        "incident_count": len(incidents),
        "unreviewed_count": sum(1 for i in incidents if i.get("review_status") in (None, "unreviewed")),
        "review_required": s["review_required"], "distance_km": s["distance_km"], "used_seconds": s["used_seconds"],
    }


# ---------- 總覽 ----------

@router.get("/overview")
def overview():
    """總覽：車輛（App 可租車隊，不含固定劇本車）、今日租還車、AI 檢測與人工審核——只算真實 App 租約。"""
    vehicles = [v for v in rs.list_vehicles(internal=True, include_parked=False) if not v.get("is_fixture")]
    sessions = _sessions_by_rental()
    insps = [i for i in inspections_with_state() if i["data_source"] == "app"]
    insp_by_rental = {i["rental_id"]: i for i in insps}
    app_sessions = [s for s in rs.list_sessions() if data_source(s["rental_id"], sessions) == "app"]

    flagged_plates = {rs._normalise_plate(i["plate"]) for i in insps if i["review_state"] == "pending_review"}
    abnormal = [v for v in vehicles if v["status"] == "MAINTENANCE" or rs._normalise_plate(v["plate"]) in flagged_plates]
    incidents = []
    for it in insps:
        for inc in it["incidents"]:
            incidents.append({**inc, "rental_id": it["rental_id"], "session_id": it["session_id"], "plate": it["plate"],
                              "at": it["return_at"] or it["analysis"].get("completed_at")})
    incidents.sort(key=lambda x: x["at"] or "", reverse=True)
    return {
        "server_time": ri.now_iso(),
        "vehicles": {
            "total": len(vehicles),
            "available": sum(v["status"] == "AVAILABLE" for v in vehicles),
            "rented": sum(v["status"] == "RENTED" for v in vehicles),
            "maintenance": sum(v["status"] == "MAINTENANCE" for v in vehicles),
            "demo": sum(bool(v.get("is_demo")) for v in vehicles),
            "abnormal": len(abnormal),
            "abnormal_plates": [v["plate"] for v in abnormal],
        },
        "today": {
            "rentals_started": sum(_today(s["started_at"]) for s in app_sessions),
            "returns_completed": sum(_today(s["returned_at"]) for s in app_sessions),
        },
        "ai": {
            "completed": sum(i["review_state"] in ("passed", "pending_review", "reviewed") for i in insps),
            "analyzing": sum(i["review_state"] == "analyzing" for i in insps),
            "failed": sum(i["review_state"] == "failed" for i in insps),
            "passed": sum(i["review_state"] == "passed" for i in insps),
            "pending_review_cases": sum(1 for inc in incidents if inc.get("review_status") in (None, "unreviewed")),
        },
        "recent_rentals": [_session_row(s, insp_by_rental.get(s["rental_id"]), sessions) for s in app_sessions[:6]],
        "recent_incidents": incidents[:6],
        "scope_note": "只統計真實 App 租約；固定劇本、舊版流程與資料集離線評測不計入。",
    }


# ---------- 租還車紀錄 ----------

@router.get("/rentals")
def rentals(include_other: bool = False):
    """租還車紀錄（每筆 App 租車 Session）。include_other=true 一併列出固定劇本 Session。"""
    sessions = _sessions_by_rental()
    insp = {i["rental_id"]: i for i in inspections_with_state()}
    out = []
    for s in rs.list_sessions():
        row = _session_row(s, insp.get(s["rental_id"]), sessions)
        if include_other or row["data_source"] == "app":
            out.append(row)
    return {"rentals": out, "server_time": ri.now_iso()}


@router.get("/rentals/{session_id}")
def rental_detail(session_id: str):
    try:
        s = rs.get_session(session_id)
    except rs.SessionError as e:
        raise HTTPException(e.status, e.detail) from e
    sessions = _sessions_by_rental()
    insp = next((i for i in inspections_with_state() if i["rental_id"] == s["rental_id"]), None)
    rental = ri.get_rental(s["rental_id"]) or {}
    plate = s["vehicle"]["plate"]
    timeline = [
        ("開始租車（建立 Session）", s["started_at"]),
        ("取車照片齊全・建立車況基準", rental.get("pickup_at")),
        ("使用者按「我要還車」", s["return_initiated_at"]),
        ("確認還車資訊（里程）", s["return_info_confirmed_at"]),
        ("還車照片齊全", rental.get("return_at")),
        ("AI 檢測開始", rental.get("analysis_started_at")),
        ("AI 檢測完成" if rental.get("status") == "ANALYSIS_COMPLETE" else "AI 檢測結束", rental.get("analysis_completed_at")),
        ("確認還車・車輛重新上架", s["returned_at"]),
        ("租約取消／封存", s["cancelled_at"]),
    ]
    return {
        "rental": _session_row(s, insp, sessions),
        "session": {k: s[k] for k in ("start_odometer_km", "end_odometer_km", "distance_km", "used_seconds",
                                      "fee_estimate", "inspection_attempts", "last_error", "rental_status")},
        "pickup": _photo_ocr("pickup", s["rental_id"], plate),
        "return": _photo_ocr("return", s["rental_id"], plate),
        "inspection": {"result": (insp or {}).get("result"), "review_state": (insp or {}).get("review_state"),
                       "issue_count": (insp or {}).get("issue_count", 0), "incidents": (insp or {}).get("incidents", []),
                       "analysis": (insp or {}).get("analysis")},
        "timeline": [{"label": label, "at": at} for label, at in timeline if at],
        "server_time": ri.now_iso(),
    }
