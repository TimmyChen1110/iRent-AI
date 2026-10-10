#!/usr/bin/env python3
"""環節三 整備中心 API（prefix /api/ops）。

管理者介面（frontend-admin → /ops）專用。原則：
  - 不改監理台既有端點與 confirm / 狀態機邏輯：任務狀態變更仍呼叫 server.patch_task，
    通知重發仍呼叫 server._notify_task，規則只有一份。
  - 事件流由 task_events 增量派生（ops_db.derive_events_from_tasks），加上 SLA 逾時掃描。
  - 所有回應附 server_time，前端 SLA 倒數以此校正時鐘。
  - 身分：Phase 3 起由 HttpOnly session 驗證；X-Ops-Reader 只保留供直接函式測試相容。

掛載方式（server.py）：
    import ops_api
    ops_api.bind(sys.modules[__name__]); app.include_router(ops_api.router)
"""
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

import re
import uuid

from fastapi import APIRouter, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

import ops_auth
import ops_db
import rental_inspections
import rental_sessions
import paths
import task_service

router = APIRouter(prefix="/api/ops", tags=["ops"])
_srv = None   # server 模組（bind() 注入，避免循環 import）


def bind(server_module) -> None:
    global _srv
    _srv = server_module
    # 測試會 monkeypatch server.DB_PATH；跟著它走，確保與監理台同一顆資料庫
    ops_db.db_path = lambda: _srv.DB_PATH
    ops_db.base_init = lambda: _srv.db().close()   # 先確保 tasks / task_events 存在
    _srv.TASK_COMPLETE_GUARD = _complete_guard     # 監理台與整備中心共用同一條完工規則
    rental_sessions.OPS_HOLD = car_hold             # App 可租車輛：整備中／人工鎖定 → 暫停出租（與車隊清單同一條規則）


def car_hold(car: str) -> str | None:
    """這台車目前是否因整備暫停出租：人工鎖定或有未完成（pending / in_progress）的整備任務。回原因，None＝無。
    與 /fleet 的 locked 判斷同一條規則；車牌不分連字號（RCG2235 = RCG-2235）。"""
    key = _plate_key(car)
    with ops_db.db() as conn:
        lock = next((l for c, l in ops_db.get_locks(conn).items() if _plate_key(c) == key and l["locked"]), None)
        n_open = sum(1 for (c,) in conn.execute("SELECT car FROM tasks WHERE status IN ('pending','in_progress')")
                     if _plate_key(c) == key)
    if lock:
        return f"人工鎖定派單：{lock['reason']}" if lock.get("reason") else "人工鎖定派單"
    if n_open:
        return f"{n_open} 項整備任務未完成"
    return None


