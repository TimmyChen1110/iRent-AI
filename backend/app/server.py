#!/usr/bin/env python3
"""iRent 車況監理台 — Server 版。

與單檔版（irent-review-dashboard.html）同一套 UI，多了：
  - 複核決策存 SQLite，全隊共享（前端每 5 秒自動同步）
  - 照片由 server 供圖（頁面輕、可看原圖）
  - 資料直接讀 pipeline/ 的實測結果（POST /api/reload 可熱更新）
  - 「AI 重判」按鈕：現場呼叫 Gemini 重新判定該案（需 環節二/.env 的 GEMINI_API_KEY）

啟動：
  pip3 install -r backend/requirements.txt
  cd backend/app
  uvicorn server:app --host 0.0.0.0 --port 8000
  → 本機開 http://localhost:8000 ；隊友連 http://<你的區網IP>:8000

注意：資料含真實車牌照片，僅限 localhost / 隊內區網，勿部署公網。
"""
import base64
import io
import json
import os
import sqlite3
import sys
import tempfile
import threading
import urllib.request
import uuid
from collections import OrderedDict
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from PIL import Image, ImageOps
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(PIPE))
from pairs_io import load_pairs  # noqa: E402

import paths  # noqa: E402  執行期可設定的路徑與金鑰檢查
from build_dashboard import build_cases, build_f2cases, car_model_block  # noqa: E402
from results_config import FINAL_RESULTS, INTERIOR_RESULTS  # noqa: E402

DB_PATH = paths.DB_PATH

app = FastAPI(
    title="iRent 車況監理台",
    # 預設關閉；本機開發設 IRENT_ENABLE_DOCS=1 開啟（見 app/paths.py）
    docs_url="/docs" if paths.DOCS_ENABLED else None,
    redoc_url="/redoc" if paths.DOCS_ENABLED else None,
    openapi_url="/openapi.json" if paths.DOCS_ENABLED else None,
)

# ---------- 服務化（複核介面 API + 判讀 API；規格見各模組檔頭） ----------
from prompt_manifest import assert_frozen  # noqa: E402
assert_frozen()   # Prompt 凍結檢查：hash 不符即拒絕啟動（服務化規格 §6）

from inspections_api import router as inspections_router  # noqa: E402
from review_api import router as review_router  # noqa: E402
app.include_router(review_router)
app.include_router(inspections_router)


