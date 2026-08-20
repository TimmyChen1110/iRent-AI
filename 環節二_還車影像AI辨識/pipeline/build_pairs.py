#!/usr/bin/env python3
"""建立借/還車照片配對資料集。

掃描「沒有進行索賠」(負樣本) 與「進行索賠資料」(正樣本) 兩個資料夾，
依 車牌 + 方位 配對借車照與還車照，輸出 pairs.json。

檔名格式（空格可有可無）：
    RCR-7661 左後 借.jpg / RCW-8382左前 還.jpg / RFH7873左後 還.jfif
    「還2」為同角度補拍，作為備用還車照記錄。
    「車況回報」為單張特寫，無借/還配對，另列 extras。
"""
import json
import re
import sys
from pathlib import Path

DATA_ROOT = Path(__file__).resolve().parents[2] / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"
NEG_DIR = DATA_ROOT / "沒有進行索賠"
POS_DIR = DATA_ROOT / "進行索賠資料"
OUT = Path(__file__).resolve().parent / "pairs.json"

FNAME_RE = re.compile(r"^([A-Z0-9-]+?)\s*(左前|左後|右前|右後)\s*(借|還)(2)?\.(jpg|jpeg|jfif)$", re.I)


def scan(folder: Path, label: str):
    """回傳 {(car, angle): {"借": path, "還": path, "還2": path}}"""
    slots, extras = {}, []
    for f in sorted(folder.iterdir()):
        if f.name.startswith(".") or f.is_dir() or f.suffix.lower() == ".zip":
            continue
        m = FNAME_RE.match(f.name)
        if not m:
            extras.append(str(f))
            continue
        car, angle, phase, dup = m.group(1), m.group(2), m.group(3), m.group(4)
        key = (car, angle)
        slot = slots.setdefault(key, {})
        slot[phase + (dup or "")] = str(f)
    pairs = []
    for (car, angle), slot in sorted(slots.items()):
        if "借" in slot and "還" in slot:
            pairs.append({
                "car": car, "angle": angle, "label": label,
                "pickup": slot["借"], "return": slot["還"],
                "return_alt": slot.get("還2"),
            })
        else:
            extras.append(f"[不成對] {car} {angle}: {sorted(slot)}")
    return pairs, extras


def main():
    neg_pairs, neg_extras = scan(NEG_DIR, "negative")
    pos_pairs, pos_extras = scan(POS_DIR, "positive")
    dataset = {
        "pairs": neg_pairs + pos_pairs,
        "extras": {"negative": neg_extras, "positive": pos_extras},
        "summary": {
            "negative_pairs": len(neg_pairs),
            "negative_cars": len({p["car"] for p in neg_pairs}),
            "positive_pairs": len(pos_pairs),
            "positive_cars": len({p["car"] for p in pos_pairs}),
        },
    }
    OUT.write_text(json.dumps(dataset, ensure_ascii=False, indent=2))
    print(json.dumps(dataset["summary"], ensure_ascii=False, indent=2))
    for kind, ex in dataset["extras"].items():
        for e in ex:
            print(f"  extra({kind}): {Path(e).name if '/' in str(e) else e}", file=sys.stderr)


if __name__ == "__main__":
    main()
