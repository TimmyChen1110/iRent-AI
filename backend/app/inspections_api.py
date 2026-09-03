#!/usr/bin/env python3
"""判讀 API（服務化規格 §5，第二優先——把現有 pipeline 包成非同步服務）。

  POST /v1/inspections                    建立（rental_id、angle 選填）→ inspection_id
  POST /v1/inspections/{id}/photos        上傳（role=pickup|return），可分批續傳
  POST /v1/inspections/{id}/finalize      封存排入佇列 → 202；冪等鍵重複回既有 id
  GET  /v1/inspections/{id}               狀態與結果（含 versions 每筆必回）

設計要點（照規格）：
  - 非同步是硬性要求：finalize 立即回應，結果輪詢取得。
    照片可分批補傳（地下停車場離線 → 恢復連線續傳 → finalize 才觸發）。
  - 冪等鍵 (rental_id, sha256(sorted(photo_hashes)))：佇列重送不重新推論。
  - v6 觸發限縮（feature_flags.should_run_v6）：只在「判無新損＋帶既有損主張」
    跑列舉。前提已驗（89 筆無主張案零已知真新損）。flag off → 只寫入不派送。
  - 降級不停止還車流程：單模型故障 → v6 停用（交集無法成立）主判定照跑；
    主判定失敗 → 照片已存檔，status=manual_review 進人工佇列。
  - versions 每筆必回：沒有它三個月後的爭議無法回答。

生產訊號寫 pipeline/shadow_signals_live.jsonl——與第一期資料集檔分開，
資料集檔（shadow_signals.jsonl）是評測基準，不混入生產流量。
"""
import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"

import paths  # noqa: E402  執行期可設定的路徑（Docker 掛 volume 於此）
UPLOADS = paths.UPLOAD_DIR
LIVE_SIGNALS = paths.LIVE_SIGNALS_PATH
DB_PATH = paths.DB_PATH

from feature_flags import should_run_v6  # noqa: E402
from prompt_manifest import PROMPT_VERSIONS  # noqa: E402

router = APIRouter()
_proc_lock = threading.Lock()
_write_lock = threading.Lock()

MODELS = {"flash": "gemini-3.7-flash", "pro": "gemini-3.1-pro-preview"}


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS inspections(
        inspection_id TEXT PRIMARY KEY,
        rental_id     TEXT NOT NULL,
        angle         TEXT,
        status        TEXT NOT NULL,   -- created|queued|processing|completed|manual_review
        idem_key      TEXT,
        created_at    TEXT NOT NULL,
        result        TEXT,            -- JSON：verdict/signals/versions
        error         TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_insp_idem ON inspections(idem_key)")
    return conn


def idempotency_key(rental_id: str, photo_hashes: list) -> str:
    """(rental_id, sha256(sorted(photo_hashes)))——佇列重送不重新推論。純函式。"""
    digest = hashlib.sha256("".join(sorted(photo_hashes)).encode()).hexdigest()
    return f"{rental_id}:{digest}"


def versions_block() -> dict:
    return {"prompt_p7": PROMPT_VERSIONS["P7"], "prompt_p9": PROMPT_VERSIONS["P9"],
            "threshold": PROMPT_VERSIONS["threshold"], "models": MODELS}


def _photo_paths(iid: str) -> dict:
    d = UPLOADS / iid
    out = {}
    for role in ("pickup", "return"):
        files = sorted((d / role).glob("*")) if (d / role).exists() else []
        if files:
            out[role] = files[0]
    return out


@router.post("/v1/inspections")
def create_inspection(rental_id: str = Form(...), angle: str = Form(None)):
    iid = f"insp_{uuid.uuid4().hex[:12]}"
    conn = _db()
    conn.execute("INSERT INTO inspections(inspection_id, rental_id, angle, status, created_at) "
                 "VALUES(?,?,?,?,?)",
                 (iid, rental_id, angle, "created", datetime.now().isoformat()))
    conn.commit()
    (UPLOADS / iid).mkdir(parents=True, exist_ok=True)
    return {"inspection_id": iid, "status": "created"}


@router.post("/v1/inspections/{iid}/photos")
async def upload_photo(iid: str, role: str = Form(...), file: UploadFile = File(...)):
    if role not in ("pickup", "return"):
        raise HTTPException(422, "role must be pickup|return")
    conn = _db()
    row = conn.execute("SELECT status FROM inspections WHERE inspection_id=?", (iid,)).fetchone()
    if not row:
        raise HTTPException(404)
    if row[0] not in ("created",):
        raise HTTPException(409, f"cannot upload in status {row[0]}")
    d = UPLOADS / iid / role
    d.mkdir(parents=True, exist_ok=True)
    data = await file.read()
    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    (d / f"{hashlib.sha256(data).hexdigest()[:16]}{suffix}").write_bytes(data)
    return {"inspection_id": iid, "role": role, "bytes": len(data)}


@router.post("/v1/inspections/{iid}/finalize")
def finalize(iid: str):
    conn = _db()
    row = conn.execute("SELECT rental_id, status FROM inspections WHERE inspection_id=?",
                       (iid,)).fetchone()
    if not row:
        raise HTTPException(404)
    rental_id, status = row
    if status != "created":
        return {"inspection_id": iid, "status": status}   # finalize 冪等
    photos = _photo_paths(iid)
    if "pickup" not in photos or "return" not in photos:
        raise HTTPException(422, "need both pickup and return photos")
    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in photos.values()]
    key = idempotency_key(rental_id, hashes)
    dup = conn.execute("SELECT inspection_id, status FROM inspections "
                       "WHERE idem_key=? AND inspection_id!=?", (key, iid)).fetchone()
    if dup:
        return {"inspection_id": dup[0], "status": dup[1], "deduplicated": True}
    conn.execute("UPDATE inspections SET status='queued', idem_key=? WHERE inspection_id=?",
                 (key, iid))
    conn.commit()
    threading.Thread(target=_process, args=(iid,), daemon=True).start()
    return JSONResponse({"inspection_id": iid, "status": "queued"}, status_code=202)


