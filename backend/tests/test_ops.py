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


def snap_interior():
    return {"mode": "interior", "source": "live", "ai_found": 1, "ai_level": "P1", "ai_conf": 0.9,
            "photos": {}, "boxes": [],
            "assessment": {"level": "髒汙", "confidence": 0.9, "score": 42, "issues": ["垃圾"], "reasoning": "後座垃圾"}}


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


# ---------- Phase 2：文案、發送、測試通知、SSE ----------

FAKE_GENERATED = {
    "user_notification": {"title": "還車檢查結果", "body": "本次還車發現左後保險桿刮痕，有取車照片可對比。", "evidence_note": "有取車照片", "dispute_channel_note": "可致電客服申訴"},
    "cs_brief": {"summary": "RCR-7661 左後刮痕", "confidence_note": "0.97", "coverage_caveat": "無", "recommended_action": "approve", "dispute_risk": "low", "dispute_risk_reason": "清楚"},
    "work_order": {"type": "repair", "priority": "urgent", "items": ["左後保險桿刮痕修補"], "special_tools": [], "estimated_minutes": 60},
    "grounding_check": {"passed": True, "problems": []},
}


@pytest.fixture()
def fake_notify(srv, monkeypatch):
    import notify
    calls = []
    def gen(case, client=None, **kw):
        calls.append(case)
        return dict(FAKE_GENERATED)
    monkeypatch.setattr(notify, "generate", gen)
    monkeypatch.setattr(srv, "_require_key", lambda: None)
    monkeypatch.setattr(srv, "_client", lambda: object())
    return calls


def run(coro):
    import asyncio
    return asyncio.run(coro)


class TestDrafts:
    def test_生成快取與強制重生(self, srv, ops, monkeypatch, fake_notify):
        t = make_task(srv, monkeypatch=monkeypatch)
        r1 = run(ops.generate_case_drafts(t["case_id"]))
        assert r1["cached"] is False and set(r1["drafts"]) == {"user", "cs", "worker"}
        assert r1["drafts"]["user"]["content"]["title"] == "還車檢查結果"
        assert r1["drafts"]["cs"]["grounding_ok"] is True
        r2 = run(ops.generate_case_drafts(t["case_id"]))
        assert r2["cached"] is True and len(fake_notify) == 1
        r3 = run(ops.generate_case_drafts(t["case_id"], force=True))
        assert r3["cached"] is False and len(fake_notify) == 2
        # notify 輸入只含結構化資料：損傷 + 估價區間
        case = fake_notify[0]
        assert case["vehicle"] == "RCR-7661" and case["damages"][0]["location"] == "左後保險桿"
        assert "estimate_twd" in case["damages"][0]

    def test_預生成不需任務_詳情以case_id取得(self, srv, ops, monkeypatch, fake_notify):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        run(ops.generate_case_drafts("RCR-7661-左後"))          # confirm 前預生成
        t = make_task(srv, monkeypatch=monkeypatch)
        d = ops.get_task(t["id"])
        assert d["drafts"]["worker"]["content"]["estimated_minutes"] == 60

    def test_人工編輯保留edited_at(self, srv, ops, monkeypatch, fake_notify):
        t = make_task(srv, monkeypatch=monkeypatch)
        run(ops.generate_case_drafts(t["case_id"]))
        d = ops.put_case_draft(t["case_id"], "user", ops.DraftIn(content={"title": "改過", "body": "x"}))
        assert d["content"]["title"] == "改過" and d["edited_at"]
        with pytest.raises(HTTPException):
            ops.put_case_draft(t["case_id"], "boss", ops.DraftIn(content={}))

    def test_找不到案件404(self, srv, ops, monkeypatch, fake_notify):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: {"mode": None, "assessment": None})
        with pytest.raises(HTTPException) as ei:
            run(ops.generate_case_drafts("NOPE-1"))
        assert ei.value.status_code == 404


