"""Rental → Pickup/Return Inspection → AI Comparison → Incident → Admin 的 End-to-End 回歸測試。

零 Gemini API 成本：示範租約走 demo_inspection_fixture 固定結果；一般租約以 mock 的
judge_pair / judge_interior 驗證 production path 的對應與「正常不開案」。
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
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(server, "send_notification", lambda payload: True)
    monkeypatch.setenv("NOTIFICATION_WEBHOOK_URL", "http://example.invalid/hook")
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setattr(ri.paths, "UPLOAD_DIR", tmp_path / "uploads")
    monkeypatch.setattr(ri, "ANALYSIS_RUNNER", ri.run_analysis)   # 同步跑分析，測試可直接斷言
    ri.reset_schema_cache()
    ri.ensure_registered_rentals()
    return server


@pytest.fixture()
def ri(srv):
    import rental_inspections
    return rental_inspections


@pytest.fixture()
def client(srv):
    return TestClient(srv.app)


DEMO = "RNT-20261005-1842"
PLATE = "ABC-1234"
ANGLES = ["左前", "右前", "左後", "右後"]


def jpeg(seed: int) -> bytes:
    im = Image.new("RGB", (800, 600), (seed % 255, 90, 160))
    b = io.BytesIO()
    im.save(b, "JPEG")
    return b.getvalue()


def upload(client, stage, view, seed, *, rental=DEMO, plate=PLATE, car="VH-ABC-1234",
           photo_id=None, mode="demo", legacy=False):
    data = jpeg(seed)
    sha = hashlib.sha256(data).hexdigest()
    form = {"rental_id": rental, "car_id": car, "expected_plate": plate, "stage": stage, "view": view,
            "recognized_plate": plate, "image_sha256": sha, "captured_at": "2026-10-05T20:02:00Z",
            "local_result_json": json.dumps({"passed": True, "plateText": plate, "plateConfidence": 0.97,
                                             "detectedView": view, "viewConfidence": 0.91, "errors": [],
                                             "modelVersions": {"plate_detector": "1.0"}})}
    if not legacy:
        form.update({"photo_id": photo_id or f"{stage}-{view}-{seed}", "vehicle_id": car,
                     "inspection_type": stage.upper(), "angle": {"左前": "FRONT_LEFT", "右前": "FRONT_RIGHT",
                                                                 "左後": "REAR_LEFT", "右後": "REAR_RIGHT",
                                                                 "車內": "INTERIOR"}[view],
                     "photo_category": "interior" if view == "車內" else "exterior",
                     "validation_mode": mode})
    r = client.post("/v1/mobile-inspections/photos", data=form, files={"photo": ("p.jpg", data, "image/jpeg")})
    return r


def run_pickup(client, rental=DEMO, **kw):
    for i, v in enumerate(ANGLES):
        assert upload(client, "pickup", v, 10 + i, rental=rental, **kw).status_code == 201
    return upload(client, "pickup", "車內", 20, rental=rental, **kw).json()


def run_return(client, rental=DEMO, **kw):
    for i, v in enumerate(ANGLES):
        assert upload(client, "return", v, 30 + i, rental=rental, **kw).status_code == 201
    return upload(client, "return", "車內", 40, rental=rental, **kw).json()


class TestIngestion:
    def test_上傳建立Rental_Inspection_Photo而非只有檔案(self, client, ri):
        j = upload(client, "pickup", "左前", 1).json()
        assert j["photo_id"] == "pickup-左前-1" and j["inspection_type"] == "PICKUP"
        assert j["angle"] == "FRONT_LEFT" and j["photo_category"] == "exterior"
        assert j["rental_status"] == "PICKUP_IN_PROGRESS"
        detail = ri.inspection_detail(DEMO)
        photo = detail["comparisons"][0]["pickup_photo"]
        assert photo["validation"]["plate_text"] == PLATE and photo["validation"]["view_confidence"] == 0.91
        assert photo["url"].startswith("/photos/mobile/") and photo["validation_mode"] == "demo"

    def test_同一張照片重送不重複建檔(self, client, ri):
        a = upload(client, "pickup", "左前", 1).json()
        b = upload(client, "pickup", "左前", 1).json()
        assert a["deduplicated"] is False and b["deduplicated"] is True and a["photo_id"] == b["photo_id"]
        with ri.db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM inspection_photos WHERE rental_id=?", (DEMO,)).fetchone()[0]
        assert n == 1
        assert ri.app_status(DEMO)["pickup"]["exterior"]["received"] == 1

    def test_舊版App欄位仍可上傳(self, client):
        r = upload(client, "pickup", "左前", 3, rental="demo-rental-001", plate="RCG-2235", car="demo-car-001",
                   legacy=True)
        assert r.status_code == 201 and r.json()["photo_id"].startswith("ph_")

    def test_未登記租約與車牌不符被拒(self, client):
        assert upload(client, "pickup", "左前", 1, rental="RNT-NOPE").status_code == 404
        assert upload(client, "pickup", "左前", 1, plate="XYZ-0000").status_code == 422

    def test_非demo租約不接受demo驗證模式(self, client, ri):
        with ri.db() as conn:
            ri.register_rental(conn, "RNT-REAL", "RDL-8265", "VH-RDL")
        assert upload(client, "pickup", "左前", 1, rental="RNT-REAL", plate="RDL-8265", mode="demo").status_code == 422
        assert upload(client, "pickup", "左前", 1, rental="RNT-REAL", plate="RDL-8265", mode="coreml").status_code == 201

    def test_照片供圖與路徑穿越(self, client, ri):
        upload(client, "pickup", "右後", 7)
        url = ri.inspection_detail(DEMO)["comparisons"][3]["pickup_photo"]["url"]
        assert client.get(url).status_code == 200
        assert client.get("/photos/mobile/../../etc/passwd").status_code == 404


class TestPickupBaseline:
    def test_四外觀加一車內才PICKUP_COMPLETE並建立基準(self, client, ri):
        for i, v in enumerate(ANGLES):
            j = upload(client, "pickup", v, 10 + i).json()
            assert j["rental_status"] == "PICKUP_IN_PROGRESS" and j["triggered"] is None
        j = upload(client, "pickup", "車內", 20).json()
        assert j["rental_status"] == "PICKUP_COMPLETE" and j["triggered"] == "baseline"
        assert j["completeness"]["complete"] and j["completeness"]["exterior"] == {"received": 4, "required": 4}
        base = ri.inspection_detail(DEMO)["baseline"]
        assert base["source"] == "demo_fixture"
        assert base["existing_damage"][0]["status"] == "EXISTING_DAMAGE"
        assert base["existing_damage"][0]["region"] == "front-bumper" and base["existing_damage"][0]["confidence"] == 0.87
        assert set(base["photo_ids"]) == set(ANGLES + ["車內"])

    def test_取車結束後再傳新取車照被拒_重送舊照仍冪等(self, client):
        run_pickup(client)
        run_return(client)
        assert upload(client, "pickup", "左前", 99).status_code == 409
        assert upload(client, "pickup", "左前", 10).json()["deduplicated"] is True


class TestReturnComparison:
    def test_還車齊五張才觸發分析_固定劇本產生兩案件(self, client, ri, srv):
        run_pickup(client)
        for i, v in enumerate(ANGLES):
            assert upload(client, "return", v, 30 + i).json()["triggered"] is None
        j = upload(client, "return", "車內", 40).json()
        assert j["triggered"] == "analysis"
        st = ri.app_status(DEMO)
        assert st["status"] == "ANALYSIS_COMPLETE" and st["analysis"] == "complete"
        assert "damage" not in json.dumps(st)   # App 狀態不帶判定內容（不歸責）

        detail = ri.inspection_detail(DEMO)
        by = {c["angle"]: c for c in detail["comparisons"]}
        assert by["右後"]["result"] == "NEW_DAMAGE" and by["右後"]["case_id"] == f"RI-{DEMO}-右後"
        assert by["右前"]["result"] == "EXISTING_DAMAGE" and by["右前"]["case_id"] is None
        assert by["左前"]["result"] == "NO_NEW_DAMAGE" and by["左後"]["result"] == "NO_NEW_DAMAGE"
        assert by["車內"]["result"] == "CLEANING_REQUIRED" and by["車內"]["case_id"] == f"RI-{DEMO}-車內"
        assert detail["interior"]["confidence"] == 0.88
        assert [f["label"] for f in detail["interior"]["findings"]] == ["食物包裝", "飲料杯", "座椅污漬"]
        assert detail["result"] == "ISSUES" and detail["issue_count"] == 2
        # Before / After 證據：取車與還車照各自掛在同一角度
        assert by["右後"]["pickup_photo"]["url"] != by["右後"]["return_photo"]["url"]

    def test_案件進入既有裁決路徑_confirm自動建單且車牌正確(self, client, ri, srv):
        import ops_api
        run_pickup(client)
        run_return(client)
        cases = [c for c in ops_api.list_cases(car=PLATE)["cases"]]
        assert {c["case_id"] for c in cases} == {f"RI-{DEMO}-右後", f"RI-{DEMO}-車內"}
        dmg = next(c for c in cases if c["mode"] == "pair")
        assert dmg["source"] == "mobile_inspection" and dmg["review_status"] == "unreviewed"
        assert dmg["ai_level"] == "P1" and dmg["ai_conf"] == 0.92
        assert dmg["damages"][0]["region"] == "right-rear-door"       # Digital Twin hotspot id
        assert dmg["boxes"] and dmg["photos"]["pickup"] and dmg["photos"]["return"]
        assert dmg["rental"]["rental_id"] == DEMO
        cln = next(c for c in cases if c["mode"] == "interior")
        assert cln["cleanliness"] == "髒汙" and cln["issues"] == ["食物包裝", "飲料杯", "座椅污漬"]

        r = srv.post_decision(srv.Decision(case_id=dmg["case_id"], decision="confirm"))
        assert r["task"]["task_type"] == "repair" and r["task"]["car"] == PLATE
        assert "右後車門" in r["task"]["title"]
        r2 = srv.post_decision(srv.Decision(case_id=cln["case_id"], decision="confirm"))
        assert r2["task"]["task_type"] == "cleaning"
        fleet = next(f for f in ops_api.fleet()["fleet"] if f["car"] == PLATE)
        assert fleet["status"] == "locked" and fleet["model"] == "Toyota Yaris" and len(fleet["open_tasks"]) == 2
        assert ops_api.get_case(dmg["case_id"])["view"]["photos"]["return"].startswith("/photos/mobile/")

    def test_fleet將未裁決的App案件車輛標為review(self, client, ri):
        import ops_api
        run_pickup(client)
        run_return(client)
        fleet = next(f for f in ops_api.fleet()["fleet"] if f["car"] == PLATE)
        assert fleet["status"] == "review" and fleet["mobile_cases"] == 2

    def test_重送還車照不會重跑出第二套案件(self, client, ri):
        run_pickup(client)
        run_return(client)
        upload(client, "return", "車內", 40)
        with ri.db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM inspection_incidents WHERE rental_id=?", (DEMO,)).fetchone()[0]
        assert n == 2


class TestProductionPath:
    @pytest.fixture()
    def real_rental(self, client, ri, monkeypatch):
        with ri.db() as conn:
            ri.register_rental(conn, "RNT-REAL", "RDL-8265", "VH-RDL", "Toyota Yaris")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        return "RNT-REAL"

    def _judge_clean(self, pickup, ret, angle=None, **kw):
        return {"mode": "pair", "gate_pass": True, "level": "P3", "kind": "正常",
                "final": {"angle_match": True, "new_damage_found": False, "damages": [],
                          "no_damage_confidence": 0.95, "pre_existing_notes": ""}}, None

    def _interior_clean(self, photo, **kw):
        return {"mode": "interior", "gate_pass": True, "level": "P3",
                "final": {"photo_ok": True, "invalid_reason": "", "level": "乾淨", "confidence": 0.93,
                          "findings": [], "reasoning": "無垃圾"}}, None

    def test_正常租約_不建立案件但保留紀錄(self, client, ri, real_rental, monkeypatch):
        import judge_photos
        import ops_api
        monkeypatch.setattr(judge_photos, "judge_pair", self._judge_clean)
        monkeypatch.setattr(judge_photos, "judge_interior", self._interior_clean)
        run_pickup(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        run_return(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        detail = ri.inspection_detail(real_rental)
        assert detail["status"] == "ANALYSIS_COMPLETE" and detail["analysis"]["source"] == "pipeline"
        assert detail["result"] == "PASSED" and detail["issue_count"] == 0
        assert {c["result"] for c in detail["comparisons"][:4]} == {"NO_NEW_DAMAGE"}
        assert detail["interior"]["result"] == "CLEAN"
        assert detail["baseline"]["source"] == "pipeline"
        assert not [c for c in ops_api.list_cases(car="RDL-8265")["cases"] if c["source"] == "mobile_inspection"]
        assert [i["rental_id"] for i in ri.list_inspections()] == [real_rental]

    def test_真實pipeline結果對應_新損與既有損傷區分(self, client, ri, real_rental, monkeypatch):
        import judge_photos

        def judge(pickup, ret, angle=None, **kw):
            if angle == "右後":
                return {"mode": "pair", "gate_pass": True, "level": "P1", "kind": "新車損",
                        "final": {"angle_match": True, "new_damage_found": True, "no_damage_confidence": 0,
                                  "damages": [{"location": "右後車門下緣", "type": "刮痕", "severity": "medium",
                                               "confidence": 0.9, "reasoning": "r", "box_2d": [1, 2, 3, 4]}],
                                  "pre_existing_notes": ""}}, None
            if angle == "右前":
                return {"mode": "pair", "gate_pass": True, "level": "P3", "kind": "正常",
                        "final": {"angle_match": True, "new_damage_found": False, "damages": [],
                                  "no_damage_confidence": 0.9, "pre_existing_notes": "右前保桿既有刮痕"}}, None
            if angle == "左後":
                return {"mode": "pair", "gate_pass": False, "retake_reason": "gate"}, None
            return self._judge_clean(pickup, ret, angle)

        monkeypatch.setattr(judge_photos, "judge_pair", judge)
        monkeypatch.setattr(judge_photos, "judge_interior", self._interior_clean)
        run_pickup(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        run_return(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        by = {c["angle"]: c for c in ri.inspection_detail(real_rental)["comparisons"]}
        assert by["右後"]["result"] == "NEW_DAMAGE" and by["右後"]["findings"][0]["region"] == "right-rear-door"
        assert by["右後"]["boxes"][0]["box_2d"] == [1, 2, 3, 4]
        assert by["右前"]["result"] == "EXISTING_DAMAGE" and by["右前"]["findings"][0]["status"] == "EXISTING_DAMAGE"
        assert by["左後"]["result"] == "UNCOMPARABLE"
        assert ri.incident_case_ids(real_rental) == [f"RI-{real_rental}-右後"]

    def test_沒有API_key_分析失敗但紀錄保留且不擋還車(self, client, ri, real_rental, monkeypatch):
        import run_eval_gemini
        monkeypatch.setattr(run_eval_gemini, "find_key", lambda: None)
        run_pickup(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        j = run_return(client, rental=real_rental, plate="RDL-8265", car="VH-RDL", mode="coreml")
        assert j["rental_status"] in ("RETURN_COMPLETE", "ANALYSIS_FAILED")   # 上傳本身成功
        st = ri.app_status(real_rental)
        assert st["status"] == "ANALYSIS_FAILED" and st["analysis"] == "failed"
        d = ri.inspection_detail(real_rental)
        assert d["result"] == "FAILED" and "GEMINI_API_KEY" in d["analysis"]["error"]
        assert d["return"]["complete"] and d["issue_count"] == 0


class TestDemoIsolation:
    def test_demo_seed讓管理者端不依賴iOS(self, srv, ri):
        srv._startup_rentals()
        st = ri.app_status(DEMO)
        assert st["status"] == "ANALYSIS_COMPLETE"
        assert srv._demo_rental_info()["case_ids"] == [f"RI-{DEMO}-右後", f"RI-{DEMO}-車內"]
        assert srv.demo_health()["demo_rental"]["car"] == PLATE
        # 已經有照片的租約不會被啟動流程再次覆蓋
        with ri.db() as conn:
            ids_before = [r[0] for r in conn.execute("SELECT photo_id FROM inspection_photos WHERE rental_id=? ORDER BY photo_id", (DEMO,))]
        srv._startup_rentals()
        with ri.db() as conn:
            ids_after = [r[0] for r in conn.execute("SELECT photo_id FROM inspection_photos WHERE rental_id=? ORDER BY photo_id", (DEMO,))]
        assert ids_before == ids_after

    def test_demo_reset清掉裁決任務並重新落地固定劇本(self, srv, ri, client, monkeypatch):
        run_pickup(client)
        run_return(client)
        t = srv.post_decision(srv.Decision(case_id=f"RI-{DEMO}-右後", decision="confirm"))["task"]
        out = srv.demo_reset()
        assert f"RI-{DEMO}-右後" in out["reset_cases"]
        with srv.db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks WHERE id=?", (t["id"],)).fetchone()[0] == 0
            assert conn.execute("SELECT COUNT(*) FROM decisions WHERE case_id LIKE 'RI-%'").fetchone()[0] == 0
        st = ri.app_status(DEMO)
        assert st["status"] == "ANALYSIS_COMPLETE"
        assert ri.inspection_detail(DEMO)["source"] == "demo_seed"

    def test_App重新開始Demo_只允許demo租約(self, client, ri, srv):
        run_pickup(client)
        run_return(client)
        srv.post_decision(srv.Decision(case_id=f"RI-{DEMO}-車內", decision="confirm"))
        r = client.post(f"/v1/mobile-inspections/rentals/{DEMO}/restart")
        assert r.status_code == 200 and set(r.json()["cleared_cases"]) == {f"RI-{DEMO}-右後", f"RI-{DEMO}-車內"}
        assert ri.app_status(DEMO)["status"] == "CREATED" and ri.incident_case_ids(DEMO) == []
        with srv.db() as conn:
            assert conn.execute("SELECT COUNT(*) FROM tasks WHERE case_id LIKE 'RI-%'").fetchone()[0] == 0
        with ri.db() as conn:
            ri.register_rental(conn, "RNT-REAL", "RDL-8265", "VH-RDL")
        assert client.post("/v1/mobile-inspections/rentals/RNT-REAL/restart").status_code == 403

    def test_production_path不受fixture影響(self, ri):
        import demo_inspection_fixture as fx
        assert fx.is_demo_rental(DEMO) and not fx.is_demo_rental("RNT-REAL")
        assert fx.analysis()["exterior"]["右後"]["findings"][0]["confidence"] == 0.92
        assert fx.analysis()["interior"]["confidence"] == 0.88


class TestAdminInspectionApi:
    def test_列表與詳情(self, client, ri, srv):
        import rental_inspections_api as api
        run_pickup(client)
        run_return(client)
        lst = api.list_inspections()["inspections"]
        assert len(lst) == 1
        row = lst[0]
        assert row["rental_id"] == DEMO and row["plate"] == PLATE and row["result"] == "ISSUES"
        assert row["pickup_at"] and row["return_at"] and row["issue_count"] == 2
        assert {i["review_status"] for i in row["incidents"]} == {"unreviewed"}
        srv.post_decision(srv.Decision(case_id=f"RI-{DEMO}-右後", decision="confirm"))
        det = api.inspection_detail(DEMO)["inspection"]
        dmg = next(i for i in det["incidents"] if i["kind"] == "damage")
        assert dmg["review_status"] == "confirmed_open" and dmg["tasks"][0]["task_type"] == "repair"
        assert dmg["region"] == "right-rear-door"
        assert len(det["comparisons"]) == 5
        with pytest.raises(Exception):
            api.inspection_detail("RNT-NOPE")

    def test_需登入(self, client):
        assert client.get("/api/ops/inspections").status_code == 401
        assert client.get(f"/v1/mobile-inspections/rentals/{DEMO}").status_code == 200   # App 端不需登入


class TestBodyRegions:
    def test_自由文字對應twin區域(self):
        import body_regions as br
        assert br.locate_exterior("右後車門下緣", "右後") == "right-rear-door"
        assert br.locate_exterior("左後保險桿", "左後") == "rear-bumper"
        assert br.locate_exterior("右前葉子板", "右前") == "right-front-fender"
        assert br.locate_exterior("", "左前") == "left-front-fender"
        assert br.locate_interior("飲料杯") == "cup-holder"
        assert br.normalize_region("RIGHT_REAR_DOOR") == "right-rear-door"
        assert br.normalize_region("nope") is None
        assert set(br.REGION_LABELS) == set(br.ALL_REGIONS)