# ---------- 決策 DB（全隊共享） ----------
# decisions      : 複核狀態（後台 UI 用，一案一列，可覆蓋）
# decision_events: ★ 訓練標籤存底（append-only，永不覆蓋）
#   每一次人工裁決都是一筆「AI 判定 vs 人工真值」的對照——稽核員本來就要看這些
#   照片，所以這批標籤的邊際成本是零。累積數月後即為訓練 CV 模型的資料集，
#   `export_training_labels.py` 可直接匯出成標準格式。
#   刻意 append-only：改判、反覆裁決的過程本身就是有價值的訊號（例如同一案件
#   先 confirm 後改 reject，代表這是難例），覆蓋掉就永遠救不回來。
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS decisions("
                 "case_id TEXT PRIMARY KEY, decision TEXT, decided_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS live_cases("
                 "case_id TEXT PRIMARY KEY, created_at TEXT, data TEXT)")
    conn.execute("""CREATE TABLE IF NOT EXISTS decision_events(
                 event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
                 case_id    TEXT NOT NULL,
                 decided_at TEXT NOT NULL,
                 decision   TEXT NOT NULL,      -- confirm | reject | retake
                 mode       TEXT,               -- pair | interior
                 source     TEXT,               -- dataset | live
                 label      INTEGER,            -- 人工真值：1=有車損/髒汙 0=無 NULL=補件不表態
                 ai_found   INTEGER,            -- AI 判定：1/0（與 label 不同即為 AI 判錯）
                 agreed     INTEGER,            -- label==ai_found
                 ai_level   TEXT,               -- P1/P2/P3
                 ai_conf    REAL,               -- 最高信心
                 photos     TEXT,               -- JSON：照片絕對路徑（訓練時據此讀圖）
                 assessment TEXT,               -- JSON：AI 完整判定（含理由）
                 boxes      TEXT,               -- JSON：AI 標註框 box_2d
                 note       TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_case ON decision_events(case_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ev_time ON decision_events(decided_at)")
    # 整備任務（環節三）：confirm 裁決自動建立，UNIQUE(case_id, task_type) 保證重複 confirm 不重複開單。
    # notification_status 為通知管道預留欄位（LINE/簡訊尚未接入，永遠是 not_sent，UI 不得宣稱已通知）。
    conn.execute("""CREATE TABLE IF NOT EXISTS tasks(
                 id         INTEGER PRIMARY KEY AUTOINCREMENT,
                 case_id    TEXT NOT NULL,
                 task_type  TEXT NOT NULL,      -- repair | cleaning
                 car        TEXT,
                 title      TEXT NOT NULL,
                 description TEXT,
                 priority   TEXT,               -- P1 | P2 | P3（沿用案件分級）
                 assignee   TEXT,
                 status     TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | completed | cancelled
                 notification_status TEXT NOT NULL DEFAULT 'not_sent',
                 created_at TEXT NOT NULL,
                 updated_at TEXT NOT NULL,
                 resolved_at TEXT,
                 UNIQUE(case_id, task_type))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS task_events(
                 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                 task_id  INTEGER NOT NULL,
                 at       TEXT NOT NULL,
                 event    TEXT NOT NULL,        -- created | status | assignee | reopened | cancelled
                 detail   TEXT)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_case ON tasks(case_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tev_task ON task_events(task_id)")
    return conn


class Decision(BaseModel):
    case_id: str
    decision: str  # confirm | reject | retake
    note: str | None = None      # 稽核員備註（難例說明，訓練時是很有用的訊號）


# 人工裁決 → 訓練標籤。retake（要求補件）不表態，label 留 NULL 不進訓練集。
_LABEL_OF = {"confirm": 1, "reject": 0, "retake": None}


def _case_snapshot(case_id: str) -> dict:
    """從當前資料組出這個案件的訓練標籤快照（照片絕對路徑、AI 判定、標註框）。

    照片存【絕對路徑】而非 base64：資料集照片本來就在 repo 裡，存路徑省空間；
    現場實測(LIVE)案件的照片只在記憶體，故另存縮圖 base64 於 live_cases。
    """
    # 1) 資料集配對案件
    pair = next((p for p in _pairs if f'{p["car"]}-{p["angle"]}' == case_id), None)
    if pair:
        a = _final_assessments().get(case_id)
        ann = _annotations().get(case_id) or {}
        dmgs = (a or {}).get("damages") or []
        return {
            "mode": "pair", "source": "dataset",
            "ai_found": int(bool((a or {}).get("new_damage_found"))) if a else None,
            "ai_level": _triage_level(a) if a else None,
            "ai_conf": max((d.get("confidence") or 0 for d in dmgs), default=None) if dmgs else None,
            "photos": {"pickup": pair["pickup"], "return": pair["return"],
                       "return_alt": pair.get("return_alt")},
            "assessment": a,
            "boxes": ann.get("findings") or [],
        }
    # 2) 現場實測案件（照片縮圖存在 live_cases）
    with db() as conn:
        row = conn.execute("SELECT data FROM live_cases WHERE case_id=?", (case_id,)).fetchone()
    if row:
        payload = json.loads(row[0])
        case, ann = payload["case"], payload.get("ann") or {}
        a = case.get("assessment") or {}
        is_f2 = bool(case.get("f2"))
        return {
            "mode": "interior" if is_f2 else "pair", "source": "live",
            "ai_found": int(a.get("level") == "髒汙") if is_f2 else int(bool(a.get("new_damage_found"))),
            "ai_level": case.get("level"),
            "ai_conf": a.get("confidence") if is_f2 else
                       max((d.get("confidence") or 0 for d in (a.get("damages") or [])), default=None),
            "photos": {"stored_in": "live_cases", "case_id": case_id},
            "assessment": a,
            "boxes": ann.get("findings") or [],
        }
    # 3) 車內照案件（F2-<car>-<type>）
    if case_id.startswith("F2-"):
        for r in json.loads(INTERIOR_RESULTS.read_text())["results"]:
            if f'F2-{r["car"]}-{r["type"]}' == case_id:
                a = r["assessment"]
                return {
                    "mode": "interior", "source": "dataset",
                    "ai_found": int(a["level"] == "髒汙"),
                    "ai_level": "P1" if a["level"] == "髒汙" else "P3",
                    "ai_conf": a.get("confidence"),
                    "photos": {"photo": str(PIPE / "interior_photos" / r["file"])},
                    "assessment": a,
                    "boxes": (_annotations().get(case_id) or {}).get("findings") or [],
                }
    # 4) 歸還期間車損案件（CHAIN-<car>-<angle>）
    if case_id.startswith("CHAIN-"):
        from build_dashboard import build_chain_cases_data
        c_case = next((c for c in build_chain_cases_data() if c["id"] == case_id), None)
        if c_case:
            a = c_case.get("assessment")
            evaluated = (c_case.get("evaluation_status") or "evaluated") == "evaluated" and a
            # 信心只能來自模型輸出；沒有就是 None（曾硬編 0.88 污染訓練標籤，勿回退）
            conf = max((d.get("confidence") or 0 for d in (a or {}).get("damages") or []),
                       default=None) if evaluated else None
            return {
                "mode": "chain", "source": "dataset",
                "ai_found": int(bool(a.get("new_damage_found"))) if evaluated else None,
                "ai_level": c_case.get("level") if evaluated else None,
                "ai_conf": conf,
                "photos": {"pickup": c_case.get("pickup"), "return": c_case.get("return")},
                "assessment": a if evaluated else None,
                "boxes": [],
            }
    return {"mode": None, "source": None, "ai_found": None, "ai_level": None,
            "ai_conf": None, "photos": {}, "assessment": None, "boxes": []}


def _triage_level(a: dict) -> str:
    import judge_photos  # noqa: PLC0415  共用同一套 P1/P2/P3 規則，不重寫
    return judge_photos.triage(a)[0]


@lru_cache(maxsize=1)
def _final_assessments() -> dict:
    return {f'{r["car"]}-{r["angle"]}': r["assessment"]
            for r in json.loads(FINAL_RESULTS.read_text())["results"] if r.get("assessment")}


@lru_cache(maxsize=1)
def _annotations() -> dict:
    return json.loads((PIPE / "dashboard_annotations.json").read_text())


@app.get("/api/decisions")
def get_decisions():
    with db() as conn:
        return {r[0]: r[1] for r in conn.execute("SELECT case_id, decision FROM decisions")}


# ---------- 整備任務（環節三：confirm → Task → 指派 → 處理 → 完成） ----------
# 人工 confirm ＝「確認有車損／髒汙」，後續一定要有人去修／去清 → 自動開整備任務。
# reject / retake 不開單。任務內容直接引用 AI 判定原文（location/type/severity/理由），
# 讓整備人員不必回頭翻案件也知道要處理什麼。

_TASK_FLOW = {  # 最簡狀態機：待處理 → 處理中 → 已完成（可取消、可重啟；不做複雜 workflow）
    "pending": {"in_progress", "cancelled"},
    "in_progress": {"completed", "pending", "cancelled"},
    "completed": {"in_progress"},          # 誤按完成可重開；重開即清掉 resolved_at
    "cancelled": {"pending"},
}


def _case_car(case_id: str) -> str:
    """從 case_id 推車輛代號（顯示用，推不出來就原樣返回）。"""
    if case_id.startswith("LIVE-"):
        return "LIVE"
    # 車牌本身可含連字號（RDE-0160），一律去前綴後只切掉最後一段（方位/車內前後）
    for prefix in ("F2-", "CHAIN-"):
        if case_id.startswith(prefix):
            return case_id[len(prefix):].rsplit("-", 1)[0]   # "F2-RDE-0160-front" → "RDE-0160"
    return case_id.rsplit("-", 1)[0]   # "RCR-7661-左後" → "RCR-7661"


def _auto_task_spec(case_id: str, snap: dict) -> dict:
    """confirm 裁決 → 任務內容。車內案件開清潔單，其餘（借還比對／跨單鏈）開維修單。"""
    a = snap.get("assessment") or {}
    priority = snap.get("ai_level") if snap.get("ai_level") in ("P1", "P2", "P3") else "P2"
    if snap.get("mode") == "interior":
        issues = a.get("issues") or []
        score = a.get("score")
        desc = "人工確認車內髒汙，須清潔。"
        if issues:
            desc += "\nAI 盤點問題：" + "、".join(issues)
        if isinstance(score, (int, float)):
            desc += f"\nCleanliness Score：{score}/100"
        if a.get("reasoning"):
            desc += f"\nAI 判定理由：{a['reasoning']}"
        return {"task_type": "cleaning", "title": "車內清潔", "description": desc,
                "priority": priority}
    dmgs = a.get("damages") or []
    if dmgs:
        d0 = dmgs[0]
        title = f'{d0.get("location") or ""}{d0.get("type") or "車損"}維修'
        lines = [f'{d.get("location") or "—"}·{d.get("type") or "—"}·{d.get("severity") or "—"}'
                 f'（信心 {d.get("confidence")}）：{d.get("reasoning") or ""}' for d in dmgs]
        desc = "人工確認新增車損，須維修。\nAI 判定：\n" + "\n".join(lines)
    else:
        title = "車損維修"
        desc = "人工確認車損（AI 未偵測到，人工複核判定為有損），請現場確認維修範圍。"
    return {"task_type": "repair", "title": title, "description": desc, "priority": priority}


def _task_row(conn, task_id: int) -> dict | None:
    cur = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
    row = cur.fetchone()
    if not row:
        return None
    t = dict(zip([c[0] for c in cur.description], row))
    t["events"] = [{"at": at, "event": ev, "detail": det} for at, ev, det in conn.execute(
        "SELECT at, event, detail FROM task_events WHERE task_id=? ORDER BY event_id", (task_id,))]
    return t


def _ensure_task(conn, case_id: str, snap: dict, now: str) -> dict:
    """建立（或喚回）整備任務。冪等：同一 case + task_type 永遠只有一張單。"""
    spec = _auto_task_spec(case_id, snap)
    row = conn.execute("SELECT id, status FROM tasks WHERE case_id=? AND task_type=?",
                       (case_id, spec["task_type"])).fetchone()
    if row:
        tid, status = row
        if status == "cancelled":   # 先前 undo 取消過 → 再次 confirm 喚回為待處理
            conn.execute("UPDATE tasks SET status='pending', updated_at=?, resolved_at=NULL"
                         " WHERE id=?", (now, tid))
            conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                         (tid, now, "reopened", "案件再次確認，已取消任務重啟為待處理"))
    else:
        cur = conn.execute(
            "INSERT INTO tasks(case_id, task_type, car, title, description, priority,"
            " status, created_at, updated_at) VALUES (?,?,?,?,?,?, 'pending', ?, ?)",
            (case_id, spec["task_type"], _case_car(case_id), spec["title"],
             spec["description"], spec["priority"], now, now))
        tid = cur.lastrowid
        conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                     (tid, now, "created", f"由案件 {case_id} 人工確認自動建立"))
    return _task_row(conn, tid)