class TestSend:
    def test_webhook實發並記錄(self, srv, ops, monkeypatch, fake_notify):
        t = make_task(srv, monkeypatch=monkeypatch)
        run(ops.generate_case_drafts(t["case_id"]))
        sent = []
        monkeypatch.setattr(srv, "send_notification", lambda p: sent.append(p) or True)
        r = ops.send_draft(t["id"], ops.SendIn(audience="user", channel="webhook"), x_ops_reader="CS")
        assert r["ok"] and r["entry"]["status"] == "sent"
        assert sent[0]["event"] == "notification" and sent[0]["content"]["title"] == "還車檢查結果"
        assert r["notification_log"][-1]["audience"] == "user"
        assert r["task"]["events"][-1]["detail"].startswith("CS：用戶通知 已送出")

    def test_未接入管道記unsupported不外發(self, srv, ops, monkeypatch, fake_notify):
        t = make_task(srv, monkeypatch=monkeypatch)
        run(ops.generate_case_drafts(t["case_id"]))
        monkeypatch.setattr(srv, "send_notification", lambda p: (_ for _ in ()).throw(AssertionError("must not send")))
        r = ops.send_draft(t["id"], ops.SendIn(audience="worker", channel="line"))
        assert r["ok"] is False and r["entry"]["status"] == "unsupported"

    def test_沒文案409_失敗可重試(self, srv, ops, monkeypatch, fake_notify):
        t = make_task(srv, monkeypatch=monkeypatch)
        with pytest.raises(HTTPException) as ei:
            ops.send_draft(t["id"], ops.SendIn(audience="cs"))
        assert ei.value.status_code == 409
        run(ops.generate_case_drafts(t["case_id"]))
        monkeypatch.setattr(srv, "send_notification", lambda p: False)
        r = ops.send_draft(t["id"], ops.SendIn(audience="cs"))
        assert r["entry"]["status"] == "failed"
        monkeypatch.setattr(srv, "send_notification", lambda p: True)
        r = ops.send_draft(t["id"], ops.SendIn(audience="cs"))
        assert r["entry"]["status"] == "sent" and len(r["notification_log"]) == 2

    def test_測試通知(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "send_notification", lambda p: True)
        assert ops.test_webhook()["status"] == "sent"
        monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL")
        assert ops.test_webhook()["status"] == "skipped"


