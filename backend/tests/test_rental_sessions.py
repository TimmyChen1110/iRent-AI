"""模擬租還車 Session 的 End-to-End 回歸測試（零 Gemini API 成本）。

AVAILABLE → PICKUP_INSPECTION → RENTED → RETURN_INITIATED → PHOTO_INSPECTION → INSPECTION_COMPLETED → RETURNED，
以及：重複租車、里程驗證、檢測失敗重試、車牌手動輸入／不一致、Demo 重置、狀態恢復。
"""
import hashlib
import io
import json

import pytest
from fastapi.testclient import TestClient
from PIL import Image


@pytest.fixture()
def srv(tmp_path, monkeypatch):
    import server
    import rental_inspections as ri
    import rental_sessions as rs
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(server, "send_notification", lambda payload: True)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(ri.paths, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(ri, "ANALYSIS_RUNNER", ri.run_analysis)   # 同步跑分析
    ri.reset_schema_cache()
    rs.reset_schema_cache()
    ri.ensure_registered_rentals()
    rs.ensure_vehicles()
    return server


@pytest.fixture()
def client(srv):
    return TestClient(srv.app)


@pytest.fixture()
def admin(srv):
    """內部開發工具（/api/ops/devtools）需要 admin 登入；lifespan 才會 seed 帳號，所以用 with。"""
    with TestClient(srv.app) as c:
        r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-demo"})
        assert r.status_code == 200, r.text
        yield c


DEV = "/api/ops/devtools"


def vehicle_of(admin, vehicle_id):
    return next(v for v in admin.get(f"{DEV}/vehicles").json()["vehicles"] if v["vehicle_id"] == vehicle_id)


FIXTURE_VEHICLE = "SIM-ABC-1234"   # 示範固定劇本（demo fixture）
PIPELINE_VEHICLE = "SIM-RCG-2235"  # 真實 pipeline（測試中 mock judge）
ANGLES = ["左前", "右前", "左後", "右後"]
CODES = {"左前": "FRONT_LEFT", "右前": "FRONT_RIGHT", "左後": "REAR_LEFT", "右後": "REAR_RIGHT", "車內": "INTERIOR"}


def jpeg(seed: int) -> bytes:
    im = Image.new("RGB", (800, 600), (seed % 255, 120, 80))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def upload(client, session, stage, view, seed, *, plate=None, confirmation=None, mode="demo"):
    data = jpeg(seed)
    sha = hashlib.sha256(data).hexdigest()
    plate = plate or session["vehicle"]["plate"]
    form = {"rental_id": session["rental_id"], "car_id": session["vehicle"]["vehicle_id"],
            "expected_plate": session["vehicle"]["plate"], "stage": stage, "view": view,
            "recognized_plate": plate, "image_sha256": sha, "captured_at": "2026-10-09T10:00:00Z",
            "local_result_json": json.dumps({"passed": True, "plateText": plate if view != "車內" else None,
                                             "plateConfidence": 0.95, "detectedView": view if view != "車內" else None,
                                             "viewConfidence": 0.9, "errors": [], "modelVersions": {"mode": mode}}),
            "photo_id": f"{session['session_id']}-{stage}-{view}-{seed}", "inspection_type": stage.upper(),
            "angle": CODES[view], "photo_category": "interior" if view == "車內" else "exterior",
            "validation_mode": mode}
    if confirmation:
        form["plate_confirmation"] = confirmation
    return client.post("/v1/mobile-inspections/photos", data=form, files={"photo": ("p.jpg", data, "image/jpeg")})


def shoot(client, session, stage, base=0, **kw):
    for i, v in enumerate(ANGLES):
        r = upload(client, session, stage, v, base + i, **kw)
        assert r.status_code == 201, r.text
    r = upload(client, session, stage, "車內", base + 9, **kw)
    assert r.status_code == 201, r.text
    return r.json()


def start(client, vehicle=FIXTURE_VEHICLE):
    r = client.post("/v1/rental-sessions", json={"vehicle_id": vehicle, "user_location": {"lat": 25.0, "lng": 121.5, "source": "gps"}})
    assert r.status_code == 201, r.text
    return r.json()


def drive_to_photo_inspection(client, vehicle=FIXTURE_VEHICLE, end_km=None):
    s = start(client, vehicle)
    shoot(client, s, "pickup", 10)
    s = client.post(f"/v1/rental-sessions/{s['session_id']}/pickup/complete").json()
    assert s["state"] == "RENTED"
    s = client.post(f"/v1/rental-sessions/{s['session_id']}/return/initiate", json={"user_location": {"lat": 25.0, "lng": 121.5, "source": "manual"}}).json()
    assert s["state"] == "RETURN_INITIATED"
    r = client.post(f"/v1/rental-sessions/{s['session_id']}/return/info",
                    json={"end_odometer_km": end_km if end_km is not None else s["start_odometer_km"] + 12})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["state"] == "PHOTO_INSPECTION" and s["distance_km"] == 12
    return s


class TestVehicles:
    def test_一般清單只有產品資訊_置頂推薦在前_固定劇本車不出現(self, client):
        j = client.get("/v1/rental-sessions/vehicles").json()
        assert "service_notice" in j and "不會扣款" in j["service_notice"]
        ids = [v["vehicle_id"] for v in j["vehicles"]]
        assert FIXTURE_VEHICLE not in ids and "demo-rfh-8122" not in ids          # internal：不給一般使用者
        assert ids[:2] == ["demo-rdg-9853", "demo-rfy-1753"] and PIPELINE_VEHICLE in ids
        for v in j["vehicles"]:
            assert v["status"] == "AVAILABLE" and v["odometer_km"] > 0 and v["service_notice"]
            for banned in ("ai_source", "ai_source_label", "category", "is_demo_vehicle", "details", "image_note", "data_note", "simulated"):
                assert banned not in v
        assert client.get(f"/v1/rental-sessions/vehicles/{FIXTURE_VEHICLE}").status_code == 404
        assert client.get("/v1/rental-sessions/vehicles/nope").status_code == 404

    def test_內部工具才看得到開發資訊(self, client, admin):
        assert client.get(f"{DEV}/vehicles").status_code == 401             # 未登入
        vs = admin.get(f"{DEV}/vehicles").json()["vehicles"]
        fx = next(v for v in vs if v["vehicle_id"] == FIXTURE_VEHICLE)
        assert fx["visibility"] == "internal" and fx["ai_source"] == "demo_fixture" and "非真實" in fx["ai_source_label"]
        assert admin.get(DEV).status_code == 200 and "內部開發工具" in admin.get(DEV).text
        # station 也不行（admin-only 前綴）
        with TestClient(admin.app) as station:
            station.post("/api/auth/login", json={"username": "station", "password": "station-demo"})
            assert station.get(f"{DEV}/vehicles").status_code == 403

    def test_沒有進行中Session時active為空(self, client):
        assert client.get("/v1/rental-sessions/active").json()["session"] is None


class TestFlow:
    def test_完整流程_示範固定劇本車輛(self, client, admin):
        s = drive_to_photo_inspection(client)
        sid = s["session_id"]
        # 還車照尚未齊：不能確認還車
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").status_code == 409
        shoot(client, s, "return", 30)
        s = client.get(f"/v1/rental-sessions/{sid}").json()
        assert s["state"] == "INSPECTION_COMPLETED" and s["analysis"] == "complete"
        res = client.get(f"/v1/rental-sessions/{sid}/inspection").json()
        assert res["ai_source"] == "demo_fixture" and "非真實" in res["ai_source_label"]
        assert res["overall"] == "ISSUES" and len(res["incidents"]) == 2        # 右後新損 + 車內髒汙（固定劇本）
        assert {c["angle"]: c["result"] for c in res["comparisons"]}["右後"] == "NEW_DAMAGE"
        assert res["interior"]["result"] == "CLEANING_REQUIRED"
        assert res["plate_check"]["status"] == "MATCH"
        assert res["review_required"] is True
        # 檢測完成 ≠ 還車完成：要確認
        s = client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()
        assert s["state"] == "RETURNED" and s["returned_at"] and s["review_required"] is True
        v = vehicle_of(admin, FIXTURE_VEHICLE)
        assert v["status"] == "AVAILABLE" and v["odometer_km"] == s["end_odometer_km"]
        assert client.get("/v1/rental-sessions/active").json()["session"] is None
        # 費用試算（示範費率）存在且標示不扣款
        assert s["fee_estimate"] is None or "不會扣款" in s["fee_estimate"]["billing_note"]
        # 冪等：再確認一次不報錯、狀態不變
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()["state"] == "RETURNED"

    def test_完整流程_真實pipeline車輛_mock判定_正常不開案(self, client, monkeypatch):
        import judge_photos
        import run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "test-key")
        monkeypatch.setattr(judge_photos, "judge_pair", lambda p, r, angle=None, **kw: (
            {"final": {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.95,
                       "pre_existing_notes": ""}, "level": "flash"}, None))
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (
            {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 95}, None))
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        shoot(client, s, "return", 30, mode="coreml")
        res = client.get(f"/v1/rental-sessions/{s['session_id']}/inspection").json()
        assert res["ai_source"] == "pipeline" and res["overall"] == "PASSED" and res["incidents"] == []
        assert all(c["result"] == "NO_NEW_DAMAGE" for c in res["comparisons"])
        assert res["interior"]["result"] == "CLEAN" and res["review_required"] is False
        s = client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return").json()
        assert s["state"] == "RETURNED" and s["review_required"] is False

    def test_沒有GEMINI_KEY_檢測失敗_可重新檢測與重新拍攝(self, client, monkeypatch):
        import run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: None)
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        sid = s["session_id"]
        shoot(client, s, "return", 30)
        s = client.get(f"/v1/rental-sessions/{sid}").json()
        assert s["state"] == "INSPECTION_FAILED" and "GEMINI_API_KEY" in (s["last_error"] or "")
        res = client.get(f"/v1/rental-sessions/{sid}/inspection").json()
        assert res["overall"] == "FAILED"
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").status_code == 409
        # 重新檢測（仍然沒 key → 再次失敗，但 attempts +1）
        s = client.post(f"/v1/rental-sessions/{sid}/inspection/retry", json={"mode": "reanalyze"}).json()
        assert s["state"] == "INSPECTION_FAILED" and s["inspection_attempts"] == 2
        # 重新拍攝：還車照清空、回到 PHOTO_INSPECTION、取車基準保留
        s = client.post(f"/v1/rental-sessions/{sid}/inspection/retry", json={"mode": "retake"}).json()
        assert s["state"] == "PHOTO_INSPECTION" and s["return"]["received"] == [] and s["pickup"]["complete"]
        assert s["rental_status"] == "PICKUP_COMPLETE"
        # 補 key 後重拍 → 成功
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")
        import judge_photos
        monkeypatch.setattr(judge_photos, "judge_pair", lambda p, r, angle=None, **kw: (
            {"final": {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.9, "pre_existing_notes": ""}}, None))
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (
            {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 90}, None))
        shoot(client, s, "return", 50)
        assert client.get(f"/v1/rental-sessions/{sid}").json()["state"] == "INSPECTION_COMPLETED"


