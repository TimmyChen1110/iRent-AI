"""比對訓練資料集的資料夾標籤 vs `validation/parse_filename.py` 解析出的真值。

背景：raw_data 的照片檔名在「車頭」兩類把左右寫反了（成因與幾何證據見
`validation/parse_filename.py` 的 _ANGLE_TO_VIEW 說明），parse_filename 會修正它。
人工目視分類過的訓練資料集用的是正確的車體視角，所以修正之後兩邊應該完全一致——
這支腳本就是用來確認這件事，資料集重新標註或換一批照片之後要重跑。

**如果這支腳本回報不一致，先懷疑 parse_filename 的修正表，不要去改模型輸出。**
模型學的是資料集資料夾，那一邊是對的。

作法：資料集裡的圖片是原始照片重新命名（+ 重新壓縮/縮圖）過的副本，位元組不同、
無法用 hash 直接對。這裡把兩邊都縮成 96×96 灰階再做 z-normalize 相關係數比對：
真正的同一張圖相關係數 ≈ 1.0，同一台車的不同角度只有 0.3~0.6，差距很大所以不會配錯。
（早期版本用 DCT perceptual hash，對「同一台車不同角度」的鑑別力不夠，容易配錯。）

用法：
    cd backend && .venv/bin/python -m scripts.check_dataset_label_convention \
        --dataset ~/Desktop/和泰黑客松/dataset
"""

import argparse
import collections
import sys
from pathlib import Path

import cv2
import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from validation.parse_filename import iter_ground_truth  # noqa: E402
from validation.run_validation import CLAIM_DIR, NO_CLAIM_DIR  # noqa: E402

LABELS = ["左前", "右前", "左後", "右後"]
SIGNATURE_SIZE = 96
# 同一張圖相關係數 ≈ 1.0，不同角度 0.3~0.6，門檻放在 0.92 很安全。
MIN_CORRELATION = 0.92
# 還要求勝過次佳夠多，避免資料集裡缺某一張時硬配到長得像的兄弟照片。
MIN_MARGIN = 0.05


def signature(path: Path) -> np.ndarray | None:
    """縮成固定大小的灰階向量並 z-normalize，內積即相關係數。"""
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    resized = cv2.resize(
        image, (SIGNATURE_SIZE, SIGNATURE_SIZE), interpolation=cv2.INTER_AREA
    ).astype(np.float32).ravel()
    resized -= resized.mean()
    std = resized.std()
    return resized / std if std > 1e-6 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path.home() / "Desktop" / "和泰黑客松" / "dataset",
        help="ImageFolder 格式的訓練資料集根目錄（底下要有 train/ 與 val/）。",
    )
    args = parser.parse_args()

    dataset_dir = args.dataset.expanduser()
    if not dataset_dir.is_dir():
        print(f"找不到資料集目錄：{dataset_dir}", file=sys.stderr)
        return 1

    reference_signatures, reference_labels = [], []
    for ground_truth in iter_ground_truth(NO_CLAIM_DIR, CLAIM_DIR):
        vector = signature(ground_truth.path)
        if vector is not None:
            reference_signatures.append(vector)
            reference_labels.append(ground_truth.view.value)
    if not reference_signatures:
        print("讀不到任何有角度標註的原始照片", file=sys.stderr)
        return 1
    reference = np.array(reference_signatures)
    print(f"原始照片（parse_filename 修正後的真值）：{len(reference)} 張")

    confusion: collections.Counter = collections.Counter()
    matched = total = 0
    margins: list[float] = []
    for split_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name != "excluded"):
        for class_dir in sorted(p for p in split_dir.iterdir() if p.is_dir()):
            for image_path in sorted(p for p in class_dir.iterdir() if p.is_file()):
                vector = signature(image_path)
                if vector is None:
                    continue
                total += 1
                correlation = reference @ vector / reference.shape[1]
                order = np.argsort(-correlation)
                best, second = int(order[0]), int(order[1])
                margin = float(correlation[best] - correlation[second])
                if correlation[best] > MIN_CORRELATION and margin > MIN_MARGIN:
                    matched += 1
                    margins.append(margin)
                    confusion[(reference_labels[best], class_dir.name)] += 1

    median_margin = float(np.median(margins)) if margins else 0.0
    print(
        f"資料集圖片 {total} 張，其中 {matched} 張比對回原始照片"
        f"（相關係數 >{MIN_CORRELATION}、勝過次佳 >{MIN_MARGIN}；margin 中位數 {median_margin:.3f}）\n"
    )
    header = "真值 \\ 資料夾"
    print(f"{header:<16}" + "".join(f"{label:>8}" for label in LABELS))
    for truth in LABELS:
        row = "".join(f"{confusion[(truth, folder)]:>8}" for folder in LABELS)
        print(f"{truth:<18}{row}")

    mismatched = [
        (truth, folder, confusion[(truth, folder)])
        for truth in LABELS
        for folder in LABELS
        if truth != folder and confusion[(truth, folder)] > 0
    ]
    agreed = sum(confusion[(label, label)] for label in LABELS)
    print()
    if not mismatched:
        print("✅ 資料集資料夾跟修正後的真值完全一致。")
        return 0

    disagreement_rate = sum(count for *_, count in mismatched) / max(matched, 1)
    print(f"⚠️ 有 {matched - agreed}/{matched} 張不一致（{disagreement_rate:.1%}）：")
    for truth, folder, count in sorted(mismatched, key=lambda item: -item[2]):
        print(f"   真值「{truth}」→ 資料夾「{folder}」（{count} 張）")
    print(
        "\n   先檢查 validation/parse_filename.py 的 _ANGLE_TO_VIEW 修正表，"
        "不要去動模型輸出——\n   模型學的是資料集資料夾，那一邊才是人工目視標註的結果。"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
