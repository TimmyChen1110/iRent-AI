"""管理者端 Inspection History API（/api/ops/inspections）。

「沒有異常」也是稽核紀錄：這裡列出每筆租約的取車／還車檢查、Before/After 照片、
AI 比對結果與衍生案件；案件本身仍走 /api/ops/cases（同一套裁決／任務）。
與 /api/ops/* 其他路由一樣受 ops_auth 中介層保護（需登入）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

import rental_inspections as ri

router = APIRouter(prefix="/api/ops/inspections", tags=["ops-inspections"])

_ops = None   # ops_api 模組（bind 後可借用 _attach_case_state 補裁決／任務狀態）


def bind(ops_api_module) -> None:
    global _ops
    _ops = ops_api_module


def _with_case_state(incidents: list[dict]) -> list[dict]:
    """把案件的裁決與任務狀態（review_status / tasks）補進 incident 列表。"""
    if not incidents or _ops is None:
        return incidents
    ids = {i["case_id"] for i in incidents}
    cases = {c["case_id"]: c for c in _ops._attach_case_state(ri.ops_cases()) if c["case_id"] in ids}
    for i in incidents:
        c = cases.get(i["case_id"])
        i["review_status"] = c["review_status"] if c else "unreviewed"
        i["decision"] = c["decision"] if c else None
        i["tasks"] = c["tasks"] if c else []
    return incidents


@router.get("")
def list_inspections():
    """每筆租約的檢查摘要 ＋ 案件裁決狀態 ＋ data_source（app／fixture／legacy）＋ review_state（審核分類）。"""
    import admin_console_api  # noqa: PLC0415
    return {"inspections": admin_console_api.inspections_with_state(), "server_time": ri.now_iso()}


@router.get("/{rental_id}")
def inspection_detail(rental_id: str):
    detail = ri.inspection_detail(rental_id)
    if detail is None:
        raise HTTPException(404, f"找不到租約 {rental_id}")
    detail["incidents"] = _with_case_state(detail["incidents"])
    import admin_console_api  # noqa: PLC0415
    sessions = admin_console_api._sessions_by_rental()
    detail["data_source"] = admin_console_api.data_source(rental_id, sessions)
    detail["session_id"] = (sessions.get(rental_id) or {}).get("session_id")
    detail["review_state"] = admin_console_api.review_state(detail["result"], detail["incidents"])
    return {"inspection": detail, "server_time": ri.now_iso()}