class TestGuards:
    def test_重複租車與不可租狀態(self, client, admin):
        s = start(client)
        r = client.post("/v1/rental-sessions", json={"vehicle_id": FIXTURE_VEHICLE})
        assert r.status_code == 409
        v = vehicle_of(admin, FIXTURE_VEHICLE)
        assert v["status"] == "RENTED" and v["active_session_id"] == s["session_id"]
        # 另一台車仍可租
        assert client.post("/v1/rental-sessions", json={"vehicle_id": PIPELINE_VEHICLE}).status_code == 201

    def test_取車照未齊不能開始租用(self, client):
        s = start(client)
        r = client.post(f"/v1/rental-sessions/{s['session_id']}/pickup/complete")
        assert r.status_code == 409 and "取車照片" in r.json()["detail"]

    def test_狀態順序_不能跳過(self, client):
        s = start(client)
        sid = s["session_id"]
        assert client.post(f"/v1/rental-sessions/{sid}/return/initiate").status_code == 409
        assert client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": 1}).status_code == 409
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").status_code == 409
        assert client.get("/v1/rental-sessions/none").status_code == 404

    def test_結束里程不可小於起始里程(self, client):
        s = start(client)
        shoot(client, s, "pickup", 10)
        sid = s["session_id"]
        client.post(f"/v1/rental-sessions/{sid}/pickup/complete")
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        r = client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] - 1})
        assert r.status_code == 422 and "不可小於" in r.json()["detail"]
        r = client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": "abc"})
        assert r.status_code == 422
        r = client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"]})
        assert r.status_code == 200 and r.json()["distance_km"] == 0

    def test_取消只能在取車檢查前(self, client, admin):
        s = start(client)
        sid = s["session_id"]
        assert client.post(f"/v1/rental-sessions/{sid}/cancel").json()["state"] == "CANCELLED"
        assert vehicle_of(admin, FIXTURE_VEHICLE)["status"] == "AVAILABLE"
        s2 = start(client)
        shoot(client, s2, "pickup", 10)
        client.post(f"/v1/rental-sessions/{s2['session_id']}/pickup/complete")
        assert client.post(f"/v1/rental-sessions/{s2['session_id']}/cancel").status_code == 409

    def test_重新整理後可恢復狀態(self, client):
        s = drive_to_photo_inspection(client)
        a = client.get("/v1/rental-sessions/active").json()["session"]
        assert a["session_id"] == s["session_id"] and a["state"] == "PHOTO_INSPECTION"
        assert a["end_odometer_km"] == s["end_odometer_km"] and a["used_seconds"] is not None


