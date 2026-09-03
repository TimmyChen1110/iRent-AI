#!/usr/bin/env python3
"""複核介面 API（服務化規格 §3，第一優先——解鎖 shadow 第二期）。

端點：
  GET  /v1/review/queue                 待複核清單（3 筆交集派送＋10 筆 pro 抽樣）
  GET  /v1/review/signals/{signal_id}   單筆完整資料（blind 流程由後端扣住 card）
  POST /v1/review/signals/{signal_id}   回填（或 blind 第一階段的 pre_verdict）
  GET  /v1/review/progress              進度＋即時判準（n<15 一律 insufficient_sample）
  GET  /v1/review/health                訊號層健康度 vs 第一期基線（規格 §7）
  GET  /v1/media/{signal_id}/{role}     借/還原圖（僅佇列內訊號可取）
  GET  /review                          複核表單頁

設計要點（照規格，不是偏好）：
  - blind 流程的 card 由【後端】控制為 null——前端隱藏擋不住開發者工具，
    會污染防錨定設計。pre_verdict 回填後才回 card。
  - review_free_text 後端強制非空（wrong_area 三類歸因的唯一依據）。
  - time_to_locate_sec 與總時長分開——目前只能給全圖（panel bbox 未定位），
    定位是介面成本不是訊號成本，判準用扣除後的口徑。
  - grid_overlay 為 §8 缺口的低成本緩解：3×3 近似網格＋高亮訊號格，
    絕對位置不準但把注意範圍縮到九分之一。
"""
import json
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"
from pairs_io import load_pairs  # noqa: E402

from shadow_mode import (SIGNALS_PATH, CARDS_DIR, build_queue,  # noqa: E402
                         progress_snapshot, signal_health)

router = APIRouter()
_lock = threading.Lock()

VERDICTS = {"confirmed_damage", "no_damage", "cannot_determine"}
POSITIONS = {"exact", "approximate", "wrong_area", "n/a"}
PHASE1_POPULATION = 119   # 第一期母體（health 分母）


def _records() -> list:
    return [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]


def _save(records: list):
    SIGNALS_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                      for r in records) + "\n")


def _queue_map() -> dict:
    return {r["signal_id"]: r for r in build_queue(_records())}


def _pairs() -> dict:
    data = load_pairs()
    return {f"{p['car']}{p['angle']}": p for p in data}


def _card(signal_id: str):
    p = CARDS_DIR / f"{signal_id}.json"
    return json.loads(p.read_text()) if p.exists() else None


@router.get("/v1/review/queue")
def review_queue():
    q = build_queue(_records())
    done = [r for r in q if r.get("review_verdict")]
    return {
        "pending": len(q) - len(done),
        "completed": len(done),
        "items": [{"signal_id": r["signal_id"], "case_id": r["case_id"],
                   "review_flow": r["review_flow"], "queue_source": r["queue_source"],
                   "done": bool(r.get("review_verdict"))} for r in q],
    }


@router.get("/v1/review/signals/{signal_id}")
def review_signal(signal_id: str):
    q = _queue_map()
    r = q.get(signal_id)
    if not r:
        raise HTTPException(404, "not in review queue")
    blind_pending = (r["review_flow"] == "blind" and not r.get("blind_pre_verdict")
                     and not r.get("review_verdict"))
    return {
        "signal_id": signal_id,
        "case_id": r["case_id"],
        "panel": r["panel"],
        "review_flow": r["review_flow"],
        "queue_source": r["queue_source"],
        "signal_type": r["signal_type"],
        "done": bool(r.get("review_verdict")),
        "images": {
            "pickup_url": f"/v1/media/{signal_id}/pickup",
            "return_url": f"/v1/media/{signal_id}/return",
            "is_cropped": False,
            "grid_overlay": {"enabled": True, "highlight_cells": r["signal_cells"],
                             "note": "網格為近似指引（panel 未定位），僅縮小注意範圍"},
        },
        # blind 且尚未交 pre_verdict → card 必為 null（後端控制）
        "card": None if blind_pending else _card(signal_id),
        "blind_phase": "pre" if blind_pending else
                       ("post" if r["review_flow"] == "blind" else None),
    }


class ReviewSubmit(BaseModel):
    review_verdict: str | None = None
    review_position_match: str | None = None
    time_to_locate_sec: float | None = None
    review_duration_sec: float | None = None
    review_free_text: str | None = None
    blind_pre_verdict: str | None = None


def validate_submission(body: ReviewSubmit, flow: str) -> list:
    """回傳錯誤清單（空＝合法）。純函式，tests 覆蓋。"""
    errs = []
    if body.blind_pre_verdict is not None and body.review_verdict is None:
        # blind 第一階段：只交 pre_verdict
        if flow != "blind":
            errs.append("blind_pre_verdict only valid for blind flow")
        if body.blind_pre_verdict not in VERDICTS:
            errs.append("invalid blind_pre_verdict")
        return errs
    if body.review_verdict not in VERDICTS:
        errs.append("invalid review_verdict")
    if body.review_position_match not in POSITIONS:
        errs.append("invalid review_position_match")
    if not (body.review_free_text or "").strip():
        errs.append("review_free_text is required (wrong_area 歸因唯一依據)")
    if body.review_duration_sec is None or body.review_duration_sec < 0:
        errs.append("review_duration_sec is required")
    if flow == "blind":
        pass  # pre_verdict 應已在第一階段存好，final 不強制重送
    return errs


@router.post("/v1/review/signals/{signal_id}")
def review_submit(signal_id: str, body: ReviewSubmit):
    with _lock:
        records = _records()
        q = {r["signal_id"]: r for r in build_queue(records)}
        r = q.get(signal_id)
        if not r:
            raise HTTPException(404, "not in review queue")
        errs = validate_submission(body, r["review_flow"])
        if errs:
            raise HTTPException(422, "; ".join(errs))
        # blind 第一階段：存 pre_verdict、回 card
        if body.blind_pre_verdict is not None and body.review_verdict is None:
            for rec in records:
                if rec["signal_id"] == signal_id:
                    rec["blind_pre_verdict"] = body.blind_pre_verdict
            _save(records)
            return {"blind_phase": "post", "card": _card(signal_id)}
        if r.get("review_verdict"):
            raise HTTPException(409, "already reviewed")
        update = {
            "review_verdict": body.review_verdict,
            "review_position_match": body.review_position_match,
            "time_to_locate_sec": body.time_to_locate_sec,
            "review_duration_sec": body.review_duration_sec,
            "review_free_text": body.review_free_text.strip(),
        }
        for rec in records:
            if rec["signal_id"] == signal_id:
                if rec["review_flow"] == "blind":
                    pre = rec.get("blind_pre_verdict")
                    update["blind_changed_after_card"] = (
                        pre is not None and pre != body.review_verdict)
                rec.update(update)
        _save(records)
    snap = progress_snapshot(_records())
    return {"saved": True, "progress": snap}


@router.get("/v1/review/progress")
def review_progress():
    return progress_snapshot(_records())


@router.get("/v1/review/health")
def review_health():
    return signal_health(_records(), PHASE1_POPULATION)


@router.get("/v1/media/{signal_id}/{role}")
def review_media(signal_id: str, role: str):
    if role not in ("pickup", "return"):
        raise HTTPException(404)
    q = _queue_map()
    r = q.get(signal_id)
    if not r:
        raise HTTPException(404, "not in review queue")
    p = _pairs().get(r["case_id"])
    if not p:
        raise HTTPException(404)
    return FileResponse(p[role])


@router.get("/review", response_class=HTMLResponse)
def review_page():
    return (HERE / "review.html").read_text()
