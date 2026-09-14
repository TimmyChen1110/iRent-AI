#!/usr/bin/env python3
"""本機 webhook 接收器——Demo/測試「通知真的從 server 送出去」用。零依賴。

用法：
  1. 本檔啟動接收器：   python3 backend/tools/webhook_receiver.py          # 預設 port 9999
  2. 另一個終端啟動監理台時設定：
       export NOTIFICATION_WEBHOOK_URL=http://127.0.0.1:9999/hook
       cd backend/app && uvicorn server:app --port 8000
  3. 在監理台 confirm 一筆案件 → 本視窗即時印出收到的 JSON payload，
     Task Card 顯示「🔔 通知已送出」。

正式 Demo 也可改用 webhook.site 之類的線上端點（URL 只放環境變數，勿進版控）。
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9999


class Hook(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            payload = json.loads(body)
            print("\n📨 收到通知：")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            print("\n📨 收到非 JSON POST：", body[:500])
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *_):   # 靜音預設 access log，只留 payload 輸出
        pass


if __name__ == "__main__":
    print(f"Webhook 接收器聽 http://127.0.0.1:{PORT}/hook （Ctrl+C 結束）")
    HTTPServer(("127.0.0.1", PORT), Hook).serve_forever()
