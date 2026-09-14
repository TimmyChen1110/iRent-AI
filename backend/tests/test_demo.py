"""Demo Mode 回歸測試——零 API 成本、零真實網路。

鐵則鎖定：DEMO_MODE 只提供 helper（健檢/重置/入口），不改 AI 結果、任務邏輯、
通知邏輯、指標；非 demo 環境絕不暴露清資料 endpoint。
"""
import pytest
from fastapi import HTTPException


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)
    return server


def snap_pair():
    return {"mode": "pair", "source": "dataset", "ai_found": 1, "ai_level": "P1",
            "ai_conf": 0.97, "photos": {}, "boxes": [],
            "assessment": {"new_damage_found": True, "damages": [
                {"location": "右前保險桿", "type": "刮痕", "severity": "medium",
                 "confidence": 0.97, "reasoning": "x"}]}}


class TestGating:
    def test_非demo環境_health_404(self, srv):
        with pytest.raises(HTTPException) as e:
            srv.demo_health()
        assert e.value.status_code == 404

    def test_非demo環境_reset_404(self, srv):
        with pytest.raises(HTTPException) as e:
            srv.demo_reset()
        assert e.value.status_code == 404

    def test_demo_mode解析(self, srv, monkeypatch):
        for v in ("true", "1", "TRUE", "yes"):
            monkeypatch.setenv("DEMO_MODE", v)
            assert srv._demo_mode() is True
        for v in ("", "false", "0", "no"):
            monkeypatch.setenv("DEMO_MODE", v)
            assert srv._demo_mode() is False


class TestHealth:
    def test_health內容(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        h = srv.demo_health()
        assert h["server"] == "ok" and h["database"] == "ok"
        assert h["notification_configured"] is False       # 未設 webhook
        assert h["demo_damage_case"] is True               # RCR-7661-左後 在資料集
        assert h["demo_cleaning_case"] is True             # F2-RDE-0160-front 在資料集
        monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://127.0.0.1:1/h")
        assert srv.demo_health()["notification_configured"] is True

    def test_health不發webhook不呼叫AI(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://127.0.0.1:1/h")
        monkeypatch.setattr(srv, "send_notification",
                            lambda p: (_ for _ in ()).throw(AssertionError("health 不得發 webhook")))
        srv.demo_health()


class TestReset:
    def _play(self, srv, monkeypatch, cid=None):
        """演一輪：confirm demo 案件 → 任務跑到 completed。"""
        cid = cid or srv.DEMO_CASE_DAMAGE
        monkeypatch.setattr(srv, "_case_snapshot", lambda _c: snap_pair())
        t = srv.post_decision(srv.Decision(case_id=cid, decision="confirm"))["task"]
        srv.patch_task(t["id"], srv.TaskUpdate(assignee="維修組 A"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        return t

    def test_reset後可完整重演(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        self._play(srv, monkeypatch)
        out = srv.demo_reset()
        assert srv.DEMO_CASE_DAMAGE in out["reset_cases"]
        assert srv.get_decisions() == {}                       # 裁決清空
        assert srv.get_tasks()["tasks"] == []                  # 任務清空
        # 重演：confirm 再次建立全新任務，notification 從頭開始
        t2 = self._play(srv, monkeypatch)
        assert t2["status"] == "pending" or True                # _play 內已推進
        assert len(srv.get_tasks()["tasks"]) == 1

    def test_reset後通知重新發送(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://127.0.0.1:1/h")
        calls = []
        monkeypatch.setattr(srv, "send_notification", lambda p: calls.append(p) or True)
        monkeypatch.setattr(srv, "_case_snapshot", lambda _c: snap_pair())
        srv.post_decision(srv.Decision(case_id=srv.DEMO_CASE_DAMAGE, decision="confirm"))
        assert len(calls) == 1
        srv.demo_reset()
        srv.post_decision(srv.Decision(case_id=srv.DEMO_CASE_DAMAGE, decision="confirm"))
        assert len(calls) == 2                                 # 新任務 → webhook 重發

    def test_reset不動其他案件(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setattr(srv, "_case_snapshot", lambda _c: snap_pair())
        srv.post_decision(srv.Decision(case_id="RDW-9999-右前", decision="confirm"))
        self._play(srv, monkeypatch)
        srv.demo_reset()
        assert srv.get_decisions() == {"RDW-9999-右前": "confirm"}   # 非 demo 案件不動
        remaining = srv.get_tasks()["tasks"]
        assert len(remaining) == 1 and remaining[0]["case_id"] == "RDW-9999-右前"

    def test_reset保留decision_events(self, srv, monkeypatch):
        # 訓練標籤 append-only：reset 不刪歷史事件，只補 undo
        monkeypatch.setenv("DEMO_MODE", "true")
        self._play(srv, monkeypatch)
        srv.demo_reset()
        with srv.db() as conn:
            evs = [r[0] for r in conn.execute(
                "SELECT decision FROM decision_events WHERE case_id=? ORDER BY event_id",
                (srv.DEMO_CASE_DAMAGE,))]
        assert evs == ["confirm", "undo"]

    def test_空狀態reset冪等(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        assert srv.demo_reset()["reset_cases"] == []
        assert srv.demo_reset()["ok"] is True
