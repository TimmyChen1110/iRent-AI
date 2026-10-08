"""Demo Vehicle Registry：Demo 車輛的照片索引（借車前／還車後／車牌辨識／配對驗證）單一資料來源。

讀 backend/app/DEMO_IMAGE_MANIFEST.json（由 backend/tools/audit_demo_images.py 產生：掃描專案照片、Core ML OCR、
品質閘門、既有 pairs.json／relabels.json）。這裡只做兩件事：
  1. vehicle_photos(plate)：給 App 的照片集（URL 走既有 /photos/pair、/photos/interior 供圖，不複製原始照片、不給絕對路徑）
  2. preload(session, stage)：Preloaded Demo（模式 B）——把登記的借車前／還車後照片灌進該 Session 的租約
     （rental_inspections.ingest_photo，validation_mode="preloaded"），之後走與即時拍攝完全相同的 AI pipeline。

原則：不虛構配對。只有 pair_verification=VERIFIED 的角度標為已驗證；車內照資料集沒有同一租約的借／還車內照，
      只能用 interior_candidates 的「乾淨」車內照當佔位（**非本車**），manifest 與 API 都明確標示 interior_standin。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import rental_inspections as ri

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MANIFEST_PATH = HERE / "DEMO_IMAGE_MANIFEST.json"
PIPE = HERE.parent / "pipeline"

# 以車牌為鍵登記到 SIM_VEHICLES（rental_sessions）；角色只影響文案
REGISTERED = {
    "RDG-9853": {"role": "primary_inspection", "visual_model": "Toyota Prius c（車尾標誌目視判讀，資料集未記錄車型）"},
    "RFH-8122": {"role": "damage_showcase", "visual_model": "Honda Fit（車尾標誌目視判讀，資料集未記錄車型）"},
}

_cache: dict | None = None


def manifest() -> dict:
    global _cache
    if _cache is None:
        _cache = json.loads(MANIFEST_PATH.read_text()) if MANIFEST_PATH.exists() else {"vehicles": [], "photos": []}
    return _cache


def reload() -> None:
    global _cache
    _cache = None


def _photo_index() -> dict[str, dict]:
    return {p["image"]: p for p in manifest().get("photos", [])}


def _abs(rel_path: str) -> Path:
    return REPO / rel_path


def _interior_standins() -> list[dict]:
    """車內佔位照：interior_candidates 中模型判「乾淨」的照片（非本車，只為讓 5 張齊全跑 pipeline）。"""
    try:
        results = json.loads((PIPE / "interior_results.json").read_text())["results"]
    except Exception:
        return []
    out = []
    for r in results:
        a = r.get("assessment") or {}
        p = PIPE / "interior_photos" / r["file"]
        if a.get("level") == "乾淨" and p.exists():
            out.append({"path": p, "source_car": r.get("car"), "level": a.get("level")})
    return out


def _entry(rel: str, stage: str, idx: dict) -> dict:
    p = idx.get(rel) or {}
    q = p.get("quality") or {}
    pl = p.get("plate") or {}
    return {
        "image": rel, "file": Path(rel).name, "url": ri.photo_url(str(_abs(rel))), "stage": stage,
        "angle": p.get("angle"), "angle_code": ri.ANGLE_CODES.get(p.get("angle") or "", None),
        "quality": {"pass": q.get("pass"), "sharpness": q.get("sharpness"), "brightness": q.get("brightness")},
        "plate_recognition": {"ocr_text": pl.get("ocr_text"), "confidence": pl.get("ocr_confidence"),
                              "verification": pl.get("verification"), "engine": pl.get("engine")},
        "source": "competition_dataset", "source_note": "比賽資料集（非公開），既有紀錄：檔名 借/還",
    }


def vehicle_photos(plate: str) -> dict | None:
    """登記車輛的照片集：before/after（逐角度）、配對驗證、車內佔位照說明。"""
    key = plate.upper()
    v = next((x for x in manifest().get("vehicles", []) if x["plate"] == key), None)
    if v is None:
        return None
    idx = _photo_index()
    before, after, pairs = [], [], []
    for pr in v.get("pairs", []):
        before.append(_entry(pr["pickup"], "pickup", idx))
        after.append(_entry(pr["return"], "return", idx))
        pairs.append({"angle": pr["angle"], "pair_verification": pr["pair_verification"], "ai_angle_match": pr.get("ai_angle_match"),
                      "human_relabel": pr.get("human_relabel"), "human_note": pr.get("human_note"), "pair_source": pr.get("pair_source")})
    standins = _interior_standins()
    return {
        "plate": key, "vehicle_model": REGISTERED.get(key, {}).get("visual_model") or v.get("model_note"),
        "role": REGISTERED.get(key, {}).get("role"),
        "cover_image": before[0]["url"] if before else None,
        "before": before, "after": after, "pairs": pairs,
        "complete_pair": v.get("complete_pair"), "verified_pair_angles": v.get("verified_pair_angles"),
        "quality_score": v.get("total_score"), "scores": v.get("scores"), "damage_angles": v.get("damage_angles"),
        "interior_standin": {
            "available": len(standins) >= 2,
            "note": "資料集沒有同一租約的車內借／還照；Preloaded Demo 用其他車輛的「乾淨」車內照當佔位（非本車），只為讓 5 張齊全跑 pipeline。",
            "pickup": ri.photo_url(str(standins[0]["path"])) if standins else None,
            "return": ri.photo_url(str(standins[1]["path"])) if len(standins) > 1 else None,
        },
        "manifest_generated_at": manifest().get("generated_at"),
    }


def registered_plates() -> list[str]:
    return [p for p in REGISTERED if any(v["plate"] == p for v in manifest().get("vehicles", []))]


class PreloadError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def preload(session: dict, stage: str) -> dict:
    """模式 B：把登記的照片灌進 Session 的租約。stage=pickup 用借車前照（4 角）+ 車內佔位；return 用還車後照 + 車內佔位。
    之後 rental_inspections 的既有邏輯：pickup 齊 → 基準；return 齊 → 背景 AI 分析（與即時拍攝相同）。"""
    if stage not in ("pickup", "return"):
        raise PreloadError(422, "stage must be pickup or return")
    photos = vehicle_photos(session["vehicle"]["plate"])
    if not photos:
        raise PreloadError(404, "此車輛沒有登記的 Demo 照片（只能即時拍攝）")
    items = photos["before"] if stage == "pickup" else photos["after"]
    if not items:
        raise PreloadError(404, f"此車輛沒有{ '借車前' if stage == 'pickup' else '還車後' }照片")
    rid = session["rental_id"]
    captured = ri.now_iso()
    ingested = []
    for it in items:
        if not it.get("angle"):
            continue
        path = _abs(it["image"])
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        res = ri.ingest_photo(
            rental_id=rid, stage=stage, view=it["angle"], image_sha256=sha, captured_at=captured, storage_path=str(path),
            local_result={"passed": True, "plateText": it["plate_recognition"]["ocr_text"] or session["vehicle"]["plate"],
                          "plateConfidence": it["plate_recognition"]["confidence"], "plateSource": "preloaded",
                          "detectedView": it["angle"], "viewConfidence": None, "errors": [],
                          "modelVersions": {"mode": "preloaded", "manifest": photos["manifest_generated_at"] or ""},
                          "preloaded": True, "pair_verification": next((p["pair_verification"] for p in photos["pairs"] if p["angle"] == it["angle"]), None)},
            photo_id=f"pre_{session['session_id']}_{stage}_{it['angle']}", validation_mode="preloaded", source="demo_preload")
        ingested.append({"angle": it["angle"], "photo_id": res["photo_id"], "url": it["url"]})
    standin = photos["interior_standin"]
    standins = _interior_standins()
    if standin["available"]:
        sp = standins[0 if stage == "pickup" else 1]["path"]
        sha = hashlib.sha256(sp.read_bytes()).hexdigest()
        res = ri.ingest_photo(
            rental_id=rid, stage=stage, view=ri.INTERIOR_ANGLE, image_sha256=sha, captured_at=captured, storage_path=str(sp),
            local_result={"passed": True, "plateText": None, "plateSource": "preloaded", "interior_standin": True,
                          "standin_note": standin["note"], "modelVersions": {"mode": "preloaded"}, "preloaded": True},
            photo_id=f"pre_{session['session_id']}_{stage}_車內", validation_mode="preloaded", source="demo_preload")
        ingested.append({"angle": ri.INTERIOR_ANGLE, "photo_id": res["photo_id"], "url": ri.photo_url(str(sp)), "interior_standin": True})
    return {"stage": stage, "ingested": ingested, "rental_status": res["rental_status"], "completeness": res["completeness"],
            "triggered": res["triggered"], "mode": "preloaded", "note": "預載 Demo 照片（資料集），非當下拍攝；AI 檢測走與即時拍攝相同的 pipeline。"}