class TestSSE:
    def test_events_after只回新事件(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        with ops.ops_db.db() as conn:
            ops._refresh_events(conn)
            last = ops.ops_db.max_event_id(conn)
        assert ops._events_after(last, "A") == []
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        evs = ops._events_after(last, "A")
        assert len(evs) == 1 and evs[0]["type"] == "task_status" and evs[0]["id"] > last


# ---------- 車輛派單狀態（模擬）與營運洞察 ----------

class TestFleet:
    def test_未完成任務即鎖定_完成後可派(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        row = next(r for r in ops.fleet()["fleet"] if r["car"] == "RCR-7661")
        assert row["status"] == "locked" and row["open_tasks"][0]["id"] == t["id"] and row["manual_lock"] is False
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        row = next(r for r in ops.fleet()["fleet"] if r["car"] == "RCR-7661")
        assert row["status"] in ("available", "review") and row["completed_tasks"] == 1 and row["last_completed_at"]

    def test_手動鎖定與解除寫事件(self, srv, ops):
        r = ops.patch_fleet("abc-123", ops.LockIn(locked=True, reason="輪胎待換"), x_ops_reader="ops")
        assert r["lock"]["car"] == "ABC-123" and r["fleet"][0]["status"] == "locked"
        assert r["fleet"][0]["lock_reason"] == "輪胎待換" and r["fleet"][0]["lock_by"] == "ops"
        types = [e["type"] for e in ops.list_events()["events"]]
        assert "fleet_lock" in types
        r = ops.patch_fleet("ABC-123", ops.LockIn(locked=False))
        assert r["fleet"][0]["status"] == "available"
        assert ops.fleet(status="locked")["counts"]["locked"] == 0

    def test_篩選與備註說明(self, srv, ops):
        f = ops.fleet(q="zzz-none")
        assert f["fleet"] == [] and "模擬" in f["note"]


class TestInsights:
    def test_結構與即時中位數(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        r = ops.insights()
        assert r["tasks"]["total"] == 1 and r["tasks"]["by_type"]["repair"]["completed"] == 1
        assert r["tasks"]["n_started"] == 1 and r["tasks"]["median_minutes_to_start"] is not None
        assert r["car_ranking"][0]["car"] == "RCR-7661" and r["car_ranking"][0]["repair"] == 1
        assert r["interior"]["n"] == sum(r["interior"][k] for k in ("乾淨", "普通", "髒汙"))
        if r["uploads"]:
            assert len(r["uploads"]["by_hour"]) == 24 and r["uploads"]["orders"] == sum(r["uploads"]["by_hour"])


# ---------- 站點手機版：完工照與我的任務 ----------

def _jpeg_bytes(w=40, h=30):
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (w, h), (200, 30, 30)).save(buf, "JPEG"); return buf.getvalue()


class TestPhotosAndMyTasks:
    def test_上傳完工照_存檔並寫歷程(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        import io
        from starlette.datastructures import UploadFile as SUF
        up = SUF(filename="done.jpg", file=io.BytesIO(_jpeg_bytes()))
        r = run(ops.upload_task_photo(t["id"], photo=up, x_ops_reader="清潔組 A"))
        assert r["ok"] and r["photo"]["url"].startswith(f"/api/ops/tasks/{t['id']}/photos/")
        assert (tmp_path / "photos" / str(t["id"]) / r["photo"]["filename"]).exists()
        d = ops.get_task(t["id"])
        assert len(d["photos"]) == 1 and d["task"]["events"][-1]["event"] == "photo"
        resp = ops.get_task_photo(t["id"], r["photo"]["filename"])
        assert resp.media_type == "image/jpeg"
        with pytest.raises(HTTPException):
            ops.get_task_photo(t["id"], "../../etc/passwd")

    def test_非影像400_找不到任務404(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        import io
        from starlette.datastructures import UploadFile as SUF
        with pytest.raises(HTTPException) as ei:
            run(ops.upload_task_photo(t["id"], photo=SUF(filename="x.txt", file=io.BytesIO(b"not an image"))))
        assert ei.value.status_code == 400
        with pytest.raises(HTTPException) as ei:
            run(ops.upload_task_photo(999, photo=SUF(filename="x.jpg", file=io.BytesIO(_jpeg_bytes()))))
        assert ei.value.status_code == 404

    def test_我的任務_指派給我與未指派(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        a = make_task(srv, "RCR-7661-左後")
        b = make_task(srv, "RCG2235-右前")
        c = make_task(srv, "RCW-8382-左前")
        srv.patch_task(b["id"], srv.TaskUpdate(assignee="維修組 A"))
        srv.patch_task(c["id"], srv.TaskUpdate(assignee="維修組 B"))
        r = ops.my_tasks(x_ops_reader="維修組 A")
        ids = [t["id"] for t in r["tasks"]]
        assert b["id"] in ids and a["id"] in ids and c["id"] not in ids
        assert r["tasks"][0]["id"] == b["id"] and r["tasks"][0]["mine"] is True
        srv.patch_task(b["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(b["id"], srv.TaskUpdate(status="completed"))
        assert b["id"] not in [t["id"] for t in ops.my_tasks(x_ops_reader="維修組 A")["tasks"]]

    def test_方言層_sqlite不改寫(self, ops, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        assert ops.ops_db.sql("INSERT OR IGNORE INTO x VALUES (?)") == "INSERT OR IGNORE INTO x VALUES (?)"
        monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
        assert ops.ops_db.dialect() == "postgres"
        assert ops.ops_db.sql("SELECT * FROM x WHERE a=?") == "SELECT * FROM x WHERE a=%s"


# ---------- 流程修正：孤兒清理、防搶單、完工照守門、逾時升級、自動指派、一致率 ----------

class TestFlowFixes:
    def test_Demo重置後事件與紀錄跟著清(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        import io
        from starlette.datastructures import UploadFile as SUF
        r = run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes()))))
        f = tmp_path / "photos" / str(t["id"]) / r["photo"]["filename"]
        assert ops.list_events()["events"] and f.exists()
        with srv.db() as conn:   # 模擬 /api/demo/reset：直接刪任務
            conn.execute("DELETE FROM task_events WHERE task_id=?", (t["id"],))
            conn.execute("DELETE FROM tasks WHERE id=?", (t["id"],))
        assert ops.list_events()["events"] == [] and not f.exists()
        assert ops.summary()["unread"] == 0

    def test_防搶單(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 A", expected_assignee=""))
        with pytest.raises(HTTPException) as ei:
            ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 B", expected_assignee=""))
        assert ei.value.status_code == 409 and "清潔組 A" in ei.value.detail
        d = ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 B", expected_assignee="清潔組 A"))
        assert d["task"]["assignee"] == "清潔組 B"

    def test_清潔任務完工須有照片_監理台路徑也擋(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())
        t = srv.post_decision(srv.Decision(case_id="F2-RDE-0160-front", decision="confirm"))["task"]
        assert t["task_type"] == "cleaning"
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        with pytest.raises(HTTPException) as ei:
            srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))   # 監理台的 PATCH 也走同一條守門
        assert ei.value.status_code == 409 and "完工照" in ei.value.detail
        import io
        from starlette.datastructures import UploadFile as SUF
        run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes()))))
        assert srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))["status"] == "completed"

    def test_維修任務預設不強制照片_設定可改(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        ops.put_settings({"require_photo_repair": True})
        with pytest.raises(HTTPException):
            srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        ops.put_settings({"require_photo_repair": False})
        assert srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))["status"] == "completed"

    def test_逾時升級推播一次並記錄(self, srv, ops, monkeypatch):
        sent = []
        monkeypatch.setattr(srv, "send_notification", lambda p: sent.append(p) or True)
        t = make_task(srv, monkeypatch=monkeypatch)
        assert len(sent) == 1 and sent[0]["kind"] == "system_event"
        old = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        with srv.db() as conn:
            conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (old, t["id"]))
        ops.list_tasks(); ops.list_tasks()
        esc = [p for p in sent if p.get("kind") == "escalation"]
        assert len(esc) == 1 and esc[0]["event"] == "sla_overdue" and esc[0]["task_id"] == t["id"]
        d = ops.get_task(t["id"])
        assert d["notification_log"][-1]["audience"] == "escalation" and d["notification_log"][-1]["status"] == "sent"

    def test_逾時升級可關閉(self, srv, ops, monkeypatch):
        sent = []
        monkeypatch.setattr(srv, "send_notification", lambda p: sent.append(p) or True)
        ops.put_settings({"escalate_on_overdue": False})
        t = make_task(srv, monkeypatch=monkeypatch)
        old = (datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds")
        with srv.db() as conn:
            conn.execute("UPDATE tasks SET created_at=? WHERE id=?", (old, t["id"]))
        ops.list_tasks()
        assert not [p for p in sent if p.get("kind") == "escalation"]

    def test_依類型自動指派只做一次(self, srv, ops, monkeypatch):
        ops.put_settings({"default_assignee_repair": "維修組 B"})
        t = make_task(srv, monkeypatch=monkeypatch)
        got = ops.get_task(t["id"])["task"]
        assert got["assignee"] == "維修組 B" and "自動指派" in got["events"][-1]["detail"]
        srv.patch_task(t["id"], srv.TaskUpdate(assignee=""))    # 人工清掉 → 不再自動覆蓋
        assert ops.get_task(t["id"])["task"]["assignee"] in (None, "")

    def test_一致率統計(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        srv.post_decision(srv.Decision(case_id="RCR-7661-左後", decision="confirm"))   # AI found=1, 人工=1 → 一致
        srv.post_decision(srv.Decision(case_id="RCG2235-右前", decision="reject"))    # AI found=1, 人工=0 → 不一致
        a = ops.insights()["agreement"]
        assert a["n"] == 2 and a["agreed"] == 1 and a["rate"] == 0.5 and len(a["days"]) == 1

    def test_基準照只取已完成任務(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        import io
        from starlette.datastructures import UploadFile as SUF
        run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes()))))
        assert ops.car_baseline("rcr-7661")["photos"] == []
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        assert len(ops.car_baseline("RCR-7661")["photos"]) == 1