# ---------- Demo Mode（DEMO_MODE=true 時啟用；只影響 UI 排序與 demo helper） ----------
# 鐵則：DEMO_MODE 不得改變 AI 結果、Task 邏輯、Notification 邏輯、Metrics。
# 它只提供：demo 案例快速入口、上台前健檢、將兩個示範案例重置回
# 「AI 已判定、尚未人工 confirm」的安全 reset。

DEMO_CASE_DAMAGE = "RCR-7661-左後"       # 新車損示範：P1、三處損傷、標註框準、真實索賠案
DEMO_CASE_CLEANING = "F2-RDE-0160-front"  # 車內髒汙示範：P1、遺留寶特瓶、有位置框
DEMO_CASE_IDS = (DEMO_CASE_DAMAGE, DEMO_CASE_CLEANING)


def _demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").lower() in ("1", "true", "yes")


def _require_demo():
    if not _demo_mode():   # 非 demo 環境不得暴露清資料 endpoint
        raise HTTPException(404)


@app.get("/api/demo/health")
def demo_health():
    """上台前健檢：零 AI 呼叫、零 webhook 發送，只確認東西都在。"""
    _require_demo()
    try:
        with db() as conn:
            conn.execute("SELECT 1").fetchone()
        db_ok = True
    except Exception:
        db_ok = False

    def case_ok(cid):
        try:
            return _case_snapshot(cid)["mode"] is not None
        except Exception:
            return False

    return {
        "server": "ok",
        "database": "ok" if db_ok else "error",
        "notification_configured": bool(_webhook_url()),
        "demo_damage_case": case_ok(DEMO_CASE_DAMAGE),
        "demo_cleaning_case": case_ok(DEMO_CASE_CLEANING),
        "demo_cases": {"damage": DEMO_CASE_DAMAGE, "cleaning": DEMO_CASE_CLEANING},
    }


@app.post("/api/demo/reset")
def demo_reset():
    """把兩個示範案例重置回「AI 已判定、尚未人工 confirm」。

    只動這兩個 case 的 decisions 與 tasks/task_events（任務刪除後，下次 confirm
    會建立全新任務、notification_status 從頭開始 → webhook 重新發送）。
    不動：AI 評測結果、照片、chain 資料、離線指標、其他案件、
    decision_events（訓練標籤 append-only，僅補記 undo 事件）。
    """
    _require_demo()
    now = datetime.now().isoformat(timespec="seconds")
    reset = []
    with db() as conn:
        for cid in DEMO_CASE_IDS:
            had = conn.execute("SELECT 1 FROM decisions WHERE case_id=?", (cid,)).fetchone()
            if had:
                conn.execute("DELETE FROM decisions WHERE case_id=?", (cid,))
                conn.execute("INSERT INTO decision_events(case_id, decided_at, decision, note)"
                             " VALUES (?,?,?,?)", (cid, now, "undo", "Demo 重置"))
            tids = [r[0] for r in conn.execute(
                "SELECT id FROM tasks WHERE case_id=?", (cid,)).fetchall()]
            for tid in tids:
                conn.execute("DELETE FROM task_events WHERE task_id=?", (tid,))
                conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
            if had or tids:
                reset.append(cid)
    return {"ok": True, "reset_cases": reset,
            "note": "示範案例已回到「AI 已判定、尚未人工確認」狀態"}


# ---------- 即時通知（Generic Webhook） ----------
# 設計原則：AI 不直接觸發營運通知——人工 confirm、task 建立成功之後才發。
# Task 是主業務資料，通知是 side effect：webhook 掛掉/超時/未設定，
# 一律只反映在 tasks.notification_status，絕不影響 confirm 與 task 建立。
# 管道：環境變數 NOTIFICATION_WEBHOOK_URL（HTTP POST JSON）。URL 屬機密，
# 不進版控、不進 log、不進 task_events。

