"""環節三 整備中心 API（/api/ops）回歸測試——零 API 成本、不打網路。

覆蓋：事件流由 task_events 派生（冪等）、已讀、SLA 計算與逾時事件、任務詳情（案件快照→照片 URL）、
狀態變更走同一套狀態機、備註、人員、設定、管道狀態不外洩 URL。
"""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient


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
        assert ops.list_tasks()["tasks"][0]["sla_status"] == "overdue"
        ops.list_events(); ops.list_tasks()
        evs = [e for e in ops.list_events()["events"] if e["type"] == "sla_overdue"]
        assert len(evs) == 1 and evs[0]["task_id"] == t["id"]

    def test_設定門檻影響計算(self, srv, ops, monkeypatch):
        make_task(srv, monkeypatch=monkeypatch)
        ops.put_settings({"sla_minutes_p1": 60})
        task = ops.list_tasks()["tasks"][0]
        assert task["sla_minutes"] == 60 and task["sla_status"] == "normal"
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

    def test_人員改名同步任務與自動指派設定(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        person = next(p for p in ops.people(all=True)["people"] if p["name"] == "維修組 A")
        ops.update_task(t["id"], ops.OpsTaskUpdate(action="assign", assignee="維修組 A"))
        ops.put_settings({"default_assignee_repair": "維修組 A"})

        changed = ops.patch_person(person["id"], ops.PersonPatch(group_name="車體組", name="車體組 A"))
        assert changed["group_name"] == "車體組" and changed["name"] == "車體組 A"
        detail = ops.get_task(t["id"])["task"]
        assert detail["assignee"] == detail["assignee_name"] == "車體組 A"
        # 改名不是指派：任務時間軸不新增 assignee 事件，紀錄在 audit log
        assert sum(e["event"] == "assignee" for e in detail["events"]) == 1
        with srv.db() as conn:
            audit = conn.execute("SELECT detail FROM ops_audit_log WHERE resource='person' AND resource_id=?",
                                 (str(person["id"]),)).fetchall()
        assert any("維修組 A → 車體組 / 車體組 A" in row[0] for row in audit)
        assert ops.get_settings()["settings"]["default_assignee_repair"] == "車體組 A"
        with pytest.raises(HTTPException) as exc:
            ops.patch_person(person["id"], ops.PersonPatch(name=""))
        assert exc.value.status_code == 400

    def test_管道狀態不外洩URL(self, srv, ops):
        h = ops.ops_health()
        wh = next(c for c in h["channels"] if c["id"] == "webhook")
        assert wh["configured"] is True and "http" not in str(wh)
        assert all(c["available"] is False for c in h["channels"] if c["id"] in ("line", "sms"))

    def test_Demo登入提示只在標準Demo帳密顯示(self, srv, ops, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.delenv("IRENT_ADMIN_PASSWORD", raising=False)
        monkeypatch.delenv("IRENT_STATION_PASSWORD", raising=False)
        assert {c["username"] for c in ops.ops_health()["demo_credentials"]} == {"admin", "station"}
        monkeypatch.setenv("IRENT_ADMIN_PASSWORD", "custom-secret")
        assert {c["username"] for c in ops.ops_health()["demo_credentials"]} == {"station"}
        monkeypatch.setenv("DEMO_MODE", "false")
        assert ops.ops_health()["demo_credentials"] == []

    def test_健康檢查不依賴Gemini或Webhook(self, srv, ops, monkeypatch):
        monkeypatch.setattr(srv, "_gemini_configured", lambda: False)
        monkeypatch.delenv("NOTIFICATION_WEBHOOK_URL", raising=False)
        response = srv.health()
        body = json.loads(response.body)
        assert response.status_code == 200
        assert body == {"status": "ok", "database": "ok", "admin_ui": "ok",
                        "gemini_configured": False, "notification_configured": False}
        assert ops.ops_health()["gemini_configured"] is False

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
        srv.patch_task(t["id"], srv.TaskUpdate(action="start"))
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
        srv.patch_task(t["id"], srv.TaskUpdate(action="start"))
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
    def test_assignee_id_additive_backfill_idempotent_and_unknown_warns(self, srv, ops, monkeypatch, caplog):
        known = make_task(srv, "RCR-7661-左後", monkeypatch)
        unknown = make_task(srv, "RCR-7662-左後", monkeypatch)
        with srv.db() as conn:
            conn.execute("UPDATE tasks SET assignee='清潔組 A', assignee_id=NULL WHERE id=?", (known["id"],))
            conn.execute("UPDATE tasks SET assignee='不存在的人', assignee_id=NULL WHERE id=?", (unknown["id"],))

        first = {t["id"]: t for t in ops.list_tasks()["tasks"]}
        second = {t["id"]: t for t in ops.list_tasks()["tasks"]}  # 重複啟動／執行仍冪等
        with srv.db() as conn:
            person_id = conn.execute("SELECT id FROM ops_people WHERE name='清潔組 A'").fetchone()[0]
        assert first[known["id"]]["assignee_id"] == person_id
        assert first[known["id"]]["assignee_name"] == "清潔組 A"
        assert second[known["id"]]["assignee_id"] == person_id
        assert first[unknown["id"]]["assignee_id"] is None
        assert "migration skipped" in caplog.text and "不存在的人" in caplog.text

    def test_assign_api_uses_stable_id_and_dual_writes_name(self, srv, ops, monkeypatch):
        task = make_task(srv, monkeypatch=monkeypatch)
        people = ops.people()["people"]
        person = next(p for p in people if p["name"] == "維修組 A")
        detail = ops.update_task(
            task["id"], ops.OpsTaskUpdate(action="assign", assignee_id=person["id"]))["task"]
        assert detail["assignee_id"] == person["id"]
        assert detail["assignee_name"] == detail["assignee"] == "維修組 A"

    def test_Demo重置後事件與紀錄跟著清(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        srv.patch_task(t["id"], srv.TaskUpdate(action="start"))
        import io
        from starlette.datastructures import UploadFile as SUF
        r = run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes()))))
        f = tmp_path / "photos" / str(t["id"]) / r["photo"]["filename"]
        assert ops.list_events()["events"] and f.exists()
        assert srv.demo_reset()["ok"] is True
        # 不依賴下一次 Ops API 的 lazy purge；reset 回傳時 metadata 與檔案都已清除。
        with srv.db() as conn:
            assert conn.execute("SELECT count(*) FROM ops_events WHERE task_id=?", (t["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM task_photos WHERE task_id=?", (t["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM notification_log WHERE task_id=?", (t["id"],)).fetchone()[0] == 0
        assert not f.exists()
        assert ops.list_events()["events"] == []
        assert ops.summary()["unread"] == 0
        assert ops.car_baseline("RCR-7661")["photos"] == []

    def test_防搶單(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 A", expected_assignee=""))
        with pytest.raises(HTTPException) as ei:
            ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 B", expected_assignee=""))
        assert ei.value.status_code == 409 and "清潔組 A" in ei.value.detail
        d = ops.update_task(t["id"], ops.OpsTaskUpdate(assignee="清潔組 B", expected_assignee="清潔組 A"))
        assert d["task"]["assignee"] == "清潔組 B"

    def test_兩人同時claim只有一人成功(self, srv, ops, monkeypatch):
        t = make_task(srv, monkeypatch=monkeypatch)
        barrier = Barrier(2)

        def claim(reader):
            barrier.wait()
            try:
                result = ops.update_task(t["id"], ops.OpsTaskUpdate(action="claim"),
                                         x_ops_reader=reader)
                return "ok", result["task"]["assignee"]
            except HTTPException as exc:
                return "error", exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, ("worker-a", "worker-b")))

        assert sorted(kind for kind, _ in results) == ["error", "ok"]
        assert next(value for kind, value in results if kind == "error") == 409
        winner = next(value for kind, value in results if kind == "ok")
        detail = ops.get_task(t["id"])["task"]
        assert detail["assignee"] == winner
        assert sum(e["event"] == "assignee" for e in detail["events"]) == 1

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
        srv.patch_task(t["id"], srv.TaskUpdate(action="start"))
        import io
        from starlette.datastructures import UploadFile as SUF
        run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes()))))
        assert ops.car_baseline("rcr-7661")["photos"] == []
        srv.patch_task(t["id"], srv.TaskUpdate(action="complete"))
        assert len(ops.car_baseline("RCR-7661")["photos"]) == 1

    def test_環節三核心流程與後端能力完整閉環(self, srv, ops, monkeypatch, tmp_path):
        """Backend integration acceptance：不呼叫 Gemini，覆蓋 Demo 的整條關鍵路徑。"""
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())

        created = srv.post_decision(
            srv.Decision(case_id="F2-RDE-0160-front", decision="confirm"))["task"]
        task_id = created["id"]

        # Admin 看得到任務；Mobile/UI 所需規則由後端提供。
        pending = next(t for t in ops.list_tasks()["tasks"] if t["id"] == task_id)
        assert pending["status"] == "pending"
        assert {"claim", "start"} <= set(pending["allowed_actions"])
        assert pending["completion_requirements"] == {
            "photo_required": True, "photo_count": 0, "satisfied": False,
            "message": "完工前需至少一張完工照",
        }

        claimed = ops.update_task(task_id, ops.OpsTaskUpdate(action="claim"),
                                  x_ops_reader="%E6%B8%85%E6%BD%94%E7%B5%84%20A")["task"]
        assert claimed["assignee"] == "清潔組 A"
        started = ops.update_task(task_id, ops.OpsTaskUpdate(action="start"))["task"]
        assert started["status"] == "in_progress"
        assert "upload_photo" in started["allowed_actions"]
        assert "complete" not in started["allowed_actions"]

        import io
        from starlette.datastructures import UploadFile as SUF
        uploaded = run(ops.upload_task_photo(
            task_id, photo=SUF(filename="done.jpg", file=io.BytesIO(_jpeg_bytes())),
            x_ops_reader="%E6%B8%85%E6%BD%94%E7%B5%84%20A"))
        assert uploaded["task"]["completion_requirements"]["satisfied"] is True
        assert "complete" in uploaded["task"]["allowed_actions"]

        completed = ops.update_task(task_id, ops.OpsTaskUpdate(action="complete"))["task"]
        assert completed["status"] == "completed" and completed["resolved_at"]
        events = [event["event"] for event in completed["events"]]
        for required in ("created", "assignee", "photo"):
            assert required in events
        assert events.count("status") == 2

        baseline = ops.car_baseline("RDE-0160")["photos"]
        assert len(baseline) == 1 and baseline[0]["task_id"] == task_id
        fleet_row = next(row for row in ops.fleet()["fleet"] if row["car"] == "RDE-0160")
        assert fleet_row["baseline_count"] == 1


