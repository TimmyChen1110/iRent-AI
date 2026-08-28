#!/usr/bin/env python3
"""v7 — 連續座標差分（修 v6 的格位量化匹配失敗：同一道痕被兩模型分到不同格）。

═══════════════════════════════════════════════════════════════════
機制（相對 v6 只改位置表示與匹配方式，其餘設計約束一字不動）：
  痕跡位置：3×3 格位 → (u, v) 連續座標＋anchored_to 錨定說明
  判讀狀態：維持 3×3 網格（區域性質不需要精度，quality 邏輯沿用）
  同模型借/還匹配：形態相容組內、距離 ≤ MATCH_RADIUS 的匈牙利匹配；
    未匹配的還車照痕跡＝佔用訊號、延伸增加＞門檻＝延伸訊號
  跨模型交集：距離 ≤ MATCH_RADIUS（v6 是格位相等——RCG2235 就死在這）
  錨定加權：任一邊「無明確參照物」→ 半徑 ×1.5；兩邊皆無 → ×2 且標
    low_spatial_confidence

執行順序（Step 0 零 API 必先做）：
  Step 0  空轉基線——同一張照片的重跑互相差分，理論上該是空的；
          實際空轉率＝所有差分方法的假陽性下限。用 v6 Stage A 現成資料。
  v7-A    匹配半徑標定：5 照 × 5 次 × 2 模型（P8 連續座標盲列舉），
          聚類估 sigma_u/sigma_v → MATCH_RADIUS = 3×√(σu²+σv²)
  v7-B    31 案借/還 × 2 模型，隨機交錯
  v7-C    差分＋距離交集＋證偽判定

預先註冊證偽條件（跑完不改）：
  A. MATCH_RADIUS > 0.15 → 座標抖動接近痕跡典型間距，v7 死亡，退回網格改測 2×2/4×4
  B. v7 空轉率 > v6 空轉率（兩模型平均）→ 連續座標引入噪音超過消除的量化誤差，死亡
  C. RDH-3092 不再產生訊號 → 死亡（不可退讓底線）
  D. clean 誤旗率 > v6 的 7.1% 且超出空轉基線可解釋範圍 → 不採用
  E. >40% 痕跡「無明確參照物」→ 降級為混合方案或死亡

═══════════════════════════════════════════════════════════════════
★ 實測結果（2026-08-28）：條件 A 觸發，v7 死亡。
  MATCH_RADIUS = 0.2954 > 0.15。Stage B 未跑（省 124 次呼叫——
  標定前置的價值）。條件 B（v7 空轉 24%/22% < v6 34%/18% 平均）與
  條件 E（無錨定率 0%，43 筆痕跡全有參照物）都通過，死因單一。
═══════════════════════════════════════════════════════════════════

【Step 0 空轉基線（cont_diff_step0.json）——所有差分方法的假陽性下限】
  同照片重跑互相差分（各 50 對，v6 格位邏輯、門檻 4.62/3）：
    flash 34%、pro 18%
  → v6 交集後 clean 誤旗 7.1% 遠低於單模型空轉率：跨模型交集扛了
    主要的假陽性抑制，v6 那 2 筆誤旗大概率就是噪音下限的顯現。
  → flash 空轉率超過規格 15% 參考線；「砍 flash、pro×2 取交集」
    的替代案被 v7-A 原始資料否定（見下：pro 雙穩態——兩次重跑常
    完全相同＝交集不過濾，或完全不同＝全滅）。

【v7-A 半徑標定（cont_diff_stageA.json，50 呼叫）——死因解剖】
  flash：σ_u=0.0946、σ_v=0.0273（僅 2 個可用 cluster——佔用太不穩，
    聚類難以湊滿 3 員）→ radius 0.2954。原始資料：同一點狀痕五次
    u=0.68/0.32/0.42/0.42/0.52——連續表示給了漂移更大的自由度。
  pro：σ=0.0000（7 clusters）→ radius 0。不是精準，是【假連續】：
    讀數內部量化在 0.05/0.10 級距（0.15/0.35/0.45/0.85…）且重跑
    逐字重複。另有雙穩態：RCW1883 五次在兩套完全不同的列舉間翻面
    （rep 1/2/5 vs 3/4，各自內部完全一致）——rep 式標定量不到。
  結構性教訓：①「連續座標消除量化」的前提兩頭落空——flash 用不了
    精度、pro 不提供精度；②rep 式標定天生量不到跨照片（借/還視角
    差異）的座標誤差，就算半徑過關也未驗證跨照匹配。
  唯一亮點：錨定要求 100% 有效（0% 無參照物）——anchored_to 欄位
    設計可沿用到任何需要位置可稽核性的場景。

【退回網格路線的格子尺寸建議（規格 §7 要求）】
  維持 3×3，不改 2×2/4×4：pro 的暗格網級距（0.05–0.10）比 3×3
  格寬（0.33）細，3×3 不損失 pro 資訊；flash 位置噪音 σ≈0.1 恰為
  3×3 格寬的三分之一，4×4（格寬 0.25）會增加邊界翻格，2×2 減半
  鑑別力而 v6 的兩筆誤旗是同格一致、不會因此減少。RCG2235 型
  跨模型格位歧異在 flash 噪音水準下無任何表示法可救——該案生產
  無關（現行判定已抓到），接受為 v6 的已知邊界。

用法：
  python3 continuous_diff.py --step 0     # 零 API：v6 資料空轉基線
  python3 continuous_diff.py --step a     # 50 呼叫＋半徑標定＋條件 A/E
  python3 continuous_diff.py --step b     # 124 呼叫（條件 A 已觸發，勿跑）
  python3 continuous_diff.py --step c     # 零 API：差分＋全部證偽條件
"""
import argparse
import itertools
import json
import math
import random
import statistics
from pathlib import Path