NOTIFY_TIMEOUT_S = 4   # 短 timeout：外部端點掛掉不能拖住 Demo


def _webhook_url() -> str | None:
    return os.environ.get("NOTIFICATION_WEBHOOK_URL") or None


def build_notification_payload(task: dict) -> dict:
    """組通知 payload。內容全部來自既存 task 資料（已引用 AI 判定原文），
    這一步零 AI 呼叫。與發送邏輯分離，日後要換 LINE/Slack 只改 send 端。"""
    return {
        "event": "task_created",
        "case_id": task["case_id"],
        "task_id": task["id"],
        "task_type": task["task_type"],
        "priority": task.get("priority"),
        "car": task.get("car"),
        "title": task["title"],
        "description": task.get("description"),
        "assignee": task.get("assignee"),
        "status": task["status"],
        "created_at": task["created_at"],
    }


def send_notification(payload: dict) -> bool:
    """對 NOTIFICATION_WEBHOOK_URL 發 HTTP POST。呼叫前 caller 需確認 URL 存在。
    回傳是否 2xx；例外由 caller 接住。測試一律 monkeypatch 本函式，不打真網路。"""
    req = urllib.request.Request(
        _webhook_url(), data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=NOTIFY_TIMEOUT_S) as resp:
        return 200 <= resp.status < 300


def _notify_task(task: dict) -> dict:
    """嘗試對一張 task 發通知並更新 notification_status，回傳最新 task。

    - 已 sent：冪等，不重發（confirm→undo→confirm 不會轟炸收件端）
    - 無 webhook 設定：skipped（UI 顯示「通知管道未設定」，不算失敗）
    - 發送失敗：failed（Task Card 可重新發送）
    必須在 DB transaction 之外呼叫——HTTP 不能佔著資料庫。
    """
    if task.get("notification_status") == "sent":
        return task
    if not _webhook_url():
        status, detail = "skipped", "通知管道未設定（NOTIFICATION_WEBHOOK_URL），未發送"
    else:
        try:
            ok = send_notification(build_notification_payload(task))
        except Exception:          # timeout / DNS / refused / 5xx——一律不外洩 URL 與細節
            ok = False
        status = "sent" if ok else "failed"
        detail = "通知已送出（webhook）" if ok else "通知發送失敗，可於整備看板重新發送"
        print(f"notification {status} (task #{task['id']})", file=sys.stderr)
    try:
        now = datetime.now().isoformat(timespec="seconds")
        with db() as conn:
            conn.execute("UPDATE tasks SET notification_status=?, updated_at=? WHERE id=?",
                         (status, now, task["id"]))
            conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                         (task["id"], now, "notify", detail))
            return _task_row(conn, task["id"])
    except Exception:              # 連狀態都寫不進去也不能拖垮 confirm
        task["notification_status"] = status
        return task


@app.post("/api/decision")
def post_decision(d: Decision):
    """記錄人工裁決。同時寫入兩張表：
      decisions       — 複核狀態（可覆蓋，後台 UI 讀這張）
      decision_events — 訓練標籤存底（append-only，永不覆蓋）
    後者是把「稽核員本來就要做的複核」直接轉成免費的 ground truth。
    confirm 另自動建立整備任務（tasks 表），回傳於 task 欄位。
    """
    if d.decision not in _LABEL_OF:
        raise HTTPException(400, "decision 必須是 confirm / reject / retake")
    now = datetime.now().isoformat(timespec="seconds")
    try:
        snap = _case_snapshot(d.case_id)
    except Exception:  # 快照失敗不能擋住複核作業——標籤是副產品，複核才是主流程
        snap = {"mode": None, "source": None, "ai_found": None, "ai_level": None,
                "ai_conf": None, "photos": {}, "assessment": None, "boxes": []}
    label = _LABEL_OF[d.decision]
    ai_found = snap["ai_found"]
    agreed = None if (label is None or ai_found is None) else int(label == ai_found)
    task = None
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?)",
                     (d.case_id, d.decision, now))
        conn.execute(
            "INSERT INTO decision_events(case_id, decided_at, decision, mode, source, label,"
            " ai_found, agreed, ai_level, ai_conf, photos, assessment, boxes, note)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (d.case_id, now, d.decision, snap["mode"], snap["source"], label,
             ai_found, agreed, snap["ai_level"], snap["ai_conf"],
             json.dumps(snap["photos"], ensure_ascii=False),
             json.dumps(snap["assessment"], ensure_ascii=False) if snap["assessment"] else None,
             json.dumps(snap["boxes"], ensure_ascii=False),
             (d.note or None)))
        if d.decision == "confirm":
            try:
                task = _ensure_task(conn, d.case_id, snap, now)
            except Exception:   # 開單失敗不能擋住裁決本身
                task = None
    # 通知在 transaction 之外：task 已落地才發，失敗只反映在 notification_status
    if task:
        task = _notify_task(task)
    return {"ok": True, "labeled": label is not None, "agreed": agreed, "task": task}


@app.delete("/api/decision/{case_id}")
def delete_decision(case_id: str):
    """復原複核狀態。刻意【不刪】decision_events——「先判了又收回」本身是難例訊號，
    而且訓練標籤一旦刪掉就永遠救不回來。
    連帶把該案【尚未開工】的整備任務取消（只動 pending；已在處理中的工作不因複核反悔而消失）。"""
    now = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("DELETE FROM decisions WHERE case_id=?", (case_id,))
        conn.execute("INSERT INTO decision_events(case_id, decided_at, decision, note)"
                     " VALUES (?,?,?,?)", (case_id, now, "undo", "使用者復原前次裁決"))
        for (tid,) in conn.execute(
                "SELECT id FROM tasks WHERE case_id=? AND status='pending'", (case_id,)).fetchall():
            conn.execute("UPDATE tasks SET status='cancelled', updated_at=? WHERE id=?", (now, tid))
            conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                         (tid, now, "cancelled", "來源案件裁決被復原，任務自動取消"))
    return {"ok": True}


# ---------- Task API（整備看板） ----------

class TaskUpdate(BaseModel):
    assignee: str | None = None
    status: str | None = None