@router.get("/v1/inspections/{iid}")
def get_inspection(iid: str):
    conn = _db()
    row = conn.execute("SELECT status, result, error, rental_id, angle "
                       "FROM inspections WHERE inspection_id=?", (iid,)).fetchone()
    if not row:
        raise HTTPException(404)
    status, result, error, rental_id, angle = row
    out = {"inspection_id": iid, "rental_id": rental_id, "angle": angle,
           "status": status, "versions": versions_block()}
    if result:
        out.update(json.loads(result))
    if error:
        out["error"] = error
    return out


def _process(iid: str):
    """背景判讀：主判定 → v6 觸發限縮 → shadow 訊號寫入。降級不擋流程。"""
    with _proc_lock:   # 免費層 RPM 有限，逐案處理
        conn = _db()
        conn.execute("UPDATE inspections SET status='processing' WHERE inspection_id=?", (iid,))
        conn.commit()
        row = conn.execute("SELECT angle FROM inspections WHERE inspection_id=?", (iid,)).fetchone()
        angle = row[0] if row else None
        photos = _photo_paths(iid)
        result = {"signals": {"layer": "v6", "enabled": False, "mode": "shadow",
                              "intersection": [], "union_only": []}}
        try:
            from judge_photos import judge_pair
            verdict, _annotated = judge_pair(photos["pickup"], photos["return"], angle=angle)
            result["verdict"] = verdict
        except Exception as e:
            # 主判定失敗：照片已存檔，進人工佇列，不擋還車
            conn.execute("UPDATE inspections SET status='manual_review', error=? "
                         "WHERE inspection_id=?", (str(e)[:300], iid))
            conn.commit()
            return
        try:
            result["signals"] = _v6_layer(photos, angle, verdict)
        except Exception as e:
            result["signals"]["degraded"] = str(e)[:200]   # v6 降級，主判定不受影響
        conn.execute("UPDATE inspections SET status='completed', result=? WHERE inspection_id=?",
                     (json.dumps(result, ensure_ascii=False, default=str), iid))
        conn.commit()


def extract_trigger(verdict: dict) -> tuple:
    """從主判定結果取 v6 觸發條件輸入。純函式。"""
    a = (verdict or {}).get("assessment") or (verdict or {}).get("final") or {}
    no_new = not a.get("new_damage_found", True)
    has_claim = bool((a.get("pre_existing_notes") or "").strip())
    return no_new, has_claim, a


def _v6_layer(photos: dict, angle: str, verdict: dict) -> dict:
    """v6 shadow 層：觸發限縮 → 4 次列舉 → 差分 → 只寫入不派送（flag off）。"""
    from blind_enumeration import PANEL_ZH_CACHE, diff_signals, enumerate_panel
    from diff_new_damage import panel_of
    from run_eval_gemini import get_client
    from shadow_mode import COUNT_THRESHOLD, EXTENT_THRESHOLD, signal_records_for_case
    from taxonomy import PANEL_ZH
    PANEL_ZH_CACHE.update(PANEL_ZH)

    no_new, has_claim, a = extract_trigger(verdict)
    gate = should_run_v6(no_new, has_claim)
    out = {"layer": "v6", "enabled": gate["dispatch"], "mode": "shadow",
           "triggered": gate["run"], "intersection": [], "union_only": []}
    if not gate["run"]:
        return out
    panel = panel_of({"location": a.get("pre_existing_notes", "")}, angle)
    if panel is None:
        panel = "FB" if angle and "前" in angle else "RB"
    client = get_client()
    per_model = {}
    for m in MODELS.values():
        per_model[m] = {
            role: enumerate_panel(client, m, str(photos[role]), panel,
                                  PANEL_ZH_CACHE.get(panel, panel))["parsed"]
            for role in ("pickup", "return")}
    case = {"car": "LIVE", "angle": angle or "?", "panel": panel, "claim": a.get("pre_existing_notes", "")}
    records = signal_records_for_case(case, per_model, "live")
    for r in records:
        r["dispatched"] = r["dispatched"] and gate["dispatch"]   # flag off → 不派送
        entry = {"cell": r["signal_cells"][0], "signal_type": r["signal_type"]}
        if r["model_agreement"] == "both":
            out["intersection"].append(entry)
        else:
            out["union_only"].append({**entry, "model": "flash" if "flash" in r["model_agreement"] else "pro"})
    LIVE_SIGNALS.parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, LIVE_SIGNALS.open("a") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return out