def _complete_guard(conn, task_id: int) -> str | None:
    """完工前檢查：依設定要求完工照（清潔預設必附）。conn 為監理台的連線（同一顆 DB）。"""
    row = conn.execute("SELECT task_type FROM tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        return None
    with ops_db.db() as oconn:
        s = ops_db.get_settings(oconn)
        n = ops_db.photo_count(oconn, task_id)
    requirement = task_service.completion_requirements(row[0], s, n)
    if not requirement["satisfied"]:
        return "完工前需至少一張完工照（可於站點手機版上傳；規則可在通知設定調整）"
    return None


def _now() -> datetime:
    return datetime.now()


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _reader(h: str | None) -> str:
    """可信 actor 優先來自 session；header 僅供舊單元測試直接呼叫函式。"""
    actor = ops_auth.current_actor()
    if actor:
        return actor.name
    if not isinstance(h, str):   # 直接呼叫函式（測試）時拿到的是 Header 預設物件
        h = ""
    return unquote(h).strip()[:40] or "anonymous"


def _station_owns(task: dict, actor: ops_auth.Actor) -> bool:
    """Station ownership 只比對 stable People ID，不再以 display name 當 identity。"""
    return actor.person_id is not None and task.get("assignee_id") == actor.person_id


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
        if t["overdue"]:
            t["sla_status"] = "overdue"
        elif t["sla_remaining_s"] <= minutes * 60 * 0.2:
            t["sla_status"] = "approaching"
        else:
            t["sla_status"] = "normal"
    else:
        t["sla_remaining_s"] = None
        t["overdue"] = False
        t["sla_status"] = "inactive"
    return t


def _with_rules(conn, task: dict, settings: dict | None = None) -> dict:
    """把後端業務能力附在 task response；前端不再自行維護狀態機或完工規則。"""
    t = dict(task)
    t["assignee_name"] = t.get("assignee")
    if t.get("assignee_id") is not None:
        person = conn.execute("SELECT name FROM ops_people WHERE id=?", (t["assignee_id"],)).fetchone()
        if person:
            t["assignee_name"] = person[0]
    settings = settings or ops_db.get_settings(conn)
    caps = task_service.capabilities(t, settings, ops_db.photo_count(conn, t["id"]))
    actor = ops_auth.current_actor()
    if actor and actor.role == "station":
        if t.get("assignee_id") is None and not t.get("assignee"):
            permitted = {"claim"}
        elif _station_owns(t, actor):
            permitted = {"start", "complete", "upload_photo"}
        else:
            permitted = set()
        caps["allowed_actions"] = [a for a in caps["allowed_actions"] if a in permitted]
        caps["action_targets"] = {a: target for a, target in caps["action_targets"].items()
                                  if a in permitted}
    t.update(caps)
    return t


def _scan_overdue(conn, sla: dict, now: datetime) -> list[dict]:
    """對逾時仍待處理的任務各產生一則 sla_overdue 事件（每任務一次）。回傳新逾時的任務，
    由呼叫端在 transaction 之外做升級推播。"""
    fresh = []
    for r in conn.execute("SELECT * FROM tasks WHERE status='pending'"):
        t = _with_sla(dict(r), sla, now)
        if t["overdue"] and not ops_db.has_overdue_event(conn, t["id"]):
            ops_db.add_event(conn, "sla_overdue", t,
                             f"{t['priority'] or 'P2'} 任務逾時未開工（SLA {t['sla_minutes']} 分鐘）",
                             at=_iso(now))
            fresh.append(t)
    return fresh


def _escalate(tasks: list[dict]) -> None:
    """逾時升級：對 webhook 再發一次（kind=escalation），結果記 notification_log 與歷程。
    HTTP 在 DB transaction 之外；失敗只記錄，不影響掃描。"""
    if not tasks:
        return
    with ops_db.db() as conn:
        enabled = ops_db.get_settings(conn).get("escalate_on_overdue", "1") == "1"
    if not enabled:
        return
    for t in tasks:
        if not _srv._webhook_url():
            status, detail = "skipped", "逾時升級：通知管道未設定，未發送"
        else:
            payload = {**_srv.build_notification_payload(t), "event": "sla_overdue", "kind": "escalation",
                       "sla_minutes": t["sla_minutes"], "sla_due_at": t["sla_due_at"]}
            try:
                ok = _srv.send_notification(payload)
            except Exception:
                ok = False
            status = "sent" if ok else "failed"
            detail = "逾時升級推播已送出（webhook）" if ok else "逾時升級推播失敗"
        with ops_db.db() as conn:
            entry = ops_db.add_notification_log(conn, t["id"], "escalation", "webhook", status, detail,
                                                actor=ops_auth.SYSTEM_ACTOR)
            _srv._add_task_event(conn, t["id"], entry["at"], "notify", detail,
                                 actor=ops_auth.SYSTEM_ACTOR)


def _auto_assign(conn) -> int:
    """依設定把尚未指派、且從未被人指派過的待處理任務自動指派（每任務只做一次）。"""
    s = ops_db.get_settings(conn)
    n = 0
    for r in conn.execute("SELECT id, task_type FROM tasks WHERE status='pending'"
                          " AND assignee_id IS NULL AND (assignee IS NULL OR assignee='')"):
        raw_id = (s.get(f"default_assignee_{r[1]}_id") or "").strip()
        person = conn.execute("SELECT id, name FROM ops_people WHERE id=? AND active=1",
                              (raw_id,)).fetchone() if raw_id.isdigit() else None
        # Legacy setting compatibility: resolve the old name only when it is unique.
        if not person:
            legacy = (s.get(f"default_assignee_{r[1]}") or "").strip()
            matches = conn.execute(
                "SELECT id, name FROM ops_people WHERE name=? AND active=1", (legacy,)).fetchall()
            person = matches[0] if len(matches) == 1 else None
        if not person or ops_db.has_assignee_event(conn, r[0]):
            continue
        person_id, who = person[0], person[1]
        now = ops_db.now_iso()
        conn.execute("UPDATE tasks SET assignee_id=?, assignee=?, updated_at=? WHERE id=?",
                     (person_id, who, now, r[0]))
        _srv._add_task_event(conn, r[0], now, "assignee", f"依類型規則自動指派給 {who}",
                             actor=ops_auth.SYSTEM_ACTOR)
        n += 1
    return n


_PENDING_ESCALATION: list[dict] = []


def _refresh_events(conn) -> None:
    """每次讀取時順手做：孤兒清理（Demo 重置後）、自動指派、派生事件、逾時掃描。"""
    purged = ops_db.purge_orphans(conn)
    for name in purged["photo_files"]:
        for tid in purged["task_ids"]:
            f = PHOTO_ROOT / str(tid) / name
            if f.exists():
                f.unlink()
    _auto_assign(conn)
    ops_db.derive_events_from_tasks(conn)
    _PENDING_ESCALATION.extend(_scan_overdue(conn, ops_db.sla_minutes(conn), _now()))


def _flush_escalations() -> None:
    """在 DB transaction 之外發升級推播（呼叫端於 with ops_db.db() 結束後呼叫）。"""
    if _PENDING_ESCALATION:
        batch, _PENDING_ESCALATION[:] = list(_PENDING_ESCALATION), []
        _escalate(batch)


# ---------- 案件快照 → 前端可用的照片 URL ----------

def _photo_url(kind: str, p: str | None) -> str | None:
    if not p:
        return None
    if p.startswith("http") or p.startswith("/photos/") or p.startswith("data:"):
        return p
    if rental_inspections.upload_root() in Path(p).parents:   # iOS App 上傳的照片
        return rental_inspections.photo_url(p)
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
        "gemini_configured": _srv._gemini_configured(),
        "demo_cases": {"damage": _srv.DEMO_CASE_DAMAGE, "cleaning": _srv.DEMO_CASE_CLEANING},
        "demo_rental": _srv._demo_rental_info() if _srv._demo_mode() else None,
        "demo_credentials": ops_auth.demo_login_hints(),
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
        out = {
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
    _flush_escalations()
    return out


@router.get("/tasks")
def list_tasks(status: str | None = None, task_type: str | None = None,
               priority: str | None = None, assignee: str | None = None,
               assignee_id: int | None = None,
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
        if assignee_id is not None:
            where.append("assignee_id=?")
            params.append(assignee_id)
        q = "SELECT id FROM tasks" + (" WHERE " + " AND ".join(where) if where else "") + \
            " ORDER BY created_at DESC"
        ids = [r[0] for r in conn.execute(q, params)]
        settings = ops_db.get_settings(conn)
        out = [_with_rules(conn, _with_sla(_srv._task_row(conn, i), sla, now), settings)
               for i in ids]
    _flush_escalations()
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
        actor = ops_auth.current_actor()
        if actor and actor.role == "station" and not _station_owns(t, actor):
            raise HTTPException(403, "只能查看分配給自己的任務")
        t = _with_sla(t, ops_db.sla_minutes(conn), now)
        t = _with_rules(conn, t)
        drafts = ops_db.get_drafts(conn, t["case_id"])
        log = ops_db.list_notification_log(conn, task_id)
        photos = ops_db.list_task_photos(conn, task_id)
    t["is_demo"] = _srv._demo_mode() and t["case_id"] in _srv.DEMO_CASE_IDS
    return {"task": t, "case": _case_view(t["case_id"]), "drafts": drafts,
            "notification_log": log, "photos": [_photo_row(p) for p in photos],
            "server_time": _iso(now)}


class OpsTaskUpdate(BaseModel):
    status: str | None = None
    action: str | None = None
    assignee: str | None = None
    assignee_id: int | None = None
    note: str | None = None
    expected_assignee: str | None = None   # 防搶單：指派前確認目前負責人仍是此值（"" = 未指派）
    expected_assignee_id: int | None = None


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, upd: OpsTaskUpdate, x_ops_reader: str | None = Header(default=None)):
    """Action / 狀態 / 指派走同一個 TaskService；備註另寫 task_events(note)。

    `status` 保留給舊監理台相容；新前端只送後端回傳的 allowed_actions。
    claim 會使用單一 compare-and-set UPDATE，沒有「先查再改」的競態窗口。
    """
    who = _reader(x_ops_reader)
    actor = ops_auth.current_actor()
    current = None
    if upd.action is not None:
        with _srv.db() as conn:
            current = _srv._task_row(conn, task_id)
        if not current:
            raise HTTPException(404, f"找不到任務 #{task_id}")
    if actor and actor.role == "station":
        if (upd.status is not None or "assignee" in upd.model_fields_set
                or "assignee_id" in upd.model_fields_set or upd.note
                or upd.action not in {"claim", "start", "complete"}):
            raise HTTPException(403, "站點人員只能接單、開工與完工")
        if upd.action != "claim" and not _station_owns(current, actor):
            raise HTTPException(403, "只能操作分配給自己的任務")
    if upd.action is not None:
        with ops_db.db() as conn:
            ruled = _with_rules(conn, current)
        if upd.action not in ruled["allowed_actions"]:
            raise HTTPException(409, f"任務目前不可執行 {upd.action}")
    if upd.action == "claim":
        if upd.status is not None or "assignee" in upd.model_fields_set or "assignee_id" in upd.model_fields_set:
            raise HTTPException(400, "claim 不可同時提供 status 或 assignee")
        if actor:
            if actor.person_id is None:
                raise HTTPException(403, "站點帳號未連結 People，請由 Admin 修正")
            _srv.patch_task(task_id, _srv.TaskUpdate(
                assignee_id=actor.person_id, expected_assignee_id=0))
        else:  # 舊單元測試／直接 function call 相容
            _srv.patch_task(task_id, _srv.TaskUpdate(assignee=who, expected_assignee=""))
    elif upd.action == "assign":
        has_identity = "assignee_id" in upd.model_fields_set or "assignee" in upd.model_fields_set
        if not has_identity or upd.status is not None:
            raise HTTPException(400, "assign 需要 assignee，且不可同時提供 status")
        fields = {k: getattr(upd, k) for k in (
            "assignee", "assignee_id", "expected_assignee", "expected_assignee_id")
                  if k in upd.model_fields_set}
        _srv.patch_task(task_id, _srv.TaskUpdate(**fields))
    elif upd.status is not None or upd.action is not None or "assignee" in upd.model_fields_set or "assignee_id" in upd.model_fields_set:
        fields = {k: getattr(upd, k) for k in (
            "assignee", "assignee_id", "expected_assignee", "expected_assignee_id")
                  if k in upd.model_fields_set}
        _srv.patch_task(task_id, _srv.TaskUpdate(
            status=upd.status, action=upd.action, **fields))
    note = (upd.note or "").strip()
    if note:
        with _srv.db() as conn:
            if not conn.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone():
                raise HTTPException(404, f"找不到任務 #{task_id}")
            _srv._add_task_event(conn, task_id, _iso(_now()), "note", f"{who}：{note[:500]}")
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
        out = {"events": evs, "unread": ops_db.unread_count(conn, reader),
               "server_time": _iso(_now())}
    _flush_escalations()
    return out


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
        person = ops_db.add_person(conn, group, name)
        ops_db.add_audit(conn, "create", "person", person["id"], f"{group} / {name}")
        return person


@router.patch("/people/{pid}")
def patch_person(pid: int, p: PersonPatch):
    group = p.group_name.strip() if p.group_name is not None else None
    name = p.name.strip() if p.name is not None else None
    if group == "" or name == "":
        raise HTTPException(400, "group_name 與 name 不可為空")
    with ops_db.db() as conn:
        current = conn.execute("SELECT * FROM ops_people WHERE id=?", (pid,)).fetchone()
        if not current:
            raise HTTPException(404, "找不到人員")
        current = dict(current)
        if name and name != current["name"] and conn.execute(
                "SELECT 1 FROM ops_people WHERE name=? AND id<>?", (name, pid)).fetchone():
            raise HTTPException(409, f"「{name}」已存在")
        r = ops_db.update_person(conn, pid, group_name=group, name=name,
                                 active=None if p.active is None else int(p.active))
        if name and name != current["name"]:
            # Stable identity 不變；只同步 legacy display name，舊 audit snapshot 不回寫。
            # 不在每張任務寫 assignee 事件：改名不是指派，時間軸會誤判成「重新指派」；
            # 改名紀錄由下方 ops_audit_log 保存。
            conn.execute("UPDATE tasks SET assignee=?, updated_at=? WHERE assignee_id=?",
                         (name, _iso(_now()), pid))
            conn.execute("UPDATE ops_settings SET value=? WHERE key LIKE 'default_assignee_%' AND value=?",
                         (name, current["name"]))
            conn.execute("UPDATE ops_users SET display_name=? WHERE person_id=?", (name, pid))
        ops_db.add_audit(conn, "update", "person", pid,
                         f"{current['group_name']} / {current['name']} → {r['group_name']} / {r['name']}; active={r['active']}")
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
        elif k in ("require_photo_cleaning", "require_photo_repair", "escalate_on_overdue"):
            clean[k] = "1" if v in (True, 1, "1", "true", "on") else "0"
        elif k in ("default_assignee_cleaning_id", "default_assignee_repair_id"):
            clean[k] = str(v).strip()
        elif isinstance(k, str) and len(k) <= 64:
            clean[k] = str(v)[:500]
    with ops_db.db() as conn:
        for kind in ("cleaning", "repair"):
            id_key, name_key = f"default_assignee_{kind}_id", f"default_assignee_{kind}"
            if id_key in clean:
                raw = clean[id_key]
                if raw:
                    person = conn.execute(
                        "SELECT id, name FROM ops_people WHERE id=? AND active=1", (raw,)).fetchone()
                    if not person:
                        raise HTTPException(400, f"{id_key} 找不到啟用中人員")
                    clean[id_key], clean[name_key] = str(person[0]), person[1]
                else:
                    clean[name_key] = ""
            elif name_key in clean:
                name = clean[name_key].strip()
                matches = conn.execute(
                    "SELECT id FROM ops_people WHERE name=? AND active=1", (name,)).fetchall() if name else []
                clean[id_key] = str(matches[0][0]) if len(matches) == 1 else ""
        ops_db.set_settings(conn, clean)
        ops_db.add_audit(conn, "update", "settings", "ops", ", ".join(sorted(clean)))
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
        _srv._add_task_event(conn, task_id, entry["at"], "notify", f"{who}：{detail}")
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
    _flush_escalations()
    return list(reversed(evs))   # 由舊到新


@router.get("/events/stream")
async def events_stream(since: int = 0, reader: str | None = None,
                        x_ops_reader: str | None = Header(default=None)):
    reader = _reader(reader or x_ops_reader)   # runtime 一律以 session actor 覆蓋 query/header

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


# ---------- 車輛站點（指揮中心 3D 地圖）----------
# 派單系統尚未串接：車輛位置 = car_locations 指定站點，否則依車牌雜湊固定指派（確定性，Demo 每次一致）。

STATIONS_PATH = Path(__file__).resolve().parent / "stations.json"


def _stations_doc() -> dict:
    try:
        return json.loads(STATIONS_PATH.read_text())
    except Exception:
        return {"cities": [], "stations": []}


def _stations() -> list[dict]:
    return _stations_doc().get("stations") or []


def _default_station_id(car: str) -> str | None:
    """依車牌雜湊（穩定、與 Python hash seed 無關）按權重指派站點。"""
    sts = _stations()
    if not sts:
        return None
    weighted = [st for st in sts for _ in range(max(1, int(st.get("weight") or 1)))]
    h = 0
    for ch in car.upper():
        h = (h * 131 + ord(ch)) % 1_000_003
    return weighted[h % len(weighted)]["id"]


def _location_of(car: str, overrides: dict[str, dict]) -> dict | None:
    sts = {st["id"]: st for st in _stations()}
    cities = {c["id"]: c for c in (_stations_doc().get("cities") or [])}
    sid = (overrides.get(car) or {}).get("station_id") or _default_station_id(car)
    st = sts.get(sid)
    if not st:
        return None
    city = cities.get(st.get("city"), {})
    return {"station_id": st["id"], "station": st["name"], "district": st.get("district"),
            "city_id": st.get("city"), "city": city.get("name"), "lng": st["lng"], "lat": st["lat"],
            "manual": car in overrides}


def _vehicle_location(v: dict) -> dict | None:
    """可租車輛（demo_vehicles）的位置：座標就是車輛實際儲存的 lat/lng（App 地圖同一組），不被站點覆蓋。
    station_id 取最近的站點，只用於行政區／城市歸類與地圖分群。"""
    loc = v.get("location") or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        return None
    sts = _stations()
    cities = {c["id"]: c for c in (_stations_doc().get("cities") or [])}
    near = min(sts, key=lambda st: (st["lat"] - lat) ** 2 + ((st["lng"] - lng) * 0.9) ** 2) if sts else None
    city = cities.get((near or {}).get("city"), {})
    return {"station_id": (near or {}).get("id"), "station": loc.get("name") or (near or {}).get("name"),
            "district": (near or {}).get("district"), "city_id": (near or {}).get("city"), "city": city.get("name"),
            "lng": lng, "lat": lat, "manual": True, "source": "vehicle",
            "nearest_station": (near or {}).get("name")}


def _rental_fleet_by_key() -> dict[str, dict]:
    try:
        return {_plate_key(v["plate"]): v for v in rental_sessions.list_vehicles(internal=True, include_parked=False)}
    except Exception:
        return {}


def _car_location(car: str, overrides: dict[str, dict], fleet_by_key: dict[str, dict]) -> dict | None:
    """可租車輛 → 車輛座標；其他（資料集車輛）→ 既有站點指派。"""
    v = fleet_by_key.get(_plate_key(car))
    return (_vehicle_location(v) if v else None) or _location_of(car, overrides)


@router.get("/stations")
def stations():
    doc = _stations_doc()
    return {"cities": doc.get("cities") or [], "stations": doc.get("stations") or [], "server_time": _iso(_now())}


class LocationIn(BaseModel):
    station_id: str | None = None   # None = 清除手動指派，回到預設


@router.patch("/fleet/{car}/location")
def patch_location(car: str, body: LocationIn, x_ops_reader: str | None = Header(default=None)):
    who = _reader(x_ops_reader)
    car = car.strip().upper()
    if not car:
        raise HTTPException(400, "car 不可為空")
    bookable = rental_sessions.vehicle_by_plate(car)
    if bookable and body.station_id:
        # 可租車輛：位置以車輛座標為準 → 直接把座標改到該站點（App 地圖同步）
        st = next((x for x in _stations() if x["id"] == body.station_id), None)
        if not st:
            raise HTTPException(400, f"未知站點 {body.station_id}")
        try:
            rental_sessions.set_vehicle_location(bookable["vehicle_id"], st["lat"], st["lng"], st["name"])
        except rental_sessions.SessionError as e:
            raise HTTPException(e.status, e.detail) from e
    with ops_db.db() as conn:
        if body.station_id:
            if body.station_id not in {st["id"] for st in _stations()}:
                raise HTTPException(400, f"未知站點 {body.station_id}")
            ops_db.set_car_location(conn, car, body.station_id, who)
        else:
            conn.execute(ops_db.sql("DELETE FROM car_locations WHERE car=?"), (car,))
        ops_db.add_audit(conn, "relocate", "fleet", car, body.station_id)
        loc = _car_location(car, ops_db.get_car_locations(conn), _rental_fleet_by_key())
    return {"car": car, "location": loc, "server_time": _iso(_now())}


def _plate_key(car: str) -> str:
    """車牌比對鍵：資料集的車號來自檔名，有的帶連字號（RCR-7661）、有的沒有（RCG2235），
    iOS 租約一律 ABC-1234 格式。同一台車在車隊清單只能出現一列，所以用去連字號大寫比對。"""
    return (car or "").upper().replace("-", "").strip()


def _display_car(candidates: set[str]) -> str:
    """同一台車的多種寫法選一個顯示：優先帶連字號的（租約／App 的格式），再按字母序。"""
    return sorted(candidates, key=lambda c: ("-" not in c, c))[0]


@router.get("/fleet")
def fleet(q: str | None = None, status: str | None = None):
    now = _now()
    with ops_db.db() as conn:
        sla = ops_db.sla_minutes(conn)
        tasks = [_with_sla(dict(r), sla, now) for r in conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")]
        locks = ops_db.get_locks(conn)
        loc_overrides = ops_db.get_car_locations(conn)
        baseline_counts = {r[0]: r[1] for r in conn.execute(
            "SELECT UPPER(p.car), COUNT(*) FROM task_photos p JOIN tasks t ON t.id=p.task_id"
            " WHERE t.status='completed' GROUP BY UPPER(p.car)")}
    ds = _dataset_cars()
    try:
        # App 可租車輛（demo_vehicles）：即使從沒被租過也要出現在車隊清單；租用中由 Session／車輛狀態決定
        rental_fleet = {v["plate"]: v for v in rental_sessions.list_vehicles(internal=True, include_parked=False)}
    except Exception:
        rental_fleet = {}
    try:
        rentals = rental_inspections.vehicles()      # iOS App 租約的車（車型、最近還車）
        mobile_cases: dict[str, int] = {}
        for c in rental_inspections.ops_cases():
            mobile_cases[c["car"]] = mobile_cases.get(c["car"], 0) + 1
    except Exception:
        rentals, mobile_cases = {}, {}
    # 同一台車的不同寫法（RCG2235 / RCG-2235）合併成一列
    groups: dict[str, set[str]] = {}
    for name in set(ds) | {t["car"] for t in tasks if t.get("car")} | set(locks) | set(rentals) | set(rental_fleet):
        groups.setdefault(_plate_key(name), set()).add(name)
    rows = []
    for key, names in groups.items():
        car = _display_car(names)
        mine = [t for t in tasks if _plate_key(t.get("car")) == key]
        open_tasks = [t for t in mine if t["status"] in ("pending", "in_progress")]
        lock = next((locks[n] for n in names if n in locks), None)
        manual = bool(lock and lock["locked"])
        info = next((ds[n] for n in names if n in ds), {})
        rental = next((rentals[n] for n in names if n in rentals), None)
        mobile_count = sum(v for k, v in mobile_cases.items() if _plate_key(k) == key)
        bookable = next((rental_fleet[n] for n in names if n in rental_fleet), None)
        if bookable and bookable["status"] == "RENTED":
            st = "rented"            # 租用中（含還車流程尚未確認還車）：不論其他條件都不可出租
        elif open_tasks or manual:
            st = "locked"
        elif info.get("unreviewed") or _unreviewed_mobile(car, mobile_cases):
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
            "baseline_count": baseline_counts.get(car.upper(), 0),
            "dataset_cases": info.get("cases", 0), "claims": info.get("claims", 0),
            "unreviewed_flags": info.get("unreviewed", 0),
            "location": (_vehicle_location(bookable) if bookable else None) or _location_of(car, loc_overrides),
            "model": (rental or {}).get("model") or (bookable or {}).get("model"),
            "last_rental": rental,
            "mobile_cases": mobile_count,
            # App 可租車輛才有以下欄位意義：rentable＝使用者現在租得到（與 App 車輛清單一致）
            "rental_fleet": bool(bookable),
            # 與 App 同一個判斷（rental_sessions.availability）；待審核（review）的 AI 案件依既有語意不鎖派單，只提示營運人員
            "rentable": bool(bookable) and bookable["status"] == "AVAILABLE",
            "rental_state": {"vehicle_id": bookable["vehicle_id"], "vehicle_status": bookable["status"],
                             "session_id": bookable.get("active_session_id"),
                             "session_state": bookable.get("active_session_state"),
                             "visibility": bookable.get("visibility"),
                             "is_demo": bool(bookable.get("is_demo")),
                             "is_fixture": bool(bookable.get("is_fixture")),
                             "admin_created": bool(bookable.get("admin_created"))} if bookable else None,
        })
    if q:
        rows = [r for r in rows if q.upper() in r["car"].upper()]
    if status:
        rows = [r for r in rows if r["status"] == status]
    order = {"rented": 0, "locked": 1, "review": 2, "available": 3}
    rows.sort(key=lambda r: (order[r["status"]], -len(r["open_tasks"]), r["car"]))
    return {"fleet": rows, "server_time": _iso(now),
            "counts": {**{k: sum(r["status"] == k for r in rows) for k in order},
                       "rentable": sum(r["rentable"] for r in rows)},
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
        ops_db.add_audit(conn, "lock" if body.locked else "unlock", "fleet", car, lock.get("reason"))
    return {"lock": lock, **fleet(q=car)}


def _unreviewed_mobile(car: str, mobile_cases: dict[str, int]) -> bool:
    key = _plate_key(car)
    if not any(v for k, v in mobile_cases.items() if _plate_key(k) == key):
        return False
    with _srv.db() as conn:
        decided = {r[0] for r in conn.execute("SELECT case_id FROM decisions")}
    return any(_plate_key(c["car"]) == key and c["case_id"] not in decided for c in rental_inspections.ops_cases())


# ---------- 案件（AI 判定 → 人工裁決）：指揮中心用的異常清單 ----------
# 資料來源與監理台相同（build_dashboard.build_cases / build_f2cases），只加上裁決與任務狀態。

def _dataset_case_list() -> list[dict]:
    from build_dashboard import build_cases, build_f2cases  # noqa: PLC0415
    out = []
    try:
        for c in build_cases(embed=False):
            a = c.get("assessment") or {}
            out.append({
                "case_id": c["id"], "car": c["car"], "angle": c["angle"], "mode": "pair",
                "kind": c.get("kind"), "ai_level": c["level"],
                "ai_conf": max((d.get("confidence") or 0 for d in a.get("damages") or []), default=None) if a.get("damages") else None,
                "ai_found": bool(a.get("new_damage_found")),
                "damages": [{"location": d.get("location"), "type": d.get("type"), "severity": d.get("severity"),
                             "confidence": d.get("confidence"), "reasoning": d.get("reasoning")} for d in (a.get("damages") or [])],
                "issues": [], "cleanliness": None, "score": None,
                "pricing": c.get("pricing"),
                "photos": {"pickup": c.get("pickup"), "return": c.get("ret")},
                "truth": c.get("truth"),
            })
    except Exception:
        pass
    try:
        for c in build_f2cases(embed=False):
            a = c.get("assessment") or {}
            out.append({
                "case_id": c["id"], "car": c["car"], "angle": c["angle"], "mode": "interior",
                "kind": c.get("kind"), "ai_level": c["level"], "ai_conf": a.get("confidence"),
                "ai_found": a.get("level") == "髒汙",
                "damages": [], "issues": a.get("issues") or [], "cleanliness": a.get("level"), "score": a.get("score"),
                "pricing": None,
                "photos": {"photo": c.get("photo")},
                "truth": c.get("truth"),
            })
    except Exception:
        pass
    return out


def _mobile_case_list(case_id: str | None = None) -> list[dict]:
    """iOS App 租約檢查產生的案件（rental_inspections）；失敗回空，不擋資料集案件。"""
    try:
        return rental_inspections.ops_cases(case_id)
    except Exception:
        return []


def _attach_case_state(cases: list[dict]) -> list[dict]:
    """加上人工裁決、對應任務、標註框、站點；並推導 review_status。"""
    ann = _srv._annotations()
    with _srv.db() as conn:
        decisions = {r[0]: {"decision": r[1], "decided_at": r[2]} for r in conn.execute("SELECT case_id, decision, decided_at FROM decisions")}
        cols = ("id", "case_id", "task_type", "status", "priority", "assignee", "created_at", "resolved_at")
        task_rows = [dict(zip(cols, r)) for r in conn.execute(
            "SELECT id, case_id, task_type, status, priority, assignee, created_at, resolved_at FROM tasks ORDER BY id")]
    with ops_db.db() as oconn:
        overrides = ops_db.get_car_locations(oconn)
    fleet_by_key = _rental_fleet_by_key()
    tasks_by_case: dict[str, list[dict]] = {}
    for t in task_rows:
        tasks_by_case.setdefault(t["case_id"], []).append(t)
    for c in cases:
        c["boxes"] = (ann.get(c["case_id"]) or {}).get("findings") or c.get("boxes") or []
        c.setdefault("source", "dataset")
        c["decision"] = decisions.get(c["case_id"])
        c["tasks"] = tasks_by_case.get(c["case_id"], [])
        c["location"] = _car_location(c["car"], overrides, fleet_by_key)
        d = (c["decision"] or {}).get("decision")
        open_task = any(t["status"] in ("pending", "in_progress") for t in c["tasks"])
        if d == "confirm":
            c["review_status"] = "confirmed_open" if open_task else "confirmed_done"
        elif d == "reject":
            c["review_status"] = "rejected"
        elif d == "retake":
            c["review_status"] = "retake"
        elif c["ai_level"] in ("P1", "P2"):
            c["review_status"] = "unreviewed"
        else:
            c["review_status"] = "normal"
    return cases


@router.get("/cases")
def list_cases(car: str | None = None, status: str | None = None, levels: str | None = None):
    """AI 判定案件清單（資料集）。status = unreviewed | confirmed_open | confirmed_done | rejected | retake | normal。"""
    cases = _attach_case_state(_dataset_case_list() + _mobile_case_list())
    if car:
        cases = [c for c in cases if _plate_key(c["car"]) == _plate_key(car)]
    if status:
        wanted = set(status.split(","))
        cases = [c for c in cases if c["review_status"] in wanted]
    if levels:
        wanted = set(levels.split(","))
        cases = [c for c in cases if c["ai_level"] in wanted]
    order = {"P1": 0, "P2": 1, "P3": 2}
    cases.sort(key=lambda c: (order.get(c["ai_level"], 3), c["car"], c["case_id"]))
    return {"cases": cases, "server_time": _iso(_now()), "demo_cases": list(_srv.DEMO_CASE_IDS) if _srv._demo_mode() else []}


@router.get("/cases/{case_id}")
def get_case(case_id: str):
    cases = [c for c in _attach_case_state(_dataset_case_list() + _mobile_case_list(case_id)) if c["case_id"] == case_id]
    view = _case_view(case_id)
    if not cases and view.get("mode") is None:
        raise HTTPException(404, f"找不到案件 {case_id}")
    return {"case": cases[0] if cases else None, "view": view, "server_time": _iso(_now())}


class CaseDecisionIn(BaseModel):
    decision: str   # confirm | reject | retake
    note: str | None = None


@router.post("/cases/{case_id}/decision")
def decide_case(case_id: str, body: CaseDecisionIn):
    """人工裁決（與監理台 POST /api/decision 同一條路：confirm 會自動建單並通知）。"""
    actor = ops_auth.current_actor()
    if actor and actor.role != "admin":
        raise HTTPException(403, "此功能僅限管理者")
    r = _srv.post_decision(_srv.Decision(case_id=case_id, decision=body.decision, note=body.note))
    return {**r, "case": get_case(case_id)["case"], "server_time": _iso(_now())}


@router.delete("/cases/{case_id}/decision")
def undo_case_decision(case_id: str):
    actor = ops_auth.current_actor()
    if actor and actor.role != "admin":
        raise HTTPException(403, "此功能僅限管理者")
    _srv.delete_decision(case_id)
    return {"ok": True, "case": get_case(case_id)["case"], "server_time": _iso(_now())}


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
        "agreement": _agreement_stats(),
    }


# ---------- 完工照（站點手機版）：存 paths.UPLOAD_DIR/ops_task_photos/<task_id>/ ----------

PHOTO_ROOT = paths.UPLOAD_DIR / "ops_task_photos"
MAX_PHOTO_BYTES = 12 * 1024 * 1024
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")


def _photo_row(p: dict) -> dict:
    return {**p, "url": f"/api/ops/tasks/{p['task_id']}/photos/{p['filename']}"}


@router.post("/tasks/{task_id}/photos")
async def upload_task_photo(task_id: int, photo: UploadFile = File(...),
                            x_ops_reader: str | None = Header(default=None)):
    """上傳一張完工照。轉正 EXIF、縮到長邊 1600、存 JPEG；寫 task_photos 與歷程。"""
    who = _reader(x_ops_reader)
    with _srv.db() as conn:
        t = _srv._task_row(conn, task_id)
    if not t:
        raise HTTPException(404, f"找不到任務 #{task_id}")
    actor = ops_auth.current_actor()
    if actor and actor.role == "station" and not _station_owns(t, actor):
        raise HTTPException(403, "只能替分配給自己的任務上傳照片")
    with ops_db.db() as conn:
        ruled = _with_rules(conn, t)
    if "upload_photo" not in ruled["allowed_actions"]:
        raise HTTPException(409, "只有處理中的任務可以上傳完工照")
    raw = await photo.read()
    if not raw:
        raise HTTPException(400, "空檔案")
    if len(raw) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "照片超過 12 MB")
    try:
        from PIL import Image, ImageOps  # noqa: PLC0415
        import io  # noqa: PLC0415
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGB")
        im.thumbnail((1600, 1600))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        data = buf.getvalue()
    except Exception:
        raise HTTPException(400, "無法讀取影像（支援 JPEG / PNG / HEIC）")
    name = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.jpg"
    d = PHOTO_ROOT / str(task_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_bytes(data)
    with ops_db.db() as conn:
        row = ops_db.add_task_photo(conn, t, name, who)
        _srv._add_task_event(conn, task_id, row["at"], "photo", f"{who}：上傳完工照 {name}")
        photos = ops_db.list_task_photos(conn, task_id)
    detail = get_task(task_id)
    return {"ok": True, "photo": _photo_row(row), "photos": [_photo_row(p) for p in photos],
            "task": detail["task"]}


@router.get("/tasks/{task_id}/photos/{name}")
def get_task_photo(task_id: int, name: str):
    actor = ops_auth.current_actor()
    if actor and actor.role == "station":
        with _srv.db() as conn:
            task = _srv._task_row(conn, task_id)
        if not task or not _station_owns(task, actor):
            raise HTTPException(403, "只能查看自己的任務照片")
    if not _SAFE_NAME.match(name):
        raise HTTPException(404)
    f = PHOTO_ROOT / str(task_id) / name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


# ---------- 站點手機版：我的任務（指派給我 + 未指派的待處理） ----------

@router.get("/my-tasks")
def my_tasks(x_ops_reader: str | None = Header(default=None)):
    who = _reader(x_ops_reader)
    actor = ops_auth.current_actor()
    now = _now()
    with ops_db.db() as conn:
        _refresh_events(conn)
        sla = ops_db.sla_minutes(conn)
        if actor and actor.role == "station":
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM tasks WHERE status IN ('pending','in_progress')"
                " AND (assignee_id=? OR (assignee_id IS NULL AND (assignee IS NULL OR assignee='')))"
                " ORDER BY created_at", (actor.person_id,))]
        else:
            ids = [r[0] for r in conn.execute(
                "SELECT id FROM tasks WHERE status IN ('pending','in_progress')"
                " AND (assignee=? OR (assignee_id IS NULL AND (assignee IS NULL OR assignee='')))"
                " ORDER BY created_at", (who,))]
        out = []
        for i in ids:
            t = _with_sla(_srv._task_row(conn, i), sla, now)
            t = _with_rules(conn, t)
            t["photos"] = [_photo_row(p) for p in ops_db.list_task_photos(conn, i)]
            t["mine"] = _station_owns(t, actor) if actor and actor.role == "station" else t.get("assignee") == who
            out.append(t)
    rank = {"P1": 0, "P2": 1, "P3": 2}
    out.sort(key=lambda t: (0 if t["mine"] else 1, 0 if t["status"] == "in_progress" else 1,
                            rank.get(t.get("priority") or "P2", 1), t["created_at"]))
    return {"tasks": out, "reader": who, "server_time": _iso(now)}


