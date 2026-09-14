"""環節三 整備中心 API（/api/ops）回歸測試——零 API 成本、不打網路。

覆蓋：事件流由 task_events 派生（冪等）、已讀、SLA 計算與逾時事件、任務詳情（案件快照→照片 URL）、
狀態變更走同一套狀態機、備註、人員、設定、管道狀態不外洩 URL。
"""
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(server, "send_notification", lambda payload: True)
    monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://example.invalid/hook")
    return server


@pytest.fixture()
def ops(srv):
    import ops_api
    return ops_api


def snap_pair():
    return {"mode": "pair", "source": "dataset", "ai_found": 1, "ai_level": "P1", "ai_conf": 0.97,
            "photos": {"pickup": "/abs/dir/RCR-7661_借_左後.jpg", "return": "/abs/dir/RCR-7661_還_左後.jpg"},
            "boxes": [{"box_2d": [100, 100, 300, 300], "label": "刮痕", "severity": "medium", "confidence": .9}],
            "assessment": {"new_damage_found": True, "damages": [
                {"location": "左後保險桿", "type": "刮痕", "severity": "medium", "confidence": 0.97, "reasoning": "r"}]}}


def make_task(srv, case_id="RCR-7661-左後", monkeypatch=None):
    if monkeypatch:
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
    return srv.post_decision(srv.Decision(case_id=case_id, decision="confirm"))["task"]


