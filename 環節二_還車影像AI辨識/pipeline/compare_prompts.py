#!/usr/bin/env python3
"""A/B 對照：現行判定 prompt vs 規格版 v2 prompt。

為什麼需要這支：現行 prompt 的實測數字（對照人工重標 Recall 95.5% / FPR 0%）
是比賽對外指標。規格版 prompt 結構上更嚴謹（先描述後判斷、主動排除混淆源、
分區代碼與 UV 座標），但「結構更嚴謹」不等於「判得更準」——必須在同一份資料上
實測對照才知道。本支輸出逐案差異，讓翻轉的案件可以被人工檢視。

評測基準採雙軌（與 README 一致）：
  原始索賠標籤   對外指標，但含 4 筆「未索賠實為真損」的雜訊
  人工重標       relabels.json，n=138（3 筆存疑排除），較接近真實表現

用法：
  python3 compare_prompts.py                                   # 用預設檔名
  python3 compare_prompts.py --b eval_results_v2smoke.json      # 指定 B 版結果
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from results_config import FINAL_RESULTS  # noqa: E402

HERE = Path(__file__).resolve().parent


def load(path: Path) -> dict:
    data = json.loads(path.read_text())
    return {(r["car"], r["angle"]): r for r in data["results"] if r.get("assessment")}


def truth_map() -> dict:
    """人工重標為準的真值；未重標者沿用原始標籤。"""
    rl = json.loads((HERE / "relabels.json").read_text())["relabels"]
    out = {}
    for r in rl:
        v = r.get("relabel")
        if v == "damage":
            out[(r["car"], r["angle"])] = True
        elif v in ("no_damage", "clean", "none"):
            out[(r["car"], r["angle"])] = False
        else:
            out[(r["car"], r["angle"])] = None   # 存疑：排除
    return out


def metrics(cases: dict, truth: dict, use_relabel=True) -> dict:
    tp = fn = fp = tn = skipped = 0
    for k, r in cases.items():
        if use_relabel:
            t = truth.get(k)
            if t is None and k in truth:
                skipped += 1
                continue
            if t is None:
                t = r["label"] == "positive"
        else:
            t = r["label"] == "positive"
        pred = r["assessment"]["new_damage_found"]
        if t and pred:
            tp += 1
        elif t and not pred:
            fn += 1
        elif not t and pred:
            fp += 1
        else:
            tn += 1
    n_pos, n_neg = tp + fn, fp + tn
    return {
        "n": tp + fn + fp + tn, "skipped_uncertain": skipped,
        "confusion": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
        "recall": round(tp / n_pos, 4) if n_pos else None,
        "false_positive_rate": round(fp / n_neg, 4) if n_neg else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
    }


def compare(a_path: Path, b_path: Path) -> dict:
    A, B = load(a_path), load(b_path)
    truth = truth_map()
    common = sorted(set(A) & set(B))
    if not common:
        return {"error": "兩份結果無交集案件"}

    Ac = {k: A[k] for k in common}
    Bc = {k: B[k] for k in common}

    flips = []
    for k in common:
        pa = A[k]["assessment"]["new_damage_found"]
        pb = B[k]["assessment"]["new_damage_found"]
        if pa == pb:
            continue
        t = truth.get(k)
        t_disp = {True: "真損", False: "無損", None: "存疑"}.get(
            t, "未重標") if k in truth else "未重標"
        # 判斷這次翻轉是變好還是變壞
        gt = t if t is not None else (A[k]["label"] == "positive")
        verdict = "改善" if pb == gt else "退步" if pa == gt else "無定論"
        flips.append({"case": f"{k[0]}-{k[1]}", "label": A[k]["label"],
                      "truth": t_disp, "A": pa, "B": pb, "verdict": verdict,
                      "B_reasoning": _first_reason(B[k]["assessment"])})

    return {
        "n_common": len(common),
        "A": {"file": a_path.name,
              "vs_原始索賠標籤": metrics(Ac, truth, use_relabel=False),
              "vs_人工重標": metrics(Ac, truth, use_relabel=True)},
        "B": {"file": b_path.name,
              "vs_原始索賠標籤": metrics(Bc, truth, use_relabel=False),
              "vs_人工重標": metrics(Bc, truth, use_relabel=True)},
        "n_flips": len(flips),
        "flips_improved": sum(1 for f in flips if f["verdict"] == "改善"),
        "flips_regressed": sum(1 for f in flips if f["verdict"] == "退步"),
        "flips": flips,
        "errors_A": _errors(Ac, truth),
        "errors_B": _errors(Bc, truth),
        "v2_field_quality": _field_quality(Bc),
    }


def _errors(cases: dict, truth: dict) -> list[dict]:
    """對照人工重標的逐案錯誤（漏抓與誤報），供人工檢視。"""
    out = []
    for k, r in sorted(cases.items()):
        t = truth.get(k)
        if t is None:
            continue   # 存疑案件排除
        pred = r["assessment"]["new_damage_found"]
        if pred == t:
            continue
        out.append({"case": f"{k[0]}-{k[1]}",
                    "kind": "漏抓FN" if t else "誤報FP",
                    "detail": _first_reason(r["assessment"])})
    return out


def _first_reason(a: dict) -> str:
    ds = a.get("damages") or []
    if ds:
        d = ds[0]
        return (d.get("observation") or d.get("reasoning") or "")[:110]
    return (a.get("pre_existing_notes") or "")[:110]


def _field_quality(B: dict) -> dict:
    """v2 專屬欄位的填答品質——結構有沒有真的被用起來。"""
    ds = [d for r in B.values() for d in (r["assessment"].get("damages") or [])]
    if not ds:
        return {"n_damages": 0}
    return {
        "n_damages": len(ds),
        "有observation": sum(1 for d in ds if (d.get("observation") or "").strip()),
        "有有效panel": sum(1 for d in ds if d.get("panel")),
        "panel幻覺被丟棄": sum(1 for d in ds if d.get("panel_invalid")),
        "有UV座標": sum(1 for d in ds if d.get("position_uv")),
        "有ruled_out": sum(1 for d in ds if d.get("ruled_out")),
        "平均ruled_out項數": round(
            sum(len(d.get("ruled_out") or []) for d in ds) / len(ds), 2),
        # 全部勾滿＝合規表演而非鑑別訊號。這個比例越低，代表模型真的有在挑。
        "全部勾滿比例": round(
            sum(1 for d in ds if len(d.get("ruled_out") or []) >= 6) / len(ds), 2),
        "有排除理由": sum(1 for d in ds if (d.get("ruled_out_basis") or "").strip()),
        "信心分布": {
            "≥0.9": sum(1 for d in ds if d.get("confidence", 0) >= 0.9),
            "0.75-0.89": sum(1 for d in ds if 0.75 <= d.get("confidence", 0) < 0.9),
            "0.6-0.74": sum(1 for d in ds if 0.6 <= d.get("confidence", 0) < 0.75),
            "<0.6": sum(1 for d in ds if d.get("confidence", 0) < 0.6),
        },
    }


def main():
    ap = argparse.ArgumentParser(description="判定 prompt A/B 對照")
    ap.add_argument("--a", default=None, help="A 版結果（預設現行 FINAL_RESULTS）")
    ap.add_argument("--b", default="eval_results_v2prompt.json", help="B 版結果")
    args = ap.parse_args()

    a_path = Path(args.a) if args.a else FINAL_RESULTS
    b_path = Path(args.b) if Path(args.b).is_absolute() else HERE / args.b
    if not b_path.exists():
        sys.exit(f"找不到 B 版結果 {b_path.name}——請先執行 detect_v2.py")

    out = compare(a_path, b_path)
    (HERE / "prompt_ab_report.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    if out.get("error"):
        sys.exit(out["error"])
    print(f"共同案件 {out['n_common']} 組\n")
    for side in ("A", "B"):
        s = out[side]
        print(f"【{side}】{s['file']}")
        for basis in ("vs_原始索賠標籤", "vs_人工重標"):
            m = s[basis]
            r = f"{m['recall']:.1%}" if m["recall"] is not None else "n/a"
            f = f"{m['false_positive_rate']:.1%}" if m["false_positive_rate"] is not None else "n/a"
            print(f"   {basis:16s} n={m['n']:3d}  Recall {r:>6}  FPR {f:>6}  {m['confusion']}")
        print()
    print(f"判定翻轉 {out['n_flips']} 組"
          f"（改善 {out['flips_improved']}／退步 {out['flips_regressed']}）")
    for f in out["flips"]:
        mark = {"改善": "✔", "退步": "✘", "無定論": "?"}[f["verdict"]]
        print(f"  {mark} {f['case']:16s} [{f['truth']}] A={f['A']} → B={f['B']}"
              f"  {f['B_reasoning'][:60]}")
    for side in ("A", "B"):
        errs = out[f"errors_{side}"]
        print(f"\n【{side} 對照人工重標的錯誤】{len(errs)} 件")
        for e in errs:
            print(f"  {e['kind']} {e['case']:16s} {e['detail'][:70]}")

    print("\n【v2 欄位填答品質】")
    print(json.dumps(out["v2_field_quality"], ensure_ascii=False, indent=1))
    print("\n報告寫入 prompt_ab_report.json")


if __name__ == "__main__":
    main()
