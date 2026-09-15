#!/usr/bin/env python3
"""環節三（整備中心）資料存取層。

本環節自己擁有的資料表都在這裡建立與存取；監理台既有的 tasks / task_events
只讀不改結構。SQL 刻意只用 SQLite 與 PostgreSQL 都接受的型別與語法
（TEXT / INTEGER、時間存 ISO 字串、無 AUTOINCREMENT 以外的方言），
日後同事切 DATABASE_URL 時只需換掉本檔的 connect() 與佔位符。

資料表：
  ops_events        通知中心事件流（由 task_events 增量派生 + SLA 掃描產生）
  event_reads       事件已讀（reader 由登入身分提供）
  case_drafts       三對象通知文案快取（以 case_id 為鍵：內容取決於 AI 判定，不隨任務重建而失效）
  notification_log  發送紀錄（webhook 實發；line / sms 記為 unsupported）
  ops_people        整備人員／組別（取代前端寫死的 ASSIGNEES）
  fleet_locks       車輛派單鎖定（手動鎖定／解除；模擬，未與派單系統串接）
  task_photos       整備完工照（站點手機版上傳；日後可作為下一次借車的基準照）
  ops_settings      key/value 設定（SLA 門檻等）
  ops_users/sessions 最小 Demo 登入與 HttpOnly session
  ops_audit_log     People / Settings / Fleet 的管理操作稽核
"""
import json
import logging
import os
import sqlite3
from datetime import datetime

import paths

logger = logging.getLogger(__name__)
_warned_assignees: set[str] = set()

# ---------- 方言層 ----------
# 同事切換 Postgres 時：設 DATABASE_URL=postgresql://...；本檔以 psycopg 連線並把 `?` 轉成 %s、
# AUTOINCREMENT 轉成 SERIAL。監理台主表（tasks 等）的遷移由 server.py 那邊處理。
# ⚠ Postgres 路徑尚未實測（本機無 Postgres）；SQLite 為預設且所有測試都在 SQLite 上跑。


def dialect() -> str:
    url = os.environ.get("DATABASE_URL", "")
    return "postgres" if url.startswith(("postgres://", "postgresql://")) else "sqlite"


def sql(q: str) -> str:
    """把 SQLite 寫法轉成當前方言：佔位符與 upsert 語法。"""
    if dialect() == "sqlite":
        return q
    return (q.replace("?", "%s")
             .replace("INSERT OR IGNORE INTO", "INSERT INTO")
             .replace("INSERT OR REPLACE INTO", "INSERT INTO"))

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
    "require_photo_cleaning": "1",     # 清潔任務完工前須至少一張完工照
    "require_photo_repair": "0",       # 維修任務不強制
    "escalate_on_overdue": "1",        # SLA 逾時自動再發一次 webhook（升級）
    "default_assignee_cleaning": "",   # 建立時依類型自動指派（空＝不自動）
    "default_assignee_repair": "",
    "default_assignee_cleaning_id": "",  # Phase 4 stable ops_people.id；name key 保留相容
    "default_assignee_repair_id": "",
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
    """CREATE TABLE IF NOT EXISTS fleet_locks(
         car     TEXT PRIMARY KEY,
         locked  INTEGER NOT NULL DEFAULT 0,
         reason  TEXT,
         by      TEXT,
         at      TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS task_photos(
         id       INTEGER PRIMARY KEY AUTOINCREMENT,
         task_id  INTEGER NOT NULL,
         case_id  TEXT,
         car      TEXT,
         filename TEXT NOT NULL,
         by       TEXT,
         actor_id INTEGER,
         actor_name TEXT,
         actor_role TEXT,
         at       TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_users(
         id            INTEGER PRIMARY KEY AUTOINCREMENT,
         username      TEXT NOT NULL UNIQUE,
         display_name  TEXT NOT NULL,
         role          TEXT NOT NULL,
         password_hash TEXT NOT NULL,
         password_salt TEXT NOT NULL,
         active        INTEGER NOT NULL DEFAULT 1,
         person_id     INTEGER,
         created_at    TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_sessions(
         token_hash TEXT PRIMARY KEY,
         user_id    INTEGER NOT NULL,
         created_at TEXT NOT NULL,
         expires_at TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS ops_audit_log(
         id         INTEGER PRIMARY KEY AUTOINCREMENT,
         at         TEXT NOT NULL,
         actor_id   INTEGER,
         actor_name TEXT,
         actor_role TEXT,
         action     TEXT NOT NULL,
         resource   TEXT NOT NULL,
         resource_id TEXT,
         detail     TEXT)""",
    "CREATE INDEX IF NOT EXISTS idx_task_photos_task ON task_photos(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_ops_events_at ON ops_events(at)",
    "CREATE INDEX IF NOT EXISTS idx_ops_events_task ON ops_events(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_nlog_task ON notification_log(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON ops_sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_audit_resource ON ops_audit_log(resource, resource_id)",
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def db_path():
    """與監理台共用同一個 SQLite 檔。ops_api.bind() 會改指向 server.DB_PATH（測試可 monkeypatch）。"""
    return paths.DB_PATH


