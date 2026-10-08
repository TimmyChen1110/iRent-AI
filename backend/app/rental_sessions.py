"""模擬租還車 Session（Rental Session）領域層：模擬車輛 → 租車 → 使用 → 還車資訊 → 還車拍照 AI 檢測 → 還車確認。

這一層把「使用者在 App 上的租還車流程」疊在既有的租約檢查（rental_inspections）之上：
  - 車輛資料是 **模擬資料**（demo_vehicles.simulated=1），不是真實 iRent 車隊；位置是固定座標，不是 GPS 追蹤。
  - 每個 Session 綁一筆 rentals 列：取車／還車照片仍走既有 POST /v1/mobile-inspections/photos，
    AI 比對仍走 rental_inspections.run_analysis（真實 pipeline；只有示範固定劇本車輛走 demo fixture，且明確標示）。
  - 狀態轉換由後端驗證（App 只能請求轉換，不能自行跳狀態）：

      AVAILABLE ─(開始租車)→ PICKUP_INSPECTION ─(取車照齊＝基準建立)→ RENTED ─(我要還車)→ RETURN_INITIATED
        ─(確認還車資訊：結束里程≥起始里程)→ PHOTO_INSPECTION ─(還車照齊、AI 分析完成)→ INSPECTION_COMPLETED ─(確認還車)→ RETURNED
                                                                     └─(AI 分析失敗)→ INSPECTION_FAILED ─(重新檢測／重新拍攝)→ PHOTO_INSPECTION

  PHOTO_INSPECTION → INSPECTION_COMPLETED / INSPECTION_FAILED 由租約的分析狀態（ANALYSIS_COMPLETE / ANALYSIS_FAILED）推導，
  在每次讀取 Session 時同步落庫（lazy sync），所以 App 重新整理後也拿得到一致的狀態。

  「檢測完成」≠「還車完成」：必須 POST confirm-return 才會 RETURNED，車輛才回到 AVAILABLE。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import demo_inspection_fixture as fixture
import rental_inspections as ri
from rental_inspections import db, now_iso, rows

# ---------- 狀態 ----------

SESSION_STATES = ("PICKUP_INSPECTION", "RENTED", "RETURN_INITIATED", "PHOTO_INSPECTION",
                  "INSPECTION_COMPLETED", "INSPECTION_FAILED", "RETURNED", "CANCELLED", "ARCHIVED")
ACTIVE_STATES = ("PICKUP_INSPECTION", "RENTED", "RETURN_INITIATED", "PHOTO_INSPECTION",
                 "INSPECTION_COMPLETED", "INSPECTION_FAILED")
VEHICLE_STATES = ("AVAILABLE", "RENTED", "RETURNED")

# ---------- 模擬車輛（固定資料；不是真實 iRent 車隊） ----------
# 位置：臺灣大學第二學生活動中心（二活）周邊，座標為示意，可用 IRENT_SIM_VEHICLES_JSON 覆寫。
NTU_SAC2 = {"lat": 25.01785, "lng": 121.53412, "name": "臺灣大學第二學生活動中心（二活）· 模擬停車位"}
DEMO_VEHICLE_ID = "demo-rfy-1753"
DEMO_ASSETS_DIR = Path(__file__).resolve().parent / "demo_assets"

SIM_VEHICLES = [
    {
        # 資料集內真車：車牌可被裝置端 Core ML OCR 辨識；還車比對走真實 Gemini pipeline（需 GEMINI_API_KEY）。
        "vehicle_id": "SIM-RCG-2235", "plate": "RCG-2235", "model": "Toyota Yaris",
        "image_url": "/photos/pair/RCG2235%E5%B7%A6%E5%89%8D%20%E5%80%9F.jpg",
        "image_note": "資料集取車照（真實照片，僅供內部 Demo）",
        "lat": NTU_SAC2["lat"], "lng": NTU_SAC2["lng"], "location_name": NTU_SAC2["name"],
        "odometer_km": 23418, "fuel_percent": 72, "ai_source": "pipeline", "fixture_rental_id": None,
    },
    {
        # 比賽示範固定劇本：後端固定產生「右後車門刮痕 92% + 車內髒汙 88%」，**不是真實 AI 判定**，UI 必須標示。
        "vehicle_id": "SIM-ABC-1234", "plate": "ABC-1234", "model": "Toyota Yaris",
        "image_url": "/photos/pair/RCG2235%E5%8F%B3%E5%89%8D%20%E5%80%9F.jpg",
        "image_note": "示意圖（資料集佔位照，非 ABC-1234 本車）",
        "lat": 25.01702, "lng": 121.53560, "location_name": "臺灣大學 · 新生南路側門（模擬停車位）",
        "odometer_km": 18760, "fuel_percent": 58, "ai_source": "demo_fixture",
        "fixture_rental_id": fixture.DEMO_RENTAL_ID,
    },
    {
        # 固定 Demo 測試車輛（category=demo）：不受使用者定位／距離限制，App 首頁固定入口；可重複重設。
        # 車牌、車款、計費數字皆為示範值（依使用者提供的 iRent 截圖），不串接真實計費；圖片為程式生成的示意圖。
        "vehicle_id": DEMO_VEHICLE_ID, "plate": "RFY-1753", "model": "TOYOTA ALTIS HYBRID",
        "image_url": "/photos/demo/rfy-1753.png",
        "image_note": "Demo 示意圖（程式生成的白色轎車 placeholder，非本車實拍）",
        "lat": 25.01760, "lng": 121.53290, "location_name": "Demo 固定示範位置（臺大二活 67 號停車格，非真實車輛位置）",
        "odometer_km": 31250, "fuel_percent": 80, "ai_source": "pipeline", "fixture_rental_id": None,
        "category": "demo",
        "details": {
            "vehicle_type": "個人用車", "seats": 5, "parking_spot": "67", "color": "白色",
            "pricing": {"hourly_twd": 130, "per_km_twd": 3.5, "estimated_km_fee_twd": 70, "estimated_total_twd": 200,
                        "note": "示範數值，不串接真實 iRent 計費，不會產生任何費用"},
            "demo_pinned": True,
            "pinned_note": "不受 GPS 距離限制：不論使用者在哪裡、是否開啟定位，都可從首頁入口進入。",
        },
    },
    {
        # 主要影像辨識 Demo 車：資料集真車，4 角借／還配對皆 OCR 雙向驗證（DEMO_VEHICLE_CANDIDATES.md 第 1 名）。
        "vehicle_id": "demo-rdg-9853", "plate": "RDG-9853", "model": "Toyota Prius c（照片目視，資料集未記錄車型）",
        "image_url": "/photos/pair/RDG9853%E5%B7%A6%E5%89%8D%20%E5%80%9F.jpg",
        "image_note": "資料集借車前實拍（左前）。",
        "lat": 25.01830, "lng": 121.53300, "location_name": "Demo 固定示範位置（臺大二活周邊；非真實車輛位置）",
        "odometer_km": 42180, "fuel_percent": 65, "ai_source": "pipeline", "fixture_rental_id": None,
        "category": "demo",
        "details": {"vehicle_type": "個人用車", "seats": 5, "parking_spot": "二活 B 區", "color": "銀色（照片目視）",
                    "pricing": {"hourly_twd": 130, "per_km_twd": 3.5, "estimated_km_fee_twd": 70, "estimated_total_twd": 200,
                                "note": "示範數值，不串接真實 iRent 計費，不會產生任何費用"},
                    "demo_pinned": True, "registry_plate": "RDG-9853", "registry_role": "primary_inspection",
                    "pinned_note": "有已驗證的借車前／還車後照片，可用預載 Demo 照片（模式 B）或即時拍攝（模式 A）。"},
    },
    {
        # 車損展示 Demo 車：右後角人工重標為真實新損（保桿右下近輪拱擦痕），借／還 OCR 雙向驗證。
        "vehicle_id": "demo-rfh-8122", "plate": "RFH-8122", "model": "Honda Fit（照片目視，資料集未記錄車型）",
        "image_url": "/photos/pair/RFH8122%E5%8F%B3%E5%BE%8C%20%E5%80%9F.jpg",
        "image_note": "資料集借車前實拍（右後）。",
        "lat": 25.01720, "lng": 121.53200, "location_name": "Demo 固定示範位置（臺大二活周邊；非真實車輛位置）",
        "odometer_km": 27930, "fuel_percent": 54, "ai_source": "pipeline", "fixture_rental_id": None,
        "category": "demo",
        "details": {"vehicle_type": "個人用車", "seats": 5, "parking_spot": "二活 C 區", "color": "白色（照片目視）",
                    "pricing": {"hourly_twd": 130, "per_km_twd": 3.5, "estimated_km_fee_twd": 70, "estimated_total_twd": 200,
                                "note": "示範數值，不串接真實 iRent 計費，不會產生任何費用"},
                    "demo_pinned": True, "registry_plate": "RFH-8122", "registry_role": "damage_showcase",
                    "pinned_note": "右後角借／還照人工重標為真實新損，適合展示「偵測到新增車損」。"},
    },
]

DDL = [
    """CREATE TABLE IF NOT EXISTS demo_vehicles(
         vehicle_id     TEXT PRIMARY KEY,
         plate          TEXT NOT NULL,
         model          TEXT NOT NULL,
         image_url      TEXT,
         image_note     TEXT,
         lat            REAL NOT NULL,
         lng            REAL NOT NULL,
         location_name  TEXT,
         status         TEXT NOT NULL,          -- AVAILABLE | RENTED | RETURNED
         odometer_km    INTEGER NOT NULL,
         fuel_percent   INTEGER,
         ai_source      TEXT NOT NULL,          -- pipeline | demo_fixture
         fixture_rental_id TEXT,
         simulated      INTEGER NOT NULL DEFAULT 1,
         category       TEXT NOT NULL DEFAULT 'simulated',   -- simulated | demo（固定 Demo 測試車輛）
         details_json   TEXT,                                 -- 座位／停車格／顏色／示範計費
         last_returned_at TEXT,
         updated_at     TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS rental_sessions(
         session_id     TEXT PRIMARY KEY,
         vehicle_id     TEXT NOT NULL,
         rental_id      TEXT NOT NULL,
         plate          TEXT NOT NULL,
         vehicle_model  TEXT,
         state          TEXT NOT NULL,
         started_at     TEXT NOT NULL,
         start_lat      REAL, start_lng REAL, start_location_source TEXT,
         start_odometer_km INTEGER NOT NULL,
         return_initiated_at TEXT,
         return_info_confirmed_at TEXT,
         return_lat     REAL, return_lng REAL, return_location_source TEXT,
         end_odometer_km INTEGER,
         inspection_attempts INTEGER NOT NULL DEFAULT 0,
         returned_at    TEXT,
         cancelled_at   TEXT,
         last_error     TEXT,
         review_required INTEGER NOT NULL DEFAULT 0,
         created_at     TEXT NOT NULL,
         updated_at     TEXT NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_rs_vehicle ON rental_sessions(vehicle_id, state)",
]

_schema_ready: set[str] = set()
_srv = None


def bind(server_module) -> None:
    global _srv
    _srv = server_module


class SessionError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _ensure_schema(conn) -> None:
    key = str(ri.db_path())
    if key in _schema_ready:
        return
    for stmt in DDL:
        conn.execute(stmt)
    # 既有資料庫補欄位（SQLite 無 IF NOT EXISTS for ADD COLUMN）
    cols = {r[1] for r in conn.execute("PRAGMA table_info(demo_vehicles)")}
    if "category" not in cols:
        conn.execute("ALTER TABLE demo_vehicles ADD COLUMN category TEXT NOT NULL DEFAULT 'simulated'")
    if "details_json" not in cols:
        conn.execute("ALTER TABLE demo_vehicles ADD COLUMN details_json TEXT")
    conn.commit()
    _schema_ready.add(key)


def reset_schema_cache() -> None:
    _schema_ready.clear()


def _conn():
    """`with _conn() as conn:`——與 rental_inspections 共用同一個 SQLite 檔，並確保本模組的表存在。"""
    class _Ctx(db):
        def __enter__(self_inner):
            conn = super().__enter__()
            _ensure_schema(conn)
            return conn
    return _Ctx()


# ---------- 模擬車輛 ----------

def ensure_vehicles() -> None:
    """啟動時登記模擬車輛（INSERT OR IGNORE：不覆蓋既有狀態／里程）。"""
    with _conn() as conn:
        for v in SIM_VEHICLES:
            details = json.dumps(v.get("details") or {}, ensure_ascii=False)
            conn.execute(
                "INSERT OR IGNORE INTO demo_vehicles(vehicle_id, plate, model, image_url, image_note, lat, lng,"
                " location_name, status, odometer_km, fuel_percent, ai_source, fixture_rental_id, simulated,"
                " category, details_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?)",
                (v["vehicle_id"], v["plate"], v["model"], v["image_url"], v["image_note"], v["lat"], v["lng"],
                 v["location_name"], "AVAILABLE", v["odometer_km"], v["fuel_percent"], v["ai_source"],
                 v["fixture_rental_id"], v.get("category", "simulated"), details, now_iso()))
            # 靜態描述欄位以程式碼為單一資料來源（狀態／里程保留）
            conn.execute("UPDATE demo_vehicles SET category=?, details_json=?, image_url=?, image_note=?, location_name=?"
                         " WHERE vehicle_id=?", (v.get("category", "simulated"), details, v["image_url"], v["image_note"],
                                                 v["location_name"], v["vehicle_id"]))


def _vehicle_view(v: dict, active: dict | None) -> dict:
    return {
        "vehicle_id": v["vehicle_id"], "plate": v["plate"], "model": v["model"],
        "image_url": v["image_url"], "image_note": v["image_note"],
        "location": {"lat": v["lat"], "lng": v["lng"], "name": v["location_name"], "simulated": True},
        "status": v["status"], "odometer_km": v["odometer_km"], "fuel_percent": v["fuel_percent"],
        "ai_source": v["ai_source"],
        "ai_source_label": "示範固定劇本（非真實 AI 判定）" if v["ai_source"] == "demo_fixture" else "Gemini 模型級聯（真實 pipeline）",
        "simulated": True, "data_note": "模擬車輛資料，非真實 iRent 車隊；位置為固定座標，非 GPS 追蹤。",
        "category": v.get("category") or "simulated",
        "is_demo_vehicle": (v.get("category") or "simulated") == "demo",
        "details": json.loads(v["details_json"]) if v.get("details_json") else {},
        "active_session_id": active["session_id"] if active else None,
        "last_returned_at": v["last_returned_at"], "updated_at": v["updated_at"],
    }


def _active_for_vehicle(conn, vehicle_id: str) -> dict | None:
    r = conn.execute(
        f"SELECT * FROM rental_sessions WHERE vehicle_id=? AND state IN ({','.join('?' * len(ACTIVE_STATES))})"
        " ORDER BY created_at DESC LIMIT 1", (vehicle_id, *ACTIVE_STATES)).fetchone()
    return dict(r) if r else None


def list_vehicles() -> list[dict]:
    with _conn() as conn:
        vs = rows(conn.execute("SELECT * FROM demo_vehicles ORDER BY vehicle_id"))
        return [_vehicle_view(v, _active_for_vehicle(conn, v["vehicle_id"])) for v in vs]


def get_vehicle(vehicle_id: str) -> dict | None:
    with _conn() as conn:
        v = conn.execute("SELECT * FROM demo_vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone()
        return _vehicle_view(dict(v), _active_for_vehicle(conn, vehicle_id)) if v else None


# ---------- Session ----------

def _new_session_id() -> str:
    return f"RS-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"


def _new_rental_id(plate: str) -> str:
    return f"RNT-SIM-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4].upper()}"


def _get(conn, session_id: str) -> dict:
    r = conn.execute("SELECT * FROM rental_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not r:
        raise SessionError(404, "unknown session_id")
    return dict(r)


def _update(conn, session_id: str, **fields) -> None:
    fields["updated_at"] = now_iso()
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE rental_sessions SET {sets} WHERE session_id=?", (*fields.values(), session_id))


def _require_state(s: dict, *allowed: str) -> None:
    if s["state"] not in allowed:
        raise SessionError(409, f"目前狀態為 {s['state']}，此操作需要 {' / '.join(allowed)}")


def _reset_case_state(case_ids: list[str]) -> None:
    if case_ids and _srv is not None:
        _srv.reset_case_state(case_ids)


def _prepare_rental(conn, vehicle: dict) -> str:
    """每個 Session 一筆 rentals 列。示範固定劇本車輛重用固定租約（重置後重演）；其餘建立新租約（走真實 pipeline）。"""
    if vehicle["fixture_rental_id"]:
        rid = vehicle["fixture_rental_id"]
        ri.register_rental(conn, rid, vehicle["plate"], "VH-" + vehicle["plate"], vehicle["model"], demo=True, source="mobile")
        case_ids = [r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (rid,))]
        ri.clear_rental(conn, rid)
        conn.execute("UPDATE rentals SET source='mobile' WHERE rental_id=?", (rid,))
        _reset_case_state(case_ids)
        return rid
    prefix = "RNT-DEMO" if (vehicle.get("category") or "simulated") == "demo" else "RNT-SIM"
    rid = f"{prefix}-{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:4].upper()}"
    ri.register_rental(conn, rid, vehicle["plate"], vehicle["vehicle_id"], vehicle["model"], demo=True, source="simulation")
    return rid


def create_session(vehicle_id: str, user_location: dict | None = None) -> dict:
    with _conn() as conn:
        v = conn.execute("SELECT * FROM demo_vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone()
        if not v:
            raise SessionError(404, "unknown vehicle_id")
        v = dict(v)
        if _active_for_vehicle(conn, vehicle_id):
            raise SessionError(409, "此車輛已有進行中的租車 Session，請勿重複租車")
        if v["status"] != "AVAILABLE":
            raise SessionError(409, f"車輛狀態為 {v['status']}，無法租借")
        rid = _prepare_rental(conn, v)
        sid = _new_session_id()
        now = now_iso()
        loc = user_location or {}
        conn.execute(
            "INSERT INTO rental_sessions(session_id, vehicle_id, rental_id, plate, vehicle_model, state, started_at,"
            " start_lat, start_lng, start_location_source, start_odometer_km, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, vehicle_id, rid, v["plate"], v["model"], "PICKUP_INSPECTION", now,
             loc.get("lat"), loc.get("lng"), loc.get("source"), v["odometer_km"], now, now))
        conn.execute("UPDATE demo_vehicles SET status='RENTED', updated_at=? WHERE vehicle_id=?", (now, vehicle_id))
        return _view(conn, _get(conn, sid))


def active_session() -> dict | None:
    with _conn() as conn:
        r = conn.execute(
            f"SELECT * FROM rental_sessions WHERE state IN ({','.join('?' * len(ACTIVE_STATES))})"
            " ORDER BY created_at DESC LIMIT 1", ACTIVE_STATES).fetchone()
        return _view(conn, dict(r)) if r else None


def get_session(session_id: str) -> dict:
    with _conn() as conn:
        return _view(conn, _get(conn, session_id))


def complete_pickup(session_id: str) -> dict:
    """取車檢查完成 → RENTED。後端以租約狀態（PICKUP_COMPLETE：4 車外 + 1 車內 已齊）為準，不信 App 自稱。"""
    with _conn() as conn:
        s = _get(conn, session_id)
        if s["state"] == "RENTED":
            return _view(conn, s)
        _require_state(s, "PICKUP_INSPECTION")
        rental = ri.get_rental(s["rental_id"], conn)
        if not rental or ri.STATUS_ORDER.index(rental["status"]) < ri.STATUS_ORDER.index("PICKUP_COMPLETE"):
            missing = ri._completeness(conn, s["rental_id"], "PICKUP")["missing"]
            raise SessionError(409, f"取車照片尚未全部上傳（缺：{'、'.join(missing) or '未知'}），無法開始租用")
        _update(conn, session_id, state="RENTED")
        return _view(conn, _get(conn, session_id))


def initiate_return(session_id: str, user_location: dict | None = None) -> dict:
    with _conn() as conn:
        s = _get(conn, session_id)
        if s["state"] == "RETURN_INITIATED":
            return _view(conn, s)
        _require_state(s, "RENTED")
        loc = user_location or {}
        _update(conn, session_id, state="RETURN_INITIATED", return_initiated_at=now_iso(),
                return_lat=loc.get("lat"), return_lng=loc.get("lng"), return_location_source=loc.get("source"))
        return _view(conn, _get(conn, session_id))


def confirm_return_info(session_id: str, end_odometer_km: int, return_location: dict | None = None) -> dict:
    """還車資訊確認：驗證結束里程 ≥ 起始里程 → PHOTO_INSPECTION。"""
    with _conn() as conn:
        s = _get(conn, session_id)
        _require_state(s, "RETURN_INITIATED", "PHOTO_INSPECTION")
        if not isinstance(end_odometer_km, int) or isinstance(end_odometer_km, bool):
            raise SessionError(422, "end_odometer_km 必須是整數")
        if end_odometer_km < s["start_odometer_km"]:
            raise SessionError(422, f"結束里程 {end_odometer_km} km 不可小於起始里程 {s['start_odometer_km']} km")
        if end_odometer_km - s["start_odometer_km"] > 5000:
            raise SessionError(422, "單次租借行駛里程超過 5000 km，請確認輸入")
        fields = {"end_odometer_km": end_odometer_km, "return_info_confirmed_at": now_iso()}
        if return_location:
            fields.update(return_lat=return_location.get("lat"), return_lng=return_location.get("lng"),
                          return_location_source=return_location.get("source"))
        if s["state"] == "RETURN_INITIATED":
            fields["state"] = "PHOTO_INSPECTION"
            fields["inspection_attempts"] = 1
        _update(conn, session_id, **fields)
        return _view(conn, _get(conn, session_id))


def retry_inspection(session_id: str, mode: str = "reanalyze") -> dict:
    """INSPECTION_FAILED → PHOTO_INSPECTION。reanalyze：同一批還車照重新排入分析；retake：清掉還車照重新拍攝。"""
    if mode not in ("reanalyze", "retake"):
        raise SessionError(422, "mode must be reanalyze or retake")
    requeue = False
    with _conn() as conn:
        s = _get(conn, session_id)
        _require_state(s, "INSPECTION_FAILED", "INSPECTION_COMPLETED", "PHOTO_INSPECTION")
        rid = s["rental_id"]
        if mode == "retake":
            case_ids = ri.clear_return_stage(conn, rid)
            _reset_case_state(case_ids)
        else:
            if not ri._completeness(conn, rid, "RETURN")["complete"]:
                raise SessionError(409, "還車照片尚未齊全，無法重新檢測；請改用重新拍攝")
            ri._set_status(conn, rid, "RETURN_COMPLETE", analysis_error=None)
            requeue = True
        _update(conn, session_id, state="PHOTO_INSPECTION", inspection_attempts=s["inspection_attempts"] + 1, last_error=None)
    if requeue:
        ri.ANALYSIS_RUNNER(rid)
    return get_session(session_id)


def confirm_return(session_id: str) -> dict:
    """檢測完成 → 使用者確認還車 → RETURNED；車輛回到 AVAILABLE、里程更新。檢測未完成不得還車。"""
    with _conn() as conn:
        s = _sync(conn, _get(conn, session_id))
        if s["state"] == "RETURNED":
            return _view(conn, s)
        _require_state(s, "INSPECTION_COMPLETED")
        now = now_iso()
        review = 1 if _review_required(conn, s) else 0
        _update(conn, session_id, state="RETURNED", returned_at=now, review_required=review)
        conn.execute("UPDATE demo_vehicles SET status='AVAILABLE', odometer_km=?, last_returned_at=?, updated_at=?"
                     " WHERE vehicle_id=?", (s["end_odometer_km"], now, now, s["vehicle_id"]))
        return _view(conn, _get(conn, session_id))


def cancel_session(session_id: str) -> dict:
    """只允許在還沒開始用車（PICKUP_INSPECTION）時取消；車輛回到 AVAILABLE。"""
    with _conn() as conn:
        s = _get(conn, session_id)
        if s["state"] == "CANCELLED":
            return _view(conn, s)
        _require_state(s, "PICKUP_INSPECTION")
        now = now_iso()
        _update(conn, session_id, state="CANCELLED", cancelled_at=now)
        conn.execute("UPDATE demo_vehicles SET status='AVAILABLE', updated_at=? WHERE vehicle_id=?", (now, s["vehicle_id"]))
        return _view(conn, _get(conn, session_id))


def reset_all() -> dict:
    """Demo 重置：結束所有 Session、車輛回 AVAILABLE（里程保留）、模擬租約紀錄清掉。只給 DEMO_MODE 用。"""
    with _conn() as conn:
        sessions = rows(conn.execute("SELECT * FROM rental_sessions"))
        case_ids = []
        for s in sessions:
            case_ids += [r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (s["rental_id"],))]
            if s["rental_id"].startswith(("RNT-SIM-", "RNT-DEMO-")):
                ri.clear_rental(conn, s["rental_id"])
                conn.execute("DELETE FROM rentals WHERE rental_id=?", (s["rental_id"],))
        conn.execute("DELETE FROM rental_sessions")
        conn.execute("UPDATE demo_vehicles SET status='AVAILABLE', updated_at=?", (now_iso(),))
    _reset_case_state(case_ids)
    return {"ok": True, "cleared_sessions": len(sessions), "cleared_cases": case_ids}


def reset_vehicle(vehicle_id: str) -> dict:
    """重設單一 Demo 測試車輛（只允許 category=demo）：進行中的 Session 封存為 ARCHIVED、車輛回 AVAILABLE（里程保留）、
    該 Session 的租約檢查紀錄與衍生案件清掉。不碰其他車輛／正式資料，不碰 AI 判定邏輯。不需要 DEMO_MODE（展示者在 App 內就能重設）。"""
    with _conn() as conn:
        v = conn.execute("SELECT * FROM demo_vehicles WHERE vehicle_id=?", (vehicle_id,)).fetchone()
        if not v:
            raise SessionError(404, "unknown vehicle_id")
        if (dict(v).get("category") or "simulated") != "demo":
            raise SessionError(403, "只有 Demo 測試車輛可以重設")
        sessions = rows(conn.execute(
            f"SELECT * FROM rental_sessions WHERE vehicle_id=? AND state IN ({','.join('?' * len(ACTIVE_STATES))})",
            (vehicle_id, *ACTIVE_STATES)))
        case_ids = []
        now = now_iso()
        for s in sessions:
            case_ids += [r[0] for r in conn.execute("SELECT case_id FROM inspection_incidents WHERE rental_id=?", (s["rental_id"],))]
            ri.clear_rental(conn, s["rental_id"])
            conn.execute("DELETE FROM rentals WHERE rental_id=?", (s["rental_id"],))
            _update(conn, s["session_id"], state="ARCHIVED", cancelled_at=now)
        conn.execute("UPDATE demo_vehicles SET status='AVAILABLE', updated_at=? WHERE vehicle_id=?", (now, vehicle_id))
    _reset_case_state(case_ids)
    return {"ok": True, "vehicle_id": vehicle_id, "archived_sessions": [s["session_id"] for s in sessions],
            "cleared_cases": case_ids, "vehicle": get_vehicle(vehicle_id)}


# ---------- 狀態同步與視圖 ----------

def _sync(conn, s: dict) -> dict:
    """PHOTO_INSPECTION 期間依租約分析狀態推導 INSPECTION_COMPLETED / INSPECTION_FAILED 並落庫。"""
    if s["state"] not in ("PHOTO_INSPECTION", "INSPECTION_COMPLETED", "INSPECTION_FAILED"):
        return s
    rental = ri.get_rental(s["rental_id"], conn) or {}
    st = rental.get("status")
    target = None
    if st == "ANALYSIS_COMPLETE":
        target = "INSPECTION_COMPLETED"
    elif st == "ANALYSIS_FAILED":
        target = "INSPECTION_FAILED"
    elif st in ("RETURN_IN_PROGRESS", "RETURN_COMPLETE", "ANALYZING", "PICKUP_COMPLETE"):
        target = "PHOTO_INSPECTION"   # 重拍／補傳中：退回拍照階段（唯一允許的「倒退」，只在檢測未定案時）
    if target and target != s["state"]:
        _update(conn, s["session_id"], state=target, last_error=rental.get("analysis_error") if target == "INSPECTION_FAILED" else None)
        s = _get(conn, s["session_id"])
    return s


def _normalise_plate(value: str | None) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _plate_check(conn, s: dict) -> dict:
    """還車照片的裝置端車牌辨識 vs 租借車牌。MATCH / MANUAL（手動輸入）/ MISMATCH（使用者確認不一致）/ PENDING。"""
    photos = ri._latest_photos(conn, s["rental_id"], "RETURN")
    details, statuses = [], []
    for angle in ri.EXTERIOR_ANGLES:
        p = photos.get(angle)
        if not p:
            continue
        v = json.loads(p["validation_json"] or "{}")
        text = v.get("plateText")
        source = v.get("plateSource") or "ocr"
        if source == "user_confirmed_mismatch" or (text and _normalise_plate(text) != _normalise_plate(s["plate"])):
            st = "MISMATCH"
        elif source == "manual":
            st = "MANUAL"
        elif text:
            st = "MATCH"            # 含 preloaded：資料集照片的 Core ML OCR 結果
        else:
            st = "UNKNOWN"
        statuses.append(st)
        details.append({"angle": angle, "angle_code": ri.ANGLE_CODES[angle], "plate_text": text,
                        "confidence": v.get("plateConfidence"), "source": source, "status": st,
                        "validation_mode": p["validation_mode"]})
    if not statuses:
        overall = "PENDING"
    elif "MISMATCH" in statuses:
        overall = "MISMATCH"
    elif "MANUAL" in statuses:
        overall = "MANUAL"
    elif all(x == "MATCH" for x in statuses):
        overall = "MATCH"
    else:
        overall = "UNKNOWN"
    label = {"MATCH": "照片車牌與租借車輛一致", "MANUAL": "車牌由使用者手動輸入，需人工確認",
             "MISMATCH": "照片車牌與租借車輛不一致，需人工確認", "UNKNOWN": "部分照片未辨識到車牌",
             "PENDING": "尚未收到還車照片"}[overall]
    return {"status": overall, "label": label, "expected_plate": s["plate"], "photos": details,
            "requires_manual_review": overall in ("MANUAL", "MISMATCH", "UNKNOWN")}


def _review_required(conn, s: dict) -> bool:
    if _plate_check(conn, s)["requires_manual_review"]:
        return True
    return bool(conn.execute("SELECT 1 FROM inspection_incidents WHERE rental_id=? LIMIT 1", (s["rental_id"],)).fetchone())


def _seconds_between(a: str | None, b: str | None) -> int | None:
    try:
        return int((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds()) if a and b else None
    except ValueError:
        return None


def _view(conn, s: dict) -> dict:
    s = _sync(conn, s)
    rental = ri.get_rental(s["rental_id"], conn) or {}
    pickup = ri._completeness(conn, s["rental_id"], "PICKUP")
    ret = ri._completeness(conn, s["rental_id"], "RETURN")
    v = conn.execute("SELECT * FROM demo_vehicles WHERE vehicle_id=?", (s["vehicle_id"],)).fetchone()
    v = dict(v) if v else {}
    end_at = s["returned_at"] or s["return_info_confirmed_at"] or s["return_initiated_at"]
    used = _seconds_between(s["started_at"], end_at) if end_at else _seconds_between(s["started_at"], now_iso())
    distance = (s["end_odometer_km"] - s["start_odometer_km"]) if s["end_odometer_km"] is not None else None
    analysis = ("complete" if rental.get("status") == "ANALYSIS_COMPLETE" else
                "failed" if rental.get("status") == "ANALYSIS_FAILED" else
                "analyzing" if rental.get("status") in ("RETURN_COMPLETE", "ANALYZING") else "pending")
    stage_photos = {}
    for itype in ("PICKUP", "RETURN"):
        stage_photos[itype] = [
            {"angle": a, "angle_code": ri.ANGLE_CODES.get(a), "url": ri.photo_url(p.get("storage_path")),
             "validation_mode": p["validation_mode"], "source": p["source"],
             "preloaded": p["validation_mode"] == "preloaded",
             "interior_standin": bool((json.loads(p["validation_json"] or "{}")).get("interior_standin"))}
            for a, p in ri._latest_photos(conn, s["rental_id"], itype).items()]
    return {
        "session_id": s["session_id"], "state": s["state"], "simulated": True,
        "photos": stage_photos,
        "capture_mode": {"PICKUP": _capture_mode(stage_photos["PICKUP"]), "RETURN": _capture_mode(stage_photos["RETURN"])},
        "vehicle": {"vehicle_id": s["vehicle_id"], "plate": s["plate"], "model": s["vehicle_model"],
                    "image_url": v.get("image_url"), "image_note": v.get("image_note"),
                    "location": {"lat": v.get("lat"), "lng": v.get("lng"), "name": v.get("location_name"), "simulated": True},
                    "status": v.get("status"), "ai_source": v.get("ai_source"),
                    "category": v.get("category") or "simulated"},
        "rental_id": s["rental_id"], "rental_status": rental.get("status"),
        "ai_source": v.get("ai_source"),
        "ai_source_label": "示範固定劇本（非真實 AI 判定）" if v.get("ai_source") == "demo_fixture" else "Gemini 模型級聯（真實 pipeline）",
        "started_at": s["started_at"],
        "start_location": {"lat": s["start_lat"], "lng": s["start_lng"], "source": s["start_location_source"]},
        "start_odometer_km": s["start_odometer_km"],
        "return_initiated_at": s["return_initiated_at"], "return_info_confirmed_at": s["return_info_confirmed_at"],
        "return_location": {"lat": s["return_lat"], "lng": s["return_lng"], "source": s["return_location_source"]},
        "end_odometer_km": s["end_odometer_km"], "distance_km": distance,
        "used_seconds": used, "returned_at": s["returned_at"], "cancelled_at": s["cancelled_at"],
        "pickup": pickup, "return": ret, "analysis": analysis,
        "inspection_attempts": s["inspection_attempts"], "last_error": s["last_error"],
        "review_required": bool(s["review_required"]), "updated_at": s["updated_at"],
    }


def _capture_mode(photos: list[dict]) -> str | None:
    """live（即時拍攝）| preloaded（預載 Demo 照片）| mixed | None"""
    if not photos:
        return None
    pre = sum(1 for p in photos if p["preloaded"])
    return "preloaded" if pre == len(photos) else "live" if pre == 0 else "mixed"


def preload_photos(session_id: str, stage: str) -> dict:
    """模式 B：把 Registry 的借車前／還車後照片灌進 Session 租約（demo_vehicle_registry.preload），回傳最新 Session。"""
    import demo_vehicle_registry as registry   # noqa: PLC0415
    if stage not in ("pickup", "return"):
        raise SessionError(422, "stage must be pickup or return")
    with _conn() as conn:
        s = _view(conn, _get(conn, session_id))
    want = "PICKUP_INSPECTION" if stage == "pickup" else "PHOTO_INSPECTION"
    if s["state"] != want:
        raise SessionError(409, f"目前狀態為 {s['state']}，{'取車' if stage == 'pickup' else '還車'}預載需要 {want}")
    try:
        result = registry.preload(s, stage)
    except registry.PreloadError as e:
        raise SessionError(e.status, e.detail) from e
    except ri.IngestError as e:
        raise SessionError(e.status, e.detail) from e
    out = get_session(session_id)
    out["preload"] = result
    return out


def inspection_result(session_id: str) -> dict:
    """App 用的檢測結果：逐角度比對、車內整潔、車牌比對、AI 來源。資料全部來自既有 inspection_detail（不另造一套判定）。"""
    with _conn() as conn:
        s = _sync(conn, _get(conn, session_id))
        plate_check = _plate_check(conn, s)
        view = _view(conn, s)
    detail = ri.inspection_detail(s["rental_id"]) or {}
    comparisons = []
    for c in detail.get("comparisons") or []:
        if c["category"] != "exterior":
            continue
        comparisons.append({"angle": c["angle"], "angle_code": c["angle_code"], "result": c["result"],
                            "result_label": RESULT_LABELS.get(c["result"], c["result"] or "尚未分析"),
                            "summary": c["summary"], "findings": c["findings"], "boxes": c["boxes"],
                            "pickup_photo_url": (c.get("pickup_photo") or {}).get("url"),
                            "return_photo_url": (c.get("return_photo") or {}).get("url"),
                            "case_id": c.get("case_id")})
    interior = detail.get("interior")
    if interior:
        interior = {**interior, "result_label": RESULT_LABELS.get(interior.get("result"), interior.get("result") or "尚未分析")}
    incidents = [{"case_id": i["case_id"], "kind": i["kind"], "angle": i["view_angle"], "label": i.get("label"),
                  "severity": i.get("severity"), "confidence": i.get("confidence"), "ai_level": i.get("ai_level"),
                  "summary": i.get("summary")} for i in detail.get("incidents") or []]
    analysis = detail.get("analysis") or {}
    return {
        "session_id": session_id, "state": view["state"], "analysis": view["analysis"],
        "ai_source": analysis.get("source") or view["ai_source"],
        "ai_source_label": ("示範固定劇本（非真實 AI 判定）" if (analysis.get("source") or view["ai_source"]) == "demo_fixture"
                            else "Gemini 模型級聯（真實 pipeline）"),
        "analysis_error": analysis.get("error"), "versions": detail.get("versions") or {},
        "overall": detail.get("result"),      # PASSED | ISSUES | FAILED | ANALYZING | PENDING
        "overall_label": {"PASSED": "未發現新增車損與髒汙", "ISSUES": f"AI 檢出 {len(incidents)} 項異常，已轉人工複核",
                          "FAILED": "AI 檢測失敗，可重新檢測或重新拍攝", "ANALYZING": "AI 分析中", "PENDING": "等待還車照片"}
                         .get(detail.get("result"), "尚未分析"),
        "comparisons": comparisons, "interior": interior, "incidents": incidents,
        "plate_check": plate_check,
        "review_required": plate_check["requires_manual_review"] or bool(incidents),
        "note": "AI 判定為決策輔助；車損歸責與收費以人工複核為準。",
    }


RESULT_LABELS = {
    "NO_NEW_DAMAGE": "未發現新增車損", "EXISTING_DAMAGE": "僅既有損傷（取車時已存在）", "NEW_DAMAGE": "偵測到新增車損",
    "UNCOMPARABLE": "兩張照片無法有效比對", "NO_BASELINE": "缺少取車基準照", "DUPLICATE_PHOTO": "還車照與取車照相同（待人工複核）",
    "CLEANING_REQUIRED": "車內髒汙，須清潔", "CLEAN": "車內整潔", "UNREADABLE": "車內照無法判讀",
}


def health() -> dict:
    with _conn() as conn:
        vs = rows(conn.execute("SELECT vehicle_id, plate, status FROM demo_vehicles"))
        active = conn.execute(
            f"SELECT COUNT(*) FROM rental_sessions WHERE state IN ({','.join('?' * len(ACTIVE_STATES))})", ACTIVE_STATES).fetchone()[0]
    return {"vehicles": vs, "active_sessions": active}
