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
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Header, HTTPException
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
        drafts = ops_db.get_drafts(conn, task_id)
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
