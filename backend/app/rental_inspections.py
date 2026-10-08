"""租約檢查（Rental Inspection）領域層：Rental → Pickup/Return Inspection → Photo → Comparison → Incident。

把 iOS App 上傳的照片（POST /v1/mobile-inspections/photos）從「檔案系統裡的檔案」
變成有歸屬的資料：每張照片知道自己屬於哪筆租約、哪台車、取車還是還車、哪個角度。

流程（CAPTURE → BASELINE → COMPARE → DETECT → INCIDENT）：
  ingest_photo()      冪等寫入照片（同租約／同階段／同角度／同 sha256 只存一次）
  _check_pickup()     4 車外 + 1 車內 齊 → PICKUP_COMPLETE → 建立 Pickup Baseline
  _check_return()     齊 → RETURN_COMPLETE → 背景執行緒 run_analysis()
  run_analysis()      ANALYZING → 逐角度 Pickup vs Return 比對 + 車內整潔 → ANALYSIS_COMPLETE
                      只有 NEW_DAMAGE / CLEANING_REQUIRED 才建立 Incident（案件）；
                      NO_NEW_DAMAGE / EXISTING_DAMAGE / CLEAN 仍保留 Inspection Record。

Incident 以 case_id `RI-<rental_id>-<角度>` 進入既有裁決／整備任務路徑
（server.post_decision → tasks → /api/ops），管理者端不需要第二套事件模型。

Demo 與 Production 分離：只有 demo_inspection_fixture.is_demo_rental() 的租約
用 fixture 固定結果；其他租約走 judge_photos.judge_pair / judge_interior。
背景機制沿用 inspections_api 的 threading.Thread（單容器、免費層 RPM 限制）。
"""
from __future__ import annotations

import json
import sqlite3
import sys
import threading
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import body_regions
import demo_inspection_fixture as fixture
import paths

# ---------- 常數 ----------

EXTERIOR_ANGLES = ("左前", "右前", "左後", "右後")
INTERIOR_ANGLE = "車內"
ALL_ANGLES = EXTERIOR_ANGLES + (INTERIOR_ANGLE,)
ANGLE_CODES = {"左前": "FRONT_LEFT", "右前": "FRONT_RIGHT", "左後": "REAR_LEFT",
               "右後": "REAR_RIGHT", "車內": "INTERIOR"}
CODE_TO_ANGLE = {v: k for k, v in ANGLE_CODES.items()}
STAGE_TO_TYPE = {"pickup": "PICKUP", "return": "RETURN"}
TYPE_TO_STAGE = {v: k for k, v in STAGE_TO_TYPE.items()}

# Rental 狀態機（線性；照片補傳不會倒退）
STATUS_ORDER = ("CREATED", "PICKUP_IN_PROGRESS", "PICKUP_COMPLETE", "RETURN_IN_PROGRESS",
                "RETURN_COMPLETE", "ANALYZING", "ANALYSIS_COMPLETE", "ANALYSIS_FAILED")
COMPARISON_RESULTS = ("NEW_DAMAGE", "EXISTING_DAMAGE", "NO_NEW_DAMAGE", "UNCOMPARABLE", "NO_BASELINE", "DUPLICATE_PHOTO")
INTERIOR_RESULTS = ("CLEANING_REQUIRED", "CLEAN", "UNREADABLE", "DUPLICATE_PHOTO")

# 證據完整性：還車照與取車照內容完全相同（SHA-256 一致）。AI 比對兩張一樣的照片一定是「無新增」，
# 但這張照片不能證明還車當下的車況，所以另開一件待人工複核的案件（不擋還車、App 不告知）。
DUPLICATE_SUMMARY = "還車照與取車照內容完全相同（SHA-256 一致），無法作為還車當下的車況證據，請要求補拍或人工複核。"


def _is_duplicate(pickup_photo: dict | None, return_photo: dict | None) -> bool:
    return bool(pickup_photo and return_photo and pickup_photo.get("image_sha256")
                and pickup_photo["image_sha256"] == return_photo["image_sha256"])


def _duplicate_result() -> dict:
    return {"result": "DUPLICATE_PHOTO", "findings": [], "boxes": [], "summary": DUPLICATE_SUMMARY}

CASE_PREFIX = "RI-"
MOBILE_UPLOAD_DIRNAME = "mobile-inspections"

_srv = None          # server 模組（bind 後：DB_PATH 可被測試 monkeypatch）
_analysis_lock = threading.Lock()


def bind(server_module) -> None:
    global _srv
    _srv = server_module


def db_path():
    return getattr(_srv, "DB_PATH", None) or paths.DB_PATH


def upload_root() -> Path:
    return paths.UPLOAD_DIR / MOBILE_UPLOAD_DIRNAME


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ---------- Schema ----------

