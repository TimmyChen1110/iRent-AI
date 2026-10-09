"""取消還車（任何未完成階段）、過期 AI 結果防護、分析逾時／進度／並行（零 Gemini API 成本）。

對應 2026-10-09 三個問題的修復：
  ① 還車流程中任何尚未 RETURNED 的階段都能取消還車 → RENTED；正在跑的分析結果不得寫回。
  ② 還車分析 4 角＋車內並行、整次分析有總期限、App 可讀進度；judge_photos._call 對 504 逾時重送。
"""
import threading
import time

import pytest

from test_rental_sessions import (  # noqa: F401  （fixtures 需要 import 進來才會被 pytest 找到）
    ANGLES, FIXTURE_VEHICLE, PIPELINE_VEHICLE, admin, client, drive_to_photo_inspection, shoot, srv, upload,
)

CLEAN_PAIR = {"final": {"angle_match": True, "new_damage_found": False, "damages": [],
                        "no_damage_confidence": 0.95, "pre_existing_notes": ""}}
CLEAN_INTERIOR = {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 95}


def session(client, sid):
    return client.get(f"/v1/rental-sessions/{sid}").json()


def admin_cases(car):
    import ops_api
    return [c for c in ops_api.list_cases(car=car)["cases"] if c["source"] == "mobile_inspection"]


@pytest.fixture()
def key(monkeypatch):
    import run_eval_gemini
    monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "test-key")


@pytest.fixture()
def threaded_runner(monkeypatch):
    """分析改回背景執行緒（與正式環境相同），測試可以在分析途中操作。"""
    import rental_inspections as ri
    threads = []

    def spawn(rid):
        t = threading.Thread(target=ri.run_analysis, args=(rid,), daemon=True)
        threads.append(t)
        t.start()
    monkeypatch.setattr(ri, "ANALYSIS_RUNNER", spawn)
    return threads


def wait_for(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class TestCancelReturnAnyStage:
    def test_檢測完成後_取消還車_回到租用中_案件清除_可重新還車(self, client):
        s = drive_to_photo_inspection(client)            # 固定劇本車：右後新損 + 車內髒汙
        sid = s["session_id"]
        shoot(client, s, "return", 30)
        assert session(client, sid)["state"] == "INSPECTION_COMPLETED"
        assert len(admin_cases("ABC-1234")) == 2
        j = client.post(f"/v1/rental-sessions/{sid}/return/cancel").json()
        assert j["state"] == "RENTED" and j["vehicle"]["status"] == "RENTED"    # 訂單不結束、車不回可租
        assert j["return"]["received"] == [] and j["analysis"] == "pending" and j["end_odometer_km"] is None
        assert j["started_at"] == s["started_at"] and j["pickup"]["complete"]   # 取車基準保留
        assert admin_cases("ABC-1234") == []                                   # 不留「租用中卻有還車案件」
        assert client.get("/v1/rental-sessions/active").json()["session"]["session_id"] == sid
        # 取消後再走一次完整還車
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 20})
        shoot(client, s, "return", 60)
        assert session(client, sid)["state"] == "INSPECTION_COMPLETED"
        done = client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()
        assert done["state"] == "RETURNED" and done["end_odometer_km"] == s["start_odometer_km"] + 20

    def test_檢測失敗後_取消還車(self, client, monkeypatch):
        import run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: None)
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        shoot(client, s, "return", 30)
        assert session(client, s["session_id"])["state"] == "INSPECTION_FAILED"
        j = client.post(f"/v1/rental-sessions/{s['session_id']}/return/cancel").json()
        assert j["state"] == "RENTED" and j["last_error"] is None and j["inspection_attempts"] == 0

    def test_已還車完成_不可取消(self, client):
        s = drive_to_photo_inspection(client)
        shoot(client, s, "return", 30)
        client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return")
        r = client.post(f"/v1/rental-sessions/{s['session_id']}/return/cancel")
        assert r.status_code == 409

    def test_取消後_手機佇列補傳的舊還車照_被拒(self, client):
        s = drive_to_photo_inspection(client)
        assert upload(client, s, "return", "左前", 31).status_code == 201
        client.post(f"/v1/rental-sessions/{s['session_id']}/return/cancel")
        r = upload(client, s, "return", "右前", 32)
        assert r.status_code == 409 and "還車" in r.json()["detail"]
        assert session(client, s["session_id"])["return"]["received"] == []