class TestPlateCheck:
    def test_手動輸入車牌_需人工確認(self, client):
        s = drive_to_photo_inspection(client)
        shoot(client, s, "return", 30, confirmation="manual")
        res = client.get(f"/v1/rental-sessions/{s['session_id']}/inspection").json()
        assert res["plate_check"]["status"] == "MANUAL" and res["plate_check"]["requires_manual_review"]
        assert all(p["source"] == "manual" for p in res["plate_check"]["photos"])

    def test_車牌不一致_預設拒收_使用者確認後收下並標記(self, client):
        s = drive_to_photo_inspection(client)
        r = upload(client, s, "return", "左前", 30, plate="ZZZ-9999")
        assert r.status_code == 422
        r = upload(client, s, "return", "左前", 30, plate="ZZZ-9999", confirmation="user_confirmed_mismatch")
        assert r.status_code == 201 and r.json()["plate_mismatch"] is True
        for i, v in enumerate(ANGLES[1:]):
            assert upload(client, s, "return", v, 31 + i).status_code == 201
        assert upload(client, s, "return", "車內", 39).status_code == 201
        res = client.get(f"/v1/rental-sessions/{s['session_id']}/inspection").json()
        assert res["plate_check"]["status"] == "MISMATCH" and res["review_required"] is True
        s2 = client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return").json()
        assert s2["state"] == "RETURNED" and s2["review_required"] is True

    def test_plate_confirmation非法值(self, client):
        s = drive_to_photo_inspection(client)
        assert upload(client, s, "return", "左前", 30, confirmation="whatever").status_code == 422