from blind_enumeration import (ALL_CELLS, MODELS, NEGATIVE_CONTROL,
                               STAGE_A_CASES, STAGE_A_REPS, TARGET_MISS,
                               _load_context, _run_calls, diff_signals)

HERE = Path(__file__).resolve().parent

RADIUS_LIMIT = 0.15          # 條件 A
ANCHOR_MISSING_LIMIT = 0.40  # 條件 E
V6_CLEAN_FLAG_RATE = 2 / 28  # 條件 D 對照
NO_ANCHOR_PHRASE = "無明確參照物"

COMPATIBLE = frozenset({
    ("linear", "linear"), ("patch", "patch"), ("point", "point"),
    ("contour", "contour"), ("discoloration", "discoloration"),
    ("edge_gap", "edge_gap"),
    # 跨形態相容組：同一物理痕跡可能被讀成不同形態（保守方向，避免
    # 「舊的消失＋新的出現」把一個痕跡放大成兩個訊號）
    ("linear", "patch"), ("patch", "linear"),
    ("contour", "patch"), ("patch", "contour"),
    ("point", "discoloration"), ("discoloration", "point"),
})


# ---------- 純函式（零 API，tests/test_continuous_diff.py 覆蓋） ----------

def mark_cell(mark: dict) -> str:
    """position_uv → 判讀網格格位（u→A/B/C、v→1/2/3，夾限到 [0,1)）。"""
    u, v = mark["position_uv"][0], mark["position_uv"][1]
    col = "ABC"[min(2, max(0, int(u * 3)))]
    row = min(3, max(1, int(v * 3) + 1))
    return f"{col}{row}"


def grid_status(panel_result: dict) -> dict:
    g = {c["cell"]: c.get("status") for c in panel_result.get("readability_grid", [])
         if c.get("cell") in ALL_CELLS}
    for c in ALL_CELLS:
        g.setdefault(c, "out_of_frame")
    return g


def anchored(mark: dict) -> bool:
    a = (mark.get("anchored_to") or "").strip()
    return bool(a) and NO_ANCHOR_PHRASE not in a


def dist(m1: dict, m2: dict) -> float:
    (u1, v1), (u2, v2) = m1["position_uv"], m2["position_uv"]
    return math.hypot(u1 - u2, v1 - v2)


def pair_radius(m1: dict, m2: dict, base: float) -> tuple:
    """錨定可靠度加權半徑。回傳 (radius, low_spatial_confidence)。"""
    n = anchored(m1) + anchored(m2)
    if n == 2:
        return base, False
    if n == 1:
        return 1.5 * base, False
    return 2.0 * base, True


