"""從 raw_data/車外車內照片上傳清單.csv 抓一批候選外部角落照片,供人工快速審視。

跟 scrape_azure_blobs.py 一樣是小規模、禮貌性抓取(同一份 CSV,同樣的 Azure Blob
公開存取範圍 —— 該檔已經記錄過這是廠商端未預期的個資曝露,已回報給使用者;
這支腳本延續同樣的節制原則:預設每類 100 張、有 delay、只寫到獨立的
raw_data/scraped/ 資料夾,不動既有的 dataset/ 或 raw_data/沒有進行索賠 等資料夾)。

id 用「車牌_訂單編號_ImageType」組成的穩定字串,不是流水號——這樣可以重複執行
這支腳本抓下一批,manifest.csv 用合併(append 新項目、跳過已存在的 id)而不是
整份覆蓋,review_decisions.csv 裡舊的審視紀錄才不會因為 id 重編而錯位或消失。

跟 scrape_azure_blobs.py 的差異:
1. 讀 CSV(而不是 xlsx),欄位: order_number, CarNo, ImageType, Image, 下載網址,
   (空欄), 上傳分類(常有誤), 時間。
2. 排除兩種已經看過的候選:
   - 車牌已經存在 dataset/train 或 dataset/val(這台車已經確定收進訓練集了)
   - (車牌,訂單編號,角度)已經在 manifest.csv 裡出現過(不管當初保留或拒絕,
     都不應該重複抽到同一張要求人審第二次)
3. 額外記錄 ImageType 對應的「系統角度」跟「上傳分類」欄位是否不一致
   (mismatch),供審視時特別留意——這欄位本身就叫「常有誤」,不能照單全收。

用法:
    cd backend && ../.venv/bin/python scripts/scrape_review_batch.py --per-category 100
"""
import argparse
import csv
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BACKEND_DIR.parent / "raw_data"
MANIFEST_CSV = RAW_DATA_DIR / "車外車內照片上傳清單.csv"
DATASET_DIR = BACKEND_DIR.parent / "dataset"
SCRAPED_DIR = RAW_DATA_DIR / "scraped"
SCRAPED_MANIFEST = SCRAPED_DIR / "manifest.csv"

IMAGE_TYPE_TO_LABEL = {1: "左前", 2: "右前", 3: "左後", 4: "右後"}


def normalize_plate(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def load_existing_plates() -> set[str]:
    plates = set()
    for split in ("train", "val"):
        split_dir = DATASET_DIR / split
        if not split_dir.exists():
            continue
        for path in split_dir.rglob("*.jpg"):
            plate = path.stem.split("_")[0]
            plates.add(normalize_plate(plate))
    return plates


def load_existing_manifest_rows() -> list[dict]:
    if not SCRAPED_MANIFEST.exists():
        return []
    with open(SCRAPED_MANIFEST, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_candidates(existing_plates: set[str], seen_ids: set[str]) -> dict[int, list[dict]]:
    rows_by_type: dict[int, list[dict]] = {t: [] for t in IMAGE_TYPE_TO_LABEL}
    with open(MANIFEST_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                image_type = int(row["ImageType"])
            except (ValueError, KeyError, TypeError):
                continue
            if image_type not in rows_by_type:
                continue
            url = row.get("下載網址")
            if not url:
                continue
            plate = normalize_plate(row.get("CarNo", ""))
            if plate in existing_plates:
                continue

            order_number = row.get("order_number")
            item_id = f"{plate}_{order_number}_{image_type}"
            if item_id in seen_ids:
                continue

            claimed_label = IMAGE_TYPE_TO_LABEL[image_type]
            upload_category = (row.get("上傳分類(常有誤)") or "").strip()
            mismatch = bool(upload_category) and upload_category != claimed_label

            rows_by_type[image_type].append({
                "id": item_id,
                "order_number": order_number,
                "plate": plate,
                "image_type": image_type,
                "claimed_label": claimed_label,
                "upload_category": upload_category,
                "label_mismatch": mismatch,
                "image_name": row.get("Image"),
                "url": url,
            })
    return rows_by_type


def download_one(url: str, dest_path: Path, timeout: float = 15.0) -> str:
    if dest_path.exists():
        return "SKIPPED_EXISTS"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            dest_path.write_bytes(response.read())
        return "OK"
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        return f"FAILED:{exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-category", type=int, default=100)
    parser.add_argument("--delay-seconds", type=float, default=0.5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    existing_plates = load_existing_plates()
    existing_manifest_rows = load_existing_manifest_rows()
    seen_ids = {row["id"] for row in existing_manifest_rows}
    print(f"排除 {len(existing_plates)} 個 dataset 裡已存在的車牌")
    print(f"排除 {len(seen_ids)} 筆已經在 manifest 裡出現過的候選(之前抓過/審過的)")

    rows_by_type = load_candidates(existing_plates, seen_ids)
    rng = random.Random(args.seed)

    new_rows = []
    for image_type, label in IMAGE_TYPE_TO_LABEL.items():
        candidates = rows_by_type.get(image_type, [])
        sample = rng.sample(candidates, k=min(args.per_category, len(candidates)))
        out_dir = SCRAPED_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)

        mismatch_count = sum(1 for r in sample if r["label_mismatch"])
        print(f"[{label}] 候選 {len(candidates)} 筆,抽樣下載 {len(sample)} 筆(其中 {mismatch_count} 筆系統角度與上傳分類不一致)")

        for row in sample:
            dest_name = f"{row['plate']}_C_{row['order_number']}.jpg"
            dest_path = out_dir / dest_name
            status = "FAILED:not_attempted"
            for attempt in range(args.retries + 1):
                status = download_one(row["url"], dest_path)
                if status in ("OK", "SKIPPED_EXISTS"):
                    break
                time.sleep(args.delay_seconds)

            new_rows.append({
                **row,
                "local_path": str(dest_path.relative_to(SCRAPED_DIR)),
                "status": status,
            })
            time.sleep(args.delay_seconds)

    SCRAPED_DIR.mkdir(parents=True, exist_ok=True)
    combined_rows = existing_manifest_rows + new_rows
    fieldnames = ["id", "order_number", "plate", "image_type", "claimed_label",
                  "upload_category", "label_mismatch", "image_name", "url",
                  "local_path", "status"]
    with open(SCRAPED_MANIFEST, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined_rows)

    ok_count = sum(1 for r in new_rows if r["status"] in ("OK", "SKIPPED_EXISTS"))
    print(f"\n這次新增: {ok_count}/{len(new_rows)} 成功下載")
    print(f"manifest 累計共 {len(combined_rows)} 筆,已寫入 {SCRAPED_MANIFEST}")


if __name__ == "__main__":
    main()