class TestStaleAnalysis:
    def test_分析進行中取消還車_過期結果不寫回_不會再觸發檢測完成(self, client, key, threaded_runner, monkeypatch):
        import judge_photos
        import rental_inspections as ri
        release = threading.Event()

        def slow_pair(p, r, angle=None, **kw):
            release.wait(5)
            dmg = [{"location": "右後保險桿", "type": "刮痕", "severity": "high", "confidence": 0.95,
                    "reasoning": "x", "box_2d": [1, 2, 3, 4]}]
            return ({"final": {"angle_match": True, "new_damage_found": True, "damages": dmg,
                               "no_damage_confidence": 0, "pre_existing_notes": ""}}, None)
        monkeypatch.setattr(judge_photos, "judge_pair", slow_pair)
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (CLEAN_INTERIOR, None))
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        sid, rid = s["session_id"], s["rental_id"]
        shoot(client, s, "return", 30, mode="coreml")
        assert wait_for(lambda: (ri.get_rental(rid) or {}).get("status") == "ANALYZING")
        # 分析中：App 讀得到進度（車內已完成 1 / 5）
        assert wait_for(lambda: (session(client, sid)["analysis_progress"] or {}).get("done") == 1)
        prog = session(client, sid)["analysis_progress"]
        assert prog["total"] == 5 and prog["elapsed_s"] is not None
        j = client.post(f"/v1/rental-sessions/{sid}/return/cancel").json()
        assert j["state"] == "RENTED"
        release.set()
        for t in threaded_runner:
            t.join(5)
        # 舊分析跑完了，但結果被丟棄：租約仍是取車完成、沒有比對結果、沒有案件、Session 仍租用中
        assert ri.get_rental(rid)["status"] == "PICKUP_COMPLETE"
        assert all(c["result"] is None for c in ri.inspection_detail(rid)["comparisons"]) and ri.incident_case_ids(rid) == []
        assert session(client, sid)["state"] == "RENTED"

    def test_排隊中的分析在租約已退回後直接略過(self, client, key, monkeypatch):
        import judge_photos
        import rental_inspections as ri
        calls = []
        monkeypatch.setattr(judge_photos, "judge_pair", lambda *a, **k: calls.append(1) or (CLEAN_PAIR, None))
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        assert ri.run_analysis(s["rental_id"]) is None          # 租約是 PICKUP_COMPLETE，不是 RETURN_COMPLETE
        assert calls == [] and ri.get_rental(s["rental_id"])["status"] == "PICKUP_COMPLETE"