def match_marks(pickup_marks: list, return_marks: list, base_radius: float) -> dict:
    """形態相容＋距離門檻內的匈牙利匹配。

    回傳 matched: [(p_idx, r_idx)]、unmatched_return: [r_idx]。
    """
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    if not pickup_marks or not return_marks:
        return {"matched": [], "unmatched_return": list(range(len(return_marks)))}
    BIG = 1e6
    cost = np.full((len(pickup_marks), len(return_marks)), BIG)
    for i, p in enumerate(pickup_marks):
        for j, r in enumerate(return_marks):
            if (p["morphology"], r["morphology"]) not in COMPATIBLE:
                continue
            d = dist(p, r)
            radius, _ = pair_radius(p, r, base_radius)
            if d <= radius:
                cost[i, j] = d
    rows, cols = linear_sum_assignment(cost)
    matched = [(i, j) for i, j in zip(rows, cols) if cost[i, j] < BIG]
    matched_r = {j for _, j in matched}
    return {"matched": matched,
            "unmatched_return": [j for j in range(len(return_marks)) if j not in matched_r]}


def diff_continuous(pickup: dict, return_: dict, base_radius: float,
                    extent_threshold) -> dict:
    """單一模型的 v7 差分。uncertain_marks 不參與；痕跡所在格位須兩邊皆 clear。"""
    gp, gr = grid_status(pickup), grid_status(return_)
    clear_both = {c for c in ALL_CELLS if gp[c] == "clear" and gr[c] == "clear"}
    pm = [m for m in (pickup.get("marks") or []) if mark_cell(m) in clear_both]
    rm = [m for m in (return_.get("marks") or []) if mark_cell(m) in clear_both]
    res = match_marks(pm, rm, base_radius)
    signals = []
    for j in res["unmatched_return"]:
        r = rm[j]
        signals.append({"type": "unmatched_mark", "position_uv": r["position_uv"],
                        "morphology": r["morphology"], "extent_cm": r.get("max_extent_cm"),
                        "description": r.get("description", ""),
                        "low_spatial_confidence": not anchored(r)})
    if extent_threshold is not None:
        for i, j in res["matched"]:
            p, r = pm[i], rm[j]
            ep, er = p.get("max_extent_cm"), r.get("max_extent_cm")
            if ep is not None and er is not None and er - ep > extent_threshold:
                _, low = pair_radius(p, r, base_radius)
                signals.append({"type": "extent_increase", "position_uv": r["position_uv"],
                                "morphology": r["morphology"],
                                "extent_cm": er, "extent_delta": er - ep,
                                "description": r.get("description", ""),
                                "low_spatial_confidence": low})
    return {"comparable_cells": sorted(clear_both), "signals": signals,
            "n_pickup_marks": len(pm), "n_return_marks": len(rm)}


def intersect_continuous(sig_a: list, sig_b: list, radius: float) -> list:
    """跨模型距離交集（v7 修 RCG2235 的關鍵：B2 vs A2 只要距離夠近就算同一訊號）。"""
    out = []
    for f in sig_a:
        near = [p for p in sig_b
                if math.hypot(f["position_uv"][0] - p["position_uv"][0],
                              f["position_uv"][1] - p["position_uv"][1]) <= radius]
        if near:
            out.append({**f, "corroborated_by": near[0]["position_uv"],
                        "model_agreement": "both"})
    return out


def cluster_marks(runs: list, gate: float = 0.20) -> list:
    """跨重跑聚類同一痕跡（貪婪：與既有 cluster 質心距離 ≤ gate 且形態相容）。

    runs: [marks_list × N reps]。回傳 clusters: [{"members": [(rep_idx, mark)]}]
    """
    clusters = []
    for rep_idx, marks in enumerate(runs):
        for m in marks:
            best, best_d = None, gate
            for cl in clusters:
                if any(ri == rep_idx for ri, _ in cl["members"]):
                    continue  # 同一次重跑內不重複入同 cluster
                cu = statistics.mean(x["position_uv"][0] for _, x in cl["members"])
                cv = statistics.mean(x["position_uv"][1] for _, x in cl["members"])
                d = math.hypot(m["position_uv"][0] - cu, m["position_uv"][1] - cv)
                rep_morph = cl["members"][0][1]["morphology"]
                if d <= best_d and (m["morphology"], rep_morph) in COMPATIBLE:
                    best, best_d = cl, d
            if best is None:
                clusters.append({"members": [(rep_idx, m)]})
            else:
                best["members"].append((rep_idx, m))
    return clusters