@app.get("/api/tasks")
def get_tasks(status: str | None = None, task_type: str | None = None,
              priority: str | None = None):
    """任務清單（含歷程）。可用 status / task_type / priority 篩選。"""
    conds, params = [], []
    for col, v in (("status", status), ("task_type", task_type), ("priority", priority)):
        if v:
            conds.append(f"{col}=?")
            params.append(v)
    where = (" WHERE " + " AND ".join(conds)) if conds else ""
    with db() as conn:
        ids = [r[0] for r in conn.execute(
            "SELECT id FROM tasks" + where +
            " ORDER BY CASE status WHEN 'pending' THEN 0 WHEN 'in_progress' THEN 1"
            " WHEN 'completed' THEN 2 ELSE 3 END, priority, created_at DESC", params)]
        return {"tasks": [_task_row(conn, i) for i in ids]}


@app.post("/api/tasks/{task_id}/notify")
def retry_notify(task_id: int):
    """重新發送通知。已 sent 者冪等直接回傳；failed / skipped / not_sent 皆可再試。"""
    with db() as conn:
        task = _task_row(conn, task_id)
    if not task:
        raise HTTPException(404, f"找不到任務 #{task_id}")
    return _notify_task(task)


@app.patch("/api/tasks/{task_id}")
def patch_task(task_id: int, upd: TaskUpdate):
    """更新任務：指派 assignee、或依狀態機推進 status。
    completed 自動寫 resolved_at；離開 completed 自動清掉。"""
    now = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        row = conn.execute("SELECT status, assignee FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"找不到任務 #{task_id}")
        cur_status, cur_assignee = row
        if upd.status is not None:
            if upd.status not in _TASK_FLOW:
                raise HTTPException(400, "status 必須是 pending / in_progress / completed / cancelled")
            if upd.status != cur_status and upd.status not in _TASK_FLOW[cur_status]:
                raise HTTPException(400, f"狀態不可由 {cur_status} 直接變更為 {upd.status}")
            if upd.status != cur_status:
                resolved = now if upd.status == "completed" else None
                conn.execute("UPDATE tasks SET status=?, resolved_at=?, updated_at=? WHERE id=?",
                             (upd.status, resolved, now, task_id))
                conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                             (task_id, now, "status", f"{cur_status} → {upd.status}"))
        if upd.assignee is not None and upd.assignee != cur_assignee:
            conn.execute("UPDATE tasks SET assignee=?, updated_at=? WHERE id=?",
                         (upd.assignee or None, now, task_id))
            conn.execute("INSERT INTO task_events(task_id, at, event, detail) VALUES (?,?,?,?)",
                         (task_id, now, "assignee", f"指派給 {upd.assignee or '（未指派）'}"))
        return _task_row(conn, task_id)


@app.get("/api/labels/stats")
def label_stats():
    """訓練標籤累積現況——讓「複核 = 在攢資料集」這件事看得見。

    可判定標籤 = decision 為 confirm/reject 者（retake 補件不表態、undo 不計）。
    每個 case_id 取【最後一次】裁決為準，但歷史事件全部保留。
    """
    with db() as conn:
        rows = conn.execute(
            "SELECT case_id, decision, mode, source, label, ai_found, agreed, decided_at"
            " FROM decision_events WHERE label IS NOT NULL ORDER BY event_id").fetchall()
        total_events = conn.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0]
    latest = {}
    for case_id, dec, mode, source, label, ai_found, agreed, at in rows:
        latest[case_id] = {"decision": dec, "mode": mode, "source": source,
                           "label": label, "ai_found": ai_found, "agreed": agreed, "at": at}
    vals = list(latest.values())
    pos = sum(1 for v in vals if v["label"] == 1)
    judged = [v for v in vals if v["agreed"] is not None]
    agree = sum(v["agreed"] for v in judged)
    by_mode = {}
    for v in vals:
        m = v["mode"] or "unknown"
        b = by_mode.setdefault(m, {"total": 0, "positive": 0})
        b["total"] += 1
        b["positive"] += (v["label"] == 1)
    return {
        "labeled_cases": len(vals),          # 可用於訓練的標籤數（去重後）
        "positive": pos, "negative": len(vals) - pos,
        "total_events": total_events,        # 含 retake / undo 的完整歷史
        "ai_agreement": round(agree / len(judged), 4) if judged else None,
        "ai_disagreed": len(judged) - agree,  # ★ AI 判錯的案例——最有訓練價值
        "by_mode": by_mode,
        "latest_at": max((v["at"] for v in vals), default=None),
    }


# ---------- 照片（僅供白名單內的檔案，防路徑穿越） ----------
_pairs = load_pairs()
PAIR_PHOTOS = {Path(p[k]).name: p[k] for p in _pairs for k in ("pickup", "return")}
INTERIOR_DIR = PIPE / "interior_photos"
INTERIOR_FILES = {f.name for f in INTERIOR_DIR.iterdir()} if INTERIOR_DIR.exists() else set()


@app.get("/photos/pair/{name}")
def pair_photo(name: str):
    p = PAIR_PHOTOS.get(name)
    if not p or not Path(p).exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/photos/interior/{name}")
def interior_photo(name: str):
    if name not in INTERIOR_FILES:
        raise HTTPException(404)
    return FileResponse(INTERIOR_DIR / name)


# ---------- 頁面（server 端組裝，資料快取、可熱更新） ----------
_page_cache = {"html": None}
_page_lock = threading.Lock()


def render_page(force=False):
    with _page_lock:
        if _page_cache["html"] and not force:
            return _page_cache["html"]
        shell = (HERE / "dashboard_shell.html").read_text()
        three = (HERE / "three.min.js").read_text()
        import importlib
        import build_dashboard
        importlib.reload(build_dashboard)
        blocks = [
            "const SERVER_MODE=true;",
            f"const DEMO_MODE={'true' if _demo_mode() else 'false'};",
            "const DEMO_CASES=" + json.dumps({"damage": DEMO_CASE_DAMAGE,
                                              "cleaning": DEMO_CASE_CLEANING}) + ";",
            "const CASES=" + json.dumps(build_dashboard.build_cases(embed=False), ensure_ascii=False) + ";",
            "const F2CASES=" + json.dumps(build_dashboard.build_f2cases(embed=False), ensure_ascii=False) + ";",
            "const CHAINCASES=" + json.dumps(build_dashboard.build_chain_cases_data(), ensure_ascii=False) + ";",
            "const ANNOTATIONS=" + json.dumps(build_dashboard.load_annotations(), ensure_ascii=False) + ";",
            "const PASSPORT_DATA=" + (PIPE / "passports.json").read_text() + ";",
        ]
        html = (shell
                .replace("<!--DATA-->", "<script>\n" + "\n".join(blocks) + "\n</script>")
                .replace("<!--THREE-->", "<script>" + three + "</script>")
                .replace("<!--CARMODEL-->", build_dashboard.car_model_block()))
        _page_cache["html"] = html
        return html


