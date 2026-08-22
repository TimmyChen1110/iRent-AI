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
from datetime import datetime
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

DB_PATH = HERE / "decisions.sqlite3"

app = FastAPI(title="iRent 車況監理台", docs_url=None, redoc_url=None)


# ---------- 決策 DB（全隊共享） ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS decisions("
                 "case_id TEXT PRIMARY KEY, decision TEXT, decided_at TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS live_cases("
                 "case_id TEXT PRIMARY KEY, created_at TEXT, data TEXT)")
    return conn


class Decision(BaseModel):
    case_id: str
    decision: str  # confirm | reject | retake


@app.get("/api/decisions")
def get_decisions():
    with db() as conn:
        return {r[0]: r[1] for r in conn.execute("SELECT case_id, decision FROM decisions")}


@app.post("/api/decision")
def post_decision(d: Decision):
    if d.decision not in ("confirm", "reject", "retake"):
        raise HTTPException(400, "decision 必須是 confirm / reject / retake")
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO decisions VALUES (?,?,?)",
                     (d.case_id, d.decision, datetime.now().isoformat(timespec="seconds")))
    return {"ok": True}


@app.delete("/api/decision/{case_id}")
def delete_decision(case_id: str):
    with db() as conn:
        conn.execute("DELETE FROM decisions WHERE case_id=?", (case_id,))
    return {"ok": True}


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
REJUDGE_SYSTEM = """你是 iRent 共享汽車的車況比對專家。你會收到同一台車、同一方位的借車照與還車照。
任務：判斷還車照中是否存在借車照沒有的【新增車損】。
準則：
1. 光線反射、水痕、髒污、倒影不是車損。
2. 借車照已存在的損傷不算新增，記在 pre_existing_notes。
3. 兩張照片明顯非同一方位時 angle_match = false。
4. no_damage_confidence 誠實反映把握程度。"""

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
def rejudge(req: RejudgeReq):
    key = PIPE / ".gemini_key"
    if not key.exists():
        raise HTTPException(503, "此機器沒有 pipeline/.gemini_key，無法呼叫 Gemini")
    pair = next((p for p in _pairs if f'{p["car"]}-{p["angle"]}' == req.case_id), None)
    if not pair:
        raise HTTPException(404, f"找不到案件 {req.case_id}（車內照不支援重判）")

    from google.genai import types  # noqa: PLC0415
    from run_eval_gemini import prep_image, Assessment  # noqa: PLC0415

    with _rejudge_lock:  # 免費層 RPM 低，一次一件
        try:
            resp = _client().models.generate_content(
                model="gemini-3.7-flash",
                contents=[
                    f"方位：{pair['angle']}。",
                    "第一張＝借車照：",
                    types.Part.from_bytes(data=prep_image(pair["pickup"]), mime_type="image/jpeg"),
                    "第二張＝還車照：",
                    types.Part.from_bytes(data=prep_image(pair["return"]), mime_type="image/jpeg"),
                    "請判斷是否有新增損傷。",
                ],
                config=types.GenerateContentConfig(
                    system_instruction=REJUDGE_SYSTEM,
                    response_mime_type="application/json",
                    response_schema=Assessment,
                    temperature=0.1,
                ),
            )
        except Exception as e:
            raise HTTPException(502, f"Gemini 呼叫失敗：{str(e)[:200]}")
    if not resp.parsed:
        raise HTTPException(502, "Gemini 未回傳有效結果")
    return {"case_id": req.case_id, "assessment": resp.parsed.model_dump(),
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
    _last_judge.clear()
    _last_judge.update({"id": result["judge_id"], "mode": mode, "raw": raw, "result": result})
    return result


# ---------- 現場實測 → 案件佇列（縮圖存 SQLite，全隊共享） ----------
_last_judge = {}


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
    if _last_judge.get("id") != req.judge_id:
        raise HTTPException(410, "此判定已過期（之後又判了新案），請重新判定後再存")
    if _last_judge.get("saved_as"):
        return _last_judge["saved_as"]  # 重複點擊 → 回同一案件
    r = _last_judge["result"]
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
                "pickup": _thumb_b64(_last_judge["raw"]["pickup"]),
                "ret": _thumb_b64(_last_judge["raw"]["ret"])}
    else:
        ann = {"findings": [f for f in fin["findings"] if len(f.get("box_2d") or []) == 4],
               "summary": ""}
        case = {"id": live_id, "live": True, "f2": True, "car": "LIVE",
                "angle": now.strftime("%m/%d %H:%M"),
                "level": r["level"], "kind": r["kind"], "truth": "live",
                "assessment": {"level": fin["level"], "confidence": fin["confidence"],
                               "issues": [f["label"] for f in fin["findings"]],
                               "reasoning": fin["reasoning"]},
                "photo": _thumb_b64(_last_judge["raw"]["interior"])}
    payload = {"case": case, "ann": ann}
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO live_cases VALUES (?,?,?)",
                     (live_id, now.isoformat(timespec="seconds"),
                      json.dumps(payload, ensure_ascii=False)))
    _last_judge["saved_as"] = payload
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
    with db() as conn:
        conn.execute("DELETE FROM live_cases WHERE case_id=?", (case_id,))
        conn.execute("DELETE FROM decisions WHERE case_id=?", (case_id,))
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