class TestReset:
    def test_清空Session只在內部工具_車輛回AVAILABLE(self, client, admin):
        s = drive_to_photo_inspection(client, PIPELINE_VEHICLE)
        assert client.post("/v1/rental-sessions/reset").status_code in (404, 405)       # 一般 API 已沒有重設
        assert client.post(f"{DEV}/reset-all").status_code == 401                        # 未登入
        j = admin.post(f"{DEV}/reset-all").json()
        assert j["ok"] and j["cleared_sessions"] == 1
        assert client.get("/v1/rental-sessions/active").json()["session"] is None
        assert client.get(f"/v1/rental-sessions/vehicles/{PIPELINE_VEHICLE}").json()["status"] == "AVAILABLE"
        assert client.get(f"/v1/rental-sessions/{s['session_id']}").status_code == 404

    def test_demo_health_含Session資訊(self, client, srv):
        j = srv.demo_health()   # /api/demo/health 受 ops 登入中介層保護；直接呼叫函式驗證內容
        assert "rental_sessions" in j and j["rental_sessions"]["active_sessions"] == 0


class TestAdminIntegration:
    def test_模擬租約出現在管理者檢查紀錄且標示demo(self, client, srv):
        import rental_inspections as ri
        s = drive_to_photo_inspection(client)
        shoot(client, s, "return", 30)
        items = ri.list_inspections()
        mine = next(i for i in items if i["rental_id"] == s["rental_id"])
        assert mine["demo"] is True and mine["result"] == "ISSUES"
        assert ri.vehicles()[s["vehicle"]["plate"]]["rental_id"] == s["rental_id"]


