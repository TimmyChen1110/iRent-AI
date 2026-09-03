#!/usr/bin/env python3
"""① 把 photo_chain 的跨單判定結果併回損傷護照。

photo_chain.py 產出的 chain_results_*.json 原本只留在檔案裡，
Dashboard 與護照都看不到——跨單新損（責任可回溯到具體訂單）是本專案
最有說服力的案例之一，必須進入護照才算閉環。

與 build_passport.py 的分工：
  build_passport.py  → 從「當單借/還比對」建檔（kind="new"/"pre_existing"）
  merge_chain.py     → 追加「跨訂單鏈」發現（kind="chain"），責任單為 curr

冪等：以 (car, prev→curr, itype) 為鍵，重跑只更新不重複追加。
用法：python3 merge_chain.py [--dry-run]
"""
import argparse
import glob
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PASSPORTS = HERE / "passports.json"


def collect():
    """讀所有 chain_results_*.json，取出判定為跨單新損的組。"""
    out = []
    for f in sorted(glob.glob(str(HERE / "chain_results_*.json"))):
        for r in json.loads(Path(f).read_text()):
            if not r.get("liable_order"):
                continue
            votes = r.get("votes") or []
            found = [v for v in votes if v.get("new_damage_found")]
            if not found:
                continue
            # 取信心最高的一票作為代表判定
            best = max(found, key=lambda v: max((d["confidence"] for d in v["damages"]), default=0))
            d0 = max(best["damages"], key=lambda d: d["confidence"])
            out.append({
                "car": r["car"],
                "prev": r["prev"],
                "curr": r["curr"],
                "itype": r["itype"],
                "angle": r.get("guess") or f"ImageType {r['itype']}",
                "damage": d0,
                "agree": f"{len(found)}/{len(votes)}",
            })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只印出將寫入的內容，不改檔")
    args = ap.parse_args()

    hits = collect()
    print(f"chain 結果中偵測到跨單新損 {len(hits)} 筆")
    if not hits:
        return

    passports = json.loads(PASSPORTS.read_text())
    added = updated = 0

    for h in hits:
        car = h["car"]
        p = passports.setdefault(car, {"car": car, "records": [], "real_orders": {}})
        key = f"{h['prev']}->{h['curr']}:{h['itype']}"
        exist = next((r for r in p["records"]
                      if r.get("kind") == "chain" and r.get("chain_key") == key), None)
        d = h["damage"]
        rec = {
            "id": exist["id"] if exist else f"C-{sum(1 for r in p['records'] if r.get('kind') == 'chain') + 1:03d}",
            "kind": "chain",
            "status": "open",
            "chain_key": key,
            "angle": h["angle"],
            "location": d["location"],
            "type": d["type"],
            "severity": d["severity"],
            "confidence": d["confidence"],
            "box_2d": exist.get("box_2d") if exist else None,
            "reasoning": d["reasoning"],
            "first_seen": {"order": h["curr"], "time": "", "source": "跨訂單照片鏈"},
            "evidence_case": f"CHAIN-{car}-{h['itype']}",
            "verified": exist.get("verified", False) if exist else False,
            "liable_order": h["curr"],
            "baseline_order": h["prev"],
            "vote_agreement": h["agree"],
        }
        if exist:
            p["records"][p["records"].index(exist)] = rec
            updated += 1
        else:
            p["records"].append(rec)
            added += 1
        print(f"  {car} {h['angle']}：{d['location']}·{d['type']} "
              f"({d['confidence']:.2f}, {h['agree']} 票) 責任單 #{h['curr']}（基準 #{h['prev']}）")

    # 重算計數（沿用 build_passport.py 的欄位語意）
    for car, p in passports.items():
        p["open_new"] = sum(1 for r in p["records"] if r["kind"] == "new")
        p["pre_existing"] = sum(1 for r in p["records"] if r["kind"] == "pre_existing")
        p["chain_new"] = sum(1 for r in p["records"] if r["kind"] == "chain")
        p.setdefault("real_orders", {})

    if args.dry_run:
        print(f"\n[dry-run] 將新增 {added} 筆、更新 {updated} 筆，未寫檔")
        return

    PASSPORTS.write_text(json.dumps(passports, ensure_ascii=False, indent=1))
    print(f"\n已寫入 passports.json：新增 {added} 筆、更新 {updated} 筆，共 {len(passports)} 台車")


if __name__ == "__main__":
    main()
