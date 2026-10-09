"""管理者車隊清單（/api/ops/fleet）與 App 可租車輛（/v1/rental-sessions/vehicles）的狀態一致性（零 Gemini API 成本）。

2026-10-09 問題三：後台車隊清單只列資料集／任務／鎖定／「已有取還車時間」的車，App 可租的車（demo_vehicles）
從沒被租過就不會出現；租用中的車在後台仍顯示 available。修復後兩邊用同一個可用性判斷（rental_sessions.availability）。
"""
from test_rental_sessions import (  # noqa: F401
    FIXTURE_VEHICLE, admin, client, drive_to_photo_inspection, shoot, srv, start,
)

ALL_PLATES = {"RCG-2235", "ABC-1234", "RFY-1753", "RDG-9853", "RFH-8122"}


def fleet_row(car):
    import ops_api
    return next(r for r in ops_api.fleet()["fleet"] if r["car"] == car)


def app_status(client, vehicle_id):
    """一般使用者清單只有 public 車輛；internal 車輛（固定劇本）走單台查詢的內部視圖。"""
    import rental_sessions as rs
    return rs.get_vehicle(vehicle_id, internal=True)["status"]


class TestFleetListsRentableVehicles:
    def test_從未租過的可租車輛也出現在後台_且標示可租用(self, client):
        import ops_api
        resp = ops_api.fleet()
        rows = {r["car"]: r for r in resp["fleet"] if r["rental_fleet"]}
        assert set(rows) == ALL_PLATES
        assert all(r["rentable"] and r["status"] in ("available", "review") for r in rows.values())   # review＝資料集既有待審 AI 案件，不鎖派單
        assert resp["counts"]["rentable"] == len(ALL_PLATES)
        assert rows["RFY-1753"]["model"] == "TOYOTA ALTIS HYBRID"
        assert rows["RFY-1753"]["rental_state"]["vehicle_id"] == "demo-rfy-1753"
        # 資料集車輛不是 App 可租車輛：不會被標成可租用
        assert not any(r["rentable"] for r in resp["fleet"] if not r["rental_fleet"])
        # App 一般清單（public）的每台車在後台都是可租用
        for v in client.get("/v1/rental-sessions/vehicles").json()["vehicles"]:
            assert v["status"] == "AVAILABLE" and v["rentable"] is True and rows[v["plate"]]["rentable"]

    def test_租用中到退租完成_後台與App同步(self, client):
        s = start(client)                                          # 取車檢查中
        assert fleet_row("ABC-1234")["status"] == "rented" and not fleet_row("ABC-1234")["rentable"]
        assert fleet_row("ABC-1234")["rental_state"]["session_state"] == "PICKUP_INSPECTION"
        assert app_status(client, FIXTURE_VEHICLE) == "RENTED"
        shoot(client, s, "pickup", 10)
        sid = s["session_id"]
        client.post(f"/v1/rental-sessions/{sid}/pickup/complete")
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 3})
        shoot(client, s, "return", 30)
        # 檢測完成但尚未確認還車：仍是租用中，不可出租
        assert client.get(f"/v1/rental-sessions/{sid}").json()["state"] == "INSPECTION_COMPLETED"
        row = fleet_row("ABC-1234")
        assert row["status"] == "rented" and not row["rentable"] and row["rental_state"]["session_state"] == "INSPECTION_COMPLETED"
        # 取消還車：仍租用中
        client.post(f"/v1/rental-sessions/{sid}/return/cancel")
        assert fleet_row("ABC-1234")["status"] == "rented"
        # 再還一次並確認還車 → 車輛重新上架
        client.post(f"/v1/rental-sessions/{sid}/return/initiate")
        client.post(f"/v1/rental-sessions/{sid}/return/info", json={"end_odometer_km": s["start_odometer_km"] + 3})
        shoot(client, s, "return", 50)
        assert client.post(f"/v1/rental-sessions/{sid}/confirm-return").json()["state"] == "RETURNED"
        row = fleet_row("ABC-1234")
        assert row["status"] != "rented" and row["rentable"] is True and row["rental_state"]["session_id"] is None
        assert app_status(client, FIXTURE_VEHICLE) == "AVAILABLE"


class TestMaintenanceBlocksRental:
    def test_人工鎖定_App顯示整備中且不能租_解除後恢復(self, client):
        import ops_api
        ops_api.patch_fleet("RFY-1753", ops_api.LockIn(locked=True, reason="輪胎更換"), x_ops_reader="營運")
        v = client.get("/v1/rental-sessions/vehicles/demo-rfy-1753").json()
        assert v["status"] == "MAINTENANCE" and v["rentable"] is False and v["unavailable_reason"] == "整備中，暫停出租"
        assert "輪胎" not in str(v)                                     # 內部原因不外露給一般使用者
        row = fleet_row("RFY-1753")
        assert row["status"] == "locked" and not row["rentable"]
        r = client.post("/v1/rental-sessions", json={"vehicle_id": "demo-rfy-1753"})
        assert r.status_code == 409 and "整備" in r.json()["detail"]
        ops_api.patch_fleet("RFY-1753", ops_api.LockIn(locked=False), x_ops_reader="營運")
        assert client.get("/v1/rental-sessions/vehicles/demo-rfy-1753").json()["status"] == "AVAILABLE"
        assert fleet_row("RFY-1753")["rentable"] is True

    def test_還車案件確認開維修單_完工前不可出租_完工後重新上架(self, client, srv):
        s = drive_to_photo_inspection(client)                       # 固定劇本：右後新損 + 車內髒汙
        shoot(client, s, "return", 30)
        client.post(f"/v1/rental-sessions/{s['session_id']}/confirm-return")
        assert app_status(client, FIXTURE_VEHICLE) == "AVAILABLE"   # 案件尚未裁決：依既有語意不鎖派單
        assert fleet_row("ABC-1234")["status"] == "review"
        task = srv.post_decision(srv.Decision(case_id=f"RI-{s['rental_id']}-右後", decision="confirm"))["task"]
        assert task and task["status"] == "pending"
        assert app_status(client, FIXTURE_VEHICLE) == "MAINTENANCE"
        assert fleet_row("ABC-1234")["status"] == "locked" and not fleet_row("ABC-1234")["rentable"]
        assert client.post("/v1/rental-sessions", json={"vehicle_id": FIXTURE_VEHICLE}).status_code == 409
        for st in ("in_progress", "completed"):
            srv.patch_task(task["id"], srv.TaskUpdate(status=st))
        assert app_status(client, FIXTURE_VEHICLE) == "AVAILABLE"
        assert fleet_row("ABC-1234")["rentable"] is True
