#!/usr/bin/env python3
"""Playwright 專用 deterministic server；所有狀態只存在暫存目錄。"""
import os
import shutil
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

work = Path(tempfile.mkdtemp(prefix="irent-e2e-"))
os.environ.update({
    "IRENT_DB_PATH": str(work / "e2e.sqlite3"),
    "IRENT_UPLOAD_DIR": str(work / "uploads"),
    "IRENT_SCRATCH_DIR": str(work / "scratch"),
    "DEMO_MODE": "true",
    "IRENT_ADMIN_PASSWORD": "admin-demo",
    "IRENT_STATION_PASSWORD": "station-demo",
})
os.environ.pop("NOTIFICATION_WEBHOOK_URL", None)
os.environ.pop("GEMINI_API_KEY", None)
os.environ.pop("GOOGLE_API_KEY", None)

try:
    import server
    import uvicorn

    # 固定案件已有 repository 內照片與 AI 結果；不呼叫 Gemini 或 webhook。
    server.post_decision(server.Decision(case_id="RCR-7661-左後", decision="confirm"))
    server.post_decision(server.Decision(case_id="F2-RDE-0160-front", decision="confirm"))
    uvicorn.run(server.app, host="127.0.0.1", port=8765, log_level="warning")
finally:
    shutil.rmtree(work, ignore_errors=True)
