#!/usr/bin/env python3
"""把監理台累積的人工裁決匯出成訓練資料集。

資料來源：app/decisions.sqlite3 的 decision_events 表——每一次人工複核
裁決都會存下「AI 判定 vs 人工真值 + 照片路徑 + 標註框」。稽核員本來就要看這些
照片，所以這批標籤的邊際成本是零；累積數月後即為訓練 CV 模型的資料集。

同一 case_id 多次裁決時取【最後一次】為準（改判以最終決定為真值），
但 --include-history 可保留完整歷程（反覆改判的案件是難例，有訓練價值）。

用法：
  python3 export_training_labels.py                      # 匯出 JSONL + 統計
  python3 export_training_labels.py --format coco        # COCO 偵測格式（含 box）
  python3 export_training_labels.py --mode pair          # 只要車損比對
  python3 export_training_labels.py --disagreed-only     # 只要 AI 判錯的（難例挖掘）
  python3 export_training_labels.py --min-cases 500      # 未達門檻不匯出

輸出：training_labels.jsonl（預設）或 training_coco.json
"""
import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
DB = HERE.parent / "app" / "decisions.sqlite3"


def load_events(db_path: Path, include_history=False):
    """回傳 [(case_id, event_dict)]；預設每案只留最後一次有效裁決。"""
    if not db_path.exists():
        sys.exit(f"找不到 {db_path}——監理台尚未產生任何裁決紀錄")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM decision_events WHERE label IS NOT NULL ORDER BY event_id").fetchall()
    except sqlite3.OperationalError:
        sys.exit("decision_events 表不存在——請先以新版 server.py 啟動過監理台")
    finally:
        conn.close()

    out = {} if not include_history else None
    hist = []
    for r in rows:
        e = dict(r)
        for k in ("photos", "assessment", "boxes"):
            e[k] = json.loads(e[k]) if e[k] else (None if k == "assessment" else {})
        if include_history:
            hist.append(e)
        else:
            out[e["case_id"]] = e          # 後寫的覆蓋前者 = 取最後一次裁決
    return hist if include_history else list(out.values())


def to_jsonl(events, path: Path):
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps({
                "case_id": e["case_id"],
                "mode": e["mode"],              # pair | interior
                "source": e["source"],          # dataset | live
                "label": e["label"],            # 1=有車損/髒汙  0=無
                "photos": e["photos"],          # 照片絕對路徑
                "boxes": e["boxes"],            # AI 標註框（人工確認過的才可信）
                "ai_found": e["ai_found"],
                "ai_agreed": e["agreed"],       # 0 = AI 判錯 → 難例
                "ai_level": e["ai_level"],
                "ai_conf": e["ai_conf"],
                "ai_reasoning": (e["assessment"] or {}).get("reasoning")
                                 or (e["assessment"] or {}).get("pre_existing_notes"),
                "note": e["note"],
                "decided_at": e["decided_at"],
            }, ensure_ascii=False) + "\n")


