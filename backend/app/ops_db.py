#!/usr/bin/env python3
"""環節三（整備中心）資料存取層。

本環節自己擁有的資料表都在這裡建立與存取；監理台既有的 tasks / task_events
只讀不改結構。SQL 刻意只用 SQLite 與 PostgreSQL 都接受的型別與語法
（TEXT / INTEGER、時間存 ISO 字串、無 AUTOINCREMENT 以外的方言），
日後同事切 DATABASE_URL 時只需換掉本檔的 connect() 與佔位符。

資料表：
  ops_events        通知中心事件流（由 task_events 增量派生 + SLA 掃描產生）
  event_reads       事件已讀（reader 為前端自選身分，無登入前提）
  case_drafts       三對象通知文案快取（以 case_id 為鍵：內容取決於 AI 判定，不隨任務重建而失效）
  notification_log  發送紀錄（webhook 實發；line / sms 記為 unsupported）
  ops_people        整備人員／組別（取代前端寫死的 ASSIGNEES）
  ops_settings      key/value 設定（SLA 門檻等）
"""
import json
import sqlite3
from datetime import datetime

import paths

# 預設整備人員：與監理台 dashboard_shell.html 的 ASSIGNEES 一致，名單值相容
DEFAULT_PEOPLE = [
    ("維修組", "維修組 A"), ("維修組", "維修組 B"),
    ("清潔組", "清潔組 A"), ("清潔組", "清潔組 B"),
]

# SLA 門檻（分鐘）：README 環節三 §預警分級與 SLA 設計。P3 為「當日」以 1440 近似。
DEFAULT_SETTINGS = {
    "sla_minutes_p1": "5",
    "sla_minutes_p2": "240",
    "sla_minutes_p3": "1440",
}