@app.get("/", response_class=HTMLResponse)
def index():
    return render_page()


# ---------- 環節三 整備中心前端（frontend-admin build 產物，SPA） ----------
OPS_STATIC = HERE / "static" / "ops"


@app.get("/ops")
@app.get("/ops/{path:path}")
def ops_


INI_API_KEY，免費層約 10 秒） ----------
# 判定標準不在此重寫：一律走 judge_photos.judge_pair()（Quality Gate → Flash 快篩
# → 臨界升級 Pro 多數決 → box_2d 標註），與現場實測、離線評測完全同一套規則。

_rejudge_lock = threading.Lock()
_gclient = None


def _client():
    """單例 Gemini client。注意必須保留對 Client 物件的引用——
    臨時物件（get_client().models...）會被 GC 連帶關閉底層 httpx 連線。"""
    global _gclient
    if _gclient is None:
        from run_eval_gemini import get_client  # noqa: PLC0415
        _gclient = get_client()
    return _gclient


def _require_key():
    """呼叫 Gemini 前的統一守門：找不到 key（環境變數 / .env / 舊 .gemini_key）就 503。"""
    try:
        from run_eval_gemini import find_key  # noqa: PLC0415
        ok = find_key() is not None
    except ImportError:  # google-genai 未安裝，同樣無法呼叫
        ok = False
    if not ok:
        raise HTTPException(503, "此機器沒有 Gemini API key：請在 環節二/.env 設定 GEMINI_API_KEY")


# ---------- 判定後加值：估價分流（S6）＋ 多對象文案（S7） ----------
# 這兩層【不碰判定準確率】——它們吃的是判定結果，不是照片。
# S6 純規則零 API（損傷類型×尺寸×材質 → 維修動作 + 級距 + 估價區間 + 值不值得追）。
# S7 一次文字模型呼叫，產出用戶／客服／派工單三種語氣，並做程式面 grounding 查核。
#
# 為何預設只開 S6：S6 零成本必開；S7 多一次 API 呼叫，現場 demo 以速度優先，
# 由前端「產生通知文案」按鈕按需觸發（POST /api/notify）。

def enrich(result: dict) -> dict:
    """對判定結果補上估價與處置建議（S6）。純程式、零 API、失敗不影響判定。"""
    try:
        import disposition  # noqa: PLC0415
        final = result.get("final") or {}
        if not final.get("new_damage_found"):
            return result
        from diff_new_damage import panel_of  # noqa: PLC0415
        st4 = (result.get("stage4") or {}).get("damages") or []
        weighted = {d.get("location"): d.get("weighted_confidence") for d in st4}
        angle = result.get("angle")
        priced, total_lo, total_hi = [], 0, 0
        for d in final.get("damages") or []:
            # 現行判定 schema 沒有 panel 欄位，只有自由文字 location。
            # 沒有 panel 就查不到材質，會讓塑膠保桿的刮痕落進「鈑金整片烤漆」級距C
            # （5,000–15,000）而非正確的「保桿修補烤漆」級距B（1,500–5,000）——
            # 現場 demo 報出三倍價會很難看，故一律先從 location 文字推分區。
            panel = d.get("panel") or panel_of(d, angle)
            p = disposition.assess(
                d, panel=panel,
                weighted_confidence=weighted.get(d.get("location"), d.get("confidence")))
            p["location"] = d.get("location")
            priced.append(p)
            if p.get("claimable"):
                total_lo += p["estimate_twd"][0]
                total_hi += p["estimate_twd"][1]
        result["pricing"] = {
            "items": priced,
            "total_estimate_twd": [total_lo, total_hi],
            "claimable_count": sum(1 for p in priced if p.get("claimable")),
            "waived_count": sum(1 for p in priced
                                if p.get("disposition") == "waive_not_worth_claiming"),
            "note": "級距示意區間，實際以維修廠估價為準",
        }
    except Exception as e:                     # 加值失敗不能拖垮判定
        result["pricing"] = {"error": str(e)[:120]}
    return result


class NotifyReq(BaseModel):
    judge_id: str | None = None
    case_id: str | None = None


@app.post("/api/notify")
async def api_notify(req: NotifyReq):
    """S7：對已完成的判定產生用戶／客服／派工單三種文案（多一次 API 呼叫）。"""
    _require_key()
    import notify  # noqa: PLC0415

    if req.judge_id:
        with _judges_lock:
            entry = _judges.get(req.judge_id)
        if not entry:
            raise HTTPException(410, "判定結果已過期，請重新判定")
        result = entry["result"]
    elif req.case_id:
        result = _CASE_JUDGE_CACHE.get(req.case_id)
        if not result:
            raise HTTPException(404, "找不到該案件的判定結果，請先執行 AI 重判")
    else:
        raise HTTPException(400, "需要 judge_id 或 case_id")

    final = result.get("final") or {}
    case = {
        "case_id": req.judge_id or req.case_id,
        "new_damage_found": final.get("new_damage_found", False),
        "damages": [{**d, **{k: v for k, v in (p or {}).items()
                             if k in ("repair_action", "band", "estimate_twd", "disposition")}}
                    for d, p in zip(final.get("damages") or [],
                                    (result.get("pricing") or {}).get("items") or [{}] * 99)],
        "coverage": result.get("coverage"),
        "level": result.get("level"), "kind": result.get("kind"),
    }
    if result.get("mode") == "interior":
        case["interior"] = {"level": final.get("level"),
                            "findings": final.get("findings") or []}

    def run():
        with _rejudge_lock:
            return notify.generate(case, client=_client())

    try:
        return await run_in_threadpool(run)
    except Exception as e:
        raise HTTPException(502, f"文案生成失敗：{str(e)[:200]}")


# AI 重判結果暫存（供 /api/notify 以 case_id 取用）
_CASE_JUDGE_CACHE: dict[str, dict] = {}


class RejudgeReq(BaseModel):
    case_id: str


