"""後台建立 Demo 測試車輛、座標單一來源、真實車牌辨識守門、取消還車保護人工裁決（零 Gemini API 成本）。"""
import hashlib
import json

from test_rental_sessions import (  # noqa: F401
    ANGLES, CODES, FIXTURE_VEHICLE, admin, client, drive_to_photo_inspection, jpeg, shoot, srv,
)

DEV = "/api/ops/devtools"
NTU = {"lat": 25.0174, "lng": 121.5397}


def create(admin, plate="RDL-7827", **kw):
    r = admin.post(f"{DEV}/demo-vehicles", json={"plate": plate, **NTU, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def app_vehicle(client, vid):
    return next((v for v in client.get("/v1/rental-sessions/vehicles").json()["vehicles"] if v["vehicle_id"] == vid), None)


def fleet_row(admin, car):
    return next((r for r in admin.get("/api/ops/fleet").json()["fleet"] if r["car"] == car), None)


def upload(client, session, stage, view, seed, *, ocr=None, recognized=None, mode="coreml", confirmation=None):
    """ocr＝裝置端 OCR 原始輸出（local_result.plateText）；recognized＝表單 recognized_plate。"""
    data = jpeg(seed)
    plate = session["vehicle"]["plate"]
    ocr = plate if ocr is None else ocr
    form = {"rental_id": session["rental_id"], "car_id": session["vehicle"]["vehicle_id"], "expected_plate": plate,
            "stage": stage, "view": view, "recognized_plate": recognized if recognized is not None else (ocr or plate),
            "image_sha256": hashlib.sha256(data).hexdigest(), "captured_at": "2026-10-09T10:00:00Z",
            "local_result_json": json.dumps({"passed": True, "plateText": ocr if view != "車內" else None,
                                             "errors": [], "modelVersions": {"mode": mode}}),
            "photo_id": f"{session['session_id']}-{stage}-{view}-{seed}", "angle": CODES[view],
            "photo_category": "interior" if view == "車內" else "exterior", "validation_mode": mode}
    if confirmation:
        form["plate_confirmation"] = confirmation
    return client.post("/v1/mobile-inspections/photos", data=form, files={"photo": ("p.jpg", data, "image/jpeg")})


class TestDemoVehicleCRUD:
    def test_建立後立即出現在App與後台_座標一致_可租用_有Demo標記(self, admin, client):
        v = create(admin, model="Toyota Corolla")
        assert v["vehicle_id"] == "demo-admin-rdl7827" and v["status"] == "AVAILABLE" and v["rentable"]
        assert v["admin_created"] and v["is_demo"] and v["category"] == "demo"
        a = app_vehicle(client, v["vehicle_id"])
        assert a and a["plate"] == "RDL-7827" and a["is_demo"] and a["status"] == "AVAILABLE"
        assert (a["location"]["lat"], a["location"]["lng"]) == (NTU["lat"], NTU["lng"])
        row = fleet_row(admin, "RDL-7827")
        assert row["rental_fleet"] and row["rentable"] and row["rental_state"]["admin_created"]
        assert (row["location"]["lat"], row["location"]["lng"]) == (NTU["lat"], NTU["lng"])   # 不被站點覆蓋
        assert row["location"]["source"] == "vehicle" and row["location"]["station_id"]       # 站點只做歸類

    def test_只限管理者(self, client):
        assert client.post(f"{DEV}/demo-vehicles", json={"plate": "RDL-7827", **NTU}).status_code in (401, 403)
        assert client.patch(f"{DEV}/vehicles/demo-rfy-1753/location", json=NTU).status_code in (401, 403)

    def test_輸入驗證(self, admin):
        assert admin.post(f"{DEV}/demo-vehicles", json={"plate": "壞車牌", **NTU}).status_code == 422
        assert admin.post(f"{DEV}/demo-vehicles", json={"plate": "RDL-7827", "lat": 35.6, "lng": 139.7}).status_code == 422
        create(admin)
        assert admin.post(f"{DEV}/demo-vehicles", json={"plate": "RDL7827", **NTU}).status_code == 409   # 不分連字號

    def test_修改車牌與位置_兩邊同步(self, admin, client):
        v = create(admin)
        new = {"lat": 25.0330, "lng": 121.5654, "location_name": "信義區測試點"}
        r = admin.patch(f"{DEV}/vehicles/{v['vehicle_id']}/location", json=new)
        assert r.status_code == 200
        a = app_vehicle(client, v["vehicle_id"])
        assert (a["location"]["lat"], a["location"]["lng"], a["location"]["name"]) == (25.0330, 121.5654, "信義區測試點")
        row = fleet_row(admin, "RDL-7827")
        assert (row["location"]["lat"], row["location"]["lng"]) == (25.0330, 121.5654)
        assert admin.patch(f"{DEV}/demo-vehicles/{v['vehicle_id']}", json={"plate": "RDZ-6950"}).json()["plate"] == "RDZ-6950"
        assert app_vehicle(client, v["vehicle_id"])["plate"] == "RDZ-6950" and fleet_row(admin, "RDL-7827") is None

    def test_既有車輛也可改座標_重啟不被寫死座標覆蓋(self, admin, client):
        import rental_sessions as rs
        admin.patch(f"{DEV}/vehicles/demo-rfy-1753/location", json={"lat": 25.04, "lng": 121.52})
        rs.ensure_vehicles()                                                   # 模擬伺服器重啟
        loc = client.get("/v1/rental-sessions/vehicles/demo-rfy-1753").json()["location"]
        assert (loc["lat"], loc["lng"]) == (25.04, 121.52)

    def test_後台移到站點_改寫車輛座標(self, admin, client):
        import ops_api
        st = ops_api._stations()[0]
        assert admin.patch("/api/ops/fleet/RFY-1753/location", json={"station_id": st["id"]}).status_code == 200
        loc = client.get("/v1/rental-sessions/vehicles/demo-rfy-1753").json()["location"]
        assert (loc["lat"], loc["lng"]) == (st["lat"], st["lng"])
        assert (fleet_row(admin, "RFY-1753")["location"]["lat"]) == st["lat"]

    def test_租用中不可改車牌與刪除_未租用可刪除且保留歷史(self, admin, client):
        v = create(admin)
        s = client.post("/v1/rental-sessions", json={"vehicle_id": v["vehicle_id"]}).json()
        assert admin.patch(f"{DEV}/demo-vehicles/{v['vehicle_id']}", json={"plate": "RDZ-6950"}).status_code == 409
        assert admin.delete(f"{DEV}/demo-vehicles/{v['vehicle_id']}").status_code == 409
        client.post(f"/v1/rental-sessions/{s['session_id']}/cancel")
        assert admin.delete(f"{DEV}/demo-vehicles/{v['vehicle_id']}").status_code == 200
        assert app_vehicle(client, v["vehicle_id"]) is None
        assert client.get(f"/v1/rental-sessions/{s['session_id']}").json()["state"] == "CANCELLED"   # 歷史保留
        # 程式內建車輛不可刪
        assert admin.delete(f"{DEV}/demo-vehicles/demo-rfy-1753").status_code == 403


class TestRealPlateRecognition:
    def _start(self, admin, client):
        v = create(admin)
        s = client.post("/v1/rental-sessions", json={"vehicle_id": v["vehicle_id"]}).json()
        assert s["state"] == "PICKUP_INSPECTION"
        return s

    def test_Demo拍攝劇本被拒_必須真實辨識(self, admin, client):
        s = self._start(admin, client)
        r = upload(client, s, "pickup", "左前", 1, mode="demo")
        assert r.status_code == 422 and "真實車牌辨識" in r.json()["detail"]

    def test_不能用租約車牌冒充辨識結果(self, admin, client):
        s = self._start(admin, client)
        r = upload(client, s, "pickup", "左前", 1, ocr="", recognized="RDL-7827")             # 沒有 OCR 結果
        assert r.status_code == 422
        r = upload(client, s, "pickup", "左前", 1, ocr="RDG-9853", recognized="RDL-7827")     # OCR 讀到別台
        assert r.status_code == 422 and "不一致" in r.json()["detail"]
        r = upload(client, s, "pickup", "左前", 1, ocr="RDG-9853")                            # 誠實回報別台：拒收
        assert r.status_code == 422 and "does not match" in r.json()["detail"]
        assert upload(client, s, "pickup", "左前", 1, ocr="RDL7827").status_code == 201       # OCR 與資料庫一致（不分連字號）

    def test_完整租還車流程_還車後重新上架(self, admin, client, monkeypatch):
        import judge_photos
        import run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")
        monkeypatch.setattr(judge_photos, "judge_pair", lambda p, r, angle=None, **kw: (
            {"final": {"angle_match": True, "new_damage_found": False, "damages": [], "no_damage_confidence": 0.9,
                       "pre_existing_notes": ""}}, None))
        s = self._start(admin, client)
        sid = s["session_id"]
        for i, a in enumerate(ANGLES):
            assert upload(client, s, "pickup", a, 10 + i).status_code == 201
        client.post(f"/v1/rental-sessions/{sid}/photos/pickup/finish")
        assert client.post(f"/v1/rental-sessions/{sid}/pickup/complete").json()["state"] == "RENTED"
        assert fleet_row(admin, "RDL-7827")["status"] == "rented"
        client.post(f"/v1/rental-sessions/{sid}/return/initiate", json={})
        client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": 10015})
        for i, a in enumerate(ANGLES):
            assert upload(client, s, "return", a, 30 + i).status_code == 201
        j = client.post(f"/v1/rental-sessions/{sid}/photos/return/finish").json()
        assert j["state"] == "INSPECTION_COMPLETED" and j["ai_source"] == "pipeline"
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()["state"] == "RETURNED"
        a = app_vehicle(client, "demo-admin-rdl7827")
        assert a["status"] == "AVAILABLE" and a["odometer_km"] == 10015 and fleet_row(admin, "RDL-7827")["rentable"]


class TestCancelReturnKeepsOpsDecisions:
    def test_已裁決的案件_不能取消還車_裁決與任務完整保留(self, client, srv):
        s = drive_to_photo_inspection(client)                           # 固定劇本：右後新損 + 車內髒汙
        sid = s["session_id"]
        shoot(client, s, "return", 30)
        case = f"RI-{s['rental_id']}-右後"
        task = srv.post_decision(srv.Decision(case_id=case, decision="confirm"))["task"]
        view = client.get(f"/v1/rental-sessions/{sid}").json()
        assert view["return_cancel_blocked"] and "營運人員" in view["return_cancel_blocked"]
        r = client.post(f"/v1/rental-sessions/{sid}/return/cancel")
        assert r.status_code == 409 and "營運人員" in r.json()["detail"]
        with srv.db() as conn:
            assert conn.execute("SELECT decision FROM decisions WHERE case_id=?", (case,)).fetchone()[0] == "confirm"
            assert conn.execute("SELECT status FROM tasks WHERE id=?", (task["id"],)).fetchone()[0] == "pending"
        j = client.get(f"/v1/rental-sessions/{sid}").json()
        assert j["state"] == "INSPECTION_COMPLETED" and len(j["return"]["received"]) == 5     # 還車資料沒被清
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()["state"] == "RETURNED"

    def test_駁回也算已處理(self, client, srv):
        s = drive_to_photo_inspection(client)
        shoot(client, s, "return", 30)
        srv.post_decision(srv.Decision(case_id=f"RI-{s['rental_id']}-車內", decision="reject"))
        assert client.post(f"/v1/rental-sessions/{s['session_id']}/return/cancel").status_code == 409

    def test_未裁決仍可取消(self, client):
        s = drive_to_photo_inspection(client)
        shoot(client, s, "return", 30)
        assert client.get(f"/v1/rental-sessions/{s['session_id']}").json()["return_cancel_blocked"] is None
        assert client.post(f"/v1/rental-sessions/{s['session_id']}/return/cancel").json()["state"] == "RENTED"


class TestFixturePlateHandover:
    """固定劇本車（SIM-ABC-1234）的車牌 ABC-1234 是劇本用、不是實際車輛：後台 Demo 車可以使用，
    固定劇本車改為停放（PARKED），不會有兩台可租車輛同時使用同一車牌，也不會把劇本假案件掛到真車上。"""

    def _dev(self, admin, vid):
        return next(v for v in admin.get(f"{DEV}/vehicles").json()["vehicles"] if v["vehicle_id"] == vid)

    def test_後台Demo車可使用劇本車牌_固定劇本車停放_劇本案件不掛到真車(self, admin, client, srv):
        import rental_inspections as ri
        import rental_sessions as rs
        assert ri.incident_case_ids(rs.fixture.DEMO_RENTAL_ID)                  # DEMO_MODE 啟動時種下的劇本案件
        v = create(admin, plate="abc-1234")
        assert v["plate"] == "ABC-1234" and v["vehicle_id"] == "demo-admin-abc1234"
        f = self._dev(admin, "SIM-ABC-1234")
        assert f["status"] == "PARKED" and f["is_fixture"] and not f["rentable"]
        assert ri.incident_case_ids(rs.fixture.DEMO_RENTAL_ID) == []            # 劇本案件已清（劇本本來就可重演）
        rows = [r for r in admin.get("/api/ops/fleet").json()["fleet"] if r["car"] == "ABC-1234"]
        assert len(rows) == 1 and rows[0]["rental_state"]["vehicle_id"] == "demo-admin-abc1234" and rows[0]["rentable"]
        assert rows[0]["mobile_cases"] == 0 and rows[0]["status"] == "available"
        assert not [c for c in admin.get("/api/ops/cases").json()["cases"] if c["car"] == "ABC-1234"]
        assert rs.vehicle_by_plate("ABC1234")["vehicle_id"] == "demo-admin-abc1234"
        r = client.post("/v1/rental-sessions", json={"vehicle_id": "SIM-ABC-1234"})
        assert r.status_code == 409 and "劇本車牌" in r.json()["detail"]
        # 重啟／Demo 重置都不會讓固定劇本車復活或重種劇本案件
        rs.ensure_vehicles()
        srv._startup_rentals()
        admin.post(f"{DEV}/reset-all")
        assert admin.post("/api/demo/reset").status_code == 200
        assert self._dev(admin, "SIM-ABC-1234")["status"] == "PARKED"
        assert ri.incident_case_ids(rs.fixture.DEMO_RENTAL_ID) == []

    def test_Demo車刪除或改車牌_固定劇本車恢復_原Demo流程可用(self, admin, client):
        v = create(admin, plate="ABC-1234")
        assert admin.patch(f"{DEV}/demo-vehicles/{v['vehicle_id']}", json={"plate": "RDL-7827"}).status_code == 200
        assert self._dev(admin, "SIM-ABC-1234")["status"] == "AVAILABLE"
        admin.patch(f"{DEV}/demo-vehicles/{v['vehicle_id']}", json={"plate": "ABC-1234"})
        assert self._dev(admin, "SIM-ABC-1234")["status"] == "PARKED"
        admin.delete(f"{DEV}/demo-vehicles/{v['vehicle_id']}")
        assert self._dev(admin, "SIM-ABC-1234")["status"] == "AVAILABLE"
        s = drive_to_photo_inspection(client)                                   # 固定劇本流程照常
        shoot(client, s, "return", 30)
        assert client.get(f"/v1/rental-sessions/{s['session_id']}").json()["state"] == "INSPECTION_COMPLETED"

    def test_同車牌仍不可兩台_固定劇本車租用中不可讓出(self, admin, client):
        s = client.post("/v1/rental-sessions", json={"vehicle_id": "SIM-ABC-1234"}).json()
        r = admin.post(f"{DEV}/demo-vehicles", json={"plate": "ABC-1234", **NTU})
        assert r.status_code == 409 and "租用中" in r.json()["detail"]
        client.post(f"/v1/rental-sessions/{s['session_id']}/cancel")
        create(admin, plate="ABC-1234")
        r = admin.post(f"{DEV}/demo-vehicles", json={"plate": "ABC1234", **NTU})            # 第二台 Demo 車
        assert r.status_code == 409 and "已存在" in r.json()["detail"]
        r = admin.post(f"{DEV}/demo-vehicles", json={"plate": "RFY-1753", **NTU})           # 內建真車牌照舊不可用
        assert r.status_code == 409