DDL = [
    """CREATE TABLE IF NOT EXISTS ops_events(
         id        INTEGER PRIMARY KEY AUTOINCREMENT,
         at        TEXT NOT NULL,
         type      TEXT NOT NULL,      -- task_created | task_status | task_assigned | notify_sent | notify_failed | sla_overdue | note
         task_id   INTEGER,
         case_id   TEXT,
         priority  TEXT,
         car       TEXT,
         title     TEXT,
         detail    TEXT,
         source_event_id INTEGER,      -- 來源 task_events.event_id（派生事件用，避免重複）
         UNIQUE(source_event_id))""",
    """CREATE TABLE IF NOT EXISTS event_reads(
         event_id INTEGER NOT NULL,
         reader   TEXT NOT NULL,
         at       TEXT NOT NULL,
         PRIMARY KEY(event_id, reader))""",
    """CREATE TABLE IF NOT EXISTS case_drafts(
         case_id   TEXT NOT NULL,
         audience  TEXT NOT NULL,      -- user | cs | worker
         content   TEXT NOT NULL,      -- JSON（notify.py 對應 schema）
         grounding_ok INTEGER,
         grounding_notes TEXT,         -- JSON list
         model     TEXT,
         generated_at TEXT,
         edited_at TEXT,
         PRIMARY KEY(case_id, audience))""",
    """CREATE TABLE IF NOT EXISTS notification_log(
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         task_id  INTEGER NOT NULL,
         audience TEXT,
         channel  TEXT NOT NULL,       -- webhook | line | sms
         status   TEXT NOT NULL,       -- sent | failed | unsupported | skipped
         detail   TEXT,
         at       TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_people(
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         group_name TEXT NOT NULL,
         name       TEXT NOT NULL UNIQUE,
         active     INTEGER NOT NULL DEFAULT 1,
         created_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_settings(
         key   TEXT PRIMARY KEY,
         value TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_ops_events_at ON ops_events(at)",
    "CREATE INDEX IF NOT EXISTS idx_ops_events_task ON ops_events(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_nlog_task ON notification_log(task_id)",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def db_path():
    """與監理台共用同一個 SQLite 檔。ops_api.bind() 會改指向 server.DB_PATH（測試可 monkeypatch）。"""
    return paths.DB_PATH


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    for stmt in DDL:
        conn.execute(stmt)
    if conn.execute("SELECT COUNT(*) FROM ops_people").fetchone()[0] == 0:
        ts = now_iso()
        conn.executemany(
            "INSERT INTO ops_people(group_name, name, active, created_at) VALUES (?,?,1,?)",
            [(g, n, ts) for g, n in DEFAULT_PEOPLE])
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO ops_settings(key, value) VALUES (?,?)", (k, v))


# ops 表依賴監理台的 tasks / task_events；ops_api.bind() 會把它設成「先跑 server.db() 建基礎表」
base_init = None


class db:
    """with db() as conn: 進入時建表（冪等）、離開時 commit / rollback。"""

    def __enter__(self):
        if base_init:
            base_init()
        self.conn = connect()
        ensure_schema(self.conn)
        return self.conn

    def __exit__(self, exc_type, *_):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        self.conn.close()
        return False


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


# ---------- settings ----------

def get_settings(conn) -> dict:
    return {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ops_settings")}


def set_settings(conn, values: dict) -> dict:
    for k, v in values.items():
        conn.execute("INSERT OR REPLACE INTO ops_settings(key, value) VALUES (?,?)", (k, str(v)))
    return get_settings(conn)


def sla_minutes(conn) -> dict:
    s = get_settings(conn)
    out = {}
    for p in ("P1", "P2", "P3"):
        try:
            out[p] = int(s.get(f"sla_minutes_{p.lower()}") or DEFAULT_SETTINGS[f"sla_minutes_{p.lower()}"])
        except ValueError:
            out[p] = int(DEFAULT_SETTINGS[f"sla_minutes_{p.lower()}"])
    return out


# ---------- people ----------

def list_people(conn, include_inactive=False) -> list[dict]:
    q = "SELECT * FROM ops_people" + ("" if include_inactive else " WHERE active=1") + \
        " ORDER BY group_name, name"
    return rows(conn.execute(q))


def add_person(conn, group_name: str, name: str) -> dict:
    conn.execute("INSERT INTO ops_people(group_name, name, active, created_at) VALUES (?,?,1,?)",
                 (group_name, name, now_iso()))
    return dict(conn.execute("SELECT * FROM ops_people WHERE name=?", (name,)).fetchone())


def update_person(conn, pid: int, **fields) -> dict | None:
    allowed = {k: v for k, v in fields.items() if k in ("group_name", "name", "active") and v is not None}
    if allowed:
        sets = ", ".join(f"{k}=?" for k in allowed)
        conn.execute(f"UPDATE ops_people SET {sets} WHERE id=?", (*allowed.values(), pid))
    r = conn.execute("SELECT * FROM ops_people WHERE id=?", (pid,)).fetchone()
    return dict(r) if r else None


# ---------- events ----------

_EVENT_TYPE_OF = {"created": "task_created", "reopened": "task_created",
                  "status": "task_status", "assignee": "task_assigned",
                  "cancelled": "task_status", "note": "note"}


def derive_events_from_tasks(conn) -> int:
    """把 task_events 尚未派生過的紀錄轉成 ops_events。冪等（UNIQUE source_event_id）。

    監理台的 confirm / PATCH 都只寫 task_events，這裡不改動它們的程式，
    改以增量派生取得事件流。回傳新增筆數。
    """
    last = conn.execute("SELECT COALESCE(MAX(source_event_id), 0) FROM ops_events").fetchone()[0]
    cur = conn.execute(
        "SELECT e.event_id, e.task_id, e.at, e.event, e.detail,"
        "       t.case_id, t.priority, t.car, t.title"
        "  FROM task_events e JOIN tasks t ON t.id = e.task_id"
        " WHERE e.event_id > ? ORDER BY e.event_id", (last,))
    n = 0
    for r in cur.fetchall():
        ev, detail = r["event"], r["detail"] or ""
        if ev == "notify":
            typ = "notify_sent" if "已送出" in detail else (
                "notify_skipped" if "未設定" in detail else "notify_failed")
        else:
            typ = _EVENT_TYPE_OF.get(ev, "task_status")
        conn.execute(
            "INSERT OR IGNORE INTO ops_events(at, type, task_id, case_id, priority, car, title,"
            " detail, source_event_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (r["at"], typ, r["task_id"], r["case_id"], r["priority"], r["car"], r["title"],
             detail, r["event_id"]))
        n += 1
    return n


def add_event(conn, typ: str, task: dict, detail: str, at: str | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO ops_events(at, type, task_id, case_id, priority, car, title, detail)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (at or now_iso(), typ, task.get("id"), task.get("case_id"), task.get("priority"),
         task.get("car"), task.get("title"), detail))
    return cur.lastrowid


def has_overdue_event(conn, task_id: int) -> bool:
    return conn.execute("SELECT 1 FROM ops_events WHERE task_id=? AND type='sla_overdue'",
                        (task_id,)).fetchone() is not None


def list_events(conn, reader: str, *, since_id: int = 0, priority: str | None = None,
                unread_only=False, types: list[str] | None = None, limit: int = 100) -> list[dict]:
    where, params = ["e.id > ?"], [since_id]
    if priority:
        where.append("e.priority = ?")
        params.append(priority)
    if types:
        where.append("e.type IN (" + ",".join("?" * len(types)) + ")")
        params.extend(types)
    if unread_only:
        where.append("r.event_id IS NULL")
    q = ("SELECT e.*, CASE WHEN r.event_id IS NULL THEN 0 ELSE 1 END AS is_read"
         "  FROM ops_events e LEFT JOIN event_reads r ON r.event_id = e.id AND r.reader = ?"
         " WHERE " + " AND ".join(where) + " ORDER BY e.id DESC LIMIT ?")
    return rows(conn.execute(q, (reader, *params, limit)))


def unread_count(conn, reader: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM ops_events e LEFT JOIN event_reads r"
        "    ON r.event_id = e.id AND r.reader = ? WHERE r.event_id IS NULL", (reader,)).fetchone()[0]


def mark_read(conn, reader: str, ids: list[int] | None) -> int:
    ts = now_iso()
    if ids is None:   # 全部
        cur = conn.execute(
            "INSERT OR IGNORE INTO event_reads(event_id, reader, at)"
            " SELECT id, ?, ? FROM ops_events", (reader, ts))
    else:
        cur = conn.executemany(
            "INSERT OR IGNORE INTO event_reads(event_id, reader, at) VALUES (?,?,?)",
            [(i, reader, ts) for i in ids])
    return cur.rowcount if cur.rowcount is not None else 0


# ---------- drafts / notification log ----------

AUDIENCES = ("user", "cs", "worker")
# notify.py 輸出欄位 → 對象代號
AUDIENCE_KEY = {"user": "user_notification", "cs": "cs_brief", "worker": "work_order"}


def _loads(v, default):
    try:
        return json.loads(v) if v else default
    except Exception:
        return default


def get_drafts(conn, case_id: str) -> dict:
    out = {}
    for r in conn.execute("SELECT * FROM case_drafts WHERE case_id=?", (case_id,)):
        d = dict(r)
        d["content"] = _loads(d["content"], {})
        d["grounding_notes"] = _loads(d["grounding_notes"], [])
        d["grounding_ok"] = bool(d["grounding_ok"])
        out[d["audience"]] = d
    return out


def save_generated_drafts(conn, case_id: str, generated: dict, model: str) -> dict:
    """把 notify.generate() 的輸出拆成三筆存入（覆蓋舊的，含人工編輯）。"""
    ts = now_iso()
    gc = generated.get("grounding_check") or {}
    for aud, key in AUDIENCE_KEY.items():
        conn.execute(
            "INSERT OR REPLACE INTO case_drafts(case_id, audience, content, grounding_ok,"
            " grounding_notes, model, generated_at, edited_at) VALUES (?,?,?,?,?,?,?,NULL)",
            (case_id, aud, json.dumps(generated.get(key) or {}, ensure_ascii=False),
             int(bool(gc.get("passed", True))), json.dumps(gc.get("problems") or [], ensure_ascii=False),
             model, ts))
    return get_drafts(conn, case_id)


def update_draft(conn, case_id: str, audience: str, content: dict) -> dict | None:
    row = conn.execute("SELECT 1 FROM case_drafts WHERE case_id=? AND audience=?",
                       (case_id, audience)).fetchone()
    ts = now_iso()
    if row:
        conn.execute("UPDATE case_drafts SET content=?, edited_at=? WHERE case_id=? AND audience=?",
                     (json.dumps(content, ensure_ascii=False), ts, case_id, audience))
    else:   # 沒生成過也允許人工直接撰寫
        conn.execute(
            "INSERT INTO case_drafts(case_id, audience, content, grounding_ok, grounding_notes,"
            " model, generated_at, edited_at) VALUES (?,?,?,1,'[]','manual',NULL,?)",
            (case_id, audience, json.dumps(content, ensure_ascii=False), ts))
    return get_drafts(conn, case_id).get(audience)


def add_notification_log(conn, task_id: int, audience: str | None, channel: str,
                         status: str, detail: str) -> dict:
    cur = conn.execute(
        "INSERT INTO notification_log(task_id, audience, channel, status, detail, at)"
        " VALUES (?,?,?,?,?,?)", (task_id, audience, channel, status, detail, now_iso()))
    return dict(conn.execute("SELECT * FROM notification_log WHERE id=?", (cur.lastrowid,)).fetchone())


def list_notification_log(conn, task_id: int) -> list[dict]:
    return rows(conn.execute("SELECT * FROM notification_log WHERE task_id=? ORDER BY id", (task_id,)))


def max_event_id(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM ops_events").fetchone()[0]