DEMO_VEHICLE = "demo-rfy-1753"


class TestDemoVehicle:
    def test_固定車輛資料與費用_一般視圖(self, client):
        v = client.get(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}").json()
        assert v["plate"] == "RFY-1753" and v["model"] == "TOYOTA ALTIS HYBRID" and v["featured"] is True
        assert v["seats"] == 5 and v["parking_spot"] == "67" and v["color"] == "白色" and v["vehicle_type"] == "個人用車"
        assert v["pricing"]["hourly_twd"] == 130 and v["pricing"]["per_km_twd"] == 3.5 and "不會扣款" in v["pricing"]["billing_note"]
        assert v["pricing"]["estimated_km_fee_twd"] == 70 and v["pricing"]["estimated_total_twd"] == 200
        assert v["image_url"].startswith("/photos/demo/")
        assert "Demo" not in json.dumps(v, ensure_ascii=False) and "示範" not in json.dumps(v, ensure_ascii=False)

    def test_示意圖可供圖(self, client):
        r = client.get("/photos/demo/rfy-1753.png")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/png")
        assert client.get("/photos/demo/../server.py").status_code in (404, 422)

    def test_完整流程_走真實pipeline並可再租(self, client, monkeypatch):
        import judge_photos, run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")
        monkeypatch.setattr(judge_photos, "judge_pair", lambda p, r, angle=None, **kw: (
            {"final": {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.9, "pre_existing_notes": ""}}, None))
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (
            {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 90}, None))
        s = drive_to_photo_inspection(client, DEMO_VEHICLE)
        assert s["rental_id"].startswith("RNT-DEMO-") and s["ai_source"] == "pipeline"
        assert client.get(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}").json()["status"] == "RENTED"
        shoot(client, s, "return", 30)
        s = client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return").json()
        assert s["state"] == "RETURNED"
        fee = s["fee_estimate"]
        assert fee["billable_hours"] == 1 and fee["time_fee_twd"] == 130 and fee["km_fee_twd"] == 42 and fee["total_twd"] == 172
        v = client.get(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}").json()
        assert v["status"] == "AVAILABLE" and v["odometer_km"] == s["end_odometer_km"]
        assert client.post("/v1/rental-sessions", json={"vehicle_id": DEMO_VEHICLE}).status_code == 201

    def test_重設只在內部工具_封存Session_不碰其他車(self, client, admin, monkeypatch):
        monkeypatch.delenv("DEMO_MODE")          # 不需要 DEMO_MODE，只需要 admin
        other = start(client, FIXTURE_VEHICLE)
        s = drive_to_photo_inspection(client, DEMO_VEHICLE)
        assert client.post(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}/reset").status_code in (404, 405)   # 一般 API 沒有
        assert client.post(f"{DEV}/vehicles/{DEMO_VEHICLE}/reset").status_code == 401
        j = admin.post(f"{DEV}/vehicles/{DEMO_VEHICLE}/reset").json()
        assert j["ok"] and j["archived_sessions"] == [s["session_id"]] and j["vehicle"]["status"] == "AVAILABLE"
        archived = client.get(f"/v1/rental-sessions/{s['session_id']}").json()
        assert archived["state"] == "ARCHIVED" and archived["rental_status"] is None
        assert client.get("/v1/rental-sessions/active").json()["session"]["session_id"] == other["session_id"]
        assert vehicle_of(admin, FIXTURE_VEHICLE)["status"] == "RENTED"
        assert admin.post(f"{DEV}/vehicles/{FIXTURE_VEHICLE}/reset").status_code == 403
        assert admin.post(f"{DEV}/vehicles/nope/reset").status_code == 404
        assert client.post("/v1/rental-sessions", json={"vehicle_id": DEMO_VEHICLE}).status_code == 201

    def test_既有資料庫缺欄位時自動補(self, srv, tmp_path):
        import sqlite3
        import rental_sessions as rs
        db = tmp_path / "test.sqlite3"
        with sqlite3.connect(db) as c:
            c.execute("DROP TABLE demo_vehicles")
            c.execute("""CREATE TABLE demo_vehicles(vehicle_id TEXT PRIMARY KEY, plate TEXT NOT NULL, model TEXT NOT NULL,
                image_url TEXT, image_note TEXT, lat REAL NOT NULL, lng REAL NOT NULL, location_name TEXT, status TEXT NOT NULL,
                odometer_km INTEGER NOT NULL, fuel_percent INTEGER, ai_source TEXT NOT NULL, fixture_rental_id TEXT,
                simulated INTEGER NOT NULL DEFAULT 1, last_returned_at TEXT, updated_at TEXT NOT NULL)""")
        rs.reset_schema_cache()
        rs.ensure_vehicles()
        assert rs.get_vehicle(DEMO_VEHICLE)["seats"] == 5 and rs.get_vehicle(FIXTURE_VEHICLE) is None