def connect():
    if dialect() == "postgres":
        import psycopg  # noqa: PLC0415  只有真的切 Postgres 才需要安裝
        from psycopg.rows import dict_row  # noqa: PLC0415
        return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row)
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    return conn


def _ddl_for_dialect(stmt: str) -> str:
    if dialect() == "sqlite":
        return stmt
    return stmt.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")


_migrated: set[str] = set()   # 已完成 DDL / seed / migration 的資料庫（以路徑或 URL 為 key）


def _schema_key() -> str:
    return os.environ.get("DATABASE_URL") or str(db_path())


def reset_schema_cache() -> None:
    """測試或切換資料庫路徑時呼叫，強制下一條連線重跑 migration。"""
    _migrated.clear()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """每條連線都會呼叫；但 DDL、seed、migration 每個 process 對同一顆 DB 只跑一次。

    原因：Python sqlite3 對任何 DML（含被 IGNORE 的 INSERT）都會隱式開寫入交易；
    Admin 5 秒輪詢 + SSE + 站點手機同時在跑時，每條連線都寫會搶 SQLite 單一寫鎖。
    hot path 只保留純 SELECT 的 legacy assignee 對應（通常零筆）。
    """
    key = _schema_key()
    if key not in _migrated:
        _migrate(conn)
        _migrated.add(key)
    _backfill_assignee_ids(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    for stmt in DDL:
        conn.execute(_ddl_for_dialect(stmt))
    # Multiple requests can enter schema setup together on a fresh database.
    # Seed each row idempotently instead of doing a racy count-then-insert.
    ts = now_iso()
    seed_sql = (
        "INSERT OR IGNORE INTO ops_people(group_name, name, active, created_at) VALUES (?,?,1,?)"
        if dialect() == "sqlite"
        else "INSERT INTO ops_people(group_name, name, active, created_at) VALUES (%s,%s,1,%s) "
             "ON CONFLICT(name) DO NOTHING"
    )
    conn.executemany(seed_sql, [(g, n, ts) for g, n in DEFAULT_PEOPLE])
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO ops_settings(key, value) VALUES (?,?)", (k, v))
    for kind in ("cleaning", "repair"):
        name_key, id_key = f"default_assignee_{kind}", f"default_assignee_{kind}_id"
        legacy = conn.execute("SELECT value FROM ops_settings WHERE key=?", (name_key,)).fetchone()
        stable = conn.execute("SELECT value FROM ops_settings WHERE key=?", (id_key,)).fetchone()
        if legacy and legacy[0] and (not stable or not stable[0]):
            matches = conn.execute("SELECT id FROM ops_people WHERE name=?", (legacy[0],)).fetchall()
            if len(matches) == 1:
                conn.execute("UPDATE ops_settings SET value=? WHERE key=?",
                             (str(matches[0][0]), id_key))
    # Phase 3 additive SQLite migration；既有 Demo DB 不需清除或重建。
    if dialect() == "sqlite":
        for table, columns in {
            "task_photos": {"actor_id": "INTEGER", "actor_name": "TEXT", "actor_role": "TEXT"},
            "notification_log": {"actor_id": "INTEGER", "actor_name": "TEXT", "actor_role": "TEXT"},
        }.items():
            existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for name, typ in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
        # `by` 是 Phase 2 的顯示快照；保留相容並補到一致的 actor contract。
        conn.execute("UPDATE task_photos SET actor_name=by WHERE actor_name IS NULL AND by IS NOT NULL")


def _backfill_assignee_ids(conn) -> None:
    """Phase 4 additive backfill：只有 name 唯一對應 People 時才寫 stable id。

    無法對應的 legacy assignment 保留 name / NULL id，等 Admin 重新指派。
    每條連線都跑，但只有 SELECT；有 legacy 列才會寫入。
    """
    for task_id, assignee in conn.execute(
            "SELECT id, assignee FROM tasks"
            " WHERE assignee_id IS NULL AND assignee IS NOT NULL AND assignee<>''").fetchall():
        matches = conn.execute("SELECT id FROM ops_people WHERE name=?", (assignee,)).fetchall()
        if len(matches) == 1:
            conn.execute("UPDATE tasks SET assignee_id=? WHERE id=?", (matches[0][0], task_id))
        else:
            key = f"{task_id}:{assignee}"
            if key not in _warned_assignees:
                logger.warning(
                    "assignee migration skipped task_id=%s name=%r matches=%s; Admin must reassign",
                    task_id, assignee, len(matches))
                _warned_assignees.add(key)


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
                         status: str, detail: str, actor=None) -> dict:
    import ops_auth  # noqa: PLC0415
    aid, aname, arole = ops_auth.actor_values(actor)
    cur = conn.execute(
        "INSERT INTO notification_log(task_id, audience, channel, status, detail, at, actor_id, actor_name, actor_role)"
        " VALUES (?,?,?,?,?,?,?,?,?)", (task_id, audience, channel, status, detail, now_iso(), aid, aname, arole))
    return dict(conn.execute("SELECT * FROM notification_log WHERE id=?", (cur.lastrowid,)).fetchone())


