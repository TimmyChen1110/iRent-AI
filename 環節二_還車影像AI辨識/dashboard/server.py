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
import json
import sqlite3
import sys
import threading
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