class TestDemoRegistryPreload:
    """Demo Vehicle Registry（DEMO_IMAGE_MANIFEST.json）：一般使用者只看已驗證的車況紀錄；預載照片只在內部工具。"""

    def test_一般車況紀錄只含已驗證角度且無開發資訊(self, client):
        r = client.get("/v1/rental-sessions/vehicles/demo-rdg-9853/records")
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["has_records"] and j["complete"] and len(j["before"]) == 4 and len(j["after"]) == 4
        text = json.dumps(j, ensure_ascii=False)
        for banned in ("ocr", "quality", "verification", "資料集", "source", "sharpness"):
            assert banned not in text.lower()
        assert client.get(j["before"][0]["url"]).status_code == 200
        # 沒有登記照片的車 → 空紀錄（不虛構）
        e = client.get("/v1/rental-sessions/vehicles/demo-rfy-1753/records").json()
        assert e["has_records"] is False and e["before"] == []
        # internal 車輛對一般 API 不存在
        assert client.get("/v1/rental-sessions/vehicles/demo-rfh-8122/records").status_code == 404

    def test_內部Registry有OCR與配對驗證(self, admin):
        j = admin.get(f"{DEV}/vehicles/demo-rdg-9853/photos").json()
        assert j["complete_pair"] is True and all(p["pair_verification"] == "VERIFIED" for p in j["pairs"])
        assert all(p["plate_recognition"]["verification"] == "VERIFIED" for p in j["before"] + j["after"])
        d = admin.get(f"{DEV}/vehicles/demo-rfh-8122/photos").json()
        assert "右後" in d["damage_angles"] and any(p["pair_verification"] != "VERIFIED" for p in d["pairs"])
        assert admin.get(f"{DEV}/vehicles/demo-rfy-1753/photos").status_code == 404

    def test_預載取車與還車照片_只在內部工具_走同一條pipeline(self, client, admin, monkeypatch):
        import judge_photos, run_eval_gemini
        calls = []
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")
        def judge(p, r, angle=None, **kw):
            calls.append((angle, p.split("/")[-1], r.split("/")[-1]))
            return ({"final": {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.9, "pre_existing_notes": ""}}, None)
        monkeypatch.setattr(judge_photos, "judge_pair", judge)
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (
            {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 90}, None))
        s = start(client, "demo-rdg-9853")
        sid = s["session_id"]
        assert client.post(f"/v1/rental-sessions/{sid}/preload/pickup").status_code in (404, 405)     # 一般 API 沒有
        assert client.post(f"{DEV}/sessions/{sid}/preload/pickup").status_code == 401
        assert admin.post(f"{DEV}/sessions/{sid}/preload/return").status_code == 409
        assert admin.post(f"{DEV}/sessions/{sid}/preload/nope").status_code == 422
        j = admin.post(f"{DEV}/sessions/{sid}/preload/pickup").json()
        assert j["preload"]["mode"] == "preloaded" and len(j["preload"]["ingested"]) == 5
        assert j["pickup"]["complete"] and j["capture_mode"]["PICKUP"] == "preloaded"
        # App 端看到的是照片 url 與 preloaded 旗標，沒有檔案路徑
        assert all(p["url"].startswith("/photos/") for p in j["photos"]["PICKUP"])
        s = client.post(f"/v1/rental-sessions/{sid}/pickup/complete").json(); assert s["state"] == "RENTED"
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        s = client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 3}).json()
        j = admin.post(f"{DEV}/sessions/{sid}/preload/return").json()
        assert j["state"] == "INSPECTION_COMPLETED"
        assert sorted(a for a, _, _ in calls) == ["右前", "右後", "左前", "左後"]
        assert all(p.startswith("RDG9853") and "借" in p and "還" in r for _, p, r in calls)
        res = client.get(f"/v1/rental-sessions/{sid}/inspection").json()
        assert res["overall"] == "PASSED" and res["plate_check"]["status"] == "MATCH"
        pipe = admin.get(f"{DEV}/sessions/{sid}/pipeline").json()
        assert pipe["inspection_detail"]["rental_id"] == s["rental_id"] and pipe["app_result"]["overall"] == "PASSED"
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()["state"] == "RETURNED"

    def test_沒有登記照片的車預載回404(self, client, admin):
        s = start(client, "demo-rfy-1753")
        assert admin.post(f"{DEV}/sessions/{s['session_id']}/preload/pickup").status_code == 404

    def test_manifest缺檔時仍可啟動(self, client, admin, monkeypatch, tmp_path):
        import demo_vehicle_registry as registry
        monkeypatch.setattr(registry, "MANIFEST_PATH", tmp_path / "missing.json")
        registry.reload()
        try:
            assert client.get("/v1/rental-sessions/vehicles").status_code == 200
            assert client.get("/v1/rental-sessions/vehicles/demo-rdg-9853/records").json()["has_records"] is False
            assert admin.get(f"{DEV}/vehicles/demo-rdg-9853/photos").status_code == 404
        finally:
            registry.reload()


