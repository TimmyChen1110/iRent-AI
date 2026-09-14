#!/usr/bin/env python3
"""把「車外車內照片上傳清單.xlsx」（真實上傳 log）彙整成整備中心「營運洞察」用的小型 JSON。

離線一次性執行，輸出 app/ops_insights.json（進版控，server 啟動不讀 xlsx）。
只做可稽核的計數，不推論：
  - 依訂單去重（一張單多張照片算一次還車）
  - 依還車時段（小時）計數 → 清潔／整備人力該排在哪個時段
  - 資料只有一天（2026-04-22），所以【不做】星期分布；n 與日期一併輸出讓前端標註口徑

用法：python3 pipeline/build_ops_insights.py
"""
import collections
import datetime
import json
import sys
from pathlib import Path

import openpyxl

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
OUT = HERE.parent / "app" / "ops_insights.json"


def find_xlsx() -> Path:
    hits = list(ROOT.glob("iRent*/車外車內照片上傳清單.xlsx"))
    if not hits:
        sys.exit("找不到 車外車內照片上傳清單.xlsx（需在 repo 根的資料集資料夾內）")
    return hits[0]


def main():
    ws = openpyxl.load_workbook(find_xlsx(), read_only=True).worksheets[0]
    orders: dict[str, dict] = {}
    photos = 0
    type_count = collections.Counter()
    for r in ws.iter_rows(min_row=2, values_only=True):
        order, car, itype, img = str(r[0]), r[1], str(r[2]), str(r[3])
        photos += 1
        type_count[itype] += 1
        ts = img.split("_")[-1].split(".")[0]          # H<order>_<type>_<YYYYMMDDhhmmss>.png
        o = orders.setdefault(order, {"car": car, "ts": ts, "types": set()})
        o["types"].add(itype)
        o["ts"] = min(o["ts"], ts)
    by_hour = [0] * 24
    dates = collections.Counter()
    cars = collections.Counter()
    interior_uploaded = 0
    for o in orders.values():
        d = datetime.datetime.strptime(o["ts"], "%Y%m%d%H%M%S")
        by_hour[d.hour] += 1
        dates[d.strftime("%Y-%m-%d")] += 1
        cars[o["car"]] += 1
        if {"10", "11"} & o["types"]:
            interior_uploaded += 1
    out = {
        "source": "車外車內照片上傳清單.xlsx（真實上傳 log）",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "photos": photos,
        "orders": len(orders),
        "vehicles": len(cars),
        "dates": dict(sorted(dates.items())),
        "by_hour": by_hour,
        "interior_uploaded_orders": interior_uploaded,
        "image_type_count": dict(sorted(type_count.items(), key=lambda kv: int(kv[0]))),
        "note": "以訂單去重計算還車時段；資料僅涵蓋單日，故不提供星期分布。",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"orders={len(orders)} photos={photos} vehicles={len(cars)} → {OUT.name}")


if __name__ == "__main__":
    main()
