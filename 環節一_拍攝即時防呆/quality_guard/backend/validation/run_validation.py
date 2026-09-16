"""對 raw_data 裡 293 張真實照片跑品質檢查管線，量測準確率並提供門檻校準依據。

用法：
    cd backend && .venv/bin/python -m validation.run_validation

輸出：
    validation/reports/validation_run_<timestamp>.csv   每張圖片的詳細結果
    validation/reports/validation_run_<timestamp>.json  彙總指標

已知現象：偶爾會在報表全部寫完之後，於直譯器關閉階段丟出
`recursive_mutex lock failed`（onnxruntime/torch 拆卸原生資源的競態），exit code 134。
報表本身是完整的，重跑通常就正常；不要為了讓 exit code 好看而加 os._exit()，
那會連真正的錯誤一起蓋掉。

這一步要在碰 FastAPI/前端之前先做完——目的是用真實資料把模糊/亮度/車牌
偵測門檻校準到合理範圍，而不是憑空猜門檻值。
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.checks.quality_rules import run_quality_check
from app.config import DEFAULT_THRESHOLDS
from app.view_taxonomy import RequiredView
from validation.metrics import levenshtein, summarize
from validation.parse_filename import iter_ground_truth, normalize_plate_text

# 真實照片來源。優先用 quality_guard/raw_data（本機自行放的軟連結或副本），
# 沒有的話退回 repo 內附的簡報資料夾——293 張原始照片本來就在那裡，多維護一份
# 副本只會讓兩邊不同步。用 IRENT_RAW_DATA_DIR 可以覆寫成別的路徑。
_REPO_ROOT = BACKEND_DIR.parents[2]
_RAW_DATA_CANDIDATES = [
    BACKEND_DIR.parent / "raw_data",
    _REPO_ROOT / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率",
]


def _resolve_raw_data_dir() -> Path:
    override = os.environ.get("IRENT_RAW_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    for candidate in _RAW_DATA_CANDIDATES:
        if (candidate / "沒有進行索賠").is_dir():
            return candidate
    return _RAW_DATA_CANDIDATES[0]


RAW_DATA_DIR = _resolve_raw_data_dir()
NO_CLAIM_DIR = RAW_DATA_DIR / "沒有進行索賠"
CLAIM_DIR = RAW_DATA_DIR / "進行索賠資料"
REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def apply_synthetic_blur(image: np.ndarray) -> np.ndarray:
    return cv2.GaussianBlur(image, (25, 25), sigmaX=8)


def apply_synthetic_darken(image: np.ndarray) -> np.ndarray:
    return np.clip(image.astype(np.float32) * 0.25, 0, 255).astype(np.uint8)


def apply_synthetic_brighten(image: np.ndarray) -> np.ndarray:
    return np.clip(image.astype(np.float32) * 1.6 + 60, 0, 255).astype(np.uint8)


def apply_synthetic_center_crop_zoom(image: np.ndarray, keep_ratio: float = 0.45) -> np.ndarray:
    """模擬「拍太近」：只留中心一小塊區域再放大回原尺寸。"""
    height, width = image.shape[:2]
    crop_h, crop_w = int(height * keep_ratio), int(width * keep_ratio)
    y0 = (height - crop_h) // 2
    x0 = (width - crop_w) // 2
    cropped = image[y0 : y0 + crop_h, x0 : x0 + crop_w]
    return cv2.resize(cropped, (width, height), interpolation=cv2.INTER_LINEAR)


def run_real_photo_pass(rows: list[dict]) -> None:
    ground_truths = list(iter_ground_truth(NO_CLAIM_DIR, CLAIM_DIR))
    print(f"共解析出 {len(ground_truths)} 張有效角度標註照片（已排除車況回報等無關檔案）")

    for gt in ground_truths:
        image = cv2.imread(str(gt.path))
        row = {
            "phase": "real",
            "file": gt.path.name,
            "source_dir": gt.path.parent.name,
            "plate_truth": gt.plate_text,
            "view_truth": gt.view.value,  # 已修正成車體視角
            "view_as_named": gt.view_as_named,  # 檔名原本寫的（車頭兩類跟真值相反）
            "decode_ok": image is not None,
        }
        if image is None:
            row.update({"error": "DECODE_FAILED"})
            rows.append(row)
            continue

        start = time.perf_counter()
        result = run_quality_check(image, required_view=gt.view, thresholds=DEFAULT_THRESHOLDS)
        elapsed_ms = (time.perf_counter() - start) * 1000

        plate_detected = result.plate_bbox is not None
        # ground truth 的車牌是正規化過的（大寫、無 "-"），但 plate_yolo 會替
        # 認得出的台灣排版補上 "-"，比對前要用同一套正規化，否則會把讀對的
        # 車牌全部算成錯的。
        plate_text = normalize_plate_text(result.plate_text or "")
        exact_match = plate_detected and plate_text == gt.plate_text
        edit_distance = levenshtein(plate_text, gt.plate_text) if plate_detected else None
        near_match = edit_distance is not None and edit_distance <= 1

        row.update(
            {
                "passed": result.passed,
                "error_codes": ";".join(e.code for e in result.errors),
                "stages_run": ";".join(result.stages_run),
                # 方向防護網套用的逆時針角度（0 = 沒動）。會被套用代表這張照片的
                # 內容是橫躺的，原本會直接卡在 PLATE_NOT_FOUND。
                "orientation_rotation": result.orientation_rotation,
                "blur_score": result.blur_score,
                "brightness_mean": result.brightness.mean if result.brightness else None,
                "brightness_dark_ratio": result.brightness.dark_ratio if result.brightness else None,
                "brightness_bright_ratio": result.brightness.bright_ratio if result.brightness else None,
                "plate_detected": plate_detected,
                "plate_text_detected": plate_text,
                "plate_confidence": result.plate_confidence,
                "plate_detect_confidence": result.plate_detect_confidence,
                "plate_area_ratio": result.plate_area_ratio,
                "plate_exact_match": exact_match,
                "plate_edit_distance": edit_distance,
                "plate_near_match": near_match,
                "view_predicted": result.view_label,
                "view_confidence": result.view_confidence,
                "view_correct": (result.view_label == gt.view.value) if result.view_label else None,
                "quality_score": result.quality_score,
                "elapsed_ms": round(elapsed_ms, 1),
            }
        )
        rows.append(row)


def run_synthetic_pass(rows: list[dict], sample_size: int, seed: int) -> None:
    ground_truths = list(iter_ground_truth(NO_CLAIM_DIR, CLAIM_DIR))
    rng = random.Random(seed)
    sample = rng.sample(ground_truths, k=min(sample_size, len(ground_truths)))
    print(f"合成劣化注入：抽樣 {len(sample)} 張真實照片做模糊/調暗/調亮/置中裁切測試")

    degradations = {
        "blur": apply_synthetic_blur,
        "darken": apply_synthetic_darken,
        "brighten": apply_synthetic_brighten,
        "center_crop_zoom": apply_synthetic_center_crop_zoom,
    }

    for gt in sample:
        original = cv2.imread(str(gt.path))
        if original is None:
            continue

        baseline = run_quality_check(original, required_view=gt.view, thresholds=DEFAULT_THRESHOLDS)

        for degradation_name, degrade_fn in degradations.items():
            degraded_image = degrade_fn(original)
            result = run_quality_check(degraded_image, required_view=gt.view, thresholds=DEFAULT_THRESHOLDS)
            rows.append(
                {
                    "phase": "synthetic",
                    "file": gt.path.name,
                    "degradation": degradation_name,
                    "view_truth": gt.view.value,
                    "baseline_error_codes": ";".join(e.code for e in baseline.errors),
                    "degraded_error_codes": ";".join(e.code for e in result.errors),
                    "baseline_blur_score": baseline.blur_score,
                    "degraded_blur_score": result.blur_score,
                    "baseline_brightness_mean": baseline.brightness.mean if baseline.brightness else None,
                    "degraded_brightness_mean": result.brightness.mean if result.brightness else None,
                    "baseline_plate_detected": baseline.plate_bbox is not None,
                    "degraded_plate_detected": result.plate_bbox is not None,
                    "baseline_plate_area_ratio": baseline.plate_area_ratio,
                    "degraded_plate_area_ratio": result.plate_area_ratio,
                    "baseline_view_predicted": baseline.view_label,
                    "degraded_view_predicted": result.view_label,
                    "baseline_view_confidence": baseline.view_confidence,
                    "degraded_view_confidence": result.view_confidence,
                    "baseline_advisories": ";".join(baseline.stage1_advisories),
                    "degraded_advisories": ";".join(result.stage1_advisories),
                }
            )


def summarize_real_pass(rows: list[dict]) -> dict:
    real_rows = [r for r in rows if r["phase"] == "real" and r.get("decode_ok")]
    exterior_rows = real_rows  # 目前本地樣本全部是外部 4 角落視角

    view_rows_all = [r for r in real_rows if r.get("view_predicted")]
    # 提早結束之後，Stage 1 就被擋掉的照片根本沒送進 YOLO，把它們算進
    # 「車牌偵測率」的分母會低估偵測器本身的能力。這裡分母改成「真的跑到
    # Stage 2 的張數」，另外用 stage2_reached_rate 呈現有多少張走到那一步。
    stage2_rows = [r for r in real_rows if "stage2_plate" in (r.get("stages_run") or "")]
    plate_detected_count = sum(1 for r in stage2_rows if r["plate_detected"])
    exact_match_count = sum(1 for r in stage2_rows if r["plate_exact_match"])
    near_match_count = sum(1 for r in stage2_rows if r["plate_near_match"])
    passed_count = sum(1 for r in real_rows if r["passed"])

    error_code_counts: dict[str, int] = {}
    for r in real_rows:
        for code in (r.get("error_codes") or "").split(";"):
            if code:
                error_code_counts[code] = error_code_counts.get(code, 0) + 1

    by_view: dict[str, dict] = {}
    for view in RequiredView:
        view_rows = [r for r in exterior_rows if r["view_truth"] == view.value]
        if not view_rows:
            continue
        classified = [r for r in view_rows if r.get("view_predicted")]
        view_stage2 = [r for r in view_rows if "stage2_plate" in (r.get("stages_run") or "")]
        by_view[view.value] = {
            "count": len(view_rows),
            "stage2_reached_count": len(view_stage2),
            "plate_detection_rate": round(
                sum(1 for r in view_stage2 if r["plate_detected"]) / len(view_stage2), 3
            )
            if view_stage2
            else None,
            "plate_exact_match_rate": round(
                sum(1 for r in view_stage2 if r["plate_exact_match"]) / len(view_stage2), 3
            )
            if view_stage2
            else None,
            # 分母是「有跑到 Stage 3 的張數」，不是該視角的總張數——Stage 2 沒過
            # 的照片根本沒送進分類器，混進分母會低估分類器本身的準確率。
            "view_classified_count": len(classified),
            "view_accuracy_when_classified": round(
                sum(1 for r in classified if r["view_correct"]) / len(classified), 3
            )
            if classified
            else None,
        }

    return {
        "total_real_photos": len(real_rows),
        "decode_failures": sum(1 for r in rows if r["phase"] == "real" and not r.get("decode_ok")),
        "overall_pass_rate": round(passed_count / len(real_rows), 3) if real_rows else None,
        "stage2_reached_count": len(stage2_rows),
        "stage2_reached_rate": round(len(stage2_rows) / len(real_rows), 3) if real_rows else None,
        # 以下三個分母都是「跑到 Stage 2 的張數」，不是全部 285 張。
        "plate_detection_rate": round(plate_detected_count / len(stage2_rows), 3) if stage2_rows else None,
        # 方向防護網救回來的張數：這些照片第一次偵測失敗，轉正後才找到車牌。
        "orientation_corrected_count": sum(
            1 for r in real_rows if r.get("orientation_rotation")
        ),
        "plate_exact_match_rate": round(exact_match_count / len(stage2_rows), 3) if stage2_rows else None,
        "plate_near_match_rate": round(near_match_count / len(stage2_rows), 3) if stage2_rows else None,
        "error_code_counts_on_real_photos": error_code_counts,
        "blur_score_distribution": summarize([r["blur_score"] for r in real_rows if r.get("blur_score") is not None]),
        "brightness_mean_distribution": summarize(
            [r["brightness_mean"] for r in real_rows if r.get("brightness_mean") is not None]
        ),
        "plate_area_ratio_distribution": summarize(
            [r["plate_area_ratio"] for r in real_rows if r.get("plate_area_ratio") is not None]
        ),
        "elapsed_ms_distribution": summarize([r["elapsed_ms"] for r in real_rows if r.get("elapsed_ms") is not None]),
        "view_classified_count": len(view_rows_all),
        "view_accuracy_when_classified": round(
            sum(1 for r in view_rows_all if r["view_correct"]) / len(view_rows_all), 3
        )
        if view_rows_all
        else None,
        "view_confidence_distribution": summarize(
            [r["view_confidence"] for r in view_rows_all if r.get("view_confidence") is not None]
        ),
        "plate_ocr_confidence_distribution": summarize(
            [r["plate_confidence"] for r in stage2_rows if r.get("plate_confidence") is not None]
        ),
        "by_view": by_view,
    }


def summarize_synthetic_pass(rows: list[dict]) -> dict:
    synthetic_rows = [r for r in rows if r["phase"] == "synthetic"]
    summary: dict[str, dict] = {}

    for degradation_name in ("blur", "darken", "brighten", "center_crop_zoom"):
        subset = [r for r in synthetic_rows if r["degradation"] == degradation_name]
        if not subset:
            continue

        false_positive_on_original = sum(
            1
            for r in subset
            if _relevant_code(degradation_name) in (r["baseline_error_codes"] or "").split(";")
        )
        caught_codes = {_relevant_code(degradation_name)}
        if degradation_name == "center_crop_zoom":
            caught_codes.add("PLATE_NOT_FOUND")
        caught_after_degradation = sum(
            1
            for r in subset
            if caught_codes & set((r["degraded_error_codes"] or "").split(";"))
        )

        # 分階段提早結束之後，「用預期的錯誤碼攔下」跟「有沒有攔下」是兩件事：
        # 例如 center_crop_zoom（裁一小塊再放大）會先在 Stage 1 被判定為模糊而擋下，
        # 根本跑不到 Stage 2 的 TOO_CLOSE。只看預期錯誤碼會誤以為沒攔到。
        blocked_after_degradation = sum(1 for r in subset if r["degraded_error_codes"])
        blocked_codes: dict[str, int] = {}
        for r in subset:
            for code in (r["degraded_error_codes"] or "").split(";"):
                if code:
                    blocked_codes[code] = blocked_codes.get(code, 0) + 1

        expected_advisory = _EXPECTED_ADVISORY.get(degradation_name)
        advisory_hits = (
            sum(
                1
                for r in subset
                if expected_advisory in (r["degraded_advisories"] or "").split(";")
            )
            if expected_advisory
            else None
        )
        advisory_false_positives = (
            sum(
                1
                for r in subset
                if expected_advisory in (r["baseline_advisories"] or "").split(";")
            )
            if expected_advisory
            else None
        )

        summary[degradation_name] = {
            "sample_size": len(subset),
            "advisory_only": degradation_name in _ADVISORY_ONLY_DEGRADATIONS,
            "expected_advisory": expected_advisory,
            "advisory_rate_after_degradation": (
                round(advisory_hits / len(subset), 3) if advisory_hits is not None else None
            ),
            "advisory_false_positive_rate_on_original": (
                round(advisory_false_positives / len(subset), 3)
                if advisory_false_positives is not None
                else None
            ),
            "relevant_error_code": _relevant_code(degradation_name),
            "false_positive_rate_on_original": round(false_positive_on_original / len(subset), 3),
            "catch_rate_after_degradation": round(caught_after_degradation / len(subset), 3),
            "blocked_rate_after_degradation": round(blocked_after_degradation / len(subset), 3),
            "blocked_by_code": dict(sorted(blocked_codes.items(), key=lambda kv: -kv[1])),
            "plate_detection_drop": round(
                sum(1 for r in subset if r["baseline_plate_detected"] and not r["degraded_plate_detected"])
                / max(1, sum(1 for r in subset if r["baseline_plate_detected"])),
                3,
            ),
        }

    return summary


# 模糊/亮度預設不擋關（見 app/config.py），所以 blur/darken/brighten 的
# 「預期錯誤碼攔截率」現在本來就會是 0——那不是退步，是設計改變。
# 這幾項要看的是 advisory_rate（有沒有標註出來）與 blocked_rate（最終有沒有被擋下）。
_ADVISORY_ONLY_DEGRADATIONS = {"blur", "darken", "brighten"}
_EXPECTED_ADVISORY = {"blur": "畫面偏模糊", "darken": "照片偏暗", "brighten": "照片偏亮"}


def _relevant_code(degradation_name: str) -> str:
    return {
        "blur": "IMAGE_BLURRY",
        "darken": "TOO_DARK",
        "brighten": "TOO_BRIGHT",
        # 置中裁切放大會讓車牌面積比例變大 -> TOO_CLOSE；車牌被裁出畫面時則會
        # 落到 PLATE_NOT_FOUND，兩者都算成功攔截（見 caught_after_degradation）。
        "center_crop_zoom": "TOO_CLOSE",
    }[degradation_name]


def _json_default(value):
    """thresholds_used 是 asdict(QualityThresholds) 的結果，裡面有 frozenset
    （plate_text_valid_lengths），json 預設不會序列化 set，少了這個報表會寫到一半就斷。"""
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"物件無法序列化成 JSON: {type(value).__name__}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic-sample-size", type=int, default=40)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    rows: list[dict] = []
    run_real_photo_pass(rows)
    run_synthetic_pass(rows, sample_size=args.synthetic_sample_size, seed=args.seed)

    csv_path = REPORTS_DIR / f"validation_run_{timestamp}.csv"
    all_keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in all_keys:
                all_keys.append(key)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_keys)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "timestamp": timestamp,
        "thresholds_used": asdict(DEFAULT_THRESHOLDS),
        "real_photo_metrics": summarize_real_pass(rows),
        "synthetic_degradation_metrics": summarize_synthetic_pass(rows),
    }
    json_path = REPORTS_DIR / f"validation_run_{timestamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=_json_default)

    print(f"\n每張圖片詳細結果: {csv_path}")
    print(f"彙總指標: {json_path}\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
