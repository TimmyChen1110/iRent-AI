"""整備任務即時通知回歸測試——零 API 成本、零真實網路。

原則鎖定：
  - 通知只在「人工 confirm → task 建立成功」之後發（AI 判定瞬間不發）
  - reject / retake 不發
  - webhook 失敗絕不影響 confirm 與 task 建立（side effect 隔離）
  - 已 sent 不重發（confirm→undo→confirm 不轟炸）；failed/skipped 可 retry
HTTP 一律 monkeypatch server.send_notification，絕不打外網。
"""
import pytest
from fastapi import HTTPException


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    return server


@pytest.fixture()
def spy(srv, monkeypatch):
    """webhook 發送間諜：記錄 payload、可設定結果；預設環境已設 URL 且發送成功。"""
    calls = []
    state = {"result": True, "exc": None}

    def fake_send(payload):
        calls.append(payload)
        if state["exc"]:
            raise state["exc"]
        return state["result"]

    monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://127.0.0.1:1/test-hook")
    monkeypatch.setattr(srv, "send_notification", fake_send)
    return {"calls": calls, "state": state}


def snap_pair():
    return {"mode": "pair", "source": "dataset", "ai_found": 1, "ai_level": "P1",
            "ai_conf": 0.97, "photos": {}, "boxes": [],
            "assessment": {"new_damage_found": True, "damages": [
                {"location": "右前保險桿", "type": "刮痕", "severity": "medium",
                 "confidence": 0.97, "reasoning": "還車照可見刮痕"}]}}


def snap_interior():
    return {"mode": "interior", "source": "live", "ai_found": 1, "ai_level": "P1",
            "ai_conf": 0.9, "photos": {}, "boxes": [],
            "assessment": {"level": "髒汙", "confidence": 0.9,
                           "issues": ["垃圾"], "reasoning": "後座垃圾"}}


def confirm(srv, cid, snap, monkeypatch):
    monkeypatch.setattr(srv, "_case_snapshot", lambda _cid: snap)
    return srv.post_decision(srv.Decision(case_id=cid, decision="confirm"))


# ---------- 觸發時機 ----------

class TestTrigger:
    def test_confirm_repair_觸發通知(self, srv, spy, monkeypatch):
        out = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)
        assert len(spy["calls"]) == 1
        p = spy["calls"][0]
        assert p["event"] == "task_created" and p["task_type"] == "repair"
        assert p["priority"] == "P1" and p["car"] == "RCR-7661"
        assert p["case_id"] == "RCR-7661-左後" and p["task_id"] == out["task"]["id"]

    def test_confirm_cleaning_觸發通知(self, srv, spy, monkeypatch):
        confirm(srv, "LIVE-0905-120000", snap_interior(), monkeypatch)
        assert spy["calls"][0]["task_type"] == "cleaning"

    def test_reject不通知(self, srv, spy, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        srv.post_decision(srv.Decision(case_id="RCR-7661-左後", decision="reject"))
        assert spy["calls"] == []

    def test_retake不通知(self, srv, spy, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        srv.post_decision(srv.Decision(case_id="RCR-7661-左後", decision="retake"))
        assert spy["calls"] == []


# ---------- 狀態更新與失敗隔離 ----------

class TestStatus:
    def test_成功寫sent並留歷程(self, srv, spy, monkeypatch):
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "sent"
        assert any(e["event"] == "notify" and "已送出" in e["detail"] for e in t["events"])

    def test_失敗寫failed(self, srv, spy, monkeypatch):
        spy["state"]["result"] = False
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "failed"

    def test_例外也寫failed(self, srv, spy, monkeypatch):
        spy["state"]["exc"] = TimeoutError("connect timeout")
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "failed"

    def test_失敗不影響task建立(self, srv, spy, monkeypatch):
        spy["state"]["exc"] = ConnectionRefusedError()
        out = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)
        assert out["ok"] is True                      # confirm 不能 500
        assert out["task"]["status"] == "pending"     # task 仍存在
        assert len(srv.get_tasks()["tasks"]) == 1

    def test_無webhook設定_不發request_標skipped(self, srv, monkeypatch):
        def boom(payload):
            raise AssertionError("未設定 webhook 卻發出了 request")
        monkeypatch.setattr(srv, "send_notification", boom)
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "skipped"


# ---------- 防重複與 retry ----------

class TestRetry:
    def test_已sent不重發(self, srv, spy, monkeypatch):
        confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)
        assert len(spy["calls"]) == 1
        srv.delete_decision("RCR-7661-左後")            # undo（任務取消）
        confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)  # 再 confirm（任務喚回）
        assert len(spy["calls"]) == 1                   # 不重發

    def test_retry_endpoint_已sent冪等(self, srv, spy, monkeypatch):
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        out = srv.retry_notify(t["id"])
        assert out["notification_status"] == "sent"
        assert len(spy["calls"]) == 1                   # 沒有第二發

    def test_failed可retry_成功轉sent(self, srv, spy, monkeypatch):
        spy["state"]["result"] = False
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "failed"
        spy["state"]["result"] = True                   # 外部端點恢復
        out = srv.retry_notify(t["id"])
        assert out["notification_status"] == "sent"
        assert len(spy["calls"]) == 2

    def test_skipped設定後可retry(self, srv, monkeypatch):
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert t["notification_status"] == "skipped"
        monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://127.0.0.1:1/test-hook")
        monkeypatch.setattr(srv, "send_notification", lambda p: True)
        assert srv.retry_notify(t["id"])["notification_status"] == "sent"

    def test_retry不存在的任務404(self, srv):
        with pytest.raises(HTTPException) as e:
            srv.retry_notify(9999)
        assert e.value.status_code == 404


# ---------- payload 與安全 ----------

class TestPayload:
    def test_payload欄位完整(self, srv):
        task = {"id": 7, "case_id": "X-左後", "task_type": "repair", "car": "X",
                "title": "T", "description": "D", "priority": "P1",
                "assignee": None, "status": "pending", "created_at": "2026-09-05T00:00:00"}
        p = srv.build_notification_payload(task)
        assert p == {"event": "task_created", "case_id": "X-左後", "task_id": 7,
                     "task_type": "repair", "priority": "P1", "car": "X",
                     "title": "T", "description": "D", "assignee": None,
                     "assignee_id": None, "assignee_name": None,
                     "status": "pending", "created_at": "2026-09-05T00:00:00",
                     "kind": "system_event", "url": None}

    def test_payload_url需設PUBLIC_BASE_URL(self, srv, monkeypatch):
        task = {"id": 7, "case_id": "X", "task_type": "repair", "title": "T", "status": "pending",
                "created_at": "2026-09-05T00:00:00"}
        monkeypatch.setenv("PUBLIC_BASE_URL", "http://10.0.0.5:8000/")
        assert srv.build_notification_payload(task)["url"] == "http://10.0.0.5:8000/ops/tasks/7"

    def test_URL不寫進task_events(self, srv, spy, monkeypatch):
        t = confirm(srv, "RCR-7661-左後", snap_pair(), monkeypatch)["task"]
        assert all("test-hook" not in (e["detail"] or "") for e in t["events"])

    def test_原始碼不含寫死的webhook網址(self, srv):
        import inspect
        src = inspect.getsource(srv)
        assert "webhook.site" not in src
        assert "hooks.slack.com" not in src
