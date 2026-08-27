#!/usr/bin/env python3
"""Stage 6 — 嚴重度、估價與處置決策（Prompt 架構規格 §3 Stage 6）。

刻意「不用模型」：估價需要可稽核性。同一種損傷在不同案件必須得到同一個報價，
否則客服無法對用戶解釋，也無法被稽核。因此本階段是純規則表 + 純程式邏輯，零 API 成本。

三個決策層：
  ① 維修動作對照表：損傷類型 × 尺寸 × 材質 → 維修動作 + 級距(A/B/C/D)
  ② 處置分流：新損信心 × 級距 → 自動處置／人工複核／僅記錄
  ③ 索賠經濟性：估價低於索賠處理成本 → 主動放棄（規格：「能算出不值得追也是系統價值」）

⚠ 價格為示意值，實際須依 iRent 維修合約定價替換 PRICE_BANDS。
   金額一律以區間呈現（規格 §Stage 7：涉及金額只給區間，並註明以實際估價為準）。

用法：
  python3 disposition.py --table          # 印出維修對照表與級距定義
  python3 disposition.py --thresholds 120 8   # 每日還車 120 台、客服可負擔 8 件 → 反推門檻
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import DAMAGE_ZH, LEGACY_TYPE_TO_CODE, PANEL_MATERIAL  # noqa: E402

HERE = Path(__file__).resolve().parent

# ---------- ① 級距與估價區間（示意價，單位 TWD） ----------
# 級距語意：A 低 / B 中 / C 高 / D 極高（換件）
PRICE_BANDS = {
    "A": {"label": "低", "range": (300, 1200)},
    "B": {"label": "中", "range": (1500, 5000)},
    "C": {"label": "高", "range": (5000, 15000)},
    "D": {"label": "極高", "range": (12000, 40000)},
}

# 索賠處理成本（客服工時 + 爭議風險的內部估值）。低於此值的損傷不值得啟動索賠。
CLAIM_HANDLING_COST = 800

# 維修動作對照表（規格 §3 Stage 6）
# (損傷類型, 尺寸上限cm 或 None, 材質群組 或 None) → (維修動作, 級距)
REPAIR_RULES = [
    ("scratch", 5, "鈑金", "拋光", "A"),
    ("scratch", 20, "鈑金", "局部烤漆", "B"),
    ("scratch", None, "鈑金", "整片烤漆", "C"),
    ("scratch", None, "塑膠", "保桿修補烤漆", "B"),
    ("scuff", None, "塑膠", "保桿修補烤漆", "B"),
    ("scuff", None, None, "局部烤漆", "B"),
    ("dent", 10, "鈑金", "免烤漆凹痕修復", "B"),
    ("dent", None, "鈑金", "鈑金＋烤漆", "C"),
    ("deformation", None, None, "鈑金＋烤漆", "C"),
    ("chip", 2, None, "點補漆", "A"),
    ("chip", None, None, "局部烤漆", "B"),
    ("crack", None, None, "換件", "D"),
    ("missing_part", None, None, "換件", "D"),
    ("glass_chip", 2, None, "樹脂修補", "A"),
    ("glass_chip", None, None, "換件", "D"),
    ("glass_crack", None, None, "換件", "D"),
    ("rim_curb", None, None, "輪圈整新", "B"),
    ("tire_damage", None, None, "換胎", "C"),
    # 鋁圈／玻璃／燈殼上的刮痕不能用鈑件邏輯處理（曾產生「輪圈：整片烤漆」這種
    # 現場人員看不懂的派工單）。這幾條放在 scratch 通則之後、依材質攔截。
    ("scratch", None, "鋁圈", "輪圈整新", "B"),
    ("scuff", None, "鋁圈", "輪圈整新", "B"),
    ("scratch", None, "玻璃", "玻璃拋光／換件評估", "B"),
    ("scratch", None, "燈殼", "燈殼拋光／換件評估", "B"),
    ("scratch", None, "橡膠", "輪胎檢查", "A"),
]

# 破漆會使凹陷升級（規格：dent 伴隨破漆 → 鈑金＋烤漆 C）
DEPTH_ESCALATE = {"through_paint", "substrate_exposed"}

# ---------- ② 處置分流門檻 ----------
AUTO_ACTION_CONF = 0.85       # 自動鎖車 + 建單 + 通知用戶
REVIEW_CONF = 0.60            # 進客服複核佇列
BAND_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def classify_repair(damage_type: str, size_cm=None, panel=None,
                    depth=None, severity=None) -> dict:
    """損傷 → 維修動作 + 級距 + 估價區間。

    severity（low/medium/high）用來調節換件類損傷的級距：現行判定的「破損」一詞
    同時涵蓋「大燈碎裂、卡榫脫落」（確實要換件，級距 D）與「一條裂痕、接縫變寬」
    （可修補，級距 C）。只看類型會讓後者也報 12,000–40,000 元。
    """
    code = damage_type if damage_type in DAMAGE_ZH else LEGACY_TYPE_TO_CODE.get(damage_type, "scratch")
    material = PANEL_MATERIAL.get(panel or "", None)

    # 凹陷伴隨破漆 → 強制升級
    if code == "dent" and depth in DEPTH_ESCALATE:
        action, band = "鈑金＋烤漆", "C"
    else:
        action, band = _lookup(code, size_cm, material)

    # 換件級距（D）遇到非 high 嚴重度 → 降一級並改為修補，避免小裂痕報出換件價
    if band == "D" and severity in ("low", "medium"):
        action, band = "板件修補／局部更換", "C"

    lo, hi = PRICE_BANDS[band]["range"]
    return {
        "damage_type": code, "damage_type_zh": DAMAGE_ZH.get(code, code),
        "panel": panel, "material": material, "size_cm": size_cm,
        "repair_action": action, "band": band, "band_label": PRICE_BANDS[band]["label"],
        "estimate_twd": [lo, hi],
        "estimate_note": "為級距示意區間，實際以維修廠估價為準",
    }


def _lookup(code, size_cm, material):
    for r_code, r_max, r_mat, action, band in REPAIR_RULES:
        if r_code != code:
            continue
        if r_mat and material and r_mat != material:
            continue
        if r_max is not None and (size_cm is None or size_cm > r_max):
            continue
        return action, band
    # 找不到規則（例如材質不明的 scratch）→ 取該類型第一條通則
    for r_code, _, r_mat, action, band in REPAIR_RULES:
        if r_code == code and r_mat is None:
            return action, band
    for r_code, _, _, action, band in REPAIR_RULES:
        if r_code == code:
            return action, band
    return "待評估", "A"


def decide(confidence: float, repair: dict, prior_q=None,
           coverage_blocked=False) -> dict:
    """②③ 處置分流 + 索賠經濟性。confidence 應為 Stage 4 加權後信心。"""
    band = repair["band"]
    lo, hi = repair["estimate_twd"]
    mid = (lo + hi) / 2

    # Stage 4 已判定不得主張（基準沒拍清楚）→ 一律僅記錄，優先於一切
    if coverage_blocked:
        return _d("record_only", "P3", False,
                  "基準觀測品質不足，不得對用戶主張——僅寫入車況檔累積", repair)

    # ③ 索賠經濟性：估價低於處理成本 → 不值得追
    if mid < CLAIM_HANDLING_COST:
        return _d("waive_not_worth_claiming", "P3", False,
                  f"估價中位 {mid:.0f} 元低於索賠處理成本 {CLAIM_HANDLING_COST} 元，"
                  f"記錄為自然耗損，不啟動索賠", repair)

    # ② 分流
    if confidence >= AUTO_ACTION_CONF and BAND_ORDER[band] >= BAND_ORDER["B"]:
        return _d("auto_action", "P1", True,
                  f"信心 {confidence:.2f} ≥ {AUTO_ACTION_CONF} 且級距 {band} ≥ B："
                  f"鎖定車輛、建立維修工單、通知用戶並附證據包", repair)
    if confidence >= REVIEW_CONF or band == "A":
        return _d("human_review", "P2", True,
                  f"信心 {confidence:.2f} 或級距 {band}：車輛保持可租，"
                  f"進客服複核佇列，不主動通知用戶", repair)
    return _d("record_only", "P3", False,
              f"信心 {confidence:.2f} < {REVIEW_CONF}：僅寫入車況檔累積。"
              f"同位置後續兩次還車再被偵測將自動升級", repair)


def _d(disposition, level, claimable, reason, repair):
    return {"disposition": disposition, "level": level, "claimable": claimable,
            "reason": reason, **repair}


def assess(damage: dict, panel=None, weighted_confidence=None,
           coverage_blocked=False) -> dict:
    """單筆損傷的完整 Stage 6 結果。"""
    repair = classify_repair(
        damage.get("damage_type") or damage.get("type", "scratch"),
        size_cm=damage.get("estimated_size_cm"),
        panel=panel or damage.get("panel"),
        depth=damage.get("depth_assessment"),
        severity=damage.get("severity"),
    )
    conf = weighted_confidence if weighted_confidence is not None else damage.get("confidence", 0)
    return decide(conf, repair, coverage_blocked=coverage_blocked)


# ---------- 告警量預算反推門檻（規格 §3 Stage 6 末段） ----------

def threshold_for_budget(daily_returns: int, cs_capacity: int,
                         fpr: float, positive_rate: float, recall: float) -> dict:
    """(誤報率 × N) + 預期真陽性數 ≤ M，反推可負擔的告警量。

    不要用 F1 最佳點決定門檻——要用客服實際可負擔的複核量反推。
    """
    n_pos = daily_returns * positive_rate
    n_neg = daily_returns - n_pos
    expected_tp = n_pos * recall
    expected_fp = n_neg * fpr
    total = expected_tp + expected_fp
    return {
        "daily_returns": daily_returns,
        "cs_capacity": cs_capacity,
        "expected_true_positives": round(expected_tp, 1),
        "expected_false_positives": round(expected_fp, 1),
        "expected_alerts": round(total, 1),
        "within_budget": total <= cs_capacity,
        "utilization": f"{total / cs_capacity:.0%}" if cs_capacity else "n/a",
        "recommendation": (
            f"目前設定每日產生約 {total:.0f} 件告警，客服可負擔 {cs_capacity} 件——"
            + ("在預算內，可考慮調降門檻以提高 recall"
               if total <= cs_capacity * 0.8 else
               "接近上限，維持現行門檻"
               if total <= cs_capacity else
               f"超出負荷 {total - cs_capacity:.0f} 件，須調高信心門檻或增加複核人力")
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Stage 6 估價與處置決策")
    ap.add_argument("--table", action="store_true", help="印出維修對照表")
    ap.add_argument("--thresholds", nargs=2, type=int, metavar=("N", "M"),
                    help="每日還車量 N、客服可負擔複核量 M → 反推告警預算")
    ap.add_argument("--fpr", type=float, default=0.033, help="誤報率（預設實測 3.3%%）")
    ap.add_argument("--recall", type=float, default=0.857, help="recall（預設實測 85.7%%）")
    ap.add_argument("--positive-rate", type=float, default=0.149,
                    help="真實有損比例（預設資料集 21/141）")
    args = ap.parse_args()

    if args.table:
        print("【維修動作對照表】")
        for code, mx, mat, action, band in REPAIR_RULES:
            size = f"≤{mx}cm" if mx else "任意"
            lo, hi = PRICE_BANDS[band]["range"]
            print(f"  {DAMAGE_ZH.get(code, code):8s} {size:8s} {mat or '不限':4s} "
                  f"→ {action:14s} 級距{band}（{PRICE_BANDS[band]['label']}）"
                  f" {lo:,}–{hi:,} 元")
        print(f"\n索賠處理成本門檻：{CLAIM_HANDLING_COST} 元"
              f"（估價中位低於此值 → 記錄為自然耗損，不啟動索賠）")
        print("\n【範例】")
        for d, panel in ((({"type": "刮痕", "estimated_size_cm": 3}), "FD_L"),
                         (({"type": "刮痕", "estimated_size_cm": 12}), "FD_L"),
                         (({"type": "破損"}), "RB"),
                         (({"damage_type": "rim_curb"}), "WHL_RL")):
            r = assess(d, panel=panel, weighted_confidence=0.9)
            print(f"  {r['damage_type_zh']:6s} {r.get('size_cm') or '-':>4} "
                  f"{panel:7s} → {r['repair_action']:14s} 級距{r['band']} "
                  f"{r['estimate_twd'][0]:,}–{r['estimate_twd'][1]:,} 元 "
                  f"→ {r['disposition']}")

    if args.thresholds:
        out = threshold_for_budget(args.thresholds[0], args.thresholds[1],
                                   args.fpr, args.positive_rate, args.recall)
        print(json.dumps(out, ensure_ascii=False, indent=1))

    if not (args.table or args.thresholds):
        ap.error("請指定 --table 或 --thresholds N M")


if __name__ == "__main__":
    main()
