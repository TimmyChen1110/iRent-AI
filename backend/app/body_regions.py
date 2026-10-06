"""車身區域對照表：AI 自由文字位置 → Digital Twin 區域 id（唯一一份）。

id 與 fleet-ops-center `HotspotLocation`（src/types/index.ts）完全一致；
前端 `damageLocator.ts` 的關鍵字規則在這裡有一份 Python 版，讓後端在建立
Incident 時就能寫入 `region`，前端拿到 region 直接定位 3D hotspot，拿不到
才退回自己的關鍵字推斷。兩邊共用同一組 id，不另外硬編第二套位置。
"""
from __future__ import annotations

import re

EXTERIOR_REGIONS = (
    "front-bumper", "rear-bumper", "hood", "roof",
    "left-front-door", "right-front-door", "left-rear-door", "right-rear-door",
    "left-front-fender", "right-front-fender", "left-rear-quarter", "right-rear-quarter",
    "windshield",
)
INTERIOR_REGIONS = ("interior", "rear-seat", "cup-holder", "driver-seat")
ALL_REGIONS = EXTERIOR_REGIONS + INTERIOR_REGIONS

REGION_LABELS = {
    "front-bumper": "前保桿", "rear-bumper": "後保桿", "hood": "引擎蓋", "roof": "車頂",
    "left-front-door": "左前車門", "right-front-door": "右前車門",
    "left-rear-door": "左後車門", "right-rear-door": "右後車門",
    "left-front-fender": "左前葉子板", "right-front-fender": "右前葉子板",
    "left-rear-quarter": "左後側板", "right-rear-quarter": "右後側板",
    "windshield": "擋風玻璃", "interior": "車內", "rear-seat": "後座",
    "cup-holder": "杯架", "driver-seat": "駕駛座",
}

# 規格文件用的大寫代號（RIGHT_REAR_DOOR）↔ twin id
REGION_CODES = {r.upper().replace("-", "_"): r for r in ALL_REGIONS}


def is_region(value: str | None) -> bool:
    return bool(value) and value in REGION_LABELS


def normalize_region(value: str | None) -> str | None:
    """接受 twin id 或規格代號（RIGHT_REAR_DOOR），回傳 twin id；不認得回 None。"""
    if not value:
        return None
    if value in REGION_LABELS:
        return value
    return REGION_CODES.get(value.upper().replace("-", "_"))


def locate_exterior(text: str | None, angle: str | None = None) -> str:
    """AI 自由文字（例「右後保險桿下緣」）→ 車外區域。規則與 damageLocator.locateDamage 同步。"""
    t = re.sub(r"\s", "", text or "")
    a = angle or ""
    left = "左" in t or ("右" not in t and "左" in a)
    right = "右" in t or ("左" not in t and "右" in a)
    rear = bool(re.search(r"後|尾|行李|hatch", t, re.I)) or (not re.search(r"前|頭|引擎", t) and "後" in a)
    front = bool(re.search(r"前|頭|引擎|大燈|水箱|日行燈|進氣", t)) or (not rear and "前" in a)

    if re.search(r"車頂|roof", t, re.I):
        return "roof"
    if re.search(r"擋風|windshield", t, re.I):
        return "windshield"
    if re.search(r"引擎蓋|hood|車頭", t) and not re.search(r"保險桿|保桿", t):
        return "hood"
    if re.search(r"車門|門板|門", t):
        if rear:
            return "left-rear-door" if left else "right-rear-door"
        return "left-front-door" if left else "right-front-door"
    if re.search(r"葉子板|側板|側裙|輪拱|側身", t):
        if rear:
            return "left-rear-quarter" if left else "right-rear-quarter"
        return "left-front-fender" if left else "right-front-fender"
    if re.search(r"保險桿|保桿|尾燈|大燈|後尾門|行李箱|車尾|反光片|下唇", t):
        if rear and not front:
            return "rear-bumper"
        if front and not rear:
            return "front-bumper"
        return "rear-bumper" if rear else "front-bumper"
    if rear:
        return "left-rear-quarter" if left else "right-rear-quarter" if right else "rear-bumper"
    if front:
        return "left-front-fender" if left else "right-front-fender" if right else "front-bumper"
    return "left-front-door" if left else "right-front-door" if right else "roof"


def locate_interior(issue: str, index: int = 0) -> str:
    """車內問題 → 車艙區域。規則與 damageLocator.locateInteriorIssue 同步。"""
    if re.search(r"杯|飲|瓶|罐", issue):
        return "cup-holder"
    if re.search(r"駕駛|前座|方向盤|儀表", issue):
        return "driver-seat"
    if re.search(r"後座|後排|行李", issue):
        return "rear-seat"
    return ("rear-seat", "cup-holder", "driver-seat")[index % 3]