def to_coco(events, path: Path):
    """COCO 偵測格式。只收 label=1 且有 box 的案件（框畫在【還車照】上）。

    ⚠️ box 來自 AI，人工只確認了「有無車損」而非框的精確度。
       正式訓練前建議先人工修框，或當作弱監督（weak supervision）使用。
    """
    cats = {}
    images, annos = [], []
    for e in events:
        if e["label"] != 1 or not e["boxes"]:
            continue
        photos = e["photos"] or {}
        img_path = photos.get("return") or photos.get("photo")
        if not img_path:
            continue                      # LIVE 案件照片只有縮圖，跳過
        img_id = len(images) + 1
        images.append({"id": img_id, "file_name": img_path, "case_id": e["case_id"]})
        for b in e["boxes"]:
            box = b.get("box_2d") or []
            if len(box) != 4:
                continue
            name = b.get("label") or "damage"
            cid = cats.setdefault(name, len(cats) + 1)
            ymin, xmin, ymax, xmax = box   # 0~1000 正規化
            annos.append({
                "id": len(annos) + 1, "image_id": img_id, "category_id": cid,
                "bbox_normalized_1000": [xmin, ymin, xmax - xmin, ymax - ymin],
                "severity": b.get("severity"), "ai_confidence": b.get("confidence"),
                "iscrowd": 0,
            })
    path.write_text(json.dumps({
        "info": {"description": "iRent 車損偵測（由監理台人工裁決匯出）",
                 "warning": "bbox 由 VLM 產生、人工僅確認有無損傷；建議先修框再訓練",
                 "bbox_format": "[x, y, w, h]，座標為 0~1000 正規化，需乘上實際圖寬高"},
        "images": images, "annotations": annos,
        "categories": [{"id": v, "name": k} for k, v in cats.items()],
    }, ensure_ascii=False, indent=1))
    return len(images), len(annos)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--format", choices=["jsonl", "coco"], default="jsonl")
    ap.add_argument("--mode", choices=["pair", "interior"], help="只匯出某一模式")
    ap.add_argument("--source", choices=["dataset", "live"])
    ap.add_argument("--disagreed-only", action="store_true", help="只要 AI 判錯的案例（難例挖掘）")
    ap.add_argument("--include-history", action="store_true", help="保留同案多次裁決的完整歷程")
    ap.add_argument("--min-cases", type=int, default=0, help="標籤數未達此門檻就不匯出")
    ap.add_argument("--out", help="輸出路徑")
    args = ap.parse_args()

    events = load_events(Path(args.db), args.include_history)
    if args.mode:
        events = [e for e in events if e["mode"] == args.mode]
    if args.source:
        events = [e for e in events if e["source"] == args.source]
    if args.disagreed_only:
        events = [e for e in events if e["agreed"] == 0]

    n = len(events)
    pos = sum(1 for e in events if e["label"] == 1)
    judged = [e for e in events if e["agreed"] is not None]
    agree = sum(e["agreed"] for e in judged)

    print(f"可用標籤 {n} 筆（正 {pos} / 負 {n - pos}）")
    if judged:
        print(f"AI 與人工一致率 {agree / len(judged):.1%}"
              f"（不一致 {len(judged) - agree} 筆 ← 最有訓練價值的難例）")
    print("模式分布:", dict(Counter(e["mode"] for e in events)))
    print("來源分布:", dict(Counter(e["source"] for e in events)))

    if n < args.min_cases:
        sys.exit(f"\n未達門檻 {args.min_cases} 筆，不匯出。"
                 f"\n提示：監理台每複核一件就多一筆標籤，持續使用即可累積。")
    if n == 0:
        print("\n目前沒有可匯出的標籤——請先在監理台完成幾件複核裁決。")
        return

    # 篩選過的輸出用不同檔名，避免覆蓋完整資料集
    suffix = "_disagreed" if args.disagreed_only else ""
    if args.mode:
        suffix += f"_{args.mode}"
    if args.format == "coco":
        out = Path(args.out or HERE / f"training_coco{suffix}.json")
        ni, na = to_coco(events, out)
        print(f"\n→ {out.name}：{ni} 張圖 / {na} 個框")
        print("  ⚠️ 框由 VLM 產生、人工僅確認有無損傷，建議先修框再正式訓練")
    else:
        out = Path(args.out or HERE / f"training_labels{suffix}.jsonl")
        to_jsonl(events, out)
        print(f"\n→ {out.name}：{n} 筆")

    # 訓練可行性提示——用實際累積量說話
    print("\n=== 訓練可行性 ===")
    if pos < 100:
        print(f"正樣本 {pos} 筆：僅夠做流程驗證，尚不足以訓練")
    elif pos < 1000:
        print(f"正樣本 {pos} 筆：可試訓「有無車損」二分類（先驗證資料品質）")
    elif pos < 5000:
        print(f"正樣本 {pos} 筆：可訓分類模型；偵測模型建議累積至 5,000+")
    else:
        print(f"正樣本 {pos} 筆：已達偵測模型訓練門檻，建議先人工修框")


if __name__ == "__main__":
    main()
