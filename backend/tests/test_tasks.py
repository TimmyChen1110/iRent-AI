"""整備任務閉環（環節三）回歸測試——零 API 成本。

覆蓋：confirm 自動開單（維修／清潔）、reject/retake 不開單、重複 confirm 冪等、
狀態機 pending → in_progress → completed（resolved_at）、指派、篩選、
undo 取消待處理任務、舊資料庫自動遷移。
AI 判定一律用 mock 快照（monkeypatch _case_snapshot），不呼叫 Gemini。
"""
import sqlite3

import pytest
from fastapi import HTTPException


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    import server
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    return server


def snap_pair(found=True):
    """借還比對案件的 AI 判定快照（mock，格式同 _case_snapshot）。"""
    dmgs = [{"location": "右前保險桿", "type": "刮痕", "severity": "medium",
             "confidence": 0.97, "reasoning": "還車照可見白色刮痕，借車照對應位置無"}] if found else []
    return {"mode": "pair", "source": "dataset",
            "ai_found": int(found), "ai_level": "P1" if found else "P3", "ai_conf": 0.97,
            "photos": {}, "boxes": [],
            "assessment": {"new_damage_found": found, "damages": dmgs}}


def snap_interior():
    """車內髒汙案件的 AI 判定快照（mock）。"""
    return {"mode": "interior", "source": "live",
            "ai_found": 1, "ai_level": "P1", "ai_conf": 0.9,
            "photos": {}, "boxes": [],
            "assessment": {"level": "髒汙", "confidence": 0.9, "score": 42,
                           "issues": ["垃圾", "飲料杯瓶"], "reasoning": "後座明顯垃圾與飲料杯"}}


def confirm(srv, case_id, snap):
    return srv.post_decision(srv.Decision(case_id=case_id, decision="confirm"))


# ---------- confirm → 自動開單 ----------