class TestAuthenticationRBAC:
    @staticmethod
    def login(client, username, password):
        response = client.post("/api/auth/login", json={"username": username, "password": password})
        assert response.status_code == 200, response.text
        return response.json()["user"]

    def test_未登入401_admin可用_station管理API為403(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with TestClient(srv.app) as anonymous:
            assert anonymous.get("/api/ops/summary").status_code == 401

        with TestClient(srv.app) as admin:
            user = self.login(admin, "admin", "admin-demo")
            assert user["role"] == "admin"
            assert admin.get("/api/ops/settings").status_code == 200
            assert admin.put("/api/ops/settings", json={"sla_minutes_p1": 6}).status_code == 200

        with TestClient(srv.app) as station:
            user = self.login(station, "station", "station-demo")
            assert user["role"] == "station" and user["name"] == "清潔組 A"
            assert station.get("/api/ops/my-tasks").status_code == 200
            assert station.put("/api/ops/settings", json={"sla_minutes_p1": 7}).status_code == 403
            assert station.get("/api/ops/people").status_code == 403

    def test_監理台寫入與燒額度端點需admin_唯讀端點不擋(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        guarded = [("post", "/api/judge"), ("post", "/api/gate"), ("get", "/api/live_cases"),
                   ("post", "/api/live_case"), ("delete", "/api/live_case/x"),
                   ("post", "/api/decision"), ("get", "/api/tasks")]
        with TestClient(srv.app) as anonymous:
            for method, path in guarded:
                assert getattr(anonymous, method)(path).status_code == 401, path
            assert anonymous.get("/api/health").status_code == 200
            assert anonymous.get("/api/ops/health").status_code == 200
            assert anonymous.get("/api/labels/stats").status_code == 200
        with TestClient(srv.app) as station:
            self.login(station, "station", "station-demo")
            for method, path in guarded:
                assert getattr(station, method)(path).status_code == 403, path

    def test_station名稱不在People時啟動自動建立並連結(self, srv, monkeypatch, caplog):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setenv("IRENT_STATION_NAME", "夜班組 Z")
        with TestClient(srv.app) as station:
            user = self.login(station, "station", "station-demo")
        assert user["name"] == "夜班組 Z" and user["person_id"] is not None
        assert "已自動建立" in caplog.text
        with srv.db() as conn:
            person = conn.execute("SELECT group_name, name FROM ops_people WHERE id=?",
                                  (user["person_id"],)).fetchone()
        assert tuple(person) == ("夜班組", "夜班組 Z")

    def test_session驗證不寫入資料庫(self, srv, monkeypatch):
        import ops_auth
        monkeypatch.setenv("DEMO_MODE", "true")
        with TestClient(srv.app) as admin:
            self.login(admin, "admin", "admin-demo")
            with srv.db() as conn:
                before = conn.execute("PRAGMA data_version").fetchone()[0]
                token = admin.cookies.get(ops_auth.COOKIE)
                for _ in range(3):
                    assert admin.get("/api/ops/summary").status_code == 200
                assert ops_auth.session_actor(token) is not None
                after = conn.execute("PRAGMA data_version").fetchone()[0]
        # summary 本身只讀；若 session 驗證或 schema 檢查偷寫入，data_version 會變
        assert before == after

    def test_station生命週期寫入可信actor且header不能偽造(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())
        task = srv.post_decision(srv.Decision(case_id="F2-RDE-0160-front", decision="confirm"))["task"]

        with TestClient(srv.app) as station:
            self.login(station, "station", "station-demo")
            headers = {"X-Ops-Reader": "forged-admin"}
            before = station.get("/api/ops/my-tasks").json()["tasks"][0]
            assert before["allowed_actions"] == ["claim"]
            assert station.patch(f"/api/ops/tasks/{task['id']}", json={"action": "start"}, headers=headers).status_code == 403
            assert station.patch(f"/api/ops/tasks/{task['id']}", json={"action": "claim"}, headers=headers).status_code == 200
            after_claim = station.get("/api/ops/my-tasks").json()["tasks"][0]
            assert "start" in after_claim["allowed_actions"] and "assign" not in after_claim["allowed_actions"]
            assert station.patch(f"/api/ops/tasks/{task['id']}", json={"action": "start"}, headers=headers).status_code == 200
            photo = {"photo": ("done.jpg", _jpeg_bytes(), "image/jpeg")}
            assert station.post(f"/api/ops/tasks/{task['id']}/photos", files=photo, headers=headers).status_code == 200
            assert station.patch(f"/api/ops/tasks/{task['id']}", json={"action": "complete"}, headers=headers).status_code == 200
            assert station.patch(f"/api/ops/tasks/{task['id']}", json={"action": "claim"}, headers=headers).status_code == 409

        detail = ops.get_task(task["id"])["task"]
        assert detail["status"] == "completed" and detail["assignee"] == "清潔組 A"
        acted = [e for e in detail["events"] if e["event"] in ("assignee", "status", "photo")]
        assert acted and all(e["actor_name"] == "清潔組 A" for e in acted)
        assert all(e["actor_role"] == "station" for e in acted)
        assert "forged-admin" not in str(acted)

    def test_admin人員與設定變更寫audit_log(self, srv, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with TestClient(srv.app) as admin:
            self.login(admin, "admin", "admin-demo")
            assert admin.post("/api/ops/people", json={"group_name": "測試組", "name": "Demo User"}).status_code == 200
            assert admin.put("/api/ops/settings", json={"sla_minutes_p2": 120}).status_code == 200
        with srv.db() as conn:
            rows = conn.execute("SELECT actor_name, actor_role, resource FROM ops_audit_log ORDER BY id").fetchall()
        assert ("營運主管", "admin", "person") in rows
        assert ("營運主管", "admin", "settings") in rows

    def test_station以person_id授權_改名後仍可完成_舊audit不改寫(
            self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setenv("DEMO_MODE", "true")
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())
        own = srv.post_decision(
            srv.Decision(case_id="F2-RDE-0160-front", decision="confirm"))["task"]
        other = srv.post_decision(
            srv.Decision(case_id="F2-RDE-0180-front", decision="confirm"))["task"]

        with TestClient(srv.app) as station:
            user = self.login(station, "station", "station-demo")
            assert user["person_id"] is not None
            assert station.patch(f"/api/ops/tasks/{own['id']}", json={"action": "claim"}).status_code == 200

            with TestClient(srv.app) as admin:
                self.login(admin, "admin", "admin-demo")
                people = admin.get("/api/ops/people").json()["people"]
                station_person = next(p for p in people if p["id"] == user["person_id"])
                assert admin.patch(
                    f"/api/ops/people/{station_person['id']}",
                    json={"name": "清潔組 改名"}).status_code == 200
                other_person = next(p for p in people if p["name"] == "清潔組 B")
                assert admin.patch(
                    f"/api/ops/tasks/{other['id']}",
                    json={"action": "assign", "assignee_id": other_person["id"]}).status_code == 200

            mine = station.get("/api/ops/my-tasks")
            assert mine.status_code == 200
            mine_task = next(t for t in mine.json()["tasks"] if t["id"] == own["id"])
            assert mine_task["mine"] and mine_task["assignee_id"] == user["person_id"]
            assert mine_task["assignee_name"] == "清潔組 改名"
            assert station.get(f"/api/ops/tasks/{own['id']}").status_code == 200
            assert station.patch(f"/api/ops/tasks/{own['id']}", json={"action": "start"}).status_code == 200
            photo = {"photo": ("done.jpg", _jpeg_bytes(), "image/jpeg")}
            assert station.post(f"/api/ops/tasks/{own['id']}/photos", files=photo).status_code == 200
            assert station.patch(f"/api/ops/tasks/{own['id']}", json={"action": "complete"}).status_code == 200

            assert station.get(f"/api/ops/tasks/{other['id']}").status_code == 403
            assert station.patch(f"/api/ops/tasks/{other['id']}", json={"action": "start"}).status_code == 403
            assert station.post(f"/api/ops/tasks/{other['id']}/photos", files=photo).status_code == 403
            assert station.patch(f"/api/ops/tasks/{other['id']}", json={"action": "complete"}).status_code == 403

        detail = ops.get_task(own["id"])["task"]
        lifecycle = [e for e in detail["events"] if e["event"] in ("assignee", "status", "photo")]
        assert lifecycle[0]["actor_name"] == "清潔組 A"  # 改名前 snapshot 不回寫
        assert lifecycle[0]["actor_id"] == user["id"]
        assert all(e["actor_id"] == user["id"] for e in lifecycle if e["actor_role"] == "station")
        assert any(e["actor_name"] == "清潔組 改名" for e in lifecycle[1:])
        with srv.db() as conn:
            photo_actor = conn.execute(
                "SELECT actor_id, actor_name, actor_role FROM task_photos WHERE task_id=?", (own["id"],)).fetchone()
        assert tuple(photo_actor) == (user["id"], "清潔組 改名", "station")

    def test_login_rate_limit_logout_revoke_and_demo_credentials(self, srv, monkeypatch):
        import ops_auth
        ops_auth._login_failures.clear()
        monkeypatch.setenv("DEMO_MODE", "true")
        with TestClient(srv.app) as client:
            for _ in range(ops_auth.LOGIN_MAX_FAILURES):
                assert client.post("/api/auth/login", json={
                    "username": "admin", "password": "wrong"}).status_code == 401
            limited = client.post("/api/auth/login", json={
                "username": "admin", "password": "admin-demo"})
            assert limited.status_code == 429 and limited.headers["retry-after"] == "60"

        ops_auth._login_failures.clear()
        with TestClient(srv.app) as client:
            self.login(client, "admin", "admin-demo")
            old_token = client.cookies.get(ops_auth.COOKIE)
            assert old_token
            assert client.post("/api/auth/logout").status_code == 200
            assert client.get("/api/auth/me", headers={
                "Cookie": f"{ops_auth.COOKIE}={old_token}"}).status_code == 401

        monkeypatch.setenv("DEMO_MODE", "false")
        monkeypatch.setenv("IRENT_ADMIN_USERNAME", "admin")
        monkeypatch.setenv("IRENT_ADMIN_PASSWORD", "admin-demo")
        monkeypatch.setenv("IRENT_STATION_USERNAME", "station")
        monkeypatch.setenv("IRENT_STATION_PASSWORD", "station-demo")
        with TestClient(srv.app) as client:
            assert client.post("/api/auth/login", json={
                "username": "admin", "password": "admin-demo"}).status_code == 401
            assert client.post("/api/auth/login", json={
                "username": "station", "password": "station-demo"}).status_code == 401
        ops_auth._login_failures.clear()


# ---------- 完工照 → 現場實測的借車基準照 ----------

class TestBaselineInJudge:
    def _done_with_photo(self, srv, ops, monkeypatch, tmp_path):
        monkeypatch.setattr(ops, "PHOTO_ROOT", tmp_path / "photos")
        t = make_task(srv, monkeypatch=monkeypatch)
        srv.patch_task(t["id"], srv.TaskUpdate(action="start"))
        import io
        from starlette.datastructures import UploadFile as SUF
        run(ops.upload_task_photo(t["id"], photo=SUF(filename="a.jpg", file=io.BytesIO(_jpeg_bytes(640, 480)))))
        srv.patch_task(t["id"], srv.TaskUpdate(action="complete"))
        return t

    def test_latest_baseline(self, srv, ops, monkeypatch, tmp_path):
        assert ops.latest_baseline("RCR-7661") is None
        t = self._done_with_photo(srv, ops, monkeypatch, tmp_path)
        b = ops.latest_baseline("rcr-7661")
        assert b["task_id"] == t["id"] and b["bytes"][:2] == b"\xff\xd8" and b["url"].endswith(".jpg")

    def test_gate用完工照當借車基準(self, srv, ops, monkeypatch, tmp_path):
        self._done_with_photo(srv, ops, monkeypatch, tmp_path)
        import io
        from starlette.datastructures import UploadFile as SUF
        r = run(srv.api_gate(mode="pair", pickup=None, ret=SUF(filename="r.jpg", file=io.BytesIO(_jpeg_bytes(640, 480))),
                             interior=None, baseline_car="RCR-7661"))
        assert set(r["gate"]) == {"pickup", "return"} and r["baseline"]["source"] == "completion_photo"
        assert r["baseline"]["car"] == "RCR-7661" and "bytes" not in r["baseline"]

    def test_沒完工照時404_未給車牌仍要求上傳(self, srv, ops, monkeypatch, tmp_path):
        import io
        from starlette.datastructures import UploadFile as SUF
        ret = SUF(filename="r.jpg", file=io.BytesIO(_jpeg_bytes()))
        with pytest.raises(HTTPException) as ei:
            run(srv.api_gate(mode="pair", pickup=None, ret=ret, interior=None, baseline_car="ZZZ-9999"))
        assert ei.value.status_code == 404
        with pytest.raises(HTTPException) as ei:
            run(srv.api_gate(mode="pair", pickup=None, ret=ret, interior=None, baseline_car=None))
        assert ei.value.status_code == 400
