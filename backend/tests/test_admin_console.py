"""精簡後台的唯讀 API：/api/ops/overview、/api/ops/rentals、/api/ops/inspections 的資料來源與審核分類（零 Gemini 成本）。"""
import pytest

from test_demo_vehicles_admin import upload
from test_rental_sessions import ANGLES, admin, client, drive_to_photo_inspection, shoot, srv  # noqa: F401

DAMAGE = [{"location": "右後保險桿", "type": "刮痕", "severity": "medium", "confidence": 0.9, "reasoning": "新刮痕", "box_2d": [1, 2, 3, 4]}]


@pytest.fixture()
def judge_rear_damage(monkeypatch):
    import judge_photos
    import run_eval_gemini
    monkeypatch.setattr(run_eval_gemini, "find_key", lambda: "k")

    def pair(p, r, angle=None, **kw):
        dmg = DAMAGE if angle == "右後" else []
        return ({"final": {"angle_match": True, "new_damage_found": bool(dmg), "damages": dmg,
                           "no_damage_confidence": 0 if dmg else 0.9, "pre_existing_notes": ""}}, None)
    monkeypatch.setattr(judge_photos, "judge_pair", pair)


def real_rental(client, vehicle="SIM-RCG-2235"):
    """真實 pipeline 車（judge 已 mock）：取車 → 還車 → AI 檢測完成。"""
    s = client.post("/v1/rental-sessions", json={"vehicle_id": vehicle}).json()
    sid = s["session_id"]
    for i, a in enumerate(ANGLES):
        assert upload(client, s, "pickup", a, 10 + i).status_code == 201
    client.post(f"/v1/rental-sessions/{sid}/photos/pickup/finish")
    client.post(f"/v1/rental-sessions/{sid}/pickup/complete")
    client.post(f"/v1/rental-sessions/{sid}/return/initiate", json={})
    client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 9})
    for i, a in enumerate(ANGLES):
        assert upload(client, s, "return", a, 30 + i).status_code == 201
    j = client.post(f"/v1/rental-sessions/{sid}/photos/return/finish").json()
    assert j["state"] == "INSPECTION_COMPLETED"
    return j


class TestOverview:
    def test_沒有真實租約時_固定劇本不計入統計(self, admin):
        o = admin.get("/api/ops/overview").json()
        assert o["vehicles"]["total"] == 4                       # App 可租車隊，不含固定劇本車 SIM-ABC-1234
        assert o["vehicles"]["available"] == 4 and o["vehicles"]["rented"] == 0
        assert o["ai"] == {"completed": 0, "analyzing": 0, "failed": 0, "passed": 0, "pending_review_cases": 0}
        assert o["recent_rentals"] == [] and o["recent_incidents"] == []   # DEMO_MODE 種下的劇本案件不出現
        assert o["today"] == {"rentals_started": 0, "returns_completed": 0}

    def test_真實租還車與人工審核反映在統計(self, admin, client, srv, judge_rear_damage):
        s = real_rental(client)
        o = admin.get("/api/ops/overview").json()
        assert o["vehicles"]["rented"] == 1 and o["today"]["rentals_started"] == 1
        assert o["ai"]["completed"] == 1 and o["ai"]["pending_review_cases"] == 1
        assert o["vehicles"]["abnormal_plates"] == ["RCG-2235"]
        assert o["recent_incidents"][0]["case_id"] == f"RI-{s['rental_id']}-右後"
        client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return")
        srv.post_decision(srv.Decision(case_id=f"RI-{s['rental_id']}-右後", decision="confirm"))
        o = admin.get("/api/ops/overview").json()
        assert o["today"]["returns_completed"] == 1 and o["ai"]["pending_review_cases"] == 0
        assert o["vehicles"]["maintenance"] == 1 and o["vehicles"]["abnormal_plates"] == ["RCG-2235"]   # 維修單鎖車


class TestRentals:
    def test_列表與明細_取車車牌辨識_照片_時間軸_案件(self, admin, client, judge_rear_damage):
        s = real_rental(client)
        rows = admin.get("/api/ops/rentals").json()["rentals"]
        assert [r["session_id"] for r in rows] == [s["session_id"]]
        r = rows[0]
        assert r["data_source"] == "app" and r["plate"] == "RCG-2235" and r["state"] == "INSPECTION_COMPLETED"
        assert r["pickup_plate_status"] == "MATCH" and r["pickup_plate_texts"] == ["RCG-2235"]
        assert r["review_state"] == "pending_review" and r["incident_count"] == 1 and r["unreviewed_count"] == 1
        d = admin.get(f"/api/ops/rentals/{s['session_id']}").json()
        assert len(d["pickup"]["photos"]) == 4 and all(p["url"] and p["plate_text"] == "RCG-2235" for p in d["pickup"]["photos"])
        assert len(d["return"]["photos"]) == 4
        labels = [t["label"] for t in d["timeline"]]
        assert labels[0].startswith("開始租車") and "AI 檢測完成" in labels
        assert d["inspection"]["incidents"][0]["review_status"] == "unreviewed"
        assert admin.get("/api/ops/rentals/RS-NOPE").status_code == 404

    def test_固定劇本Session預設不列_可切換顯示並標示(self, admin, client):
        s = drive_to_photo_inspection(client)                         # 固定劇本車
        shoot(client, s, "return", 30)
        assert admin.get("/api/ops/rentals").json()["rentals"] == []
        rows = admin.get("/api/ops/rentals?include_other=true").json()["rentals"]
        assert len(rows) == 1 and rows[0]["data_source"] == "fixture"
        assert admin.get("/api/ops/overview").json()["ai"]["completed"] == 0

    def test_需要登入(self, client):
        for path in ("/api/ops/overview", "/api/ops/rentals"):
            assert client.get(path).status_code == 401


class TestInspectionsReviewState:
    def test_資料來源與審核分類(self, admin, client, srv, judge_rear_damage):
        s = real_rental(client)
        items = {i["rental_id"]: i for i in admin.get("/api/ops/inspections").json()["inspections"]}
        assert items[s["rental_id"]]["data_source"] == "app" and items[s["rental_id"]]["review_state"] == "pending_review"
        assert items[s["rental_id"]]["session_id"] == s["session_id"]
        import demo_inspection_fixture as fixture
        assert items[fixture.DEMO_RENTAL_ID]["data_source"] == "fixture"            # DEMO_MODE 種下的劇本
        srv.post_decision(srv.Decision(case_id=f"RI-{s['rental_id']}-右後", decision="reject"))
        d = admin.get(f"/api/ops/inspections/{s['rental_id']}").json()["inspection"]
        assert d["review_state"] == "reviewed" and d["data_source"] == "app"