def estimate_sigma(runs_by_case: dict, min_members: int = 3) -> dict:
    """由重跑聚類估位置讀數離散度 → MATCH_RADIUS 與延伸門檻。

    runs_by_case: {case_key: [marks_list × N reps]}（單一模型或混合皆可）。
    """
    stds_u, stds_v, extent_stds, cluster_sizes = [], [], [], []
    for runs in runs_by_case.values():
        for cl in cluster_marks(runs):
            cluster_sizes.append(len(cl["members"]))
            if len(cl["members"]) < min_members:
                continue
            us = [m["position_uv"][0] for _, m in cl["members"]]
            vs = [m["position_uv"][1] for _, m in cl["members"]]
            stds_u.append(statistics.stdev(us))
            stds_v.append(statistics.stdev(vs))
            es = [m["max_extent_cm"] for _, m in cl["members"]
                  if m.get("max_extent_cm") is not None]
            if len(es) >= 2:
                extent_stds.append(statistics.stdev(es))
    su = statistics.median(stds_u) if stds_u else None
    sv = statistics.median(stds_v) if stds_v else None
    ee = statistics.median(extent_stds) if extent_stds else None
    return {
        "n_clusters_used": len(stds_u),
        "sigma_u": round(su, 4) if su is not None else None,
        "sigma_v": round(sv, 4) if sv is not None else None,
        "match_radius": round(3 * math.hypot(su, sv), 4) if su is not None else None,
        "extent_std_median": round(ee, 2) if ee is not None else None,
        "extent_threshold": round(3 * ee, 2) if ee else None,
    }


def anchor_quality(all_marks: list) -> dict:
    n = len(all_marks)
    missing = sum(1 for m in all_marks if not anchored(m))
    return {"n_marks": n, "no_anchor": missing,
            "no_anchor_rate": round(missing / n, 4) if n else None}


def null_rate_v6(rows: list, extent_threshold, count_threshold) -> dict:
    """Step 0：v6 Stage A 重跑互相差分的空轉率（格位邏輯）。每模型各算。"""
    out = {}
    for model in MODELS:
        by_case = {}
        for r in rows:
            if r.get("parsed") and r["model"] == model:
                by_case.setdefault((r["car"], r["angle"]), []).append(r["parsed"])
        flags, pair_signal_cells = [], []
        for reps in by_case.values():
            for a, b in itertools.combinations(reps, 2):
                s = diff_signals(a, b, extent_threshold, count_threshold)
                flags.append(bool(s["any"]))
                pair_signal_cells.append(len(s["any"]))
        out[model] = {"pairs": len(flags),
                      "null_rate": round(sum(flags) / len(flags), 4) if flags else None,
                      "mean_signal_cells": round(statistics.mean(pair_signal_cells), 3)
                      if pair_signal_cells else None}
    return out


def null_rate_v7(rows: list, base_radius: float, extent_threshold) -> dict:
    """條件 B：v7-A 重跑互相差分的空轉率（連續座標邏輯）。"""
    out = {}
    for model in MODELS:
        by_case = {}
        for r in rows:
            if r.get("parsed") and r["model"] == model:
                by_case.setdefault((r["car"], r["angle"]), []).append(r["parsed"])
        flags = []
        for reps in by_case.values():
            for a, b in itertools.combinations(reps, 2):
                s = diff_continuous(a, b, base_radius, extent_threshold)
                flags.append(bool(s["signals"]))
        out[model] = {"pairs": len(flags),
                      "null_rate": round(sum(flags) / len(flags), 4) if flags else None}
    return out


# ---------- P8 prompt ----------

