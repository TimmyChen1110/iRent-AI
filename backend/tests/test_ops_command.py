"""指揮中心 API：站點對照、車輛位置、案件清單與裁決（零 API 成本、不打網路）。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import server
    import ops_db
    monkeypatch.setattr(server, "DB_PATH", tmp_path / "test.sqlite3")
    monkeypatch.setattr(server, "send_notification", lambda payload: True)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("IRENT_ADMIN_PASSWORD", "admin-demo")
    ops_db.reset_schema_cache()
    c = TestClient(server.app)
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin-demo"})
    assert r.status_code == 200, r.text
    return c


def test_stations_and_default_location_are_deterministic(client):
    r = client.get("/api/ops/stations")
    assert r.status_code == 200
    ids = {s["id"] for s in r.json()["stations"]}
    assert "xinyi-a3" in ids and len(r.json()["cities"]) == 4
    f1 = client.get("/api/ops/fleet").json()["fleet"]
    f2 = client.get("/api/ops/fleet").json()["fleet"]
    assert f1 and all(row["location"] and row["location"]["station_id"] in ids for row in f1)
    assert [row["location"]["station_id"] for row in f1] == [row["location"]["station_id"] for row in f2]


def test_manual_location_override_and_clear(client):
    car = client.get("/api/ops/fleet").json()["fleet"][0]["car"]
    r = client.patch(f"/api/ops/fleet/{car}/location", json={"station_id": "zuoying-p1"})
    assert r.status_code == 200 and r.json()["location"]["station_id"] == "zuoying-p1"
    assert r.json()["location"]["manual"] is True
    row = next(x for x in client.get("/api/ops/fleet").json()["fleet"] if x["car"] == car)
    assert row["location"]["city"] == "高雄"
    assert client.patch(f"/api/ops/fleet/{car}/location", json={"station_id": "nope"}).status_code == 400
    r = client.patch(f"/api/ops/fleet/{car}/location", json={"station_id": None})
    assert r.json()["location"]["manual"] is False


def test_cases_list_and_decision_roundtrip(client):
    r = client.get("/api/ops/cases")
    assert r.status_code == 200
    cases = r.json()["cases"]
    assert cases and {"pair", "interior"} <= {c["mode"] for c in cases}
    demo = next(c for c in cases if c["case_id"] == "RCR-7661-左後")
    assert demo["review_status"] == "unreviewed" and demo["ai_level"] == "P1"
    assert demo["photos"]["pickup"].startswith("/photos/pair/") and demo["damages"]
    assert demo["location"]["station"]

    r = client.post("/api/ops/cases/RCR-7661-左後/decision", json={"decision": "confirm"})
    assert r.status_code == 200 and r.json()["ok"]
    assert r.json()["case"]["review_status"] == "confirmed_open"
    assert r.json()["task"]["task_type"] == "repair"
    one = client.get("/api/ops/cases/RCR-7661-左後").json()
    assert one["case"]["tasks"][0]["status"] == "pending"
    assert one["view"]["decision"]["decision"] == "confirm"

    r = client.delete("/api/ops/cases/RCR-7661-左後/decision")
    assert r.status_code == 200 and r.json()["case"]["review_status"] == "unreviewed"
    filtered = client.get("/api/ops/cases?status=unreviewed&levels=P1").json()["cases"]
    assert all(c["review_status"] == "unreviewed" and c["ai_level"] == "P1" for c in filtered)


def test_station_role_cannot_decide(client):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "station", "password": "station-demo"})
    if r.status_code != 200:
        pytest.skip("station demo account not configured")
    r = client.post("/api/ops/cases/RCR-7661-左後/decision", json={"decision": "confirm"})
    assert r.status_code == 403