# ---------- 完工照 → 下一次借車的基準照 ----------

@router.get("/cars/{car}/baseline")
def car_baseline(car: str, limit: int = 6):
    """該車最近的完工照（最新在前）。環節二比對可優先取用此基準，而非只靠用戶自拍的借車照。"""
    car = car.strip().upper()
    with ops_db.db() as conn:
        rows = ops_db.rows(conn.execute(
            "SELECT p.*, t.task_type, t.status FROM task_photos p JOIN tasks t ON t.id = p.task_id"
            " WHERE UPPER(p.car)=? AND t.status='completed' ORDER BY p.id DESC LIMIT ?", (car, limit)))
    return {"car": car, "photos": [_photo_row(r) for r in rows], "server_time": _iso(_now())}


def _agreement_stats() -> dict:
    """人工裁決 vs AI 判定一致率：來源 decision_events（append-only）。只算有表態（label 非 NULL）者。"""
    with _srv.db() as conn:
        rows = conn.execute(
            "SELECT substr(decided_at,1,10) AS day, COUNT(*) AS n, SUM(agreed) AS agreed"
            "  FROM decision_events WHERE agreed IS NOT NULL GROUP BY day ORDER BY day").fetchall()
    days = [{"day": d, "n": n, "agreed": a or 0} for d, n, a in rows]
    n = sum(x["n"] for x in days)
    a = sum(x["agreed"] for x in days)
    return {"days": days, "n": n, "agreed": a, "rate": round(a / n, 3) if n else None}


def latest_baseline(car: str) -> dict | None:
    """該車最近一張完工照（已完成任務），含 bytes；供現場實測／判讀端當借車基準照。"""
    car = (car or "").strip().upper()
    if not car:
        return None
    with ops_db.db() as conn:
        r = conn.execute(
            "SELECT p.* FROM task_photos p JOIN tasks t ON t.id = p.task_id"
            " WHERE UPPER(p.car)=? AND t.status='completed' ORDER BY p.id DESC LIMIT 1", (car,)).fetchone()
    if not r:
        return None
    r = dict(r)
    f = PHOTO_ROOT / str(r["task_id"]) / r["filename"]
    if not f.is_file():
        return None
    return {"car": car, "task_id": r["task_id"], "filename": r["filename"], "by": r["by"], "at": r["at"],
            "url": f"/api/ops/tasks/{r['task_id']}/photos/{r['filename']}", "bytes": f.read_bytes()}
