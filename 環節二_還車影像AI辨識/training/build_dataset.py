#!/usr/bin/env python3
"""組出「單張有無車損」二分類訓練集。

資料來源（依優先序合併，後者覆蓋前者）：
  1. pipeline/relabels.json      — 141 組逐圖人工重標（目前唯一的已驗證標籤）
  2. dashboard/decisions.sqlite3 — 監理台累積的複核裁決（上線後會持續長大）

任務定義：判斷【還車照】單張是否有車損。
  label=1 → 該還車照有新增車損（relabel=damage / 裁決 confirm）
  label=0 → 無（relabel=clean / 裁決 reject）
  not_comparable / uncertain / retake 一律排除——那代表「判不出來」，
  不是「沒有車損」，當負樣本會直接汙染資料集。

★ 切分以【車輛】為單位，不是以照片為單位。
  同一台車有 4 個方位，若按照片隨機切，同車的照片會同時出現在 train 與 val，
  模型會靠「認得這台車」而非「認得車損」得到虛高分數（資料洩漏）。

用法：python3 build_dataset.py            # 產生 dataset.json
      python3 build_dataset.py --stats    # 只看統計不寫檔
"""
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"
DB = HERE.parent / "dashboard" / "decisions.sqlite3"
OUT = HERE / "dataset.json"

# 人工重標 → 標籤；只收明確的兩類
RELABEL_MAP = {"damage": 1, "clean": 0}


def from_relabels() -> dict:
    """{(car, angle): {label, photo, source}}"""
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((PIPE / "pairs.json").read_text())["pairs"]}
    out = {}
    for r in json.loads((PIPE / "relabels.json").read_text())["relabels"]:
        lab = RELABEL_MAP.get(r.get("relabel"))
        if lab is None:
            continue                       # not_comparable / uncertain → 排除
        key = (r["car"], r["angle"])
        p = pairs.get(key)
        if not p:
            continue
        out[key] = {"car": r["car"], "angle": r["angle"], "label": lab,
                    "photo": p["return"],   # 任務是「還車照有無車損」
                    "pickup": p["pickup"],
                    "source": "relabel", "note": r.get("note") or ""}
    return out


def from_decisions() -> dict:
    """監理台累積的裁決。現在多半是空的，上線後會是主要來源。"""
    if not DB.exists():
        return {}
    conn = sqlite3.connect(DB)
    try:
        rows = conn.execute(
            "SELECT case_id, label, photos FROM decision_events"
            " WHERE label IS NOT NULL AND mode='pair' ORDER BY event_id").fetchall()
    except sqlite3.OperationalError:
        return {}
    finally:
        conn.close()
    out = {}
    for case_id, label, photos in rows:
        try:
            ph = json.loads(photos or "{}")
        except json.JSONDecodeError:
            continue
        ret = ph.get("return")
        if not ret or not Path(ret).exists():
            continue                        # LIVE 案件只有縮圖，無法訓練
        car, _, angle = case_id.rpartition("-")
        out[(car, angle)] = {"car": car, "angle": angle, "label": int(label),
                             "photo": ret, "pickup": ph.get("pickup"),
                             "source": "review", "note": ""}
    return out


def build():
    data = from_relabels()
    n_relabel = len(data)
    data.update(from_decisions())           # 監理台裁決優先（較新、人工當下確認）
    rows = [v for v in data.values() if Path(v["photo"]).exists()]
    return rows, n_relabel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    rows, n_relabel = build()
    pos = sum(r["label"] for r in rows)
    cars = {r["car"] for r in rows}
    dcars = {r["car"] for r in rows if r["label"] == 1}

    print(f"樣本 {len(rows)}（正 {pos} / 負 {len(rows) - pos}，正樣本比例 {100*pos/len(rows):.1f}%）")
    print(f"來源: {dict(Counter(r['source'] for r in rows))}"
          f"（relabels {n_relabel} 筆 + 監理台 {len(rows) - n_relabel if len(rows) > n_relabel else 0} 筆）")
    print(f"車輛 {len(cars)} 台（{len(dcars)} 台含車損）")
    print(f"方位分布: {dict(Counter(r['angle'] for r in rows))}")

    if args.stats:
        return
    OUT.write_text(json.dumps({
        "task": "還車照單張二分類：有無新增車損",
        "label_meaning": {"1": "有車損", "0": "無車損"},
        "split_policy": "以車輛(car)為單位分組切分，避免同車照片跨 train/val 造成洩漏",
        "n": len(rows), "positive": pos, "cars": len(cars),
        "samples": rows,
    }, ensure_ascii=False, indent=1))
    print(f"\n→ {OUT.name}")


if __name__ == "__main__":
    main()