class Test3DSupport:
    """App 3D 車輛：車型樣式、車損紀錄（只回有車身區域的）、資料集車頭照角度校正。"""

    def test_車輛帶3D樣式(self, client):
        vs = {v["vehicle_id"]: v for v in client.get("/v1/rental-sessions/vehicles").json()["vehicles"]}
        assert vs["demo-rfy-1753"]["body_style"] == "sedan" and vs["demo-rdg-9853"]["body_style"] == "hatchback"
        s = start(client, "demo-rfy-1753")
        assert s["vehicle"]["body_style"] == "sedan"

    def test_車頭照角度以畫面實際角度呈現(self, client):
        j = client.get("/v1/rental-sessions/vehicles/demo-rdg-9853/records").json()
        by_angle = {p["angle"]: p["url"] for p in j["before"]}
        assert "%E5%8F%B3%E5%89%8D" in by_angle["左前"]       # 畫面左前角 = 檔名「右前」
        assert "%E5%B7%A6%E5%BE%8C" in by_angle["左後"]       # 車尾照不變

    def test_車損紀錄只含有區域的新損_還車後才出現(self, client, admin, monkeypatch):
        import judge_photos, run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")
        def judge(p, r, angle=None, **kw):
            dmg = [{"location": "右後保險桿", "type": "刮痕", "severity": "medium", "confidence": 0.9, "reasoning": "x", "box_2d": [1, 2, 3, 4]}] if angle == "右後" else []
            return ({"final": {"angle_match": True, "new_damage_found": bool(dmg), "damages": dmg, "no_damage_confidence": 0.9, "pre_existing_notes": ""}}, None)
        monkeypatch.setattr(judge_photos, "judge_pair", judge)
        monkeypatch.setattr(judge_photos, "judge_interior", lambda p, **kw: (
            {"final": {"photo_ok": True, "level": "乾淨", "confidence": 0.9, "findings": [], "reasoning": "ok"}, "score": 90}, None))
        s = drive_to_photo_inspection(client, DEMO_VEHICLE)
        shoot(client, s, "return", 30)
        res = client.get(f"/v1/rental-sessions/{s['session_id']}/inspection").json()
        rr = next(c for c in res["comparisons"] if c["angle"] == "右後")
        assert rr["findings"][0]["region"] == "rear-bumper" and rr["boxes"][0]["box_2d"] == [1, 2, 3, 4]
        assert client.get(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}/records").json()["damage_records"] == []   # 尚未還車
        client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return")
        recs = client.get(f"/v1/rental-sessions/vehicles/{DEMO_VEHICLE}/records").json()["damage_records"]
        assert len(recs) == 1 and recs[0]["region"] == "rear-bumper" and recs[0]["type"] == "刮痕" and recs[0]["photo_url"].startswith("/photos/")