@app.post("/api/rejudge")
async def rejudge(req: RejudgeReq):
    """對資料集內既有案件重跑判定。

    走與現場實測、離線評測完全相同的鏈路（judge_photos.judge_pair）——
    曾經這裡自帶一套簡化 prompt（4 條準則 vs 正式的 8 條）、不跑級聯、不回
    box_2d，導致同一案件「AI 重判」的結果與 Dashboard 原判定不一致，
    而原因是 prompt 不同、不是模型不穩，無法向評審解釋。
    """
    _require_key()
    pair = next((p for p in _pairs if f'{p["car"]}-{p["angle"]}' == req.case_id), None)
    if not pair:
        raise HTTPException(404, f"找不到案件 {req.case_id}（車內照不支援重判）")

    import judge_photos  # noqa: PLC0415  延遲載入

    def run():
        with _rejudge_lock:  # 免費層 RPM 低，一次一件（與現場實測共用鎖）
            # 資料集照片已知可讀，跳過 Quality Gate 直接判（gate 數值仍會回在結果內）
            return judge_photos.judge_pair(pair["pickup"], pair["return"],
                                           client=_client(), skip_gate=True,
                                           angle=pair["angle"])

    try:
        result, _img = await run_in_threadpool(run)
    except Exception as e:
        raise HTTPException(502, f"重判失敗：{str(e)[:200]}")

    final = result.get("final")
    if not final:
        raise HTTPException(502, "未取得有效判定結果")
    enrich(result)                      # S6 估價分流（零 API）
    _CASE_JUDGE_CACHE[req.case_id] = result   # 供 POST /api/notify 產文案
    # 標註框同步更新（box_2d 已隨判定取得，零額外 API），前端據此重畫疊加層
    ann = {"findings": [{"box_2d": d["box_2d"], "label": d["type"], "severity": d["severity"],
                         "confidence": d["confidence"],
                         "description": f'{d["location"]}：{d["reasoning"]}'}
                        for d in final["damages"] if len(d.get("box_2d") or []) == 4],
           "summary": ""}
    return {"case_id": req.case_id,
            "assessment": final,
            "level": result["level"], "kind": result["kind"],
            "cascade": result.get("cascade"),
            "annotation": ann,
            "pricing": result.get("pricing"),
            "elapsed_s": result.get("elapsed_s"),
            "judged_at": datetime.now().isoformat(timespec="seconds")}


# ---------- 現場實測：任意照片即時判定（POST /api/judge，multipart 上傳） ----------
ALLOWED_SUFFIX = {".jpg", ".jpeg", ".png", ".jfif", ".webp", ".heic", ".heif"}


async def _save_uploads(td, need):
    """上傳檔存進暫存目錄，回 (路徑 dict, 原始 bytes dict)。"""
    paths, raw = {}, {}
    for name, f in need:
        suffix = Path(f.filename or "").suffix.lower()
        p = Path(td) / (name + (suffix if suffix in ALLOWED_SUFFIX else ".jpg"))
        raw[name] = await f.read()
        p.write_bytes(raw[name])
        paths[name] = p
    return paths, raw


@app.post("/api/gate")
async def api_gate(mode: str = Form("pair"),
                   pickup: UploadFile | None = File(None),
                   ret: UploadFile | None = File(None),
                   interior: UploadFile | None = File(None)):
    """只跑 Quality Gate（純 CV、<1 秒、零 API）——前端先呼叫這支即時顯示品質檢核，
    通過才續打 /api/judge，讓「檢核→判定」有分段回饋。"""
    import judge_photos  # noqa: PLC0415
    need = [("pickup", pickup), ("ret", ret)] if mode == "pair" else [("interior", interior)]
    for name, f in need:
        if f is None:
            raise HTTPException(400, f"缺少 {name} 照片")
    with tempfile.TemporaryDirectory(prefix="irent-gate-") as td:
        saved, _ = await _save_uploads(td, need)   # 勿命名為 paths（遮蔽模組）
        try:
            names = {"pickup": "pickup", "ret": "return", "interior": "photo"}
            gates = judge_photos._run_gate({names[k]: p for k, p in saved.items()},
                                           interior=(mode != "pair"))
        except Exception as e:
            raise HTTPException(400, f"照片無法讀取：{str(e)[:120]}")
    return {"gate": gates, "gate_pass": all(g["pass"] for g in gates.values())}


def lan_ip() -> str:
    """取「手機掃碼連得到」的區網 IP。

    ⚠️ 不能用「UDP connect 8.8.8.8 看 getsockname」那招：開著 VPN 時
    預設路由走 tunnel（utun*），會回傳 10.x 之類的隧道位址，
    手機在 Wi-Fi/熱點上根本連不到——QR 掃了開不起來就是這個原因。
    改為優先掃實體網卡（en0/en1…）上的私有位址。
    """
    import socket  # noqa: PLC0415
    try:
        import psutil  # noqa: PLC0415
        addrs = psutil.net_if_addrs()
    except ImportError:
        addrs = None

    def private(a: str) -> bool:
        return (a.startswith("192.168.") or a.startswith("10.")
                or any(a.startswith(f"172.{i}.") for i in range(16, 32)))

    if addrs:
        # 實體網卡優先，且排除 VPN/虛擬介面
        for name in sorted(addrs, key=lambda n: (not n.startswith("en"), n)):
            if name.startswith(("utun", "tun", "tap", "ppp", "awdl", "llw", "bridge")):
                continue
            for a in addrs[name]:
                if getattr(a, "family", None) == socket.AF_INET and private(a.address):
                    return a.address

    # 沒有 psutil 時退回 ifconfig 解析（macOS/Linux 皆可）
    import re
    import subprocess  # noqa: PLC0415
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return "localhost"
    iface = None
    for line in out.splitlines():
        m = re.match(r"^([a-z0-9]+):", line)
        if m:
            iface = m.group(1)
        elif iface and iface.startswith("en") and line.strip().startswith("inet "):
            a = line.split()[1]
            if private(a):
                return a
    return "localhost"