class TestEvents:
    def test_task_events派生為ops_events且冪等(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        r1 = ops.list_events(x_ops_reader="客服")
        types = [e["type"] for e in r1["events"]]
        assert "task_created" in types and "notify_sent" in types
        n = len(r1["events"])
        r2 = ops.list_events(x_ops_reader="客服")
        assert len(r2["events"]) == n            # 再讀不重複派生
        assert all(e["task_id"] == t["id"] for e in r2["events"])
        assert r2["unread"] == n

    def test_已讀依reader分開(self, srv, ops, monkeypatch):
        make_task(srv, monkeypatch=monkeypatch)
        ids = [e["id"] for e in ops.list_events(x_ops_reader="A")["events"]]
        ops.read_events(ops.ReadBody(ids=ids[:1]), x_ops_reader="A")
        assert ops.list_events(x_ops_reader="A")["unread"] == len(ids) - 1
        assert ops.list_events(x_ops_reader="B")["unread"] == len(ids)
        ops.read_events(ops.ReadBody(ids=None), x_ops_reader="B")
        assert ops.list_events(x_ops_reader="B")["unread"] == 0
        assert ops.list_events(unread=True, x_ops_reader="A")["events"][0]["id"] != ids[0]

    def test_通知失敗事件型別(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "send_notification", lambda payload: False)
        make_task(srv, monkeypatch=monkeypatch)
        assert "notify_failed" in [e["type"] for e in ops.list_events()["events"]]


class TestSLA:
    def test_pending任務有倒數_開工後停止(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        got = ops.list_tasks()["tasks"][0]
        assert got["sla_minutes"] == 5 and got["priority"] == "P1"
        assert 0 < got["sla_remaining_s"] <= 300 and got["overdue"] is False
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        got = ops.list_tasks()["tasks"][0]
        assert got["sla_remaining_s"] is None and got["overdue"] is False

    def test_逾時產生一則sla_overdue事件(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        old = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        with srv.db() as conn:
            conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (old, t["id"]))
        assert ops.summary()["overdue"] == 1
        ops.list_events(); ops.list_tasks()
        evs = [e for e in ops.list_events()["events"] if e["type"] == "sla_overdue"]
        assert len(evs) == 1 and evs[0]["task_id"] == t["id"]

    def test_設定門檻影響計算(self, srv, ops, monkeypatch):
        make_task(srv, monkeypatch=monkeypatch)
        ops.put_settings({"sla_minutes_p1": 60})
        assert ops.list_tasks()["tasks"][0]["sla_minutes"] == 60
        with pytest.raises(HTTPException):
            ops.put_settings({"sla_minutes_p1": "abc"})
        with pytest.raises(HTTPException):
            ops.put_settings({"sla_minutes_p2": 0})


class TestTaskDetail:
    def test_詳情含照片URL與標註框(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        d = ops.get_task(t["id"])
        assert d["case"]["photos"]["pickup"].startswith("/photos/pair/")
        assert d["case"]["photos"]["return"].startswith("/photos/pair/")
        assert d["case"]["boxes"][0]["label"] == "刮痕"
        assert d["case"]["decision"]["decision"] == "confirm"
        assert d["task"]["events"][0]["event"] == "created"

    def test_快照失敗不擋任務(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: (_ for _ in ()).throw(RuntimeError("boom")))
        d = ops.get_task(t["id"])
        assert d["case"]["mode"] is None and d["task"]["id"] == t["id"]

    def test_找不到任務404(self, srv, ops):
        with pytest.raises(HTTPException) as ei:
            ops.get_task(999)
        assert ei.value.status_code == 404


class TestUpdate:
    def test_狀態變更與監理台同一套狀態機(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        with pytest.raises(HTTPException):
            ops.update_task(t["id"], ops.OpsTaskUpdate(status="completed"))   # pending 不能直接完成
        d = ops.update_task(t["id"], ops.OpsTaskUpdate(status="in_progress", assignee="維修組 A"))
        assert d["task"]["status"] == "in_progress" and d["task"]["assignee"] == "維修組 A"
        d = ops.update_task(t["id"], ops.OpsTaskUpdate(status="completed"))
        assert d["task"]["resolved_at"]

    def test_備註寫進歷程並署名(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        d = ops.update_task(t["id"], ops.OpsTaskUpdate(note="  已聯絡站點  "), x_ops_reader="%E5%AE%A2%E6%9C%8D")
        last = d["task"]["events"][-1]
        assert last["event"] == "note" and last["detail"] == "客服：已聯絡站點"
        assert "note" in [e["type"] for e in ops.list_events()["events"]]

    def test_重發通知(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "send_notification", lambda payload: False)
        t = make_task(srv, monkeypatch=monkeypatch)
        assert t["notification_status"] == "failed"
        monkeypatch.setattr(srv, "send_notification", lambda payload: True)
        d = ops.retry_notify(t["id"])
        assert d["task"]["notification_status"] == "sent"


class TestPeopleSettingsChannels:
    def test_預設人員與新增停用(self, srv, ops):
        names = [p["name"] for p in ops.people()["people"]]
        assert names == ["清潔組 A", "清潔組 B", "維修組 A", "維修組 B"] or set(names) == {"維修組 A", "維修組 B", "清潔組 A", "清潔組 B"}
        p = ops.add_person(ops.PersonIn(group_name="維修組", name="維修組 C"))
        with pytest.raises(HTTPException):
            ops.add_person(ops.PersonIn(group_name="維修組", name="維修組 C"))
        ops.patch_person(p["id"], ops.PersonPatch(active=False))
        assert "維修組 C" not in [x["name"] for x in ops.people()["people"]]
        assert "維修組 C" in [x["name"] for x in ops.people(all=True)["people"]]

    def test_管道狀態不外洩URL(self, srv, ops):
        h = ops.ops_health()
        wh = next(c for c in h["channels"] if c["id"] == "webhook")
        assert wh["configured"] is True and "http" not in str(wh)
        assert all(c["available"] is False for c in h["channels"] if c["id"] in ("line", "sms"))

    def test_summary計數(self, srv, ops, monkeypatch):
        make_task(srv, monkeypatch=monkeypatch)
        s = ops.summary()
        assert s["pending"] == 1 and s["p1_not_started"] == 1 and s["notify_failed"] == 0 and s["server_time"]
