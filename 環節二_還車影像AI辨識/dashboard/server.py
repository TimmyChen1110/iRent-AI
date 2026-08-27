#!/usr/bin/env python3
"""iRent 車況監理台 — Server 版。

與單檔版（irent-review-dashboard.html）同一套 UI，多了：
  - 複核決策存 SQLite，全隊共享（前端每 5 秒自動同步）
  - 照片由 server 供圖（頁面輕、可看原圖）
  - 資料直接讀 pipeline/ 的實測結果（POST /api/reload 可熱更新）
  - 「AI 重判」按鈕：現場呼叫 Gemini 重新判定該案（需 pipeline/.gemini_key）

啟動：
  pip3 install fastapi uvicorn pillow
  cd 環節二_還車影像AI辨識/dashboard
  uvicorn server:app --host 0.0.0.0 --port 8000
  → 本機開 http://localhost:8000 ；隊友連 http://<你的區網IP>:8000

注意：資料含真實車牌照片，僅限 localhost / 隊內區網，勿部署公網。
"""
import base64
import io
import json
import sqlite3
import sys
import tempfile
import threading
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

from build_dashboard import build_cases, build_f2cases, car_model_block  # noqa: E402
from results_config import FINAL_RESULTS, INTERIOR_RESULTS  # noqa: E402

DB_PATH = HERE / "decisions.sqlite3"

app = FastAPI(title="iRent 車況監理台", docs_url=None, redoc_url=None)


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


@app.post("/api/decision")
def post_decision(d: Decision):
    """記錄人工裁決。同時寫入兩張表：
      decisions       — 複核狀態（可覆蓋，後台 UI 讀這張）
      decision_events — 訓練標籤存底（append-only，永不覆蓋）
    後者是把「稽核員本來就要做的複核」直接轉成免費的 ground truth。
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
    return {"ok": True, "labeled": label is not None, "agreed": agreed}


@app.delete("/api/decision/{case_id}")
def delete_decision(case_id: str):
    """復原複核狀態。刻意【不刪】decision_events——「先判了又收回」本身是難例訊號，
    而且訓練標籤一旦刪掉就永遠救不回來。"""
    now = datetime.now().isoformat(timespec="seconds")
    with db() as conn:
        conn.execute("DELETE FROM decisions WHERE case_id=?", (case_id,))
        conn.execute("INSERT INTO decision_events(case_id, decided_at, decision, note)"
                     " VALUES (?,?,?,?)", (case_id, now, "undo", "使用者復原前次裁決"))
    return {"ok": True}


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
_pairs = json.loads((PIPE / "pairs.json").read_text())["pairs"]
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
        blocks = [
            "const SERVER_MODE=true;",
            "const CASES=" + json.dumps(build_cases(embed=False), ensure_ascii=False) + ";",
            "const F2CASES=" + json.dumps(build_f2cases(embed=False), ensure_ascii=False) + ";",
            "const ANNOTATIONS=" + (PIPE / "dashboard_annotations.json").read_text() + ";",
            "const PASSPORT_DATA=" + (PIPE / "passports.json").read_text() + ";",
        ]
        html = (shell
                .replace("<!--DATA-->", "<script>\n" + "\n".join(blocks) + "\n</script>")
                .replace("<!--THREE-->", "<script>" + three + "</script>")
                .replace("<!--CARMODEL-->", car_model_block()))
        _page_cache["html"] = html
        return html


@app.get("/", response_class=HTMLResponse)
def index():
    return render_page()


@app.post("/api/reload")
def reload_data():
    """pipeline 資料更新後呼叫，重新組頁。"""
    render_page(force=True)
    return {"ok": True}


# ---------- AI 現場重判（需 pipeline/.gemini_key，免費層約 10 秒） ----------
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
    key = PIPE / ".gemini_key"
    if not key.exists():
        raise HTTPException(503, "此機器沒有 pipeline/.gemini_key，無法呼叫 Gemini")
    pair = next((p for p in _pairs if f'{p["car"]}-{p["angle"]}' == req.case_id), None)
    if not pair:
        raise HTTPException(404, f"找不到案件 {req.case_id}（車內照不支援重判）")

    import judge_photos  # noqa: PLC0415  延遲載入

    def run():
        with _rejudge_lock:  # 免費層 RPM 低，一次一件（與現場實測共用鎖）
            # 資料集照片已知可讀，跳過 Quality Gate 直接判（gate 數值仍會回在結果內）
            return judge_photos.judge_pair(pair["pickup"], pair["return"],
                                           client=_client(), skip_gate=True)

    try:
        result, _img = await run_in_threadpool(run)
    except Exception as e:
        raise HTTPException(502, f"重判失敗：{str(e)[:200]}")

    final = result.get("final")
    if not final:
        raise HTTPException(502, "未取得有效判定結果")
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
        paths, _ = await _save_uploads(td, need)
        try:
            names = {"pickup": "pickup", "ret": "return", "interior": "photo"}
            gates = judge_photos._run_gate({names[k]: p for k, p in paths.items()},
                                           interior=(mode != "pair"))
        except Exception as e:
            raise HTTPException(400, f"照片無法讀取：{str(e)[:120]}")
    return {"gate": gates, "gate_pass": all(g["pass"] for g in gates.values())}


@app.get("/api/qr")
def api_qr(request: Request):
    """回傳「手機掃碼直開」用的區網網址 QR（base64 PNG）。"""
    import qrcode  # noqa: PLC0415
    import socket  # noqa: PLC0415
    try:  # 取本機區網 IP（UDP 不實際發包）
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except OSError:
        ip = "localhost"
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
    if not (PIPE / ".gemini_key").exists():
        raise HTTPException(503, "此機器沒有 pipeline/.gemini_key，無法呼叫 Gemini")
    import judge_photos  # noqa: PLC0415  延遲載入：不啟用此功能時 server 照常跑

    need = [("pickup", pickup), ("ret", ret)] if mode == "pair" else [("interior", interior)]
    for name, f in need:
        if f is None:
            raise HTTPException(400, f"缺少 {name} 照片")

    logs = []
    with tempfile.TemporaryDirectory(prefix="irent-judge-") as td:
        # raw bytes 留在記憶體供「存入案件佇列」縮圖用（下次判定即覆蓋）
        paths, raw = await _save_uploads(td, need)

        def run():
            with _rejudge_lock:  # 免費層 RPM 低，一次一件（與 AI 重判共用鎖）
                if mode == "pair":
                    return judge_photos.judge_pair(paths["pickup"], paths["ret"], client=_client(),
                                                   skip_gate=skip_gate, log=logs.append)
                return judge_photos.judge_interior(paths["interior"], client=_client(),
                                                   skip_gate=skip_gate, log=logs.append)

        try:
            result, img = await run_in_threadpool(run)
        except Exception as e:
            raise HTTPException(502, f"判定失敗：{str(e)[:200]}")

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