@app.get("/api/qr")
def api_qr(request: Request):
    """回傳「手機掃碼直開」用的區網網址 QR（base64 PNG）。"""
    import qrcode  # noqa: PLC0415
    ip = lan_ip()
    url = f"http://{ip}:{request.url.port or 8000}"
    img = qrcode.make(url, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return {"url": url, "png_b64": base64.b64encode(buf.getvalue()).decode()}


@app.post("/api/judge")
async def api_judge(mode: str = Form("pair"),
                    pickup: UploadFile | None = File(None),
                    ret: UploadFile | None = File(None),
                    interior: UploadFile | None = File(None),
                    skip_gate: bool = Form(False)):
    """現場實測：跑完整鏈路（Quality Gate → 級聯判定 → 視覺標註）。
    上傳照片只寫進暫存目錄（with 區塊結束即刪除），不進 repo。"""
    _require_key()
    import judge_photos  # noqa: PLC0415  延遲載入：不啟用此功能時 server 照常跑

    need = [("pickup", pickup), ("ret", ret)] if mode == "pair" else [("interior", interior)]
    for name, f in need:
        if f is None:
            raise HTTPException(400, f"缺少 {name} 照片")

    logs = []
    with tempfile.TemporaryDirectory(prefix="irent-judge-") as td:
        # raw bytes 留在記憶體供「存入案件佇列」縮圖用（下次判定即覆蓋）
        # 變數名不可用 paths——會遮蔽模組 paths，使上方的金鑰檢查 UnboundLocalError
        saved, raw = await _save_uploads(td, need)

        def run():
            with _rejudge_lock:  # 免費層 RPM 低，一次一件（與 AI 重判共用鎖）
                if mode == "pair":
                    return judge_photos.judge_pair(saved["pickup"], saved["ret"], client=_client(),
                                                   skip_gate=skip_gate, log=logs.append)
                return judge_photos.judge_interior(saved["interior"], client=_client(),
                                                   skip_gate=skip_gate, log=logs.append)

        try:
            result, img = await run_in_threadpool(run)
        except Exception as e:
            raise HTTPException(502, f"判定失敗：{str(e)[:200]}")

    enrich(result)          # S6 估價分流（零 API，失敗不影響判定）
    # 暫存路徑對前端沒有意義，拿掉；標註圖直接以 base64 回傳
    for k in ("pickup", "return", "photo"):
        result.pop(k, None)
    result["logs"] = logs
    if img is not None:
        if img.width > 1280:
            img = img.resize((1280, int(img.height * 1280 / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=82)
        result["annotated_b64"] = base64.b64encode(buf.getvalue()).decode()
    # 供「存入案件佇列」：只留最近一次判定（照片 bytes 僅存記憶體）
    result["judge_id"] = uuid.uuid4().hex[:12]
    _remember_judge({"id": result["judge_id"], "mode": mode, "raw": raw, "result": result})
    return result


# ---------- 現場實測 → 案件佇列（縮圖存 SQLite，全隊共享） ----------
# 以 judge_id 為 key 的有限容量暫存（照片 bytes 僅存記憶體）。
# 曾是單筆全域 dict——兩人同時用「現場實測」時，後判者會覆蓋前judge者的
# 照片，前者按「存入案件佇列」不是拿到 410 就是存進別人的照片。
# 現場 demo（評審手機掃碼 + 隊友電腦操作）必然併發，故改為多筆並加鎖。
_JUDGE_CACHE_MAX = 20
_judges = OrderedDict()          # judge_id -> {"mode","raw","result","saved_as"}
_judges_lock = threading.Lock()


def _remember_judge(entry: dict):
    with _judges_lock:
        _judges[entry["id"]] = entry
        while len(_judges) > _JUDGE_CACHE_MAX:
            _judges.popitem(last=False)   # 淘汰最舊的一筆


def _thumb_b64(data: bytes, w=480, q=55):
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    if im.width > w:
        im = im.resize((w, int(im.height * w / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode()


class LiveCaseReq(BaseModel):
    judge_id: str


@app.post("/api/live_case")
def save_live_case(req: LiveCaseReq):
    with _judges_lock:
        entry = _judges.get(req.judge_id)
    if entry is None:
        raise HTTPException(410, "此判定已過期（暫存已滿或 server 重啟），請重新判定後再存")
    if entry.get("saved_as"):
        return entry["saved_as"]  # 重複點擊 → 回同一案件
    r = entry["result"]
    fin = r.get("final")
    if not fin:
        raise HTTPException(400, "品質不合格案件沒有判定結果，不入佇列")
    now = datetime.now()
    live_id = "LIVE-" + now.strftime("%m%d-%H%M%S")
    if r["mode"] == "pair":
        ann = {"findings": [{"box_2d": d["box_2d"], "label": d["type"], "severity": d["severity"],
                             "confidence": d["confidence"],
                             "description": f'{d["location"]}：{d["reasoning"]}'}
                            for d in fin["damages"] if len(d.get("box_2d") or []) == 4],
               "summary": ""}
        case = {"id": live_id, "live": True, "car": "LIVE", "angle": now.strftime("%m/%d %H:%M"),
                "level": r["level"], "kind": r["kind"], "truth": "live", "assessment": fin,
                "pickup": _thumb_b64(entry["raw"]["pickup"]),
                "ret": _thumb_b64(entry["raw"]["ret"])}
    else:
        ann = {"findings": [f for f in fin["findings"] if len(f.get("box_2d") or []) == 4],
               "summary": ""}
        case = {"id": live_id, "live": True, "f2": True, "car": "LIVE",
                "angle": now.strftime("%m/%d %H:%M"),
                "level": r["level"], "kind": r["kind"], "truth": "live",
                "assessment": {"level": fin["level"], "confidence": fin["confidence"],
                               "issues": [f["label"] for f in fin["findings"]],
                               "reasoning": fin["reasoning"]},
                "photo": _thumb_b64(entry["raw"]["interior"])}
    payload = {"case": case, "ann": ann}
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO live_cases VALUES (?,?,?)",
                     (live_id, now.isoformat(timespec="seconds"),
                      json.dumps(payload, ensure_ascii=False)))
    entry["saved_as"] = payload
    return payload


@app.get("/api/live_cases")
def get_live_cases(ids: int = 0):
    with db() as conn:
        if ids:  # 輕量輪詢用：只回 id 清單
            return [row[0] for row in conn.execute(
                "SELECT case_id FROM live_cases ORDER BY created_at DESC")]
        return [json.loads(row[0]) for row in conn.execute(
            "SELECT data FROM live_cases ORDER BY created_at DESC")]


@app.delete("/api/live_case/{case_id}")
def delete_live_case(case_id: str):
    """移除現場實測案件。同樣不刪 decision_events（訓練標籤存底）。"""
    with db() as conn:
        conn.execute("DELETE FROM live_cases WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM decisions WHERE case_id=?", (case_id,))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