DDL = [
    """CREATE TABLE IF NOT EXISTS rentals(
         rental_id      TEXT PRIMARY KEY,
         vehicle_id     TEXT NOT NULL,
         plate          TEXT NOT NULL,
         vehicle_model  TEXT,
         status         TEXT NOT NULL,
         pickup_at      TEXT,
         return_at      TEXT,
         analysis_started_at TEXT,
         analysis_completed_at TEXT,
         analysis_error TEXT,
         analysis_source TEXT,          -- demo_fixture | pipeline
         versions_json  TEXT,
         source         TEXT NOT NULL,  -- mobile | demo_seed
         demo           INTEGER NOT NULL DEFAULT 0,
         created_at     TEXT NOT NULL,
         updated_at     TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS rental_inspections(
         id              INTEGER PRIMARY KEY AUTOINCREMENT,
         rental_id       TEXT NOT NULL,
         inspection_type TEXT NOT NULL,  -- PICKUP | RETURN
         status          TEXT NOT NULL,  -- IN_PROGRESS | COMPLETE
         completed_at    TEXT,
         baseline_json   TEXT,           -- PICKUP：既有車損基準
         interior_skipped INTEGER NOT NULL DEFAULT 0,  -- 車內照選填：使用者完成拍攝時略過
         created_at      TEXT NOT NULL,
         UNIQUE(rental_id, inspection_type))""",
    """CREATE TABLE IF NOT EXISTS inspection_photos(
         photo_id        TEXT PRIMARY KEY,   -- App 端 UUID（重試不重複）或伺服器產生
         rental_id       TEXT NOT NULL,
         vehicle_id      TEXT NOT NULL,
         inspection_type TEXT NOT NULL,
         photo_category  TEXT NOT NULL,      -- exterior | interior
         view_angle      TEXT NOT NULL,      -- 左前 | 右前 | 左後 | 右後 | 車內（沿用 ViewClassifier 命名）
         image_sha256    TEXT NOT NULL,
         captured_at     TEXT NOT NULL,
         uploaded_at     TEXT NOT NULL,
         storage_path    TEXT,
         validation_json TEXT NOT NULL,      -- 裝置端 Core ML 結果（plate / view / quality）
         validation_mode TEXT NOT NULL,      -- coreml | demo | seed
         source          TEXT NOT NULL,      -- mobile | demo_seed
         UNIQUE(rental_id, inspection_type, view_angle, image_sha256))""",
    """CREATE TABLE IF NOT EXISTS inspection_comparisons(
         id              INTEGER PRIMARY KEY AUTOINCREMENT,
         rental_id       TEXT NOT NULL,
         view_angle      TEXT NOT NULL,
         result          TEXT NOT NULL,
         findings_json   TEXT NOT NULL,
         boxes_json      TEXT NOT NULL,
         summary         TEXT,
         pickup_photo_id TEXT,
         return_photo_id TEXT,
         assessment_json TEXT,               -- 模型原始輸出（demo 為 fixture）
         created_at      TEXT NOT NULL,
         UNIQUE(rental_id, view_angle))""",
    """CREATE TABLE IF NOT EXISTS inspection_incidents(
         case_id         TEXT PRIMARY KEY,   -- RI-<rental_id>-<角度>
         rental_id       TEXT NOT NULL,
         car             TEXT NOT NULL,
         kind            TEXT NOT NULL,      -- damage | cleaning
         view_angle      TEXT NOT NULL,
         region          TEXT,               -- Digital Twin 區域 id（body_regions）
         label           TEXT,
         damage_type     TEXT,
         severity        TEXT,
         confidence      REAL,
         ai_level        TEXT,
         findings_json   TEXT NOT NULL,
         boxes_json      TEXT NOT NULL,
         summary         TEXT,
         pickup_photo_id TEXT,
         return_photo_id TEXT,
         created_at      TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_insp_photo_rental ON inspection_photos(rental_id, inspection_type)",
    "CREATE INDEX IF NOT EXISTS idx_insp_incident_rental ON inspection_incidents(rental_id)",
]

_schema_ready: set[str] = set()


class db:
    """`with db() as conn:` —— 共用監理台同一個 SQLite 檔；離開時 commit / rollback 並關閉。"""

    def __init__(self):
        self.path = str(db_path())

    def __enter__(self):
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        if self.path not in _schema_ready:
            for stmt in DDL:
                self.conn.execute(stmt)
            cols = {r[1] for r in self.conn.execute("PRAGMA table_info(rental_inspections)")}
            if "interior_skipped" not in cols:   # 車內照選填：使用者完成拍攝時選擇略過
                self.conn.execute("ALTER TABLE rental_inspections ADD COLUMN interior_skipped INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()
            _schema_ready.add(self.path)
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()


def reset_schema_cache() -> None:
    _schema_ready.clear()


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


def _loads(v, default):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


# ---------- Rental 登記 ----------

def ensure_registered_rentals() -> None:
    """啟動時登記示範租約（取代原 DEMO_RENTAL_PLATES）。正式環境改接租賃系統。"""
    with db() as conn:
        for r in fixture.REGISTERED_RENTALS:
            register_rental(conn, r["rental_id"], r["plate"], r["vehicle_id"], r.get("vehicle_model"),
                            demo=True, source="mobile")


def register_rental(conn, rental_id: str, plate: str, vehicle_id: str, vehicle_model: str | None = None,
                    *, demo: bool = False, source: str = "mobile") -> dict:
    now = now_iso()
    conn.execute(
        "INSERT OR IGNORE INTO rentals(rental_id, vehicle_id, plate, vehicle_model, status, source, demo,"
        " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (rental_id, vehicle_id, plate, vehicle_model, "CREATED", source, int(demo), now, now))
    return get_rental(rental_id, conn)


def get_rental(rental_id: str, conn=None) -> dict | None:
    if conn is None:
        with db() as c:
            return get_rental(rental_id, c)
    r = conn.execute("SELECT * FROM rentals WHERE rental_id=?", (rental_id,)).fetchone()
    return dict(r) if r else None


def _set_status(conn, rental_id: str, status: str, **fields) -> None:
    sets = ["status=?", "updated_at=?"]
    vals = [status, now_iso()]
    for k, v in fields.items():
        sets.append(f"{k}=?")
        vals.append(v)
    vals.append(rental_id)
    conn.execute(f"UPDATE rentals SET {', '.join(sets)} WHERE rental_id=?", vals)


def _advance(conn, rental: dict, target: str, **fields) -> None:
    """狀態只往前走（補傳照片不倒退）。"""
    if STATUS_ORDER.index(target) >= STATUS_ORDER.index(rental["status"]):
        _set_status(conn, rental["rental_id"], target, **fields)
        rental["status"] = target


# ---------- 照片入庫 ----------

class IngestError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def photo_category_for(view: str) -> str:
    return "interior" if view == INTERIOR_ANGLE else "exterior"


def ingest_photo(*, rental_id: str, stage: str, view: str, image_sha256: str, captured_at: str,
                 storage_path: str | None, local_result: dict, photo_id: str | None = None,
                 validation_mode: str = "coreml", source: str = "mobile") -> dict:
    """冪等寫入一張照片並推進租約狀態。回傳給 App 的狀態摘要。"""
    itype = STAGE_TO_TYPE[stage]
    with db() as conn:
        rental = get_rental(rental_id, conn)
        if not rental:
            raise IngestError(404, "unknown rental_id")
        if itype == "PICKUP" and STATUS_ORDER.index(rental["status"]) > STATUS_ORDER.index("PICKUP_COMPLETE"):
            dup = conn.execute(
                "SELECT photo_id FROM inspection_photos WHERE rental_id=? AND inspection_type=? AND view_angle=? AND image_sha256=?",
                (rental_id, itype, view, image_sha256)).fetchone()
            if not dup:
                raise IngestError(409, "此租約的取車檢查已結束，無法再新增取車照片；示範租約請先重新開始 Demo")
        now = now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO rental_inspections(rental_id, inspection_type, status, created_at) VALUES (?,?,?,?)",
            (rental_id, itype, "IN_PROGRESS", now))
        existing = conn.execute(
            "SELECT photo_id FROM inspection_photos WHERE rental_id=? AND inspection_type=? AND view_angle=? AND image_sha256=?",
            (rental_id, itype, view, image_sha256)).fetchone()
        if photo_id:
            same_id = conn.execute("SELECT image_sha256 FROM inspection_photos WHERE photo_id=?", (photo_id,)).fetchone()
            if same_id and same_id[0] != image_sha256:
                photo_id = None       # 同 id 不同內容：不覆蓋，另存
        deduplicated = existing is not None
        if not deduplicated:
            pid = photo_id or f"ph_{uuid.uuid4().hex[:12]}"
            if conn.execute("SELECT 1 FROM inspection_photos WHERE photo_id=?", (pid,)).fetchone():
                pid = f"ph_{uuid.uuid4().hex[:12]}"
            conn.execute(
                "INSERT INTO inspection_photos(photo_id, rental_id, vehicle_id, inspection_type, photo_category,"
                " view_angle, image_sha256, captured_at, uploaded_at, storage_path, validation_json,"
                " validation_mode, source) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pid, rental_id, rental["vehicle_id"], itype, photo_category_for(view), view, image_sha256,
                 captured_at, now, storage_path, json.dumps(local_result, ensure_ascii=False),
                 validation_mode, source))
            photo_id = pid
        else:
            photo_id = existing[0]
        if itype == "PICKUP":
            _advance(conn, rental, "PICKUP_IN_PROGRESS")
            triggered = _check_pickup(conn, rental)
        else:
            _advance(conn, rental, "RETURN_IN_PROGRESS")
            triggered = _check_return(conn, rental)
        completeness = _completeness(conn, rental_id, itype)
        status = rental["status"]
    if triggered == "analysis":
        ANALYSIS_RUNNER(rental_id)
    return {"photo_id": photo_id, "deduplicated": deduplicated, "rental_status": status,
            "inspection_type": itype, "completeness": completeness, "triggered": triggered}


def _completeness(conn, rental_id: str, itype: str) -> dict:
    got = {r[0] for r in conn.execute(
        "SELECT DISTINCT view_angle FROM inspection_photos WHERE rental_id=? AND inspection_type=?",
        (rental_id, itype))}
    # 車內照為選填：四個外觀角度齊即完成；車內照有拍就一起分析（整潔度），沒拍就不判定
    missing = [a for a in EXTERIOR_ANGLES if a not in got]
    skipped = conn.execute("SELECT interior_skipped FROM rental_inspections WHERE rental_id=? AND inspection_type=?",
                           (rental_id, itype)).fetchone()
    interior_done = INTERIOR_ANGLE in got
    return {"required": list(EXTERIOR_ANGLES), "optional": [INTERIOR_ANGLE],
            "received": [a for a in ALL_ANGLES if a in got],
            "missing": missing, "complete": not missing,
            "interior_skipped": bool(skipped and skipped[0]) and not interior_done,
            # 還車分析的觸發條件：外觀齊，且車內照已上傳或使用者已略過（避免補拍車內照時重跑一次 AI）
            "ready": not missing and (interior_done or bool(skipped and skipped[0])),
            "exterior": {"received": sum(a in got for a in EXTERIOR_ANGLES), "required": len(EXTERIOR_ANGLES)},
            "interior": {"received": int(interior_done), "required": 0}}


def finish_capture(rental_id: str, stage: str) -> dict:
    """使用者按「完成」：車內照沒拍 → 記為略過；外觀已齊就建立基準（取車）或開始 AI 分析（還車）。
    外觀還沒齊（照片還在上傳）時只記旗標，最後一張外觀照上傳後自動觸發。"""
    itype = STAGE_TO_TYPE[stage]
    with db() as conn:
        rental = get_rental(rental_id, conn)
        if not rental:
            raise IngestError(404, "unknown rental_id")
        now = now_iso()
        conn.execute("INSERT OR IGNORE INTO rental_inspections(rental_id, inspection_type, status, created_at) VALUES (?,?,?,?)",
                     (rental_id, itype, "IN_PROGRESS", now))
        got = {r[0] for r in conn.execute("SELECT DISTINCT view_angle FROM inspection_photos WHERE rental_id=? AND inspection_type=?",
                                          (rental_id, itype))}
        if INTERIOR_ANGLE not in got:
            conn.execute("UPDATE rental_inspections SET interior_skipped=1 WHERE rental_id=? AND inspection_type=?", (rental_id, itype))
        triggered = None
        if itype == "RETURN" and rental["status"] not in ("RETURN_COMPLETE", "ANALYZING", "ANALYSIS_COMPLETE", "ANALYSIS_FAILED"):
            triggered = _check_return(conn, rental)
        completeness = _completeness(conn, rental_id, itype)
    if triggered == "analysis":
        ANALYSIS_RUNNER(rental_id)
    return {"triggered": triggered, "completeness": completeness}


def _latest_photos(conn, rental_id: str, itype: str) -> dict[str, dict]:
    """每個角度取最後上傳的一張（重拍以最新為準）。"""
    out: dict[str, dict] = {}
    for r in rows(conn.execute(
            "SELECT * FROM inspection_photos WHERE rental_id=? AND inspection_type=? ORDER BY uploaded_at, rowid",
            (rental_id, itype))):
        out[r["view_angle"]] = r
    return out


def _check_pickup(conn, rental: dict) -> str | None:
    if not _completeness(conn, rental["rental_id"], "PICKUP")["complete"]:
        return None
    # 齊了就（重）建基準：重拍以最新照片為準，基準跟著更新
    photos = _latest_photos(conn, rental["rental_id"], "PICKUP")
    pickup_at = max((p["captured_at"] for p in photos.values()), default=now_iso())
    baseline = _build_baseline(rental, photos)
    conn.execute("UPDATE rental_inspections SET status='COMPLETE', completed_at=?, baseline_json=?"
                 " WHERE rental_id=? AND inspection_type='PICKUP'",
                 (now_iso(), json.dumps(baseline, ensure_ascii=False), rental["rental_id"]))
    _advance(conn, rental, "PICKUP_COMPLETE", pickup_at=pickup_at)
    return "baseline"


def _build_baseline(rental: dict, photos: dict[str, dict]) -> dict:
    """Pickup Baseline：照片集合 + 既有車損。Production 不跑單張損傷列舉（成本／免費層限制），
    既有損傷在還車比對時由模型的 pre_existing_notes 帶出；Demo 由 fixture 提供。"""
    base = {"photo_ids": {a: p["photo_id"] for a, p in photos.items()}, "established_at": now_iso()}
    if fixture.is_demo_rental(rental["rental_id"]):
        base.update(fixture.baseline())
    else:
        base.update({"source": "pipeline", "existing_damage": [],
                     "note": "基準由取車照建立；既有損傷於還車比對時由模型標註（pre_existing_notes）。"})
    return base


def _check_return(conn, rental: dict) -> str | None:
    if not _completeness(conn, rental["rental_id"], "RETURN")["ready"]:
        return None
    photos = _latest_photos(conn, rental["rental_id"], "RETURN")
    return_at = max((p["captured_at"] for p in photos.values()), default=now_iso())
    conn.execute("UPDATE rental_inspections SET status='COMPLETE', completed_at=? WHERE rental_id=? AND inspection_type='RETURN'",
                 (now_iso(), rental["rental_id"]))
    # 還車齊了就（重新）排分析；補傳／重拍會再跑一次，案件以 case_id 覆寫
    _set_status(conn, rental["rental_id"], "RETURN_COMPLETE", return_at=return_at, analysis_error=None)
    rental["status"] = "RETURN_COMPLETE"
    return "analysis"


# ---------- 背景分析 ----------

def _spawn_analysis(rental_id: str) -> None:
    threading.Thread(target=run_analysis, args=(rental_id,), daemon=True).start()


ANALYSIS_RUNNER = _spawn_analysis   # 測試可換成同步呼叫


def recover_stale_analyses() -> list[str]:
    """啟動時復原：分析是行內 thread，process 被 kill 會讓租約永遠卡在 RETURN_COMPLETE / ANALYZING。
    還車已齊 → 重新排入分析；還車未齊（不該發生，防呆）→ 退回 RETURN_IN_PROGRESS。"""
    requeued = []
    with db() as conn:
        for r in rows(conn.execute("SELECT rental_id FROM rentals WHERE status IN ('RETURN_COMPLETE','ANALYZING')")):
            rid = r["rental_id"]
            if _completeness(conn, rid, "RETURN")["ready"]:
                _set_status(conn, rid, "RETURN_COMPLETE", analysis_error=None)
                requeued.append(rid)
            else:
                _set_status(conn, rid, "RETURN_IN_PROGRESS")
    for rid in requeued:
        print(f"rental analysis requeued after restart: {rid}", file=sys.stderr)
        ANALYSIS_RUNNER(rid)
    return requeued


def run_analysis(rental_id: str) -> dict | None:
    """RETURN_COMPLETE → ANALYZING → ANALYSIS_COMPLETE | ANALYSIS_FAILED。失敗保留紀錄、不擋還車。"""
    with _analysis_lock:
        with db() as conn:
            rental = get_rental(rental_id, conn)
            if not rental:
                return None
            _set_status(conn, rental_id, "ANALYZING", analysis_started_at=now_iso())
            pickup = _latest_photos(conn, rental_id, "PICKUP")
            ret = _latest_photos(conn, rental_id, "RETURN")
            base_row = conn.execute("SELECT baseline_json FROM rental_inspections WHERE rental_id=? AND inspection_type='PICKUP'",
                                    (rental_id,)).fetchone()
            baseline = _loads(base_row[0] if base_row else None, {})
        try:
            if fixture.is_demo_rental(rental_id):
                result = fixture.analysis()
            else:
                result = _real_analysis(rental, pickup, ret, baseline)
        except BaseException as e:   # get_client() 無 key 會 sys.exit → SystemExit 也要接住
            err = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"rental analysis failed ({rental_id}): {err}", file=sys.stderr)
            traceback.print_exc()
            with db() as conn:
                _set_status(conn, rental_id, "ANALYSIS_FAILED", analysis_error=err,
                            analysis_completed_at=now_iso())
            return None
        with db() as conn:
            _write_results(conn, rental, result, pickup, ret)
            _set_status(conn, rental_id, "ANALYSIS_COMPLETE", analysis_completed_at=now_iso(),
                        analysis_source=result.get("source"), analysis_error=None,
                        versions_json=json.dumps(result.get("versions") or {}, ensure_ascii=False))
        return result


def _real_analysis(rental: dict, pickup: dict, ret: dict, baseline: dict) -> dict:
    """Production path：逐角度 judge_pair + 車內 judge_interior（既有 pipeline，不重寫）。"""
    from run_eval_gemini import find_key  # noqa: PLC0415
    if not find_key():
        raise RuntimeError("GEMINI_API_KEY 未設定：無法執行 AI 比對（紀錄已保存，待人工複核）")
    from judge_photos import judge_interior, judge_pair  # noqa: PLC0415
    from prompt_manifest import PROMPT_VERSIONS  # noqa: PLC0415

    out = {"source": "pipeline", "exterior": {}, "interior": None,
           "versions": {"prompt_p7": PROMPT_VERSIONS.get("P7"), "prompt_p9": PROMPT_VERSIONS.get("P9"),
                        "threshold": PROMPT_VERSIONS.get("threshold")}}
    for angle in EXTERIOR_ANGLES:
        p, r = pickup.get(angle), ret.get(angle)
        if not r or not r.get("storage_path"):
            continue
        if not p or not p.get("storage_path"):
            out["exterior"][angle] = {"result": "NO_BASELINE", "findings": [], "boxes": [],
                                      "summary": "缺少取車基準照，無法比對。"}
            continue
        if _is_duplicate(p, r):
            out["exterior"][angle] = _duplicate_result()   # 同一張照片不必送 AI
            continue
        res, _img = judge_pair(p["storage_path"], r["storage_path"], angle=angle)
        out["exterior"][angle] = _map_pair_result(res, angle)
    r = ret.get(INTERIOR_ANGLE)
    if r and r.get("storage_path"):
        if _is_duplicate(pickup.get(INTERIOR_ANGLE), r):
            out["interior"] = _duplicate_result()
        else:
            res, _img = judge_interior(r["storage_path"])
            out["interior"] = _map_interior_result(res)
    return out


def _map_pair_result(res: dict, angle: str) -> dict:
    final = res.get("final")
    if not final:
        return {"result": "UNCOMPARABLE", "findings": [], "boxes": [],
                "summary": f"照片品質不合格（{res.get('retake_reason') or 'gate'}），無法比對。", "assessment": res}
    findings, boxes = [], []
    for d in final.get("damages") or []:
        region = body_regions.locate_exterior(d.get("location"), angle)
        findings.append({"region": region, "label": d.get("location") or body_regions.REGION_LABELS[region],
                         "type": d.get("type"), "severity": d.get("severity"), "confidence": d.get("confidence"),
                         "status": "NEW_DAMAGE", "reasoning": d.get("reasoning")})
        if len(d.get("box_2d") or []) == 4:
            boxes.append({"box_2d": d["box_2d"], "label": d.get("type") or "新損", "severity": d.get("severity"),
                          "confidence": d.get("confidence"), "description": f"{d.get('location')}：{d.get('reasoning')}"})
    pre = (final.get("pre_existing_notes") or "").strip()
    if pre:
        region = body_regions.locate_exterior(pre, angle)
        findings.append({"region": region, "label": pre, "type": None, "severity": None, "confidence": None,
                         "status": "EXISTING_DAMAGE", "reasoning": "取車照與還車照皆存在，列為既有損傷。"})
    if final.get("new_damage_found"):
        result = "NEW_DAMAGE"
    elif not final.get("angle_match", True):
        result = "UNCOMPARABLE"
    elif pre:
        result = "EXISTING_DAMAGE"
    else:
        result = "NO_NEW_DAMAGE"
    summary = {"NEW_DAMAGE": f"{angle}偵測到 {len(boxes) or len([f for f in findings if f['status']=='NEW_DAMAGE'])} 處新增車損。",
               "UNCOMPARABLE": "兩張照片無法有效比對。",
               "EXISTING_DAMAGE": "僅既有損傷，無新增車損。",
               "NO_NEW_DAMAGE": "未發現新增車損。"}[result]
    return {"result": result, "findings": findings, "boxes": boxes, "summary": summary,
            "assessment": {k: v for k, v in res.items() if k not in ("gate",)}, "level": res.get("level")}


def _map_interior_result(res: dict) -> dict:
    final = res.get("final") or (res.get("screening") or {}).get("assessment")
    if not final:
        return {"result": "UNREADABLE", "cleanliness": None, "confidence": None, "findings": [], "boxes": [],
                "summary": f"車內照無法判讀（{res.get('retake_reason') or 'gate'}）。", "assessment": res}
    if final.get("photo_ok") is False:
        return {"result": "UNREADABLE", "cleanliness": None, "confidence": final.get("confidence"), "findings": [],
                "boxes": [], "summary": f"車內照無法判讀：{final.get('invalid_reason') or ''}", "assessment": res}
    findings, boxes = [], []
    for i, f in enumerate(final.get("findings") or []):
        label = f.get("label") or "髒污"
        findings.append({"label": label, "region": body_regions.locate_interior(label, i),
                         "severity": f.get("severity"), "confidence": f.get("confidence"),
                         "description": f.get("description")})
        if len(f.get("box_2d") or []) == 4:
            boxes.append({"box_2d": f["box_2d"], "label": label, "severity": f.get("severity"),
                          "confidence": f.get("confidence"), "description": f.get("description")})
    dirty = final.get("level") == "髒汙"
    return {"result": "CLEANING_REQUIRED" if dirty else "CLEAN", "cleanliness": final.get("level"),
            "confidence": final.get("confidence"), "score": res.get("score"), "findings": findings, "boxes": boxes,
            "summary": f"車內「{final.get('level')}」：{final.get('reasoning') or ''}",
            "assessment": {k: v for k, v in res.items() if k not in ("gate",)}}


def _write_results(conn, rental: dict, result: dict, pickup: dict, ret: dict) -> None:
    rid = rental["rental_id"]
    now = now_iso()
    conn.execute("DELETE FROM inspection_comparisons WHERE rental_id=?", (rid,))
    wanted: dict[str, dict] = {}
    for angle, cmp in (result.get("exterior") or {}).items():
        p, r = pickup.get(angle), ret.get(angle)
        conn.execute(
            "INSERT INTO inspection_comparisons(rental_id, view_angle, result, findings_json, boxes_json, summary,"
            " pickup_photo_id, return_photo_id, assessment_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, angle, cmp["result"], json.dumps(cmp.get("findings") or [], ensure_ascii=False),
             json.dumps(cmp.get("boxes") or [], ensure_ascii=False), cmp.get("summary"),
             p["photo_id"] if p else None, r["photo_id"] if r else None,
             json.dumps(cmp.get("assessment"), ensure_ascii=False, default=str) if cmp.get("assessment") else None, now))
        if cmp["result"] == "DUPLICATE_PHOTO":
            wanted[case_id_for(rid, angle)] = _integrity_incident(angle, cmp, p, r)
        new = [f for f in cmp.get("findings") or [] if f.get("status") == "NEW_DAMAGE"]
        if cmp["result"] == "NEW_DAMAGE" and new:
            top = max(new, key=lambda f: f.get("confidence") or 0)
            conf = top.get("confidence")
            level = "P1" if (conf or 0) >= 0.85 or any(f.get("severity") == "high" for f in new) else "P2"
            wanted[case_id_for(rid, angle)] = {
                "kind": "damage", "view_angle": angle, "region": top.get("region"), "label": top.get("label"),
                "damage_type": top.get("type"), "severity": top.get("severity"), "confidence": conf, "ai_level": level,
                "findings": new, "boxes": cmp.get("boxes") or [], "summary": cmp.get("summary"),
                "pickup_photo_id": p["photo_id"] if p else None, "return_photo_id": r["photo_id"] if r else None}
    interior = result.get("interior")
    if interior:
        r = ret.get(INTERIOR_ANGLE)
        p = pickup.get(INTERIOR_ANGLE)
        conn.execute(
            "INSERT INTO inspection_comparisons(rental_id, view_angle, result, findings_json, boxes_json, summary,"
            " pickup_photo_id, return_photo_id, assessment_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, INTERIOR_ANGLE, interior["result"], json.dumps(interior.get("findings") or [], ensure_ascii=False),
             json.dumps(interior.get("boxes") or [], ensure_ascii=False), interior.get("summary"),
             p["photo_id"] if p else None, r["photo_id"] if r else None,
             json.dumps({k: v for k, v in interior.items() if k not in ("findings", "boxes")}, ensure_ascii=False, default=str), now))
        if interior["result"] == "DUPLICATE_PHOTO":
            wanted[case_id_for(rid, INTERIOR_ANGLE)] = _integrity_incident(INTERIOR_ANGLE, interior, p, r)
        if interior["result"] == "CLEANING_REQUIRED":
            wanted[case_id_for(rid, INTERIOR_ANGLE)] = {
                "kind": "cleaning", "view_angle": INTERIOR_ANGLE, "region": "interior", "label": "車內",
                "damage_type": None, "severity": "medium", "confidence": interior.get("confidence"), "ai_level": "P1",
                "findings": interior.get("findings") or [], "boxes": interior.get("boxes") or [],
                "summary": interior.get("summary"), "pickup_photo_id": p["photo_id"] if p else None,
                "return_photo_id": r["photo_id"] if r else None}
    # 案件以 case_id 覆寫；重跑後不再成立且尚未裁決的案件移除
    existing = {r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (rid,))}
    decided = {r[0] for r in conn.execute("SELECT case_id FROM decisions")} if _table_exists(conn, "decisions") else set()
    for cid in existing - set(wanted):
        if cid not in decided:
            conn.execute("DELETE FROM inspection_incidents WHERE case_id=?", (cid,))
    for cid, inc in wanted.items():
        conn.execute(
            "INSERT OR REPLACE INTO inspection_incidents(case_id, rental_id, car, kind, view_angle, region, label,"
            " damage_type, severity, confidence, ai_level, findings_json, boxes_json, summary, pickup_photo_id,"
            " return_photo_id, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, rid, rental["plate"], inc["kind"], inc["view_angle"], inc["region"], inc["label"], inc["damage_type"],
             inc["severity"], inc["confidence"], inc["ai_level"], json.dumps(inc["findings"], ensure_ascii=False),
             json.dumps(inc["boxes"], ensure_ascii=False), inc["summary"], inc["pickup_photo_id"], inc["return_photo_id"], now))


def _integrity_incident(angle: str, cmp: dict, p: dict | None, r: dict | None) -> dict:
    """照片重複使用 → 證據完整性案件（P2、待人工複核；confirm 不會自動開維修／清潔單的依據：assessment 無 damages）。"""
    return {"kind": "integrity", "view_angle": angle, "region": "interior" if angle == INTERIOR_ANGLE else None,
            "label": f"{angle}照片與取車相同", "damage_type": None, "severity": None, "confidence": 1.0,
            "ai_level": "P2", "findings": [], "boxes": [], "summary": cmp.get("summary") or DUPLICATE_SUMMARY,
            "pickup_photo_id": p["photo_id"] if p else None, "return_photo_id": r["photo_id"] if r else None}


def _table_exists(conn, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def case_id_for(rental_id: str, angle: str) -> str:
    return f"{CASE_PREFIX}{rental_id}-{angle}"


# ---------- 照片 URL ----------

def photo_url(storage_path: str | None) -> str | None:
    """絕對路徑 → 可供圖的 URL：App 上傳 → /photos/mobile/…；示範佔位照 → 既有 /photos/pair|interior/…。"""
    if not storage_path:
        return None
    p = Path(storage_path)
    try:
        rel = p.resolve().relative_to(upload_root().resolve())
        return "/photos/mobile/" + "/".join(quote(part) for part in rel.parts)
    except ValueError:
        pass
    if "interior_photos" in p.parts:
        return f"/photos/interior/{quote(p.name)}"
    return f"/photos/pair/{quote(p.name)}"


def resolve_mobile_photo(rel_path: str) -> Path | None:
    """/photos/mobile/<rel> → 檔案；防路徑穿越。"""
    root = upload_root().resolve()
    target = (root / rel_path).resolve()
    if root not in target.parents or not target.is_file():
        return None
    return target


# ---------- 查詢（Admin / App） ----------

def _photo_view(p: dict | None) -> dict | None:
    if not p:
        return None
    v = _loads(p.get("validation_json"), {})
    return {"photo_id": p["photo_id"], "angle": p["view_angle"], "angle_code": ANGLE_CODES.get(p["view_angle"]),
            "category": p["photo_category"], "captured_at": p["captured_at"], "uploaded_at": p["uploaded_at"],
            "url": photo_url(p.get("storage_path")), "validation_mode": p["validation_mode"], "source": p["source"],
            "validation": {"passed": v.get("passed"), "plate_text": v.get("plateText"),
                           "plate_confidence": v.get("plateConfidence"), "view": v.get("detectedView"),
                           "view_confidence": v.get("viewConfidence"), "model_versions": v.get("modelVersions") or {}}}


def _overall_result(rental: dict, incidents: list[dict]) -> str:
    st = rental["status"]
    if st == "ANALYSIS_COMPLETE":
        return "ISSUES" if incidents else "PASSED"
    if st == "ANALYSIS_FAILED":
        return "FAILED"
    if st in ("RETURN_COMPLETE", "ANALYZING"):
        return "ANALYZING"
    return "PENDING"


def _rental_summary(conn, rental: dict) -> dict:
    rid = rental["rental_id"]
    incidents = rows(conn.execute("SELECT case_id, kind, view_angle, region, label, confidence, ai_level FROM inspection_incidents WHERE rental_id=? ORDER BY kind", (rid,)))
    insp = {r["inspection_type"]: r for r in rows(conn.execute("SELECT * FROM rental_inspections WHERE rental_id=?", (rid,)))}
    return {
        "rental_id": rid, "vehicle_id": rental["vehicle_id"], "plate": rental["plate"],
        "vehicle_model": rental["vehicle_model"], "status": rental["status"],
        "pickup_at": rental["pickup_at"], "return_at": rental["return_at"],
        "pickup": {**_completeness(conn, rid, "PICKUP"), "status": (insp.get("PICKUP") or {}).get("status"),
                   "completed_at": (insp.get("PICKUP") or {}).get("completed_at")},
        "return": {**_completeness(conn, rid, "RETURN"), "status": (insp.get("RETURN") or {}).get("status"),
                   "completed_at": (insp.get("RETURN") or {}).get("completed_at")},
        "result": _overall_result(rental, incidents), "issue_count": len(incidents),
        "incidents": incidents, "analysis": {"source": rental["analysis_source"], "error": rental["analysis_error"],
                                             "started_at": rental["analysis_started_at"],
                                             "completed_at": rental["analysis_completed_at"]},
        "source": rental["source"], "demo": bool(rental["demo"]), "updated_at": rental["updated_at"],
    }


def list_inspections() -> list[dict]:
    with db() as conn:
        rentals = rows(conn.execute("SELECT * FROM rentals ORDER BY COALESCE(return_at, pickup_at, updated_at) DESC"))
        out = [_rental_summary(conn, r) for r in rentals]
    # 還沒有任何照片的登記租約不列（它們只是車牌登記）
    return [s for s in out if s["pickup"]["received"] or s["return"]["received"]]


def inspection_detail(rental_id: str) -> dict | None:
    with db() as conn:
        rental = get_rental(rental_id, conn)
        if not rental:
            return None
        summary = _rental_summary(conn, rental)
        pickup = _latest_photos(conn, rental_id, "PICKUP")
        ret = _latest_photos(conn, rental_id, "RETURN")
        base_row = conn.execute("SELECT baseline_json FROM rental_inspections WHERE rental_id=? AND inspection_type='PICKUP'", (rental_id,)).fetchone()
        comps = rows(conn.execute("SELECT * FROM inspection_comparisons WHERE rental_id=?", (rental_id,)))
        incidents = rows(conn.execute("SELECT * FROM inspection_incidents WHERE rental_id=?", (rental_id,)))
    by_angle = {c["view_angle"]: c for c in comps}
    comparisons = []
    for angle in ALL_ANGLES:
        c = by_angle.get(angle)
        comparisons.append({
            "angle": angle, "angle_code": ANGLE_CODES[angle], "category": photo_category_for(angle),
            "pickup_photo": _photo_view(pickup.get(angle)), "return_photo": _photo_view(ret.get(angle)),
            "result": c["result"] if c else None, "findings": _loads(c["findings_json"], []) if c else [],
            "boxes": _loads(c["boxes_json"], []) if c else [], "summary": c["summary"] if c else None,
            "case_id": next((i["case_id"] for i in incidents if i["view_angle"] == angle), None),
        })
    interior_cmp = by_angle.get(INTERIOR_ANGLE)
    interior_assess = _loads(interior_cmp["assessment_json"], {}) if interior_cmp else {}
    summary["baseline"] = _loads(base_row[0] if base_row else None, None)
    summary["comparisons"] = comparisons
    summary["interior"] = ({"result": interior_cmp["result"], "cleanliness": interior_assess.get("cleanliness"),
                            "confidence": interior_assess.get("confidence"), "score": interior_assess.get("score"),
                            "findings": _loads(interior_cmp["findings_json"], []), "summary": interior_cmp["summary"]}
                           if interior_cmp else None)
    summary["versions"] = _loads(rental.get("versions_json"), {})
    summary["incidents"] = [{**i, "findings": _loads(i["findings_json"], []), "boxes": _loads(i["boxes_json"], [])}
                            for i in incidents]
    for i in summary["incidents"]:
        i.pop("findings_json", None)
        i.pop("boxes_json", None)
    return summary


def app_status(rental_id: str) -> dict | None:
    """給 App 的精簡狀態：收到幾張、分析狀態。刻意不回傳車損／髒汙判定（App 不歸責）。"""
    with db() as conn:
        rental = get_rental(rental_id, conn)
        if not rental:
            return None
        s = _rental_summary(conn, rental)
    return {"rental_id": rental_id, "plate": s["plate"], "vehicle_model": s["vehicle_model"], "status": s["status"],
            "pickup": s["pickup"], "return": s["return"],
            "analysis": "complete" if s["status"] == "ANALYSIS_COMPLETE" else
                        "failed" if s["status"] == "ANALYSIS_FAILED" else
                        "analyzing" if s["status"] in ("RETURN_COMPLETE", "ANALYZING") else "pending",
            "demo": s["demo"]}


# ---------- 給既有裁決／案件路徑（server._case_snapshot、ops_api.list_cases） ----------

def is_case_id(case_id: str) -> bool:
    return case_id.startswith(CASE_PREFIX)


def _incident_rows(case_id: str | None = None) -> list[dict]:
    with db() as conn:
        if case_id:
            inc = rows(conn.execute("SELECT * FROM inspection_incidents WHERE case_id=?", (case_id,)))
        else:
            inc = rows(conn.execute("SELECT * FROM inspection_incidents ORDER BY created_at DESC"))
        if not inc:
            return []
        rids = {i["rental_id"] for i in inc}
        rentals = {r["rental_id"]: r for r in rows(conn.execute(
            f"SELECT * FROM rentals WHERE rental_id IN ({','.join('?' * len(rids))})", tuple(rids)))}
        photos = {p["photo_id"]: p for p in rows(conn.execute(
            f"SELECT * FROM inspection_photos WHERE rental_id IN ({','.join('?' * len(rids))})", tuple(rids)))}
    for i in inc:
        i["rental"] = rentals.get(i["rental_id"])
        i["pickup_photo"] = photos.get(i["pickup_photo_id"])
        i["return_photo"] = photos.get(i["return_photo_id"])
        i["findings"] = _loads(i.pop("findings_json"), [])
        i["boxes"] = _loads(i.pop("boxes_json"), [])
    return inc


def case_car(case_id: str) -> str | None:
    inc = _incident_rows(case_id)
    return inc[0]["car"] if inc else None


def _assessment_for(inc: dict) -> dict:
    if inc["kind"] == "integrity":
        # 沒有 damages / issues：confirm 後不會據此生成維修或清潔內容，案件本身要求的是補拍／人工複核
        return {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": None,
                "pre_existing_notes": "", "integrity": "DUPLICATE_PHOTO", "reasoning": inc["summary"]}
    if inc["kind"] == "cleaning":
        return {"level": "髒汙", "confidence": inc["confidence"], "score": None,
                "issues": [f.get("label") for f in inc["findings"]], "reasoning": inc["summary"]}
    return {"angle_match": True, "new_damage_found": True,
            "damages": [{"location": f.get("label"), "type": f.get("type"), "severity": f.get("severity"),
                         "confidence": f.get("confidence"), "reasoning": f.get("reasoning"), "region": f.get("region")}
                        for f in inc["findings"]],
            "no_damage_confidence": 0.0, "pre_existing_notes": ""}


def case_snapshot(case_id: str) -> dict | None:
    """server._case_snapshot 的 RI- 分支：裁決建單與訓練標籤所需的快照。照片存絕對路徑。"""
    inc = _incident_rows(case_id)
    if not inc:
        return None
    i = inc[0]
    if i["kind"] == "cleaning":
        photos = {"photo": (i["return_photo"] or {}).get("storage_path")}
        mode = "interior"
    else:
        photos = {"pickup": (i["pickup_photo"] or {}).get("storage_path"),
                  "return": (i["return_photo"] or {}).get("storage_path")}
        mode = "pair"
    return {"mode": mode, "source": "mobile", "ai_found": 1, "ai_level": i["ai_level"], "ai_conf": i["confidence"],
            "photos": photos, "assessment": _assessment_for(i), "boxes": i["boxes"],
            "rental_id": i["rental_id"], "region": i["region"]}


def ops_cases(case_id: str | None = None) -> list[dict]:
    """App 產生的案件 → 與 ops_api._dataset_case_list 相同形狀（attach_case_state 之前）。"""
    out = []
    for i in _incident_rows(case_id):
        rental = i["rental"] or {}
        common = {
            "case_id": i["case_id"], "car": i["car"], "angle": i["view_angle"], "kind": None,
            "ai_level": i["ai_level"], "ai_conf": i["confidence"], "ai_found": True,
            "pricing": None, "truth": "mobile", "boxes": i["boxes"],
            "source": "mobile_inspection",
            "rental": {"rental_id": i["rental_id"], "pickup_at": rental.get("pickup_at"),
                       "return_at": rental.get("return_at"), "vehicle_model": rental.get("vehicle_model"),
                       "analysis_source": rental.get("analysis_source")},
        }
        if i["kind"] == "integrity":
            out.append({**common, "mode": "interior" if i["view_angle"] == INTERIOR_ANGLE else "pair",
                        "kind": "照片重複", "damages": [], "issues": [i["summary"]], "cleanliness": None, "score": None,
                        "photos": {"pickup": photo_url((i["pickup_photo"] or {}).get("storage_path")),
                                   "return": photo_url((i["return_photo"] or {}).get("storage_path")),
                                   "photo": photo_url((i["return_photo"] or {}).get("storage_path"))}})
        elif i["kind"] == "cleaning":
            out.append({**common, "mode": "interior", "kind": "車內髒污",
                        "damages": [], "issues": [f.get("label") for f in i["findings"]],
                        "cleanliness": "髒汙", "score": None,
                        "photos": {"photo": photo_url((i["return_photo"] or {}).get("storage_path")),
                                   "pickup": photo_url((i["pickup_photo"] or {}).get("storage_path"))}})
        else:
            out.append({**common, "mode": "pair", "kind": "新車損" if i["ai_level"] == "P1" else "疑似新損",
                        "damages": [{"location": f.get("label"), "type": f.get("type"), "severity": f.get("severity"),
                                     "confidence": f.get("confidence"), "reasoning": f.get("reasoning"),
                                     "region": f.get("region")} for f in i["findings"]],
                        "issues": [], "cleanliness": None, "score": None,
                        "photos": {"pickup": photo_url((i["pickup_photo"] or {}).get("storage_path")),
                                   "return": photo_url((i["return_photo"] or {}).get("storage_path"))}})
    return out


def vehicles() -> dict[str, dict]:
    """車牌 → 租約摘要（供 /api/ops/fleet 補車型與最近還車時間）。"""
    with db() as conn:
        rs = rows(conn.execute("SELECT * FROM rentals WHERE pickup_at IS NOT NULL OR return_at IS NOT NULL"
                               " ORDER BY COALESCE(return_at, pickup_at)"))
    out = {}
    for r in rs:
        out[r["plate"]] = {"model": r["vehicle_model"], "rental_id": r["rental_id"], "status": r["status"],
                           "pickup_at": r["pickup_at"], "return_at": r["return_at"]}
    return out


def incident_case_ids(rental_id: str) -> list[str]:
    with db() as conn:
        return [r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (rental_id,))]


# ---------- Demo：重新開始／重置 ----------

def clear_rental(conn, rental_id: str) -> None:
    """刪除該租約的檢查、照片、比對、案件紀錄，租約本身回到 CREATED（登記保留）。"""
    for t in ("rental_inspections", "inspection_photos", "inspection_comparisons", "inspection_incidents"):
        conn.execute(f"DELETE FROM {t} WHERE rental_id=?", (rental_id,))
    conn.execute("UPDATE rentals SET status='CREATED', pickup_at=NULL, return_at=NULL, analysis_started_at=NULL,"
                 " analysis_completed_at=NULL, analysis_error=NULL, analysis_source=NULL, versions_json=NULL,"
                 " updated_at=? WHERE rental_id=?", (now_iso(), rental_id))


def clear_return_stage(conn, rental_id: str) -> list[str]:
    """重新拍攝還車照：刪掉該租約的 RETURN 照片、比對結果與衍生案件，租約退回 PICKUP_COMPLETE（取車基準保留）。
    回傳被清掉的 case_id（呼叫端用 server.reset_case_state 清裁決／任務）。"""
    case_ids = [r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (rental_id,))]
    conn.execute("DELETE FROM inspection_photos WHERE rental_id=? AND inspection_type='RETURN'", (rental_id,))
    conn.execute("DELETE FROM rental_inspections WHERE rental_id=? AND inspection_type='RETURN'", (rental_id,))
    conn.execute("DELETE FROM inspection_comparisons WHERE rental_id=?", (rental_id,))
    conn.execute("DELETE FROM inspection_incidents WHERE rental_id=?", (rental_id,))
    conn.execute("UPDATE rentals SET status='PICKUP_COMPLETE', return_at=NULL, analysis_started_at=NULL,"
                 " analysis_completed_at=NULL, analysis_error=NULL, analysis_source=NULL, versions_json=NULL,"
                 " updated_at=? WHERE rental_id=?", (now_iso(), rental_id))
    return case_ids


def restart_rental(rental_id: str) -> dict:
    """App「重新開始 Demo」：只允許 demo 租約。案件的裁決／任務由 server.demo_reset 同路徑清理。"""
    with db() as conn:
        rental = get_rental(rental_id, conn)
        if not rental:
            raise IngestError(404, "unknown rental_id")
        if not rental["demo"]:
            raise IngestError(403, "只有示範租約可以重新開始")
        case_ids = incident_case_ids(rental_id)
        clear_rental(conn, rental_id)
    return {"rental_id": rental_id, "status": "CREATED", "cleared_cases": case_ids}


def seed_demo_rental(run: bool = True) -> dict:
    """DEMO_MODE 啟動／重置時：示範租約直接落在 ANALYSIS_COMPLETE（含佔位照），管理者端不依賴 iOS。"""
    spec = fixture.DEMO_RENTAL
    rid = spec["rental_id"]
    with db() as conn:
        register_rental(conn, rid, spec["plate"], spec["vehicle_id"], spec["vehicle_model"], demo=True, source="mobile")
        clear_rental(conn, rid)
        conn.execute("UPDATE rentals SET source='demo_seed' WHERE rental_id=?", (rid,))
        now = now_iso()
        for itype in ("PICKUP", "RETURN"):
            conn.execute("INSERT OR IGNORE INTO rental_inspections(rental_id, inspection_type, status, created_at) VALUES (?,?,?,?)",
                         (rid, itype, "IN_PROGRESS", now))
        for n, p in enumerate(fixture.stand_in_photos()):
            conn.execute(
                "INSERT INTO inspection_photos(photo_id, rental_id, vehicle_id, inspection_type, photo_category, view_angle,"
                " image_sha256, captured_at, uploaded_at, storage_path, validation_json, validation_mode, source)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f"seed_{rid}_{n}", rid, spec["vehicle_id"], p["inspection_type"], photo_category_for(p["view_angle"]),
                 p["view_angle"], f"seed{n:02d}", p["captured_at"], p["captured_at"], p["storage_path"],
                 json.dumps({"passed": True, "plateText": spec["plate"], "modelVersions": {"mode": "seed"}}, ensure_ascii=False),
                 "seed", "demo_seed"))
        rental = get_rental(rid, conn)
        rental["status"] = "CREATED"
        _advance(conn, rental, "PICKUP_IN_PROGRESS")
        _check_pickup(conn, rental)
        _advance(conn, rental, "RETURN_IN_PROGRESS")
        _check_return(conn, rental)
        conn.execute("UPDATE rentals SET pickup_at=?, return_at=? WHERE rental_id=?",
                     (spec["pickup_at"], spec["return_at"], rid))
    if run:
        run_analysis(rid)
    return app_status(rid)