P8_TEMPLATE = """你是車輛表面狀態的記錄員。

你的任務不是判斷損傷、不是評估責任、不是估算費用。
你的任務是把指定區域內所有可見的表面痕跡，盡可能完整地記錄下來，
包含你不確定是什麼的痕跡。

【記錄原則】
1. 只記錄你實際看到的視覺特徵。不要推測成因，不要下損傷判定。
2. 使用中性的形態描述，不要使用「刮痕」「凹陷」「損壞」這類判定性詞彙。
3. 不確定的痕跡也要記錄，放進 uncertain_marks，不要略過。
4. 若某區域因反光、遮擋、過暗、髒汙而無法判讀，如實標記，不要推測其內容。

【目標區域】
分區：{panel}（{panel_zh}）

【座標系定義】
請以此分區的實際邊界（鈑件接縫、輪拱線、窗框下緣、保桿分模線）
為基準，建立正規化座標：
  u = 0.00 為該分區靠車頭側的邊界
  u = 1.00 為該分區靠車尾側的邊界
  v = 0.00 為該分區的上緣
  v = 1.00 為該分區的下緣

不要以整張照片的邊界為基準。若分區的某一側邊界未完整入鏡，
請依可見的部分推估邊界位置，並在 boundary_note 中說明。

【位置錨定要求】
座標的用途是讓不同照片之間可以比對同一個位置，
因此每一個痕跡都必須說明你是依據什麼判定它的座標。

在 anchored_to 欄位中，列出你用來定位的可辨識參照物，例如：
  「位於門把中心點下方，水平位置與門把右緣對齊」
  「距離輪拱前緣約三分之一個輪拱寬度」
  「位於保桿分模線與霧燈框之間的中點」

若該區域沒有任何可辨識的參照物（大片無特徵的鈑面），
請在 anchored_to 中明確說明「無明確參照物，座標為目視估計」。
這會讓下游知道該筆座標的可靠度較低。

【形態分類】
記錄痕跡時使用以下中性形態詞：
  linear        線狀。長度明顯大於寬度
  patch         面狀。長寬相近的區域性差異
  point         點狀。直徑小於 1 公分的局部
  contour       表面起伏。反射光帶在此處走向或寬度改變，但無明顯色差
  discoloration 色差。與周圍表面顏色不同，但無明顯質地變化
  edge_gap      邊緣或接縫的異常間隙、錯位

【合併規則】
為使不同次記錄可比對，請遵守以下合併規則：
- 方向相近、間距小於自身長度的多道平行線狀痕跡，
  記為 1 個 linear 痕跡，並在 count_within 中說明包含幾道
- 彼此距離小於 3 公分的多個點狀痕跡，記為 1 個 point 痕跡，
  並在 count_within 中給出數量
- 延伸範圍較大的痕跡（如反射扭曲區），座標記在其中心位置，
  並在 extent_uv 中給出涵蓋範圍

【尺寸基準】
使用畫面中的已知尺寸物件作為比例尺：
1. 車牌：台灣小型車車牌實際尺寸為 32.0 × 15.0 公分
2. 輪圈：一般小型車鋁圈直徑約 40 公分（非本車型精確值，僅供粗估）

在 size_reference_used 中說明採用了哪個基準。
若畫面中無可用基準，max_extent_cm 給 null，不要憑印象估算。

【判讀狀態網格】
除了痕跡記錄之外，請將此分區劃分為 3×3 共 9 格，
標示每一格的判讀狀態：
  水平（靠車頭側 → 靠車尾側）：A / B / C
  垂直（上緣 → 下緣）：1 / 2 / 3

每一格的狀態擇一：
  clear                可完整判讀
  reflection_obscured  被反光覆蓋，超過三分之一面積無法判讀
  too_dark             暗部細節遺失
  soiled               被泥沙或灰塵覆蓋，可能遮蔽表面狀態
  out_of_frame         未入鏡或僅邊緣入鏡
  occluded             被其他物體遮擋

這個網格只用於標示判讀狀態，不用於標示痕跡位置。
痕跡位置一律使用上述的連續座標。

readability_grid 必須包含全部 9 格。
extent_uv 為 [[u_min, v_min], [u_max, v_max]]。"""


def enumerate_panel_p8(client, model: str, photo_path: str, panel: str, panel_zh: str) -> dict:
    """P8 連續座標盲列舉。與 v6 相同：無時序線索、無主張、借還逐字同 prompt。"""
    from typing import Optional
    from google.genai import types
    from pydantic import BaseModel
    from run_eval_gemini import prep_image

    class Mark(BaseModel):
        mark_id: str
        morphology: str
        description: str
        position_uv: list[float]
        extent_uv: Optional[list[list[float]]] = None
        anchored_to: str
        max_extent_cm: Optional[float] = None
        count_within: int = 1
        size_reference_used: Optional[str] = None
        note: Optional[str] = None

    class UncertainMark(BaseModel):
        mark_id: str
        morphology: str
        description: str
        position_uv: list[float]
        extent_uv: Optional[list[list[float]]] = None
        anchored_to: str
        max_extent_cm: Optional[float] = None

    class GridCell(BaseModel):
        cell: str
        status: str

    class P8Enumeration(BaseModel):
        panel: str
        boundary_note: Optional[str] = None
        marks: list[Mark]
        uncertain_marks: list[UncertainMark]
        readability_grid: list[GridCell]

    resp = client.models.generate_content(
        model=model,
        contents=["照片：",
                  types.Part.from_bytes(data=prep_image(photo_path), mime_type="image/jpeg"),
                  "請依系統指示記錄指定分區的表面狀態。"],
        config=types.GenerateContentConfig(
            system_instruction=P8_TEMPLATE.format(panel=panel, panel_zh=panel_zh),
            response_mime_type="application/json",
            response_schema=P8Enumeration,
            temperature=0,
        ),
    )
    if not resp.parsed:
        raise ValueError("parse failed")
    return {"parsed": resp.parsed.model_dump(), "raw": resp.text}


