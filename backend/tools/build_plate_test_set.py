#!/usr/bin/env python3
"""建立「車牌辨識測試資料集」（給 Stonk 或任何外部驗證方的可匯出測試資料）。

輸出 backend/tools/plate_test_set/manifest.json：每張測試照片的路徑、sha256、預期車牌（來自資料集檔名）、
拍攝角度，以及用 **與 iOS App 相同的 Core ML 模型**（PlateDetector + PlateOCR，環節一 app_models/coreml）
實際跑出的辨識結果（車牌文字、信心、是否與預期一致）。

不假設 Stonk 的 API 規格：這裡只產出自描述的 manifest 與圖片；之後串接時由對方格式再轉。

用法（macOS，需 Xcode Command Line Tools；辨識用 Swift 驗證程式 app_models/scripts/validate_coreml_detector.swift）：
  python3 backend/tools/build_plate_test_set.py                 # 建 manifest（含辨識）
  python3 backend/tools/build_plate_test_set.py --no-recognize  # 只列照片與預期車牌（不跑模型）
  python3 backend/tools/build_plate_test_set.py --copy-images /path/to/export   # 另複製圖片到匯出資料夾

注意：資料集照片為比賽提供的 iRent 營運照片（車牌可見、非公開），只能在隊內／評審範圍使用，不可對外公開。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DATASET = REPO / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率" / "沒有進行索賠"
STAGE1 = REPO / "環節一_拍攝即時防呆" / "app_models"
VALIDATOR_SRC = STAGE1 / "scripts" / "validate_coreml_detector.swift"
DETECTOR = STAGE1 / "coreml" / "PlateDetector.mlpackage"
OCR = STAGE1 / "coreml" / "PlateOCR.mlpackage"
OUT_DIR = HERE / "plate_test_set"

# 預設挑選：模擬車輛 RCG-2235 的 8 張（4 方位 × 借／還）＋ 環節一 README 提過的另外三台車各 4 張借車照 ＋ app_models 範例照。
DEFAULT_CARS = ("RCG2235", "RCQ6760", "RDG8578", "RCX5100")
SAMPLE_PHOTOS = {"1.jpg": "RCG-2235", "2.jpg": None, "3.jpg": None}   # README 記載 1.jpg 為 RCG-2235；2、3 未標註（2026-10-09 Core ML 讀為 RDG-8571 / RDR-6350，皆為資料集車號，待人工確認）

NAME_RE = re.compile(r"^(?P<plate>[A-Z]{2,3}-?\d{4})(?P<angle>左前|右前|左後|右後)\s*(?P<stage>借|還)")


def format_plate(raw: str) -> str:
    raw = raw.replace("-", "").upper()
    m = re.match(r"^([A-Z]{2,3})(\d{4})$", raw)
    return f"{m.group(1)}-{m.group(2)}" if m else raw


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def compile_validator() -> Path | None:
    if not VALIDATOR_SRC.exists():
        return None
    out = Path(tempfile.gettempdir()) / "irent_plate_validate"
    if out.exists() and out.stat().st_mtime >= VALIDATOR_SRC.stat().st_mtime:
        return out
    try:
        subprocess.run(["swiftc", "-O", "-o", str(out), str(VALIDATOR_SRC)], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"無法編譯 Swift 驗證程式：{e}", file=sys.stderr)
        return None
    return out


def recognize(validator: Path, image: Path) -> dict:
    """跑 Core ML 偵測＋OCR（CPU），解析輸出。"""
    cmd = [str(validator), str(DETECTOR), str(image), "--ocr", str(OCR), "--cpu-only"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"engine": ENGINE, "status": "timeout", "plate_text": None, "confidence": None, "detections": None}
    out = r.stdout + r.stderr
    det = re.search(r"Detections above [\d.]+: (\d+)", out)
    det_conf = re.search(r"label=\S+ confidence=([\d.]+)", out)
    plate = re.search(r"OCR plate: (\S+)", out)
    conf = re.search(r"OCR mean character confidence: ([\d.]+)", out)
    exif = re.search(r"EXIF orientation: (\d+)", out)
    if plate:
        status = "recognized"
    elif det and det.group(1) == "0" or "No plate" in out:
        status = "no_plate_detected"
    elif "No characters recognized" in out:
        status = "ocr_unreadable"        # 偵測到車牌框但 OCR 讀不出字（App 端會要求重拍或手動輸入）
    else:
        status = "error"
    return {"engine": ENGINE, "status": status, "plate_text": plate.group(1) if plate else None,
            "confidence": round(float(conf.group(1)), 4) if conf else None,
            "detections": int(det.group(1)) if det else None,
            "detection_confidence": round(float(det_conf.group(1)), 4) if det_conf else None,
            "exif_orientation": int(exif.group(1)) if exif else None,
            "raw_tail": out.strip().splitlines()[-1][:200] if out.strip() and status == "error" else None}


ENGINE = "coreml:PlateDetector(YOLO)+PlateOCR(CCT) — 與 iOS App OnDeviceRecognitionService 相同模型（macOS CPU 執行）"


def collect(cars: tuple[str, ...]) -> list[dict]:
    items = []
    if DATASET.exists():
        for p in sorted(DATASET.glob("*.jpg")):
            m = NAME_RE.match(p.name)
            if not m or m.group("plate").replace("-", "") not in cars:
                continue
            items.append({"image": str(p.relative_to(REPO)), "expected_plate": format_plate(m.group("plate")),
                          "angle": m.group("angle"), "stage": "pickup" if m.group("stage") == "借" else "return",
                          "source": "competition_dataset", "license": "比賽提供之 iRent 營運照片（非公開，僅限隊內／評審）",
                          "notes": "檔名的車頭左右標記與畫面實際角度相反（見環節一 README）；此處 angle 為檔名欄位。"})
    for name, plate in SAMPLE_PHOTOS.items():
        p = STAGE1 / name
        if p.exists():
            items.append({"image": str(p.relative_to(REPO)), "expected_plate": plate, "angle": None, "stage": None,
                          "source": "stage1_app_models_sample",
                          "license": "環節一 app_models 自備測試照（1.jpg 經 README 記錄為 RCG-2235）",
                          "notes": None if plate else "未標註預期車牌：辨識結果需人工確認後再填入 expected_plate。"})
    return items


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cars", nargs="*", default=list(DEFAULT_CARS), help="資料集車號（無連字號），預設含模擬車輛 RCG2235")
    ap.add_argument("--no-recognize", action="store_true", help="不跑 Core ML，只產 manifest")
    ap.add_argument("--copy-images", type=Path, default=None, help="把圖片複製到此資料夾（匯出給外部時用）")
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    args = ap.parse_args()

    items = collect(tuple(args.cars))
    if not items:
        print("找不到任何測試照片（資料集資料夾不存在？）", file=sys.stderr)
        return 1
    validator = None if args.no_recognize else compile_validator()
    if not args.no_recognize and validator is None:
        print("辨識略過：Swift 驗證程式不可用（需 macOS + Xcode CLT）。manifest 仍會產出。", file=sys.stderr)

    args.out.mkdir(parents=True, exist_ok=True)
    if args.copy_images:
        args.copy_images.mkdir(parents=True, exist_ok=True)
    summary = {"total": len(items), "recognized": 0, "matched": 0, "mismatched": 0, "no_plate": 0, "unlabeled": 0}
    for it in items:
        p = REPO / it["image"]
        it["sha256"] = sha256(p)
        it["bytes"] = p.stat().st_size
        if args.copy_images:
            dst = args.copy_images / f"{it['sha256'][:12]}_{p.name}"
            shutil.copy2(p, dst)
            it["exported_file"] = dst.name
        if validator:
            rec = recognize(validator, p)
            if rec["status"] == "recognized":
                summary["recognized"] += 1
                if it["expected_plate"] is None:
                    rec["match"] = None
                    summary["unlabeled"] += 1
                else:
                    rec["match"] = rec["plate_text"].replace("-", "").upper() == it["expected_plate"].replace("-", "").upper()
                    summary["matched" if rec["match"] else "mismatched"] += 1
            elif rec["status"] in ("no_plate_detected", "ocr_unreadable"):
                rec["match"] = False if it["expected_plate"] else None
                summary["no_plate"] += 1
            it["recognition"] = rec
            print(f"{p.name:32s} expected={it['expected_plate']!s:10s} → {rec['status']:18s} {rec['plate_text'] or '-'} conf={rec['confidence']}")
        else:
            it["recognition"] = {"engine": None, "status": "not_run"}
    manifest = {
        "name": "iRent 模擬租車 Demo — 車牌辨識測試資料集",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "提供給 Stonk（或任何外部驗證）的車牌辨識測試資料：圖片 + 預期車牌 + 本專案 Core ML 辨識結果。不假設對方 API 規格。",
        "plate_format": "台灣車牌：3 英文 + 4 數字（例 RCG-2235）；比對時忽略連字號與大小寫。",
        "recognition_engine": ENGINE if validator else None,
        "summary": summary,
        "items": items,
        "caveats": [
            "資料集照片為非公開營運照片，匯出僅限隊內／評審使用。",
            "expected_plate 來自資料集檔名；2.jpg / 3.jpg 無標註，需人工確認。",
            "辨識結果為 macOS CPU 執行同一組 Core ML 模型，iPhone 實機（Neural Engine）結果可能略有差異（OCR 已固定走 CPU/GPU）。",
        ],
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nmanifest → {args.out / 'manifest.json'}\n{json.dumps(summary, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
