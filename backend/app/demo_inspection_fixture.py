"""Competition Demo 固定劇本（deterministic demo fixture）——唯一允許寫死結果的地方。

Production path（rental_inspections._real_analysis）永遠跑真實 pipeline；
只有 `is_demo_rental()` 為真的租約會走這裡的固定結果。這個模組刻意不碰
資料庫、不碰 FastAPI：它只回答「示範租約長什麼樣」「示範結果是什麼」，
由 rental_inspections 負責落地。

示範租約 RNT-20261005-1842（ABC-1234 Toyota Yaris）：
  Pickup 20:02 → Baseline（右前保險桿既有輕微刮痕 87%）
  Return 20:42 → 右後車門新增刮痕 92%（NEW_DAMAGE）、右前既有損傷不重複開案（EXISTING_DAMAGE）、
                 車內髒汙 88%（食物包裝／飲料杯／座椅污漬 → CLEANING_REQUIRED）

示範固定照片（stand-in）：App 尚未上傳前，用資料集既有照片佔位，讓管理者端
不依賴 iOS 也能完整展示；App 一上傳真照片就會取代佔位照並重跑固定結果。
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"

DEMO_RENTAL_ID = "RNT-20261005-1842"

DEMO_RENTAL = {
    "rental_id": DEMO_RENTAL_ID,
    "vehicle_id": "VH-ABC-1234",
    "plate": "ABC-1234",
    "vehicle_model": "Toyota Yaris",
    "pickup_at": "2026-10-05T20:02:00",
    "return_at": "2026-10-05T20:42:00",
}

# 真實 Core ML 測試用的舊示範租約（RCG-2235 是資料集內真車，車牌可被 OCR 驗證）
LEGACY_DEMO_RENTAL = {
    "rental_id": "demo-rental-001",
    "vehicle_id": "demo-car-001",
    "plate": "RCG-2235",
    "vehicle_model": "Toyota Yaris",
}

# 後端啟動時登記的租約（取代原本 user_capture_api.DEMO_RENTAL_PLATES）
REGISTERED_RENTALS = (DEMO_RENTAL, LEGACY_DEMO_RENTAL)

FIXTURE_VERSION = "demo-fixture-2026.10"


def is_demo_rental(rental_id: str | None) -> bool:
    return rental_id == DEMO_RENTAL_ID


def baseline() -> dict:
    """Pickup Baseline：記錄既有車損，讓還車比對不把舊傷判成 NEW_DAMAGE。"""
    return {
        "source": "demo_fixture",
        "version": FIXTURE_VERSION,
        "existing_damage": [{
            "angle": "右前",
            "region": "front-bumper",
            "label": "右前保險桿",
            "type": "刮痕",
            "severity": "low",
            "confidence": 0.87,
            "status": "EXISTING_DAMAGE",
            "reasoning": "取車照已存在的輕微刮痕，列入基準，還車時不重複判定。",
        }],
        "note": "示範固定基準：既有損傷由 fixture 提供。",
    }


def analysis() -> dict:
    """Return 比對固定結果：每個車外角度一筆、車內一筆。"""
    return {
        "source": "demo_fixture",
        "versions": {"fixture": FIXTURE_VERSION},
        "exterior": {
            "左前": {"result": "NO_NEW_DAMAGE", "findings": [], "boxes": [],
                    "summary": "左前與取車照一致，未發現新增車損。"},
            "右前": {"result": "EXISTING_DAMAGE", "boxes": [],
                    "findings": [{
                        "region": "front-bumper", "label": "右前保險桿", "type": "刮痕",
                        "severity": "low", "confidence": 0.87, "status": "EXISTING_DAMAGE",
                        "reasoning": "與取車基準中的既有刮痕一致，非本次租借造成。",
                    }],
                    "summary": "右前保險桿刮痕與取車基準相同（既有損傷），不建立案件。"},
            "左後": {"result": "NO_NEW_DAMAGE", "findings": [], "boxes": [],
                    "summary": "左後與取車照一致，未發現新增車損。"},
            "右後": {"result": "NEW_DAMAGE",
                    "findings": [{
                        "region": "right-rear-door", "label": "右後車門", "type": "刮痕",
                        "severity": "medium", "confidence": 0.92, "status": "NEW_DAMAGE",
                        "reasoning": "還車照右後車門中段出現取車照沒有的線狀刮痕，長約 15 公分。",
                    }],
                    "boxes": [{"box_2d": [470, 560, 560, 760], "label": "刮痕", "severity": "medium",
                               "confidence": 0.92, "description": "右後車門：取車照無此刮痕"}],
                    "summary": "右後車門新增刮痕（信心 92%，中度）。"},
        },
        "interior": {
            "result": "CLEANING_REQUIRED",
            "cleanliness": "髒汙",
            "confidence": 0.88,
            "score": 38,
            "findings": [
                {"label": "食物包裝", "region": "rear-seat", "severity": "medium", "confidence": 0.9,
                 "description": "後座遺留食物包裝袋"},
                {"label": "飲料杯", "region": "cup-holder", "severity": "medium", "confidence": 0.88,
                 "description": "杯架遺留飲料杯"},
                {"label": "座椅污漬", "region": "rear-seat", "severity": "medium", "confidence": 0.84,
                 "description": "後座椅面有液體污漬"},
            ],
            "boxes": [
                {"box_2d": [560, 120, 760, 420], "label": "食物包裝", "severity": "medium", "confidence": 0.9},
                {"box_2d": [620, 520, 800, 660], "label": "飲料杯", "severity": "medium", "confidence": 0.88},
                {"box_2d": [380, 400, 520, 720], "label": "座椅污漬", "severity": "medium", "confidence": 0.84},
            ],
            "summary": "車內髒汙（信心 88%）：食物包裝、飲料杯、座椅污漬，須清潔。",
        },
    }


# ---------- 示範固定照片（App 尚未上傳前的佔位照） ----------

def _dataset_pair_photos() -> dict[tuple[str, str], str]:
    """RCG2235 四方位借／還照 → {(PICKUP|RETURN, 角度): 絕對路徑}。資料集不在就回空。"""
    try:
        from pairs_io import load_pairs  # noqa: PLC0415
        out = {}
        for p in load_pairs():
            if p["car"].replace("-", "") != "RCG2235":
                continue
            out[("PICKUP", p["angle"])] = p["pickup"]
            out[("RETURN", p["angle"])] = p["return"]
        return out
    except Exception:
        return {}


def _dataset_interior_photos() -> dict[str, str]:
    """車內照：取車用一張「乾淨」、還車用示範髒汙照（遺留寶特瓶）。"""
    out = {}
    try:
        results = json.loads((PIPE / "interior_results.json").read_text())["results"]
        dirty = next((r for r in results if r["file"].startswith("H47353140_10")), None)
        clean = next((r for r in results if (r.get("assessment") or {}).get("level") == "乾淨"), None)
        if clean:
            out["PICKUP"] = str(PIPE / "interior_photos" / clean["file"])
        if dirty:
            out["RETURN"] = str(PIPE / "interior_photos" / dirty["file"])
    except Exception:
        pass
    return out


def stand_in_photos() -> list[dict]:
    """示範租約的 10 張佔位照（4 車外 + 1 車內 × 取車／還車）。檔案不存在也照登記（供圖 404 即可）。"""
    pairs = _dataset_pair_photos()
    interior = _dataset_interior_photos()
    photos = []
    for itype, stamp in (("PICKUP", DEMO_RENTAL["pickup_at"]), ("RETURN", DEMO_RENTAL["return_at"])):
        for angle in ("左前", "右前", "左後", "右後"):
            photos.append({"inspection_type": itype, "view_angle": angle,
                           "storage_path": pairs.get((itype, angle)), "captured_at": stamp})
        photos.append({"inspection_type": itype, "view_angle": "車內",
                       "storage_path": interior.get(itype), "captured_at": stamp})
    return photos