# ---------- 各步驟 ----------

def step_0(_args):
    rows = [json.loads(l) for l in
            (HERE / "blind_enum_progress_stageA.jsonl").read_text().splitlines()]
    sa = json.loads((HERE / "blind_enum_stageA.json").read_text())
    et = max(s["extent_threshold"] for s in sa.values() if s.get("extent_threshold"))
    ct = max(s["count_threshold"] for s in sa.values())
    out = null_rate_v6(rows, et, ct)
    result = {"thresholds": {"extent_cm": et, "count": ct}, "null_rate_v6": out,
              "v6_clean_flag_rate_for_reference": round(V6_CLEAN_FLAG_RATE, 4)}
    (HERE / "cont_diff_step0.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _marks_of(parsed):
    return parsed.get("marks") or []


def step_a(args):
    cases, pairs = _load_context()
    by_key = {(c["car"], c["angle"]): c for c in cases}
    calls = []
    for key in STAGE_A_CASES:
        c = by_key[key]
        for model in MODELS:
            for rep in range(1, STAGE_A_REPS + 1):
                calls.append({"car": c["car"], "angle": c["angle"], "role": "pickup",
                              "model": model, "rep": rep, "panel": c["panel"],
                              "photo": pairs[key]["pickup"]})
    progress = HERE / "cont_diff_progress_stageA.jsonl"
    if not args.analyze:
        rows = _run_calls(calls, args.workers, args.rpm, progress,
                          call_fn=enumerate_panel_p8)
    else:
        rows = [json.loads(l) for l in progress.read_text().splitlines()]
        rows = [r for r in rows if r.get("parsed")]

    stats = {}
    all_marks = []
    for model in MODELS:
        runs = {}
        for r in rows:
            if r["model"] != model:
                continue
            runs.setdefault((r["car"], r["angle"]), []).append(_marks_of(r["parsed"]))
            all_marks += _marks_of(r["parsed"])
        stats[model] = estimate_sigma(runs)
    # 統一半徑：兩模型較保守（較大）者；延伸門檻同理，缺值退回 v6 的 4.62
    radii = [s["match_radius"] for s in stats.values() if s.get("match_radius")]
    ets = [s["extent_threshold"] for s in stats.values() if s.get("extent_threshold")]
    radius = max(radii) if radii else None
    et = max(ets) if ets else 4.62
    aq = anchor_quality(all_marks)
    nr7 = null_rate_v7(rows, radius, et) if radius else None
    step0 = json.loads((HERE / "cont_diff_step0.json").read_text())
    v6nr = step0["null_rate_v6"]
    mean_ = lambda d: statistics.mean(x["null_rate"] for x in d.values())
    summary = {
        "per_model": stats, "match_radius": radius, "extent_threshold": et,
        "anchor_quality": aq,
        "null_rate_v7": nr7,
        "condition_A_triggered": (radius is None or radius > RADIUS_LIMIT),
        "condition_B_triggered": (nr7 is not None and mean_(nr7) > mean_(v6nr)),
        "condition_E_triggered": (aq["no_anchor_rate"] is not None
                                  and aq["no_anchor_rate"] > ANCHOR_MISSING_LIMIT),
    }
    (HERE / "cont_diff_stageA.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def step_b(args):
    cases, pairs = _load_context()
    calls = []
    for c in cases:
        p = pairs[(c["car"], c["angle"])]
        for model in MODELS:
            for role, photo in (("pickup", p["pickup"]), ("return", p["return"])):
                calls.append({"car": c["car"], "angle": c["angle"], "role": role,
                              "model": model, "rep": 0, "panel": c["panel"], "photo": photo})
    random.Random(43).shuffle(calls)   # 隨機交錯（種子 43，與 v6 的 42 區隔）
    progress = HERE / "cont_diff_progress_stageB.jsonl"
    _run_calls(calls, args.workers, args.rpm, progress, call_fn=enumerate_panel_p8)
    print("v7-B 完成，執行 --step c 產生差分。")


def step_c(_args):
    cases, _ = _load_context()
    sa = json.loads((HERE / "cont_diff_stageA.json").read_text())
    radius, et = sa["match_radius"], sa["extent_threshold"]
    rows = [json.loads(l) for l in
            (HERE / "cont_diff_progress_stageB.jsonl").read_text().splitlines()]
    idx = {}
    for r in rows:
        if r.get("parsed"):
            idx[(r["car"], r["angle"], r["role"], r["model"])] = r["parsed"]

    rel = {(r["car"], r["angle"]): r["relabel"]
           for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}
    per_case, signal_cases = [], []
    all_marks = []
    for c in cases:
        key = (c["car"], c["angle"])
        sigs, missing = {}, []
        for model in MODELS:
            pk, rt = idx.get((*key, "pickup", model)), idx.get((*key, "return", model))
            if not pk or not rt:
                missing.append(model)
                continue
            all_marks += _marks_of(pk) + _marks_of(rt)
            sigs[model] = diff_continuous(pk, rt, radius, et)
        if missing:
            per_case.append({**{k: c[k] for k in ("car", "angle", "panel")},
                             "status": f"missing: {missing}"})
            continue
        final = intersect_continuous(sigs[MODELS[0]]["signals"],
                                     sigs[MODELS[1]]["signals"], radius)
        rec = {**{k: c[k] for k in ("car", "angle", "panel")},
               "relabel": rel.get(key, "?"),
               "final_signals": final,
               "per_model": {m: s for m, s in sigs.items()}}
        per_case.append(rec)
        if final:
            signal_cases.append(rec)

    is_neg_ctrl = lambda r: (r["car"], r["angle"]) == NEGATIVE_CONTROL
    is_target = lambda r: (r["car"], r["angle"]) == TARGET_MISS
    tgt = next((r for r in per_case if is_target(r)), None)
    neg = next((r for r in per_case if is_neg_ctrl(r)), None)
    clean_flags = [r for r in signal_cases
                   if not is_neg_ctrl(r) and r.get("relabel") == "clean"]
    n_clean = sum(1 for r in per_case
                  if not is_neg_ctrl(r) and r.get("relabel") == "clean" and "per_model" in r)
    aq = anchor_quality(all_marks)
    clean_rate = round(len(clean_flags) / n_clean, 4) if n_clean else None
    verdict = {
        "match_radius": radius, "extent_threshold": et,
        "condition_A_triggered": sa["condition_A_triggered"],
        "condition_B_triggered": sa["condition_B_triggered"],
        "condition_C_triggered": bool(tgt and not tgt.get("final_signals")),
        "condition_D": {"clean_flags": [f"{r['car']}{r['angle']}" for r in clean_flags],
                        "clean_flag_rate": clean_rate,
                        "v6_reference": round(V6_CLEAN_FLAG_RATE, 4),
                        "triggered": clean_rate is not None and clean_rate > V6_CLEAN_FLAG_RATE},
        "condition_E_triggered": (aq["no_anchor_rate"] is not None
                                  and aq["no_anchor_rate"] > ANCHOR_MISSING_LIMIT),
        "anchor_quality_stageB": aq,
        "neg_ctrl_signal": bool(neg and neg.get("final_signals")),
        "signal_cases": [f"{r['car']}{r['angle']}({r['relabel']}):{len(r['final_signals'])}"
                         for r in signal_cases],
    }
    (HERE / "cont_diff_result.json").write_text(
        json.dumps({"verdict": verdict, "cases": per_case}, ensure_ascii=False, indent=1))
    print(json.dumps(verdict, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True, choices=["0", "a", "b", "c"])
    ap.add_argument("--analyze", action="store_true", help="step a：只重算不呼叫 API")
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    {"0": step_0, "a": step_a, "b": step_b, "c": step_c}[args.step](args)


if __name__ == "__main__":
    main()
