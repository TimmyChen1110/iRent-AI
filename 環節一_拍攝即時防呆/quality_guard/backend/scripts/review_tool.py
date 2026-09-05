"""本地快速審視工具：看過 raw_data/scraped 裡下載的候選照片，標記保留/拒絕/更正角度。

只在本機執行(預設綁定 127.0.0.1),不會對外公開。這批照片含真實顧客車牌等
個資,絕對不要用任何方式發布/上傳到外部服務(包含但不限於公開網頁、雲端分享)。

用法:
    cd backend && ../.venv/bin/python -m uvicorn scripts.review_tool:app --port 8008
    瀏覽器開 http://127.0.0.1:8008/

審視結果會即時寫進 raw_data/scraped/review_decisions.csv,關掉瀏覽器/重開
伺服器都不會遺失進度,可以分好幾次審完。
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BACKEND_DIR.parent / "raw_data"
SCRAPED_DIR = RAW_DATA_DIR / "scraped"
MANIFEST_PATH = SCRAPED_DIR / "manifest.csv"
DECISIONS_PATH = SCRAPED_DIR / "review_decisions.csv"
STATIC_DIR = Path(__file__).resolve().parent / "review_static"

app = FastAPI()
app.mount("/files", StaticFiles(directory=SCRAPED_DIR), name="files")


class Decision(BaseModel):
    id: str
    decision: str  # "keep" | "reject"
    final_label: Optional[str] = None


def load_manifest() -> list[dict]:
    with open(MANIFEST_PATH, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_decisions() -> dict[str, dict]:
    if not DECISIONS_PATH.exists():
        return {}
    with open(DECISIONS_PATH, newline="", encoding="utf-8-sig") as f:
        return {row["id"]: row for row in csv.DictReader(f)}


def save_decisions(decisions: dict[int, dict]) -> None:
    fieldnames = ["id", "decision", "final_label", "reviewed_at"]
    with open(DECISIONS_PATH, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in sorted(decisions.values(), key=lambda r: r["id"]):
            writer.writerow(row)


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/items")
def get_items():
    manifest = load_manifest()
    decisions = load_decisions()
    items = []
    for row in manifest:
        if row.get("status") not in ("OK", "SKIPPED_EXISTS"):
            continue
        full_path = SCRAPED_DIR / row["local_path"]
        if not full_path.exists():
            continue

        item_id = row["id"]
        decision = decisions.get(item_id)
        items.append({
            "id": item_id,
            "plate": row["plate"],
            "order_number": row["order_number"],
            "claimed_label": row["claimed_label"],
            "upload_category": row["upload_category"],
            "label_mismatch": row["label_mismatch"] == "True",
            "local_path": row["local_path"],
            "decision": decision["decision"] if decision else None,
            "final_label": (decision.get("final_label") or None) if decision else None,
        })
    return items


@app.post("/api/decision")
def post_decision(payload: Decision):
    decisions = load_decisions()
    decisions[payload.id] = {
        "id": payload.id,
        "decision": payload.decision,
        "final_label": payload.final_label or "",
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    save_decisions(decisions)
    return {"ok": True}