def list_notification_log(conn, task_id: int) -> list[dict]:
    return rows(conn.execute("SELECT * FROM notification_log WHERE task_id=? ORDER BY id", (task_id,)))


def max_event_id(conn) -> int:
    return conn.execute("SELECT COALESCE(MAX(id), 0) FROM ops_events").fetchone()[0]


# ---------- fleet locks ----------

def get_locks(conn) -> dict:
    return {r["car"]: dict(r) for r in conn.execute("SELECT * FROM fleet_locks")}


def set_lock(conn, car: str, locked: bool, reason: str | None, by: str) -> dict:
    conn.execute("INSERT OR REPLACE INTO fleet_locks(car, locked, reason, by, at) VALUES (?,?,?,?,?)",
                 (car, int(locked), reason, by, now_iso()))
    return dict(conn.execute("SELECT * FROM fleet_locks WHERE car=?", (car,)).fetchone())


# ---------- task photos ----------

def add_task_photo(conn, task: dict, filename: str, by: str, actor=None) -> dict:
    import ops_auth  # noqa: PLC0415
    aid, aname, arole = ops_auth.actor_values(actor)
    cur = conn.execute(
        "INSERT INTO task_photos(task_id, case_id, car, filename, by, at, actor_id, actor_name, actor_role)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (task["id"], task.get("case_id"), task.get("car"), filename, by, now_iso(), aid, aname, arole))
    return dict(conn.execute("SELECT * FROM task_photos WHERE id=?", (cur.lastrowid,)).fetchone())


def list_task_photos(conn, task_id: int) -> list[dict]:
    return rows(conn.execute("SELECT * FROM task_photos WHERE task_id=? ORDER BY id", (task_id,)))


# ---------- 孤兒清理：任務被刪（Demo 重置）後，事件／已讀／發送紀錄／完工照跟著清 ----------

def purge_orphans(conn) -> dict:
    gone = [r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM ops_events WHERE task_id IS NOT NULL"
        "   AND task_id NOT IN (SELECT id FROM tasks)")]
    gone += [r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM task_photos WHERE task_id NOT IN (SELECT id FROM tasks)")]
    gone += [r[0] for r in conn.execute(
        "SELECT DISTINCT task_id FROM notification_log WHERE task_id NOT IN (SELECT id FROM tasks)")]
    gone = sorted(set(gone))
    photo_files = []
    for tid in gone:
        photo_files += [r[0] for r in conn.execute("SELECT filename FROM task_photos WHERE task_id=?", (tid,))]
        conn.execute("DELETE FROM event_reads WHERE event_id IN (SELECT id FROM ops_events WHERE task_id=?)", (tid,))
        conn.execute("DELETE FROM ops_events WHERE task_id=?", (tid,))
        conn.execute("DELETE FROM notification_log WHERE task_id=?", (tid,))
        conn.execute("DELETE FROM task_photos WHERE task_id=?", (tid,))
    return {"task_ids": gone, "photo_files": photo_files}


def photo_count(conn, task_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM task_photos WHERE task_id=?", (task_id,)).fetchone()[0]


def has_assignee_event(conn, task_id: int) -> bool:
    return conn.execute("SELECT 1 FROM task_events WHERE task_id=? AND event='assignee'", (task_id,)).fetchone() is not None


def add_audit(conn, action: str, resource: str, resource_id=None, detail: str | None = None,
              actor=None) -> dict:
    import ops_auth  # noqa: PLC0415
    aid, aname, arole = ops_auth.actor_values(actor)
    cur = conn.execute(
        "INSERT INTO ops_audit_log(at, actor_id, actor_name, actor_role, action, resource, resource_id, detail)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (now_iso(), aid, aname, arole, action, resource,
         None if resource_id is None else str(resource_id), detail))
    return dict(conn.execute("SELECT * FROM ops_audit_log WHERE id=?", (cur.lastrowid,)).fetchone())
