"""把 review_tool.py 收集到的審視結果套用到 dataset/ 裡。

三種決定分別處理:
- keep：用跟 build_dataset.py 一致的「車牌 hash 分 train/val」規則(同一份
  公式、同樣 15% val 比例),複製進 dataset/{train,val}/{角度}/。
- borderline（邊界模糊：車輛本身清楚完整,但角度卡在兩個角落交界,例如
  接近正前方/正後方/正側面）：複製進 dataset/calibration_borderline/,
  不進 train/val——這批不是拿來訓練,是拿來校準 Stage 4 信心門檻用的獨立
  測試集,混進訓練資料反而會弄髒訓練集。
- reject：直接略過,不會進 dataset。

用法:
    cd backend && ../.venv/bin/python scripts/apply_review_decisions.py
"""
import csv
import hashlib
import shutil
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BACKEND_DIR.parent / "raw_data"
SCRAPED_DIR = RAW_DATA_DIR / "scraped"
MANIFEST_PATH = SCRAPED_DIR / "manifest.csv"
DECISIONS_PATH = SCRAPED_DIR / "review_decisions.csv"
DATASET_DIR = BACKEND_DIR.parent / "dataset"
BORDERLINE_DIR = DATASET_DIR / "calibration_borderline"

VAL_RATIO = 0.15


def plate_split_bucket(plate_text: str) -> str:
    digest = hashlib.sha1(plate_text.encode("utf-8")).hexdigest()
    bucket = int(digest, 16) % 100
    return "val" if bucket < VAL_RATIO * 100 else "train"


def main() -> None:
    if not DECISIONS_PATH.exists():
        print("找不到 review_decisions.csv,還沒有審視紀錄可以套用。")
        return

    with open(MANIFEST_PATH, newline="", encoding="utf-8-sig") as f:
        manifest = {row["id"]: row for row in csv.DictReader(f)}
    with open(DECISIONS_PATH, newline="", encoding="utf-8-sig") as f:
        decisions = list(csv.DictReader(f))

    counts = {"keep": 0, "reject": 0, "borderline": 0, "other": 0}
    missing_label, copied_dataset, copied_borderline, skipped_exists = 0, 0, 0, 0

    BORDERLINE_DIR.mkdir(parents=True, exist_ok=True)

    for decision in decisions:
        kind = decision["decision"]
        counts[kind] = counts.get(kind, 0) + 1

        if kind == "reject":
            continue

        item_id = decision["id"]
        row = manifest.get(item_id)
        if row is None:
            continue

        src_path = SCRAPED_DIR / row["local_path"]
        if not src_path.exists():
            continue

        if kind == "keep":
            final_label = decision.get("final_label") or row["claimed_label"]
            if not final_label:
                missing_label += 1
                continue

            split = plate_split_bucket(row["plate"])
            dst_dir = DATASET_DIR / split / final_label
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst_path = dst_dir / f"{row['plate']}_C_{row['order_number']}.jpg"

            if dst_path.exists():
                skipped_exists += 1
                continue

            shutil.copy2(src_path, dst_path)
            copied_dataset += 1

        elif kind == "borderline":
            dst_path = BORDERLINE_DIR / f"{row['plate']}_C_{row['order_number']}_系統標籤={row['claimed_label']}.jpg"

            if dst_path.exists():
                skipped_exists += 1
                continue

            shutil.copy2(src_path, dst_path)
            copied_borderline += 1

    print(f"審視紀錄共 {len(decisions)} 筆")
    print(f"  保留(keep): {counts.get('keep', 0)}")
    print(f"  邊界模糊(borderline): {counts.get('borderline', 0)}")
    print(f"  拒絕(reject): {counts.get('reject', 0)}")
    print(f"  缺少最終角度標籤(略過): {missing_label}")
    print(f"  已複製進 dataset/train|val: {copied_dataset}")
    print(f"  已複製進 dataset/calibration_borderline/: {copied_borderline}")
    print(f"  目的地已存在(略過): {skipped_exists}")


if __name__ == "__main__":
    main()