class TestAnalysisPerformance:
    def test_四角同時判定(self, client, key, monkeypatch):
        """四個角度必須同時在跑：Barrier(4) 依序執行會逾時 → 分析失敗。"""
        import judge_photos
        barrier = threading.Barrier(4, timeout=3)

        def pair(p, r, angle=None, **kw):
            barrier.wait()
            assert kw.get("parallel_votes") is True and kw.get("throttle") is not None and kw.get("client") is not None
            return (CLEAN_PAIR, None)
        monkeypatch.setattr(judge_photos, "judge_pair", pair)
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (CLEAN_INTERIOR, None))
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        shoot(client, s, "return", 30, mode="coreml")
        j = session(client, s["session_id"])
        assert j["state"] == "INSPECTION_COMPLETED", j["last_error"]
        res = client.get(f"/v1/rental-sessions/{s['session_id']}/inspection").json()
        assert [c["angle"] for c in res["comparisons"]] == list(ANGLES)       # 結果順序固定

    def test_超過總期限_檢測失敗_可重新檢測成功(self, client, key, monkeypatch):
        import judge_photos
        import rental_inspections as ri
        monkeypatch.setattr(ri, "ANALYSIS_DEADLINE_S", 0.3)
        slow = {"on": True}

        def pair(p, r, angle=None, **kw):
            if slow["on"] and angle == "右後":
                time.sleep(1.0)
            return (CLEAN_PAIR, None)
        monkeypatch.setattr(judge_photos, "judge_pair", pair)
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (CLEAN_INTERIOR, None))
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        sid = s["session_id"]
        shoot(client, s, "return", 30, mode="coreml")
        j = session(client, sid)
        assert j["state"] == "INSPECTION_FAILED" and "右後" in j["last_error"] and "秒" in j["last_error"]
        slow["on"] = False
        j = client.post(f"/v1/rental-sessions/{sid}/inspection/retry", json={"mode": "reanalyze"}).json()
        assert j["state"] == "INSPECTION_COMPLETED"
        time.sleep(1.1)                  # 第一次逾時的那個呼叫在背景跑完：不得覆寫第二次的結果
        assert session(client, sid)["state"] == "INSPECTION_COMPLETED"


class TestJudgePhotosRetryAndVotes:
    def test_504逾時會重送(self, monkeypatch):
        import judge_photos as jp
        from google.genai import errors
        monkeypatch.setattr(jp.time, "sleep", lambda s: None)
        attempts = []

        class Models:
            def generate_content(self, **kw):
                attempts.append(1)
                if len(attempts) == 1:
                    raise errors.ServerError(504, {"error": {"code": 504, "message": "Deadline expired", "status": "DEADLINE_EXCEEDED"}})
                return type("R", (), {"parsed": "ok"})()

        client = type("C", (), {"models": Models()})()
        throttle = type("T", (), {"wait": lambda self: None})()
        assert jp._call(client, "m", [], "sys", None, throttle) == ("m", "ok") and len(attempts) == 2

    def test_Pro複核三票同時送出_多數決與依序一致(self, monkeypatch, tmp_path):
        import judge_photos as jp
        from PIL import Image
        for n in ("a.jpg", "b.jpg"):
            Image.new("RGB", (64, 48), (90, 90, 90)).save(tmp_path / n)
        monkeypatch.setattr(jp, "_run_gate", lambda photos, interior=False: {k: {"pass": True, "reasons": []} for k in photos})
        screening = {"angle_match": True, "new_damage_found": True, "no_damage_confidence": 0, "pre_existing_notes": "",
                     "damages": [{"location": "右後", "type": "刮痕", "severity": "low", "confidence": 0.6,
                                  "reasoning": "r", "box_2d": [1, 2, 3, 4]}]}
        no = {**screening, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.9}

        def run(parallel):
            barrier = threading.Barrier(3, timeout=2) if parallel else None
            seq = iter([screening, screening, no, no] if not parallel else [screening])
            votes = iter([screening, no, no])
            lock = threading.Lock()

            def fake_call(client, model, contents, system, schema, throttle, retries=3, fallback=None):
                if model == jp.SCREEN_MODEL:
                    return model, type("P", (), {"model_dump": lambda self, v=next(seq): v})()
                if barrier:
                    with lock:
                        v = next(votes)
                    barrier.wait()          # 三票必須同時在等待 → 證明並行
                else:
                    v = next(seq)
                return model, type("P", (), {"model_dump": lambda self, v=v: v})()
            monkeypatch.setattr(jp, "_call", fake_call)
            res, _ = jp.judge_pair(tmp_path / "a.jpg", tmp_path / "b.jpg", client=object(), parallel_votes=parallel)
            return res
        seq_res, par_res = run(False), run(True)
        assert seq_res["cascade"]["votes"] == [True, False, False] and par_res["cascade"]["votes"] == [True, False, False]
        assert seq_res["final"]["new_damage_found"] is False and par_res["final"]["new_damage_found"] is False