class TestBackNavigation:
    def test_撤回開始還車_回到租用中_有還車照後不可撤回(self, client):
        s = start(client)
        shoot(client, s, "pickup", 10)
        sid = s["session_id"]
        client.post(f"/v1/rental-sessions/{sid}/pickup/complete")
        assert client.post(f"/v1/rental-sessions/{sid}/return/cancel").json()["state"] == "RENTED"      # 冪等
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        j = client.post(f"/v1/rental-sessions/{sid}/return/cancel").json()
        assert j["state"] == "RENTED" and j["return_initiated_at"] is None and j["pickup"]["complete"]
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        s2 = client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 5}).json()
        assert s2["state"] == "PHOTO_INSPECTION"
        assert client.post(f"/v1/rental-sessions/{sid}/return/cancel").json()["state"] == "RENTED"       # 還沒拍還車照
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 5})
        assert upload(client, s2, "return", "左前", 31).status_code == 201
        r = client.post(f"/v1/rental-sessions/{sid}/return/cancel")
        assert r.status_code == 409 and "還車照片" in r.json()["detail"]
        # 不可從取車檢查撤回
        s3 = start(client, PIPELINE_VEHICLE)
        assert client.post(f"/v1/rental-sessions/{s3['session_id']}/return/cancel").status_code == 409