class TestAutoCreate:
    def test_confirm新車損_建立repair(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        out = confirm(srv, "RCR-7661-左後", snap_pair())
        t = out["task"]
        assert t["task_type"] == "repair"
        assert t["status"] == "pending"
        assert t["priority"] == "P1"
        assert t["car"] == "RCR-7661"
        assert "右前保險桿" in t["title"] and "維修" in t["title"]
        assert "刮痕" in t["description"]          # 引用 AI 判定原文
        assert t["events"][0]["event"] == "created"

    def test_confirm髒汙_建立cleaning(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())
        out = confirm(srv, "LIVE-0905-120000", snap_interior())
        t = out["task"]
        assert t["task_type"] == "cleaning"
        assert t["title"] == "車內清潔"
        assert t["car"] == "LIVE"
        assert "垃圾" in t["description"] and "42/100" in t["description"]

    def test_車牌含連字號的案件id解析(self, srv, monkeypatch):
        # 真實 F2 id 形如 F2-RDE-0160-front（車牌本身含連字號）
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_interior())
        t = confirm(srv, "F2-RDE-0160-front", snap_interior())["task"]
        assert t["car"] == "RDE-0160"
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        t2 = confirm(srv, "CHAIN-RDE-0180-右後", snap_pair())["task"]
        assert t2["car"] == "RDE-0180"

    def test_reject不建立task(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        out = srv.post_decision(srv.Decision(case_id="RCR-7661-左後", decision="reject"))
        assert out["task"] is None
        assert srv.get_tasks()["tasks"] == []

    def test_retake不建立task(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        out = srv.post_decision(srv.Decision(case_id="RCR-7661-左後", decision="retake"))
        assert out["task"] is None
        assert srv.get_tasks()["tasks"] == []

    def test_重複confirm不重複開單(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        t1 = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        t2 = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        assert t1["id"] == t2["id"]
        assert len(srv.get_tasks()["tasks"]) == 1

    def test_AI無損但人工confirm_仍開維修單(self, srv, monkeypatch):
        # confirm 的語意是「人工確認有損」，即使 AI 沒抓到也要有人去修
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair(found=False))
        t = confirm(srv, "RCG2235-右前", snap_pair(found=False))["task"]
        assert t["task_type"] == "repair"
        assert "人工複核判定" in t["description"]

    def test_confirm建單失敗時裁決與事件一併回滾(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        monkeypatch.setattr(srv, "_ensure_task",
                            lambda *args: (_ for _ in ()).throw(RuntimeError("disk full")))
        with pytest.raises(HTTPException) as exc:
            confirm(srv, "RCR-7661-左後", snap_pair())
        assert exc.value.status_code == 500
        with srv.db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM decision_events").fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


# ---------- 狀態機 ----------

class TestStatusFlow:
    def _make(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        return confirm(srv, "RCR-7661-左後", snap_pair())["task"]

    def test_pending_to_in_progress_to_completed(self, srv, monkeypatch):
        t = self._make(srv, monkeypatch)
        t = srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        assert t["status"] == "in_progress" and t["resolved_at"] is None
        t = srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        assert t["status"] == "completed" and t["resolved_at"]

    def test_completed重開清掉resolved_at(self, srv, monkeypatch):
        t = self._make(srv, monkeypatch)
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))
        t = srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        assert t["status"] == "in_progress" and t["resolved_at"] is None

    def test_非法跳轉被拒(self, srv, monkeypatch):
        t = self._make(srv, monkeypatch)
        with pytest.raises(HTTPException) as e:
            srv.patch_task(t["id"], srv.TaskUpdate(status="completed"))  # pending 不可直接完成
        assert e.value.status_code == 400

    def test_非法status值被拒(self, srv, monkeypatch):
        t = self._make(srv, monkeypatch)
        with pytest.raises(HTTPException):
            srv.patch_task(t["id"], srv.TaskUpdate(status="done"))

    def test_不存在的任務404(self, srv):
        with pytest.raises(HTTPException) as e:
            srv.patch_task(9999, srv.TaskUpdate(status="in_progress"))
        assert e.value.status_code == 404

    def test_狀態變更有歷程(self, srv, monkeypatch):
        t = self._make(srv, monkeypatch)
        t = srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        assert any(e["event"] == "status" and "in_progress" in (e["detail"] or "")
                   for e in t["events"])


# ---------- 指派 ----------

class TestAssign:
    def test_assignee可更新且留歷程(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        t = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        t = srv.patch_task(t["id"], srv.TaskUpdate(assignee="維修組 A"))
        assert t["assignee"] == "維修組 A"
        assert any(e["event"] == "assignee" for e in t["events"])
        t = srv.patch_task(t["id"], srv.TaskUpdate(assignee="維修組 B"))
        assert t["assignee"] == "維修組 B"


# ---------- 查詢與篩選 ----------

class TestFilters:
    def _seed(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid:
                            snap_interior() if cid.startswith("F2-") else snap_pair())
        confirm(srv, "RCR-7661-左後", snap_pair())
        confirm(srv, "F2-RDE-0160-front", snap_interior())

    def test_filter(self, srv, monkeypatch):
        self._seed(srv, monkeypatch)
        assert len(srv.get_tasks()["tasks"]) == 2
        assert len(srv.get_tasks(task_type="cleaning")["tasks"]) == 1
        assert len(srv.get_tasks(status="pending")["tasks"]) == 2
        assert len(srv.get_tasks(priority="P1")["tasks"]) == 2
        assert srv.get_tasks(status="completed")["tasks"] == []

    def test_排序_待處理在前(self, srv, monkeypatch):
        self._seed(srv, monkeypatch)
        first = srv.get_tasks()["tasks"][0]
        srv.patch_task(first["id"], srv.TaskUpdate(status="in_progress"))
        srv.patch_task(first["id"], srv.TaskUpdate(status="completed"))
        tasks = srv.get_tasks()["tasks"]
        assert tasks[0]["status"] == "pending" and tasks[-1]["status"] == "completed"


# ---------- undo 與冪等喚回 ----------

class TestUndo:
    def test_undo取消pending任務_再confirm喚回(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        t = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        srv.delete_decision("RCR-7661-左後")
        assert srv.get_tasks(status="cancelled")["tasks"][0]["id"] == t["id"]
        t2 = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        assert t2["id"] == t["id"] and t2["status"] == "pending"
        assert any(e["event"] == "reopened" for e in t2["events"])

    def test_undo不動處理中的任務(self, srv, monkeypatch):
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        t = confirm(srv, "RCR-7661-左後", snap_pair())["task"]
        srv.patch_task(t["id"], srv.TaskUpdate(status="in_progress"))
        srv.delete_decision("RCR-7661-左後")
        assert srv.get_tasks()["tasks"][0]["status"] == "in_progress"


# ---------- 舊資料庫相容 ----------

class TestMigration:
    def test_舊DB只有decisions表也能啟動(self, srv, tmp_path, monkeypatch):
        old = tmp_path / "old.sqlite3"
        conn = sqlite3.connect(old)
        conn.execute("CREATE TABLE decisions(case_id TEXT PRIMARY KEY, decision TEXT, decided_at TEXT)")
        conn.execute("INSERT INTO decisions VALUES ('X-左後', 'confirm', '2026-08-01T00:00:00')")
        conn.commit()
        conn.close()
        monkeypatch.setattr(srv, "DB_PATH", old)
        assert srv.get_tasks()["tasks"] == []          # 缺表自動建立，不爆
        monkeypatch.setattr(srv, "_case_snapshot", lambda cid: snap_pair())
        out = confirm(srv, "RCR-7661-左後", snap_pair())
        assert out["task"]["task_type"] == "repair"    # 舊 DB 上完整流程可用
        assert srv.get_decisions()["X-左後"] == "confirm"  # 舊資料仍在
