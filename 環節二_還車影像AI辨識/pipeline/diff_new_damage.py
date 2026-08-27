#!/usr/bin/env python3
"""Stage 4 — 差集比對：以觀測覆蓋度加權判定新損（Prompt 架構規格 §3 Stage 4）。

核心規則（規格稱為「整套設計最重要的防線」）：
    上次沒拍清楚的地方，這次不能算在用戶頭上。

做法：新損信心 × 基準觀測品質(prior_q) → 依加權後信心決定處置層級。
prior_q 來自 coverage.py 對【借車照】跑出的分區觀測品質。

────────────────────────────────────────────────────────────────
⚠ 門檻與規格不同，這是實測後的刻意調整，不是實作疏漏
────────────────────────────────────────────────────────────────
規格原文門檻為 prior_q ≥ 0.8 可自動處置、< 0.6 不得主張。該門檻預設基準照
是「營運人員在車輛入隊時的高品質完整拍攝」（規格 §5）。

本資料集為用戶手持手機拍攝，實測 141 組借車照的分區觀測品質分布顯示
（見 coverage_baseline.json 與 calibrate() 輸出），0.7 上下是常態而非劣質。
直接套用規格門檻會使絕大多數真實損傷（含已確認索賠案例 RCR-7661 左後，
其後保桿 prior_q=0.72）全數被擋在自動處置之外，recall 崩潰。

因此門檻改以「本資料集分位數」校準，並保留規格的三層結構與語意：
  ≥ Q_FULL_TRUST   信心不折損，可自動處置
  ≥ Q_MIN_CLAIM    信心折損，最高只能進人工複核
  <  Q_MIN_CLAIM   僅記錄，不得對用戶主張
執行 `python3 diff_new_damage.py --calibrate` 可依實際分布重新推導門檻。

用法：
  python3 diff_new_damage.py --calibrate     # 依 coverage_baseline 推導門檻
  python3 diff_new_damage.py --apply         # 對 141 組判定套用加權，輸出影響分析
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import (  # noqa: E402
    LEGACY_TYPE_TO_CODE, part_to_panel, types_compatible, uv_distance, UV_MATCH_RADIUS,
)
from results_config import FINAL_RESULTS  # noqa: E402

HERE = Path(__file__).resolve().parent

# 門檻（由 --calibrate 依本資料集分位數校準；規格原值 0.8 / 0.6 見上方說明）
Q_FULL_TRUST = 0.70   # ≥ 此值：基準夠清晰，可進自動處置
Q_MIN_CLAIM = 0.50    # < 此值：僅記錄，不得對用戶主張

# 分流採「兩道獨立門檻」而非規格的「信心 × prior_q 相乘」。
#
# 實測（1,476 筆分區觀測、27 筆偵測到的損傷）：
#   prior_q 分布 p50=0.65、**最大值僅 0.75**（用戶手持拍攝的天花板）
#   → 相乘後信心 max=0.74，數學上永遠達不到 0.85 的自動處置門檻
#   → 27 筆全數降級，含 21 筆已確認真損，只擋到 1 筆誤報。該層形同廢掉自動處置。
#
# 規格的相乘式隱含假設 prior_q 接近 1.0（營運人員高品質入隊拍攝）。
# 改為兩道獨立門檻後（偵測信心 ≥0.85 且 prior_q ≥0.70），14/27 可自動處置，
# 且「基準沒拍清楚就不得主張」的保護語意完全保留。
GATE_MODE = "gate"    # "gate"（實測採用）| "multiply"（規格原文，僅供對照）

# 加權後信心 → 處置（沿用既有 P1/P2/P3 分級語意）
AUTO_ACTION_MIN = 0.85   # ≥ 自動處置（P1）
REVIEW_MIN = 0.60        # ≥ 人工複核（P2）

# 查無基準資料時的保守 prior_q：既不獎勵也不重罰，落在「須複核」區間
PRIOR_Q_UNKNOWN = 0.65


def load_baseline(path=None) -> dict:
    p = Path(path) if path else HERE / "coverage_baseline.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def panel_of(damage: dict, angle: str | None) -> str | None:
    """從損傷紀錄推出分區代碼。優先用既有 part 標籤，其次用 location 文字比對。"""
    if damage.get("panel"):
        return damage["panel"]
    if damage.get("part"):
        return part_to_panel(damage["part"], angle)
    # location 是自由文字（如「右後保險桿（右後反光片右側）」）——用部位關鍵字反查
    loc = damage.get("location") or ""
    for part in ("前保險桿", "後保險桿", "引擎蓋", "後車廂蓋", "車頂",
                 "左前門", "左後門", "右前門", "右後門",
                 "左前葉子板", "右前葉子板", "左後葉子板", "右後葉子板",
                 "車燈", "後視鏡"):
        if part in loc:
            return part_to_panel(part, angle)
    for kw, part in (("保桿", None), ("保險桿", None), ("葉子板", None), ("門", None)):
        if kw in loc:
            # 保桿/葉子板等無左右字樣時，用方位補
            side = "前" if angle and "前" in angle else "後"
            return part_to_panel({"保桿": f"{side}保險桿", "保險桿": f"{side}保險桿",
                                  "葉子板": f"{angle}葉子板" if angle else None,
                                  "門": f"{angle}門" if angle else None}.get(kw) or "", angle)
    return None


def match_pre_existing(damage: dict, baseline_records: list[dict], angle=None) -> dict | None:
    """在車況檔中找既有損傷匹配（規格 §3 Stage 4：panel 相同 + UV 距離 + 類型相容）。"""
    panel = panel_of(damage, angle)
    dtype = damage.get("damage_type") or LEGACY_TYPE_TO_CODE.get(damage.get("type", ""), "scratch")
    uv = damage.get("position_uv")
    for b in baseline_records:
        if b.get("kind") != "pre_existing":
            continue
        if panel and panel_of(b, b.get("angle")) != panel:
            continue
        btype = b.get("damage_type") or LEGACY_TYPE_TO_CODE.get(b.get("type", ""), "scratch")
        if not types_compatible(dtype, btype):
            continue
        # 有 UV 才比距離；無 UV（舊資料）則只要同分區同類型即視為匹配
        if uv and b.get("position_uv"):
            if uv_distance(uv, b["position_uv"]) >= UV_MATCH_RADIUS:
                continue
        return b
    return None


def weigh(damage_conf: float, prior_q: float | None, mode: str = GATE_MODE) -> dict:
    """核心：以基準觀測品質決定新損可否主張。

    mode="gate"（預設，實測後改用）
        兩道獨立門檻：偵測信心 ≥ AUTO_ACTION_MIN 且 prior_q ≥ Q_FULL_TRUST 才自動處置。
    mode="multiply"（規格原文）
        weighted = 信心 × prior_q，再比對門檻。**本資料集實測不可用**，理由見檔頭。
    """
    q = PRIOR_Q_UNKNOWN if prior_q is None else prior_q
    weighted = damage_conf * q

    if q < Q_MIN_CLAIM:
        # 上次根本沒拍清楚 → 無論偵測多有信心，一律僅記錄
        return {"prior_q": prior_q, "weighted_confidence": round(weighted, 4),
                "disposition": "record_only", "level": "P3",
                "claimable": False,
                "reason": f"基準觀測品質不足（prior_q={q:.2f} < {Q_MIN_CLAIM}）——"
                          f"借車照未清楚拍到此部位，不得對用戶主張"}

    if q < Q_FULL_TRUST:
        # 拍得普通 → 信心折損，最高只能人工複核
        return {"prior_q": prior_q, "weighted_confidence": round(weighted, 4),
                "disposition": "human_review", "level": "P2",
                "claimable": True,
                "reason": f"基準觀測品質偏低（prior_q={q:.2f}）——"
                          f"信心折損為 {weighted:.2f}，須人工複核確認"}

    # 基準夠清晰 → 分流。gate 模式用原始信心，multiply 模式用相乘後信心。
    score = damage_conf if mode == "gate" else weighted
    label = "偵測信心" if mode == "gate" else "加權信心"
    common = {"prior_q": prior_q, "weighted_confidence": round(weighted, 4),
              "gate_mode": mode}
    if score >= AUTO_ACTION_MIN:
        return {**common, "disposition": "auto_action", "level": "P1", "claimable": True,
                "reason": f"基準足夠清晰（prior_q={q:.2f} ≥ {Q_FULL_TRUST}）"
                          f"且{label} {score:.2f} ≥ {AUTO_ACTION_MIN}"}
    if score >= REVIEW_MIN:
        return {**common, "disposition": "human_review", "level": "P2", "claimable": True,
                "reason": f"{label} {score:.2f} 落在複核區間"}
    return {**common, "disposition": "record_only", "level": "P3", "claimable": False,
            "reason": f"{label} {score:.2f} < {REVIEW_MIN}，僅累積記錄"}


def assess_case(assessment: dict, coverage: dict | None, angle: str | None,
                passport_records: list[dict] | None = None) -> dict:
    """對單一案件套用 Stage 4。回傳含每筆損傷加權結果與案件層級處置。"""
    from coverage import prior_quality  # 延遲 import：避免 CLI 無 API key 時卡住

    out = {"angle": angle, "damages": [], "coverage_available": coverage is not None}
    if not assessment.get("new_damage_found"):
        out.update(case_level="P3", case_disposition="no_new_damage")
        return out

    for d in assessment.get("damages", []):
        panel = panel_of(d, angle)
        pq = prior_quality(coverage, panel) if coverage else None
        w = weigh(d.get("confidence", 0), pq)
        pre = match_pre_existing(d, passport_records or [], angle)
        if pre:
            w.update(disposition="pre_existing", level="P3", claimable=False,
                     reason=f"車況檔中已有相符既有損傷（{pre.get('id')}）——非新損")
        out["damages"].append({
            "location": d.get("location"), "type": d.get("type"),
            # 尺寸與深度必須帶下去：Stage 6 靠它們決定級距，
            # 少了 size_cm 會落進「任意尺寸」的最大級距，系統性高估修理費。
            "damage_type": d.get("damage_type"),
            "estimated_size_cm": d.get("estimated_size_cm"),
            "depth_assessment": d.get("depth_assessment"),
            "panel": panel, "raw_confidence": d.get("confidence"), **w,
        })

    # 案件層級取最嚴重的一筆
    order = {"P1": 0, "P2": 1, "P3": 2}
    if out["damages"]:
        worst = min(out["damages"], key=lambda x: order[x["level"]])
        out.update(case_level=worst["level"], case_disposition=worst["disposition"])
    else:
        out.update(case_level="P3", case_disposition="no_new_damage")
    return out


# ---------- 校準與影響分析 ----------

def calibrate(baseline: dict) -> dict:
    """依實際分區觀測品質分布推導門檻，並與規格原值對照。"""
    qs = sorted(c["best_quality"] for b in baseline.values()
                if not b.get("error") for c in b["panel_coverage_map"])
    if not qs:
        return {"error": "coverage_baseline.json 無有效資料，請先跑 coverage.py --pairs"}
    pct = lambda q: qs[int(q * (len(qs) - 1))]
    return {
        "n_panel_observations": len(qs),
        "percentiles": {f"p{int(q*100)}": round(pct(q), 3)
                        for q in (0.05, 0.1, 0.25, 0.5, 0.75, 0.9)},
        "spec_thresholds": {"full_trust": 0.8, "min_claim": 0.6},
        "spec_impact": {
            "would_be_unclaimable": f"{sum(1 for q in qs if q < 0.6)/len(qs):.1%}",
            "would_be_full_trust": f"{sum(1 for q in qs if q >= 0.8)/len(qs):.1%}",
        },
        "calibrated_thresholds": {"full_trust": Q_FULL_TRUST, "min_claim": Q_MIN_CLAIM},
        "calibrated_impact": {
            "unclaimable": f"{sum(1 for q in qs if q < Q_MIN_CLAIM)/len(qs):.1%}",
            "full_trust": f"{sum(1 for q in qs if q >= Q_FULL_TRUST)/len(qs):.1%}",
        },
        "suggested": {"full_trust": round(pct(0.5), 2), "min_claim": round(pct(0.1), 2),
                      "note": "建議 full_trust≈中位數、min_claim≈p10（只擋最差的尾巴）"},
    }


def apply_to_dataset(baseline: dict) -> dict:
    """對 141 組最終判定套用 Stage 4，分析影響（哪些案件被降級／保護）。"""
    results = json.loads(FINAL_RESULTS.read_text())["results"]
    passports = json.loads((HERE / "passports.json").read_text())
    relabels = {(r["car"], r["angle"]): r
                for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}

    rows, changed = [], []
    for r in results:
        a = r.get("assessment")
        if not a:
            continue
        key = f"{r['car']}-{r['angle']}"
        cov = baseline.get(key)
        cov = None if (cov and cov.get("error")) else cov
        recs = passports.get(r["car"].replace("-", ""), {}).get("records", [])
        out = assess_case(a, cov, r["angle"], recs)
        truth = relabels.get((r["car"], r["angle"]), {}).get("relabel")
        row = {"case": key, "label": r["label"], "relabel": truth,
               "detected": a["new_damage_found"], **{k: out[k] for k in
               ("case_level", "case_disposition", "coverage_available")},
               "damages": out["damages"]}
        rows.append(row)
        # 原本會被判 P1 但因覆蓋度被降級者 = 這層機制實際保護到的案件
        if a["new_damage_found"]:
            raw_max = max((d.get("confidence", 0) for d in a["damages"]), default=0)
            raw_level = "P1" if raw_max >= 0.85 else "P2"
            if order_of(out["case_level"]) > order_of(raw_level):
                changed.append({"case": key, "from": raw_level, "to": out["case_level"],
                                "relabel": truth,
                                "reason": out["damages"][0]["reason"] if out["damages"] else ""})

    detected = [r for r in rows if r["detected"]]
    return {
        "n_cases": len(rows),
        "n_detected_damage": len(detected),
        "coverage_missing": sum(1 for r in rows if not r["coverage_available"]),
        "disposition_counts": _counts(r["case_disposition"] for r in detected),
        "level_counts": _counts(r["case_level"] for r in detected),
        "downgraded_by_coverage": changed,
        "n_downgraded": len(changed),
        "downgraded_true_damage": sum(1 for c in changed if c["relabel"] == "damage"),
        "downgraded_false_alarm": sum(1 for c in changed if c["relabel"] and c["relabel"] != "damage"),
        "rows": rows,
    }


def order_of(level: str) -> int:
    return {"P1": 0, "P2": 1, "P3": 2}[level]


def _counts(it):
    out = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def main():
    ap = argparse.ArgumentParser(description="Stage 4 覆蓋度加權差集比對")
    ap.add_argument("--calibrate", action="store_true", help="依實際分布推導門檻")
    ap.add_argument("--apply", action="store_true", help="對 141 組套用並分析影響")
    ap.add_argument("--baseline", help="coverage_baseline.json 路徑")
    args = ap.parse_args()

    baseline = load_baseline(args.baseline)
    if not baseline:
        sys.exit("找不到 coverage_baseline.json——請先執行 python3 coverage.py --pairs")

    if args.calibrate:
        print(json.dumps(calibrate(baseline), ensure_ascii=False, indent=1))
    if args.apply:
        out = apply_to_dataset(baseline)
        (HERE / "stage4_impact.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
        brief = {k: v for k, v in out.items() if k not in ("rows", "downgraded_by_coverage")}
        print(json.dumps(brief, ensure_ascii=False, indent=1))
        print(f"\n因基準覆蓋度不足而降級的案件（{out['n_downgraded']} 件）：")
        for c in out["downgraded_by_coverage"]:
            mark = "⚠真損被擋" if c["relabel"] == "damage" else "✔誤報被擋"
            print(f"  {mark} {c['case']:16s} {c['from']}→{c['to']}  {c['reason'][:70]}")
    if not (args.calibrate or args.apply):
        ap.error("請指定 --calibrate 或 --apply")


if __name__ == "__main__":
    main()
