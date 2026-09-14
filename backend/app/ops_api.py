#!/usr/bin/env python3
"""環節三 整備中心 API（prefix /api/ops）。

管理者介面（frontend-admin → /ops）專用。原則：
  - 不改監理台既有端點與 confirm / 狀態機邏輯：任務狀態變更仍呼叫 server.patch_task，
    通知重發仍呼叫 server._notify_task，規則只有一份。
  - 事件流由 task_events 增量派生（ops_db.derive_events_from_tasks），加上 SLA 逾時掃描。
  - 所有回應附 server_time，前端 SLA 倒數以此校正時鐘。
  - 身分：無登入，前端自選身分經 X-Ops-Reader 標頭送來，只用於已讀與歷程署名。

掛載方式（server.py）：
    import ops_api
    ops_api.bind(sys.modules[__name__]); app.include_router(ops_api.router)
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ops_db

router = APIRouter(prefix="/api/ops", tags=["ops"])
_srv = None   # server 模組（bind() 注入，避免循環 import）


def bind(server_module) -> None:
    global _srv
    _srv = server_module
    # 測試會 monkeypatch server.DB_PATH；跟著它走，確保與監理台同一顆資料庫
    ops_db.db_path = lambda: _srv.DB_PATH
    ops_db.base_init = lambda: _srv.db().close()   # 先確保 tasks / task_events 存在


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _reader(h: str | None) -> str:
    """X-Ops-Reader：前端以 encodeURIComponent 編碼（HTTP 標頭不能直接放中文）。"""
    if not isinstance(h, str):   # 直接呼叫函式（測試）時拿到的是 Header 預設物件
        h = ""
    return unquote(h).strip()[:40] or "anonymous"


# ---------- SLA ----------

def _with_sla(task: dict, sla: dict, now: datetime) -> dict:
    """為任務加上 sla_due_at / sla_remaining_s / overdue。SLA 定義為「待處理 → 開工」期限；
    已開工、已完成、已取消不再計算。"""
    t = dict(task)
    minutes = sla.get(t.get("priority") or "P2", sla["P2"])
    try:
        created = datetime.fromisoformat(t["created_at"])
    except Exception:
        created = now
    due = created + timedelta(minutes=minutes)
    t["sla_minutes"] = minutes
    t["sla_due_at"] = _iso(due)
    if t.get("status") == "pending":
        t["sla_remaining_s"] = int((due - now).total_seconds())
        t["overdue"] = t["sla_remaining_s"] < 0
    else:
        t["sla_remaining_s"] = None
        t["overdue"] = False
    return t


def _scan_overdue(conn, sla: dict, now: datetime) -> int:
    """對逾時仍待處理的任務各產生一則 sla_overdue 事件（每任務一次）。
    在每次讀取事件／任務時順手執行，成本極低，不需背景 thread。"""
    n = 0
    for r in conn.execute("SELECT * FROM tasks WHERE status='pending'"):
        t = _with_sla(dict(r), sla, now)
        if t["overdue"] and not ops_db.has_overdue_event(conn, t["id"]):
            ops_db.add_event(conn, "sla_overdue", t,
                             f"{t['priority'] or 'P2'} 任務逾時未開工（SLA {t['sla_minutes']} 分鐘）",
                             at=_iso(now))
            n += 1
    return n


def _refresh_events(conn) -> None:
    ops_db.derive_events_from_tasks(conn)
    _scan_overdue(conn, ops_db.sla_minutes(conn), _now())


# ---------- 案件快照 → 前端可用的照片 URL ----------

def _photo_url(kind: str, p: str | None) -> str | None:
    if not p:
        return None
    if p.startswith("http") or p.startswith("/photos/") or p.startswith("data:"):
        return p
    return f"/photos/{kind}/{quote(Path(p).name)}"


def _case_view(case_id: str) -> dict:
    """任務詳情用的案件資料：照片 URL、AI 標註框、判定摘要。快照失敗回空殼，不擋任務。"""
    try:
        snap = _srv._case_snapshot(case_id)
    except Exception:
        snap = {"mode": None, "source": None, "photos": {}, "assessment": None, "boxes": [],
                "ai_level": None, "ai_conf": None}
    photos = snap.get("photos") or {}
    view = {"case_id": case_id, "mode": snap.get("mode"), "source": snap.get("source"),
            "ai_level": snap.get("ai_level"), "ai_conf": snap.get("ai_conf"),
            "assessment": snap.get("assessment"), "boxes": snap.get("boxes") or [],
            "photos": {}}
    if photos.get("stored_in") == "live_cases":
        with _srv.db() as conn:
            row = conn.execute("SELECT data FROM live_cases WHERE case_id=?", (case_id,)).fetchone()
        if row:
            case = json.loads(row[0]).get("case") or {}
            b64 = lambda v: f"data:image/jpeg;base64,{v}" if v else None  # noqa: E731
            if case.get("f2"):
                view["photos"] = {"photo": b64(case.get("photo"))}
            else:
                view["photos"] = {"pickup": b64(case.get("pickup")), "return": b64(case.get("ret"))}
    elif snap.get("mode") == "interior":
        view["photos"] = {"photo": _photo_url("interior", photos.get("photo"))}
    else:
        view["photos"] = {"pickup": _photo_url("pair", photos.get("pickup")),
                          "return": _photo_url("pair", photos.get("return"))}
    with _srv.db() as conn:
        d = conn.execute("SELECT decision, decided_at FROM decisions WHERE case_id=?", (case_id,)).fetchone()
    view["decision"] = {"decision": d[0], "decided_at": d[1]} if d else None
    return view


# ---------- 端點 ----------

@router.get("/health")
def ops_health():
    return {
        "server_time": _iso(_now()),
        "demo_mode": _srv._demo_mode(),
        "demo_cases": {"damage": _srv.DEMO_CASE_DAMAGE, "cleaning": _srv.DEMO_CASE_CLEANING},
        "channels": _channels(),
    }


def _channels() -> list[dict]:
    """各通知管道狀態：只回布林，絕不回傳 URL / token。"""
    return [
        {"id": "webhook", "label": "Webhook", "configured": bool(_srv._webhook_url()),
         "available": True, "note": "人工確認建立任務時 HTTP POST JSON；失敗可重發"},
        {"id": "line", "label": "LINE 推播", "configured": False, "available": False,
         "note": "未接入：尚無程式碼"},
        {"id": "sms", "label": "簡訊", "configured": False, "available": False,
         "note": "未接入：尚無程式碼"},
    ]


@router.get("/channels")
def channels():
    return {"channels": _channels(), "server_time": _iso(_now())}


@router.get("/summary")
def summary(x_ops_reader: str | None = Header(default=None)):
    now = _now()
    with ops_db.db() as conn:
        _refresh_events(conn)
        sla = ops_db.sla_minutes(conn)
        tasks = [_with_sla(dict(r), sla, now) for r in conn.execute("SELECT * FROM tasks")]
        today = now.date().isoformat()
        return {
            "server_time": _iso(now),
            "pending": sum(t["status"] == "pending" for t in tasks),
            "in_progress": sum(t["status"] == "in_progress" for t in tasks),
            "completed_today": sum(t["status"] == "completed" and (t.get("resolved_at") or "").startswith(today)
                                   for t in tasks),
            "p1_not_started": sum(t["status"] == "pending" and t.get("priority") == "P1" for t in tasks),
            "overdue": sum(t["overdue"] for t in tasks),
            "notify_failed": sum(t.get("notification_status") == "failed" and t["status"] in ("pending", "in_progress")
                                 for t in tasks),
            "unread": ops_db.unread_count(conn, _reader(x_ops_reader)),
        }


@router.get("/tasks")
def list_tasks(status: str | None = None, task_type: str | None = None,
               priority: str | None = None, assignee: str | None = None,
               overdue: bool | None = None):
    now = _now()
    with ops_db.db() as conn:
        _refresh_events(conn)
        sla = ops_db.sla_minutes(conn)
        where, params = [], []
        for col, v in (("status", status), ("task_type", task_type),
                       ("priority", priority), ("assignee", assignee)):
            if v:
                where.append(f"{col}=?")
                params.append(v)
        q = "SELECT id FROM tasks" + (" WHERE " + " AND ".join(where) if where else "") + \
            " ORDER BY created_at DESC"
        ids = [r[0] for r in conn.execute(q, params)]
        out = [_with_sla(_srv._task_row(conn, i), sla, now) for i in ids]
    if overdue:
        out = [t for t in out if t["overdue"]]
    demo_ids = set(_srv.DEMO_CASE_IDS) if _srv._demo_mode() else set()
    for t in out:
        t["is_demo"] = t["case_id"] in demo_ids
    return {"tasks": out, "server_time": _iso(now), "sla": sla}


@router.get("/tasks/{task_id}")
def get_task(task_id: int):
    now = _now()
    with ops_db.db() as conn:
        _refresh_events(conn)
        t = _srv._task_row(conn, task_id)
        if not t:
            raise HTTPException(404, f"找不到任務 #{task_id}")
        t = _with_sla(t, ops_db.sla_minutes(conn), now)
        drafts = ops_db.get_drafts(conn, t["case_id"])
        log = ops_db.list_notification_log(conn, task_id)
    t["is_demo"] = _srv._demo_mode() and t["case_id"] in _srv.DEMO_CASE_IDS
    return {"task": t, "case": _case_view(t["case_id"]), "drafts": drafts,
            "notification_log": log, "server_time": _iso(now)}


class OpsTaskUpdate(BaseModel):
    status: str | None = None
    assignee: str | None = None
    note: str | None = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, upd: OpsTaskUpdate, x_ops_reader: str | None = Header(default=None)):
    """狀態 / 指派走監理台的 patch_task（同一套狀態機）；備註另寫 task_events(note)。"""
    who = _reader(x_ops_reader)
    if upd.status is not None or upd.assignee is not None:
        _srv.patch_task(task_id, _srv.TaskUpdate(status=upd.status, assignee=upd.assignee))
    note = (upd.note or "").strip()
    if note:
        with _srv.db() as conn:
            if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise HTTPException(404, f"找不到任務 #{task_id}")
            conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                         (task_id, _iso(_now()), "note", f"{who}：{note[:500]}"))
    return get_task(task_id)


@router.post("/tasks/{task_id}/notify")
def retry_notify(task_id: int):
    with _srv.db() as conn:
        t = _srv._task_row(conn, task_id)
    if not t:
        raise HTTPException(404, f"找不到任務 #{task_id}")
    _srv._notify_task(t)
    return get_task(task_id)


@router.get("/events")
def list_events(since: int = 0, priority: str | None = None, unread: bool = False,
                types: str | None = None, limit: int = 100,
                x_ops_reader: str | None = Header(default=None)):
    reader = _reader(x_ops_reader)
    with ops_db.db() as conn:
        _refresh_events(conn)
        evs = ops_db.list_events(conn, reader, since_id=since, priority=priority,
                                 unread_only=unread, types=types.split(",") if types else None,
                                 limit=max(1, min(limit, 500)))
        return {"events": evs, "unread": ops_db.unread_count(conn, reader),
                "server_time": _iso(_now())}


class ReadBody(BaseModel):
    ids: list[int] | None = None   # None = 全部標已讀


@router.post("/events/read")
def read_events(body: ReadBody, x_ops_reader: str | None = Header(default=None)):
    reader = _reader(x_ops_reader)
    with ops_db.db() as conn:
        ops_db.mark_read(conn, reader, body.ids)
        return {"ok": True, "unread": ops_db.unread_count(conn, reader)}


@router.get("/people")
def people(all: bool = False):
    with ops_db.db() as conn:
        return {"people": ops_db.list_people(conn, include_inactive=all)}


class PersonIn(BaseModel):
    group_name: str
    name: str


class PersonPatch(BaseModel):
    group_name: str | None = None
    name: str | None = None
    active: bool | None = None


@router.post("/people")
def add_person(p: PersonIn):
    name, group = p.name.strip(), p.group_name.strip()
    if not name or not group:
        raise HTTPException(400, "group_name 與 name 不可為空")
    with ops_db.db() as conn:
        if conn.execute("SELECT 1 FROM ops_people WHERE name=?", (name,)).fetchone():
            raise HTTPException(409, f"「{name}」已存在")
        return ops_db.add_person(conn, group, name)


@router.patch("/people/{pid}")
def patch_person(pid: int, p: PersonPatch):
    with ops_db.db() as conn:
        r = ops_db.update_person(conn, pid, group_name=p.group_name, name=p.name,
                                 active=None if p.active is None else int(p.active))
    if not r:
        raise HTTPException(404, "找不到人員")
    return r


@router.get("/settings")
def get_settings():
    with ops_db.db() as conn:
        return {"settings": ops_db.get_settings(conn), "sla": ops_db.sla_minutes(conn)}


@router.put("/settings")
def put_settings(values: dict):
    clean = {}
    for k, v in values.items():
        if k.startswith("sla_minutes_"):
            try:
                iv = int(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k} 必須是整數分鐘")
            if not 1 <= iv <= 60 * 24 * 7:
                raise HTTPException(400, f"{k} 需介於 1 與 10080 分鐘")
            clean[k] = iv
        elif isinstance(k, str) and len(k) <= 64:
            clean[k] = str(v)[:500]
    with ops_db.db() as conn:
        ops_db.set_settings(conn, clean)
        return {"settings": ops_db.get_settings(conn), "sla": ops_db.sla_minutes(conn)}


# ---------- 三對象文案（notify.py Stage 7）：以 case_id 快取，可於 Demo 前預生成 ----------

def _notify_case_input(case_id: str) -> dict:
    """把案件快照整理成 notify.generate() 的輸入。只放結構化資料中確實存在的內容；
    估價走 disposition（純程式）——文案階段的金額只能來自這裡的區間。"""
    snap = _srv._case_snapshot(case_id)
    a = snap.get("assessment") or {}
    if snap.get("mode") is None:
        raise HTTPException(404, f"找不到案件 {case_id} 的判定結果")
    case = {"case_id": case_id, "vehicle": _srv._case_car(case_id), "level": snap.get("ai_level")}
    if snap.get("mode") == "interior":
        case["new_damage_found"] = False
        case["damages"] = []
        case["interior"] = {"level": a.get("level"), "score": a.get("score"),
                            "items": a.get("issues") or [], "reasoning": a.get("reasoning")}
        return case
    case["new_damage_found"] = bool(a.get("new_damage_found"))
    dmgs = []
    for d in a.get("damages") or []:
        row = {"location": d.get("location"), "damage_type_zh": d.get("type"),
               "severity": d.get("severity"), "raw_confidence": d.get("confidence"),
               "observation": d.get("reasoning")}
        try:
            import disposition  # noqa: PLC0415
            from diff_new_damage import panel_of  # noqa: PLC0415
            p = disposition.assess(d, panel=panel_of(d, case_id.rsplit("-", 1)[-1]),
                                   weighted_confidence=d.get("confidence"))
            row.update({k: v for k, v in p.items()
                        if k in ("repair_action", "band", "estimate_twd", "disposition", "panel")})
        except Exception:
            pass
        dmgs.append(row)
    case["damages"] = dmgs
    return case


@router.get("/cases/{case_id}/drafts")
def get_case_drafts(case_id: str):
    with ops_db.db() as conn:
        return {"case_id": case_id, "drafts": ops_db.get_drafts(conn, case_id)}


@router.post("/cases/{case_id}/drafts")
async def generate_case_drafts(case_id: str, force: bool = False):
    """生成三對象文案（一次 Gemini 呼叫）。已有快取且未 force 則直接回傳——
    Demo 前可預生成，現場「重新生成」即 force=1。"""
    with ops_db.db() as conn:
        existing = ops_db.get_drafts(conn, case_id)
    if existing and not force:
        return {"case_id": case_id, "drafts": existing, "cached": True}
    _srv._require_key()
    import notify  # noqa: PLC0415
    case = _notify_case_input(case_id)

    def run():
        with _srv._rejudge_lock:     # 免費層 RPM 低，與重判／現場實測共用同一把鎖
            return notify.generate(case, client=_srv._client())
    try:
        generated = await run_in_threadpool(run)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"文案生成失敗：{str(e)[:200]}")
    with ops_db.db() as conn:
        drafts = ops_db.save_generated_drafts(conn, case_id, generated, notify.MODEL)
    return {"case_id": case_id, "drafts": drafts, "cached": False}


class DraftIn(BaseModel):
    content: dict


@router.put("/cases/{case_id}/drafts/{audience}")
def put_case_draft(case_id: str, audience: str, body: DraftIn):
    if audience not in ops_db.AUDIENCES:
        raise HTTPException(400, "audience 必須是 user / cs / worker")
    with ops_db.db() as conn:
        return ops_db.update_draft(conn, case_id, audience, body.content)


# ---------- 發送（管道：webhook 實發；line / sms 未接入，記錄為 unsupported） ----------

CHANNELS = {"webhook", "line", "sms"}


class SendIn(BaseModel):
    audience: str
    channel: str = "webhook"


def _send_webhook(payload: dict) -> bool:
    return _srv.send_notification(payload)


@router.post("/tasks/{task_id}/send")
def send_draft(task_id: int, body: SendIn, x_ops_reader: str | None = Header(default=None)):
    if body.audience not in ops_db.AUDIENCES:
        raise HTTPException(400, "audience 必須是 user / cs / worker")
    if body.channel not in CHANNELS:
        raise HTTPException(400, "channel 必須是 webhook / line / sms")
    who = _reader(x_ops_reader)
    with ops_db.db() as conn:
        t = _srv._task_row(conn, task_id)
        if not t:
            raise HTTPException(404, f"找不到任務 #{task_id}")
        draft = ops_db.get_drafts(conn, t["case_id"]).get(body.audience)
    if not draft:
        raise HTTPException(409, "尚未生成此對象的文案")
    aud_txt = {"user": "用戶通知", "cs": "客服摘要", "worker": "派工單"}[body.audience]
    if body.channel != "webhook":
        status, detail = "unsupported", f"{body.channel} 管道尚未接入，未發送"
    elif not _srv._webhook_url():
        status, detail = "skipped", "通知管道未設定（NOTIFICATION_WEBHOOK_URL），未發送"
    else:
        payload = {"event": "notification", "audience": body.audience, "channel": body.channel,
                   "task_id": task_id, "case_id": t["case_id"], "car": t.get("car"),
                   "priority": t.get("priority"), "task_type": t["task_type"],
                   "content": draft["content"], "sent_by": who,
                   "sent_at": _iso(_now())}
        try:
            ok = _send_webhook(payload)
        except Exception:
            ok = False
        status = "sent" if ok else "failed"
        detail = f"{aud_txt} 已送出（webhook）" if ok else f"{aud_txt} 發送失敗，可重試"
    with ops_db.db() as conn:
        entry = ops_db.add_notification_log(conn, task_id, body.audience, body.channel, status, detail)
        conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                     (task_id, entry["at"], "notify", f"{who}：{detail}"))
    return {"ok": status == "sent", "entry": entry, **get_task(task_id)}


@router.post("/settings/test")
def test_webhook():
    """對 webhook 發一則測試訊息，回傳結果；不寫任何任務紀錄。"""
    if not _srv._webhook_url():
        return {"ok": False, "status": "skipped", "detail": "通知管道未設定（NOTIFICATION_WEBHOOK_URL）"}
    try:
        ok = _send_webhook({"event": "test", "sent_at": _iso(_now()), "message": "iRent 整備中心測試通知"})
    except Exception:
        ok = False
    return {"ok": ok, "status": "sent" if ok else "failed",
            "detail": "測試通知已送出" if ok else "測試通知失敗（timeout / 連線被拒 / 非 2xx）"}


# ---------- SSE：新事件即時推送（server 端每 2 秒查一次資料庫；15 秒心跳） ----------

SSE_POLL_S = 2.0
SSE_HEARTBEAT_S = 15.0


def _events_after(last_id: int, reader: str) -> list[dict]:
    with ops_db.db() as conn:
        _refresh_events(conn)
        evs = ops_db.list_events(conn, reader, since_id=last_id, limit=50)
    return list(reversed(evs))   # 由舊到新


@router.get("/events/stream")
async def events_stream(since: int = 0, reader: str | None = None,
                        x_ops_reader: str | None = Header(default=None)):
    reader = _reader(reader or x_ops_reader)   # EventSource 不能帶自訂標頭，改用 query

    async def gen():
        last = since
        if last == 0:
            with ops_db.db() as conn:
                last = ops_db.max_event_id(conn)
        yield f"event: hello\ndata: {json.dumps({'last_id': last, 'server_time': _iso(_now())})}\n\n"
        idle = 0.0
        while True:
            await asyncio.sleep(SSE_POLL_S)
            try:
                evs = await run_in_threadpool(_events_after, last, reader)
            except Exception:
                evs = []
            if evs:
                for e in evs:
                    last = max(last, e["id"])
                    yield f"id: {e['id']}\nevent: ops\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                idle = 0.0
            else:
                idle += SSE_POLL_S
                if idle >= SSE_HEARTBEAT_S:
                    yield f": ping {_iso(_now())}\n\n"
                    idle = 0.0

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 車輛派單狀態（模擬：未與派單系統串接） ----------
# 規則：有未完成任務（pending / in_progress）或手動鎖定 → 整備中，不可派；否則可派。
# 「待確認」= AI 判定 P1/P2 但尚無人工裁決的資料集案件，僅提示，不鎖車。

def _dataset_cars() -> dict[str, dict]:
    """資料集內車輛：借還配對 + 車內照。回 {car: {"cases": n, "ai_flagged": n, "unreviewed": n}}。"""
    cars: dict[str, dict] = {}
    try:
        with _srv.db() as conn:
            decided = {r[0] for r in conn.execute("SELECT case_id FROM decisions")}
        for p in _srv._pairs:
            car = p["car"]
            cid = f'{car}-{p["angle"]}'
            a = _srv._final_assessments().get(cid)
            lvl = _srv._triage_level(a) if a else None
            c = cars.setdefault(car, {"cases": 0, "ai_flagged": 0, "unreviewed": 0, "claims": 0})
            c["cases"] += 1
            c["claims"] += int(p.get("label") == "positive")
            if lvl in ("P1", "P2"):
                c["ai_flagged"] += 1
                c["unreviewed"] += int(cid not in decided)
    except Exception:
        pass
    return cars


@router.get("/fleet")
def fleet(q: str | None = None, status: str | None = None):
    now = _now()
    with ops_db.db() as conn:
        sla = ops_db.sla_minutes(conn)
        tasks = [_with_sla(dict(r), sla, now) for r in conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")]
        locks = ops_db.get_locks(conn)
    ds = _dataset_cars()
    cars = set(ds) | {t["car"] for t in tasks if t.get("car")} | set(locks)
    rows = []
    for car in cars:
        mine = [t for t in tasks if t.get("car") == car]
        open_tasks = [t for t in mine if t["status"] in ("pending", "in_progress")]
        lock = locks.get(car)
        manual = bool(lock and lock["locked"])
        info = ds.get(car, {})
        if open_tasks or manual:
            st = "locked"
        elif info.get("unreviewed"):
            st = "review"
        else:
            st = "available"
        done = [t for t in mine if t["status"] == "completed" and t.get("resolved_at")]
        rows.append({
            "car": car, "status": st, "manual_lock": manual,
            "lock_reason": (lock or {}).get("reason") if manual else None,
            "lock_by": (lock or {}).get("by") if manual else None,
            "lock_at": (lock or {}).get("at") if manual else None,
            "open_tasks": [{"id": t["id"], "task_type": t["task_type"], "status": t["status"],
                            "priority": t["priority"], "title": t["title"], "overdue": t["overdue"]}
                           for t in open_tasks],
            "completed_tasks": len(done),
            "last_completed_at": max((t["resolved_at"] for t in done), default=None),
            "dataset_cases": info.get("cases", 0), "claims": info.get("claims", 0),
            "unreviewed_flags": info.get("unreviewed", 0),
        })
    if q:
        rows = [r for r in rows if q.upper() in r["car"].upper()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    order = {"locked": 0, "review": 1, "available": 2}
    rows.sort(key=lambda r: (order[r["status"]], -len(r["open_tasks"]), r["car"]))
    return {"fleet": rows, "server_time": _iso(now),
            "counts": {k: sum(r["status"] == k for r in rows) for k in order},
            "note": "派單鎖定為模擬狀態：未與派單系統串接，僅反映整備任務與手動鎖定。"}


class LockIn(BaseModel):
    locked: bool
    reason: str | None = None


@router.patch("/fleet/{car}")
def patch_fleet(car: str, body: LockIn, x_ops_reader: str | None = Header(default=None)):
    who = _reader(x_ops_reader)
    car = car.strip().upper()
    if not car:
        raise HTTPException(400, "car 不可為空")
    with ops_db.db() as conn:
        lock = ops_db.set_lock(conn, car, body.locked, (body.reason or "").strip()[:200] or None, who)
        ops_db.add_event(conn, "fleet_lock" if body.locked else "fleet_unlock",
                         {"car": car, "title": "手動鎖定派單" if body.locked else "解除派單鎖定", "priority": "P3"},
                         f"{who}：{'鎖定' if body.locked else '解除鎖定'} {car}" + (f"（{lock['reason']}）" if lock.get("reason") else ""))
    return {"lock": lock, **fleet(q=car)}


# ---------- 營運洞察：離線 log 彙整（ops_insights.json）+ 即時整備數據 ----------

INSIGHTS_PATH = Path(__file__).resolve().parent / "ops_insights.json"


def _minutes(a: str | None, b: str | None) -> float | None:
    try:
        return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60
    except Exception:
        return None


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    m = len(xs) // 2
    return round(xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2, 1)


@router.get("/insights")
def insights():
    now = _now()
    static = json.loads(INSIGHTS_PATH.read_text()) if INSIGHTS_PATH.exists() else None
    with ops_db.db() as conn:
        tasks = [_srv._task_row(conn, r[0]) for r in conn.execute("SELECT id FROM tasks")]
    # 即時整備數據
    to_start, to_done = [], []
    by_type = {"repair": {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0},
               "cleaning": {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0}}
    for t in tasks:
        by_type.setdefault(t["task_type"], {"pending": 0, "in_progress": 0, "completed": 0, "cancelled": 0})[t["status"]] += 1
        started = next((e["at"] for e in t["events"] if e["event"] == "status" and "in_progress" in (e["detail"] or "")), None)
        if started:
            to_start.append(_minutes(t["created_at"], started))
        if t.get("resolved_at"):
            to_done.append(_minutes(t["created_at"], t["resolved_at"]))
    # 車輛事件排行：人工確認任務（即時）＋ 資料集索賠正樣本
    ds = _dataset_cars()
    per_car: dict[str, dict] = {}
    for t in tasks:
        if t["status"] == "cancelled" or not t.get("car"):
            continue
        c = per_car.setdefault(t["car"], {"car": t["car"], "repair": 0, "cleaning": 0, "claims": 0})
        c[t["task_type"]] = c.get(t["task_type"], 0) + 1
    for car, info in ds.items():
        if info.get("claims"):
            per_car.setdefault(car, {"car": car, "repair": 0, "cleaning": 0, "claims": 0})["claims"] = info["claims"]
    ranking = sorted(per_car.values(), key=lambda c: -(c["repair"] + c["cleaning"] + c["claims"]))[:10]
    # 車內整潔分布（資料集離線分類）。結果檔無 photo_ok 欄位；模型在 reasoning 註明「無法」
    # 判讀者（多為車外照誤傳）排除，避免把不可判讀照片算成「普通」。
    interior = {"乾淨": 0, "普通": 0, "髒汙": 0, "n": 0, "excluded_unreadable": 0}
    try:
        for r in json.loads(_srv.INTERIOR_RESULTS.read_text())["results"]:
            a = r.get("assessment") or {}
            lvl = a.get("level")
            if "無法" in (a.get("reasoning") or ""):
                interior["excluded_unreadable"] += 1
                continue
            if lvl in interior:
                interior[lvl] += 1
                interior["n"] += 1
    except Exception:
        pass
    return {
        "server_time": _iso(now),
        "uploads": static,
        "tasks": {"total": len(tasks), "by_type": by_type,
                  "median_minutes_to_start": _median(to_start), "median_minutes_to_complete": _median(to_done),
                  "n_started": len(to_start), "n_completed": len(to_done)},
        "car_ranking": ranking,
        "interior": interior,
    }
