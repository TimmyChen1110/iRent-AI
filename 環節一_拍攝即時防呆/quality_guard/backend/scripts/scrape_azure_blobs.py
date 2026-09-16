"""[選用/需手動執行] 從 raw_data/車外車內照片上傳清單.xlsx 小規模抓取外部角落照片。

⚠️ 背景說明：清單裡每筆記錄都附一個 Azure Blob Storage 的直連網址
(https://irentv2data.blob.core.windows.net/carpic/...)。先前測試發現這些
網址目前不需要任何登入即可公開存取——這看起來像是廠商端未預期的資料曝露
（車牌屬於個資，且是真實顧客租車紀錄），已經另外回報給使用者。

這支腳本本身只做「小規模、禮貌性」的抓取，用來擴充本地驗證集
（validation/run_validation.py 用的 293 張真實照片樣本量偏小）：

- 只抓 ImageType ∈ {1, 2, 3, 4}（左前/右前/左後/右後 4 個外部角落），
  室內視角（10/11）跟本階段任務無關，不抓。
- 每類別預設只抓一小批（--per-category，預設 20，需要手動調到 50~100）。
- 請求之間有延遲（--delay-seconds），失敗會重試但不會無限重試。
- 已存在的檔案會跳過（可重複執行）。
- 絕對不會寫入 raw_data/沒有進行索賠 或 raw_data/進行索賠資料，
  只會寫到 raw_data/scraped/ 底下。

這支腳本不會被 app/ 或 validation/run_validation.py 自動匯入或觸發，
必須手動執行，且 run_validation.py 預設不會讀取 scraped/ 資料夾
（要加 --include-scraped 才會）。
"""

import argparse
import csv
import random
import time
import urllib.error
import urllib.request
from pathlib import Path

import openpyxl

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BACKEND_DIR.parent / "raw_data"
MANIFEST_XLSX = RAW_DATA_DIR / "車外車內照片上傳清單.xlsx"
SCRAPED_DIR = RAW_DATA_DIR / "scraped"

IMAGE_TYPE_TO_LABEL = {1: "左前", 2: "右前", 3: "左後", 4: "右後"}


def load_rows_by_type() -> dict[int, list[dict]]:
    workbook = openpyxl.load_workbook(MANIFEST_XLSX, data_only=True)
    sheet = workbook.worksheets[0]
    rows_by_type: dict[int, list[dict]] = {t: [] for t in IMAGE_TYPE_TO_LABEL}

    for row in sheet.iter_rows(min_row=2, values_only=True):
        order_number, car_no, image_type, image_name, url = (list(row) + [None] * 5)[:5]
        if image_type not in rows_by_type:
            continue
        if not url:
            continue
        rows_by_type[image_type].append(
            {
                "order_number": order_number,
                "car_no": car_no,
                "image_type": image_type,
                "image_name": image_name,
                "url": url,
            }
        )
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
    parser.add_argument("--per-category", type=int, default=20, help="每個角度類別抓取的張數（預設小量 dry-run）")
    parser.add_argument("--delay-seconds", type=float, default=0.6)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--retries", type=int, default=2)
    args = parser.parse_args()

    rows_by_type = load_rows_by_type()
    rng = random.Random(args.seed)

    manifest_rows = []
    for image_type, label in IMAGE_TYPE_TO_LABEL.items():
        candidates = rows_by_type.get(image_type, [])
        sample = rng.sample(candidates, k=min(args.per_category, len(candidates)))
        out_dir = SCRAPED_DIR / label
        out_dir.mkdir(parents=True, exist_ok=True)

        print(f"[{label}] 候選 {len(candidates)} 筆，抽樣下載 {len(sample)} 筆")

        for row in sample:
            dest_path = out_dir / row["image_name"]
            status = "FAILED:not_attempted"
            for attempt in range(args.retries + 1):
                status = download_one(row["url"], dest_path)
                if status == "OK" or status == "SKIPPED_EXISTS":
                    break
                time.sleep(args.delay_seconds)

            manifest_rows.append({**row, "status": status, "dest_path": str(dest_path)})
            time.sleep(args.delay_seconds)

    SCRAPED_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = SCRAPED_DIR / "scrape_manifest.csv"
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()) if manifest_rows else [])
        writer.writeheader()
        writer.writerows(manifest_rows)

    ok_count = sum(1 for r in manifest_rows if r["status"] == "OK")
    print(f"\n完成：{ok_count}/{len(manifest_rows)} 成功下載，manifest 已寫入 {manifest_path}")


if __name__ == "__main__":
    main()
