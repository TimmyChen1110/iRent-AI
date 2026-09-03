#!/usr/bin/env python3
"""③ API 成本推算：從實測 token 用量 × 官方牌價，外推全量規模。

⚠️ 這是「牌價推算」不是「帳單核對」——免費層用量不計費，故無帳單可對。
   若日後轉付費層，請以實際帳單校正本檔數字後再更新 README。

牌價來源：ai.google.dev/gemini-api/docs/pricing（查核日 2026-08-30，USD / 1M tokens）
  gemini-3.7-flash      輸入 0.75 / 輸出 3.75   ← 2026-12-31 前優惠價
                        輸入 1.50 / 輸出 7.50   ← 2027-01-01 起（翻倍）
  gemini-3.1-pro-preview 輸入 2.00 / 輸出 12.00  （≤200k prompt）

用法：python3 cost_model.py [--after-2027]
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

FLASH_2026 = (0.75, 3.75)
FLASH_2027 = (1.50, 7.50)
PRO = (2.00, 12.00)
CASCADE_VOTES = 3        # run_cascade.py 預設 --votes 3


def measured(results_file="eval_results_gemini_37_flash_v3.json"):
    """從實測結果檔取 token 用量與級聯觸發率。

    必須讀「級聯前」的快篩結果：_cascaded.json 的 assessment 已被 Pro 覆寫，
    低信心案會變成高信心，觸發率會被低估（4 → 3）。
    """
    d = json.loads((HERE / results_file).read_text())["results"]
    tin = sum(r["usage"]["input"] for r in d if r.get("usage"))
    tout = sum(r["usage"]["output"] for r in d if r.get("usage"))

    # 級聯觸發條件與 run_cascade.needs_escalation 一致
    def esc(a):
        if not a["angle_match"]:
            return True
        if not a["new_damage_found"]:
            return a.get("no_damage_confidence", 1.0) < 0.7
        return max((x["confidence"] for x in a["damages"]), default=0) < 0.85

    n_esc = sum(1 for r in d if esc(r["assessment"]))
    return len(d), tin, tout, n_esc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--after-2027", action="store_true", help="套用 2027 起的 flash 牌價")
    args = ap.parse_args()
    f_in, f_out = FLASH_2027 if args.after_2027 else FLASH_2026

    n, tin, tout, n_esc = measured()
    flash = tin / 1e6 * f_in + tout / 1e6 * f_out
    # 升級案改用 Pro 跑 N 票，單次 token 量以 flash 平均值估算
    pro = n_esc * CASCADE_VOTES * (tin / n / 1e6 * PRO[0] + tout / n / 1e6 * PRO[1])
    total = flash + pro
    per = total / n

    print(f"牌價：{'2027 起' if args.after_2027 else '2026 優惠價'}  flash {f_in}/{f_out}、pro {PRO[0]}/{PRO[1]} USD per 1M\n")
    print(f"實測 {n} 組（{tin:,} in / {tout:,} out）")
    print(f"  Flash 快篩      ${flash:.4f}")
    print(f"  Pro 級聯 {n_esc}×{CASCADE_VOTES}票  ${pro:.4f}   （觸發率 {100*n_esc/n:.1f}%，佔成本 {100*pro/total:.0f}%）")
    print(f"  合計            ${total:.4f}")
    print(f"  每組配對        ${per:.5f}\n")

    print("外推（假設 token 用量與級聯率不變）：")
    for label, pairs in [("1,126 台可鏈車 × 8 方位", 1126 * 8),
                         ("4,820 張訂單 × 4 方位", 4820 * 4),
                         ("27,367 張照片（每 2 張 1 組）", 27367 // 2)]:
        print(f"  {label:28s} {pairs:>7,} 組  ${pairs * per:>8.2f}"
              f"   RPM8 需 {pairs / 8 / 60:>5.1f} 小時")
    print(f"\n每張訂單成本：${4 * per:.4f}")


if __name__ == "__main__":
    main()
