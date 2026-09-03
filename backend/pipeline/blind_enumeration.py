#!/usr/bin/env python3
"""v6 — 盲列舉差分比對（解 RDH-3092 型「真新損疊在真舊損上」漏檢的第六次嘗試）。

═══════════════════════════════════════════════════════════════════
機制（與 reverse_check 的命題確認本質不同）：
  不給任何主張，對借車照與還車照【分開、各自獨立】跑同一份盲列舉 prompt
  （P7：目標 panel 劃 3×3 網格、中性形態詞、逐格記錄痕跡與可判讀狀態），
  再由程式端差分兩份清單。

  核心假設：同家族模型的一致性幻覺（reverse_check 證實的失敗根因）
  在差分下會自我抵消——幻覺兩邊都出現 → 差分為零；
  真新損只在還車照出現 → 產生格位佔用／延伸／數量訊號。

  負控制組：RCG2235-右後（人工證實不存在、兩模型盲列舉都會「看見」的
  反光片旁刮痕）。它若產生差分訊號＝幻覺不一致＝假設推翻。

三階段：
  Stage A  讀數穩定性標定——5 張借車照 × 5 次重跑 × 2 模型，
           量測格位佔用一致性與 max_extent_cm 變異。
           不做這步，Stage B 的差分無法與讀數抖動區分。
  Stage B  31 筆案件（30 筆「判無新損＋帶既有損主張」＋負控制組）
           借/還各跑一次 × 2 模型，隨機交錯順序。
  Stage C  程式端差分：只比對兩邊皆 clear 的格位；
           訊號＝佔用新增／延伸增加＞門檻／數量增加≥門檻；
           兩模型取交集（目的為高 precision 送審，不是 recall）。

證偽條件（先訂好，任一成立即停，不調 prompt 搶救）：
  A. Stage A 中 >20% readable 格位佔用狀態不一致 → 噪音淹沒訊號，
     連跨家族路線一併排除（問題在單張列舉穩定性，非家族偏誤）
  B. 負控制組 RCG2235-右後 產生新損訊號 → 幻覺不具一致性，假設推翻
  C. RDH-3092 目標格位仍無訊號 → 模型單張內分不出疊加程度差
  D. 31 筆產生 >8 筆訊號 → 送審量超過路線價值

═══════════════════════════════════════════════════════════════════
★ 全量實測結果（2026-08-28，Stage A 50 呼叫＋Stage B 124 呼叫，0 error）：
  四項證偽條件全數未觸發——v6 是六次嘗試中第一個存活的機制。

⚠ 2026-08-30 後記：目標案例 RDH-3092 經 shadow 第二期人工複核＋原圖
  複驗，先改判 uncertain、再經用戶最終定案改判 clean＝無新損（借車照
  同區已可見變形，AI 判無新損為正確；見 shadow_mode.py 檔頭與
  shadow_cards/RDH-3092_*_仲裁證據.jpg）。本檔記錄的機制測試依然成立，
  但「抓回唯一漏檢」的效益主張已撤回——A2 訊號抓到的是視角可見度差，
  且該筆現已確定為 clean，此訊號實為一筆誤旗。
  現行 prompt 對照修正後重標為 100%／0.85%（n=137），本層僅剩結構性價值。
═══════════════════════════════════════════════════════════════════

【Stage A 讀數穩定性（blind_enum_stageA.json，後續任何列舉式方法的噪音基線）】
  flash：佔用不一致率 20.0%（恰在 20% 邊界、未超過）、計數變動 9 格、
         readable 翻面 8 格、extent std 中位數 1.54cm／最大 5.3cm
  pro  ：佔用不一致率 4.8%、extent std 中位數 0.0cm（讀數幾乎完全一致）
  → 門檻：EXTENT=4.62cm（3×1.54，取兩模型較保守者）、COUNT=3
  flash 單獨不夠穩，pro 很穩；跨模型交集是讓 flash 噪音無害化的必要設計。

【Stage C 差分判定（blind_enum_diff.json，格位精確交集＝預先註冊的規則）】
  條件 A 未觸發（如上）
  條件 C 未觸發：RDH-3092 兩模型【各自獨立】指向同一格 A2（佔用＋延伸雙訊號）
    borrow 照 A2 兩模型皆列空；還車照 flash「contour 25cm 反射光帶中斷扭曲＋
    linear 15cm 壓痕」、pro「contour 40cm 大面積起伏＋linear 20cm 平行淺色痕」
    ——唯一漏抓案例被抓回，且是最乾淨的命中形態。
  條件 D 未觸發：30 筆候選中 3 筆訊號（RDH-3092 真損＋RDL7832右前 C2、
    RDW-7085左前 B3 兩筆 clean 誤旗）→ clean 誤旗率 2/28 = 7.1%
  條件 B 的檢驗結果比預期更細緻（重要）：
    - 負控制組的前提本身錯了：RCG2235-右後是 relabel=damage 的真損案
      （還車照那道縱向黑刮痕是真的），它不是「幻覺對照」而是第二個真損。
    - 幻覺一致性的真正答案：reverse_check 時代的「反光片旁幻覺刮痕」在
      P7 網格協議下【沒有出現在該位置】；模型在借車照 B3（保桿下緣轉角）
      穩定看見一個深色痕（Stage A 10 次中 9 次＋Stage B 兩模型皆有），
      而它在借/還兩邊都被列出 → 差分為零 → 一致性感知在差分下確實自我抵消。
    - 真刮痕的訊號兩模型都有冒出（flash B2、pro A2/A3——同一道痕、
      網格配位不同），被格位精確交集丟掉。此案在生產環境無影響：
      現行判定本來就抓到 RCG2235-右後（new_damage_found=true），
      它不會進入本層的候選集合（本層只吃「判無新損＋帶既有損主張」者）。

【相鄰格容忍交集（事後敏感度分析，不採用）】
  改為相鄰格也算交集：真損 2/2 全中，但 clean 誤旗 8/28（28.6%）、
  訊號數 9 > 8 → 觸發條件 D。且屬事後調參。維持預先註冊的格位精確規則。

【生產語意（若接入）】
  本層只跑「判無新損＋帶既有損主張」案件（141 組中 30 筆，21%），
  每案 4 次呼叫（借/還 × 2 模型）。訊號＝送人工複核旗標，不自動改判。
  合併效果：Recall 95.5% → 100%（22/22，RDH-3092 由本層旗標救回）、
  自動判定 FPR 維持 0%（旗標只增加人工工作量：+7.1% 的既有損案送審）。

【誠實限制】
  - n=30 是本資料集該類案件的全體，但絕對數仍小；clean 誤旗率 7.1% 的
    信賴區間很寬。接入前應照 README 規範跑 shadow mode。
  - temperature=0 仍有讀數抖動（Stage A 實測），單次差分非確定性。
  - RDZ-0187（過暗存疑案）兩模型格位多數不可比對 → 無訊號，
    正確地落回 quality_gate 軸，不歸本層管。
  - 對 reverse_check「同家族第二意見不獨立」結論的修正：該結論在
    【命題確認】形態下成立；【盲列舉＋差分】形態下，一致性感知錯誤
    變得無害（自我抵消），不一致的讀數抖動由跨模型交集過濾。
    失敗的不是同家族查核，是「拿主張去問」這個形態。

與規格的兩處刻意偏差（檔案內一致，不影響差分）：
  - WHEEL_DIAMETER_CM 無 per-車型資料 → 模板改為通用註記
    「一般小型車鋁圈直徑約 40 公分（非本車型精確值，僅供粗估）」
  - RFM-2791左前 主張文字推不出 panel → 落回該方位主 panel FB

用法：
  python3 blind_enumeration.py --stage a            # Stage A（50 次呼叫）
  python3 blind_enumeration.py --stage a --analyze  # 只重算 Stage A 統計
  python3 blind_enumeration.py --stage b            # Stage B（124 次呼叫）
  python3 blind_enumeration.py --stage c            # 零 API：差分＋證偽判定
（斷點續跑：blind_enum_progress.jsonl；原始回應文字一併保留）
"""
import argparse
import json
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent

ALL_CELLS = tuple(f"{col}{row}" for col in "ABC" for row in (1, 2, 3))
MORPHOLOGIES = ("linear", "patch", "point", "contour", "discoloration", "edge_gap")
READABLE_STATES = ("clear", "reflection_obscured", "too_dark", "soiled",
                   "out_of_frame", "occluded")

# 門檻由 Stage A 實測決定（--stage c 會從 stage A 統計檔讀取），此為未標定前的哨兵
EXTENT_THRESHOLD_FALLBACK = None
COUNT_THRESHOLD_FALLBACK = None

NEGATIVE_CONTROL = ("RCG2235", "右後")   # 一致性幻覺所在（人工證實借車照乾淨）
TARGET_MISS = ("RDH-3092", "左後")       # 真新損疊真舊損（唯一漏抓）

# Stage A 標定樣本：兩個關鍵案例＋三個不同 panel/方位的一般案例
STAGE_A_CASES = [TARGET_MISS, NEGATIVE_CONTROL,
                 ("RDW-7085", "左前"), ("RDG9853", "左前"), ("RCW1883", "右後")]

MODELS = ("gemini-3.7-flash", "gemini-3.1-pro-preview")
STAGE_A_REPS = 5


# ---------- 純函式（零 API，tests/test_blind_enumeration.py 覆蓋） ----------

def cell_map(panel_result: dict) -> dict:
    """列舉輸出 → {cell: cell_dict}，缺格視為不可比對（out_of_frame）。"""
    m = {c["cell"]: c for c in panel_result.get("cells", []) if c.get("cell") in ALL_CELLS}
    for c in ALL_CELLS:
        m.setdefault(c, {"cell": c, "readable": "out_of_frame", "marks": [],
                         "uncertain_marks": []})
    return m


def comparable_cells(pickup: dict, return_: dict) -> set:
    """只比對兩張照片都 clear 的格位。uncertain_marks 不參與任何差分。"""
    pm, rm = cell_map(pickup), cell_map(return_)
    return {c for c in ALL_CELLS
            if pm[c].get("readable") == "clear" and rm[c].get("readable") == "clear"}


def max_extent(cell: dict):
    """格內 marks 的最大延伸（cm）。無 marks → 0；有 marks 但全無數值 → None（不可量測）。"""
    marks = cell.get("marks") or []
    if not marks:
        return 0.0
    vals = [m["max_extent_cm"] for m in marks if m.get("max_extent_cm") is not None]
    return max(vals) if vals else None


def diff_signals(pickup: dict, return_: dict, extent_threshold, count_threshold) -> dict:
    """單一模型的差分訊號（規格 §3.3）。門檻為 None 時該類訊號停用（未標定）。"""
    pm, rm = cell_map(pickup), cell_map(return_)
    cells = comparable_cells(pickup, return_)
    occupancy, extent, count = set(), set(), set()
    for c in cells:
        n_p, n_r = len(pm[c].get("marks") or []), len(rm[c].get("marks") or [])
        if n_p == 0 and n_r > 0:
            occupancy.add(c)
        if extent_threshold is not None:
            ep, er = max_extent(pm[c]), max_extent(rm[c])
            if ep is not None and er is not None and er - ep > extent_threshold:
                extent.add(c)
        if count_threshold is not None and n_r - n_p >= count_threshold:
            count.add(c)
    return {"comparable": cells, "occupancy": occupancy, "extent": extent,
            "count": count, "any": occupancy | extent | count}


def intersect_models(sig_a: dict, sig_b: dict) -> set:
    """兩模型交集（高 precision 送審，不取聯集）。"""
    return sig_a["any"] & sig_b["any"]


def stage_a_stats(runs_by_case: dict) -> dict:
    """讀數穩定性標定。runs_by_case: {(case_key): [panel_result × N reps]}

    佔用一致性：只在「該格於該次重跑中 readable=clear」的次數 ≥2 時可評估；
    不一致＝clear 次數中有時有 marks 有時無（0 < frac < 1）。
    """
    assessable = inconsistent = 0
    extent_stds, count_varies, readable_flips, cells_seen = [], 0, 0, 0
    detail = []
    for key, reps in runs_by_case.items():
        maps = [cell_map(r) for r in reps]
        for c in ALL_CELLS:
            states = [m[c].get("readable") for m in maps]
            cells_seen += 1
            if len(set(states)) > 1:
                readable_flips += 1
            clear_reps = [m[c] for m, s in zip(maps, states) if s == "clear"]
            if len(clear_reps) < 2:
                continue
            occ = [len(cr.get("marks") or []) > 0 for cr in clear_reps]
            assessable += 1
            frac = sum(occ) / len(occ)
            if 0 < frac < 1:
                inconsistent += 1
            counts = [len(cr.get("marks") or []) for cr in clear_reps]
            if max(counts) - min(counts) >= 1:
                count_varies += 1
            extents = [e for e in (max_extent(cr) for cr in clear_reps)
                       if e is not None and e > 0]
            if len(extents) >= 2:
                extent_stds.append(statistics.stdev(extents))
            detail.append({"case": list(key), "cell": c, "occupied_frac": round(frac, 2),
                           "counts": counts,
                           "extents": [max_extent(cr) for cr in clear_reps]})
    med_std = round(statistics.median(extent_stds), 2) if extent_stds else None
    return {
        "assessable_cells": assessable,
        "occupancy_inconsistent": inconsistent,
        "occupancy_inconsistent_rate": round(inconsistent / assessable, 4) if assessable else None,
        "count_varying_cells": count_varies,
        "readable_flip_cells": readable_flips,
        "cells_total": cells_seen,
        "extent_std_median": med_std,
        "extent_std_max": round(max(extent_stds), 2) if extent_stds else None,
        "extent_threshold": round(3 * med_std, 2) if med_std else None,
        "count_threshold": 3 if count_varies else 2,
        "condition_A_triggered": (inconsistent / assessable > 0.20) if assessable else None,
        "cells_detail": detail,
    }


# ---------- P7 prompt ----------

P7_TEMPLATE = """你是車輛表面狀態的記錄員。

你的任務不是判斷損傷、不是評估責任、不是估算費用。
你的任務是把指定區域內所有可見的表面痕跡，盡可能完整地記錄下來，
包含你不確定是什麼的痕跡。

【記錄原則】
1. 只記錄你實際看到的視覺特徵。不要推測成因，不要下損傷判定。
2. 使用中性的形態描述，不要使用「刮痕」「凹陷」「損壞」這類判定性詞彙。
3. 不確定的痕跡也要記錄，放進 uncertain_marks，不要略過。
4. 若某格因反光、遮擋、過暗、髒汙而無法判讀，如實標記，不要推測其內容。

【目標區域】
分區：{panel}（{panel_zh}）

【網格定義】
請將此分區劃分為 3×3 共 9 格：
  水平方向（靠車頭側 → 靠車尾側）：A / B / C
  垂直方向（上緣 → 下緣）：1 / 2 / 3
  格位標示為 A1、A2、A3、B1 … C3

判斷格位時，以該分區的實際邊界（鈑件接縫、輪拱線、窗框下緣）
為劃分基準，不要以整張照片的邊界為基準。

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
- 同一格內、方向相近、間距小於自身長度的多道平行線狀痕跡，
  記為「1 個 linear 痕跡」，並在 note 中說明包含幾道
- 同一格內分散的多個點狀痕跡，記為「1 個 point 痕跡」，
  並在 count_within 中給出數量
- 跨越兩格以上的單一痕跡，記在它佔面積最大的那一格，
  並在 spans_cells 中列出所有跨越的格位

【尺寸基準】
使用畫面中的已知尺寸物件作為比例尺：
1. 車牌：台灣小型車車牌實際尺寸為 32.0 × 15.0 公分
2. 輪圈：一般小型車鋁圈直徑約 40 公分（非本車型精確值，僅供粗估）

在 size_reference_used 中說明採用了哪個基準。
若畫面中無可用基準，max_extent_cm 給 null，不要憑印象估算。

【格位判讀狀態】
每一格都必須給出 readable 狀態，即使該格沒有任何痕跡：
  clear                可完整判讀
  reflection_obscured  被反光覆蓋，超過三分之一面積無法判讀
  too_dark             暗部細節遺失
  soiled               被泥沙或灰塵覆蓋，可能遮蔽表面狀態
  out_of_frame         未入鏡或僅邊緣入鏡
  occluded             被其他物體遮擋

這個欄位會決定該格是否納入後續比對，請誠實填寫。
寧可標為不可判讀，不要勉強給出內容。

所有 9 格都必須出現在 cells 陣列中，即使該格無痕跡（marks 給空陣列）。"""


def build_prompt(panel: str, panel_zh: str) -> str:
    return P7_TEMPLATE.format(panel=panel, panel_zh=panel_zh)


# ---------- API ----------

def enumerate_panel(client, model: str, photo_path: str, panel: str, panel_zh: str) -> dict:
    """單張照片的盲列舉。不提供借/還身分、不提供任何主張（規格 §3.1 約束 1/2）。"""
    from typing import Optional
    from google.genai import types
    from pydantic import BaseModel, Field
    from run_eval_gemini import prep_image

    class Mark(BaseModel):
        mark_id: str
        morphology: str = Field(description="linear|patch|point|contour|discoloration|edge_gap")
        description: str
        position_in_cell: str
        max_extent_cm: Optional[float] = None
        count_within: int = 1
        spans_cells: list[str] = []
        size_reference_used: Optional[str] = None
        note: Optional[str] = None

    class UncertainMark(BaseModel):
        mark_id: str
        morphology: str
        description: str
        position_in_cell: str
        max_extent_cm: Optional[float] = None

    class Cell(BaseModel):
        cell: str
        readable: str = Field(description="clear|reflection_obscured|too_dark|soiled|out_of_frame|occluded")
        readable_note: Optional[str] = None
        marks: list[Mark]
        uncertain_marks: list[UncertainMark]

    class PanelEnumeration(BaseModel):
        panel: str
        cells: list[Cell]
        overall_notes: Optional[str] = None

    resp = client.models.generate_content(
        model=model,
        contents=["照片：",
                  types.Part.from_bytes(data=prep_image(photo_path), mime_type="image/jpeg"),
                  "請依系統指示記錄指定分區的表面狀態。"],
        config=types.GenerateContentConfig(
            system_instruction=build_prompt(panel, PANEL_ZH_CACHE.get(panel, panel)),
            response_mime_type="application/json",
            response_schema=PanelEnumeration,
            temperature=0,
        ),
    )
    if not resp.parsed:
        raise ValueError("parse failed")
    return {"parsed": resp.parsed.model_dump(), "raw": resp.text}


PANEL_ZH_CACHE: dict = {}


def _load_context():
    """候選案件、panel 映射、照片路徑。"""
    from taxonomy import PANEL_ZH
    from diff_new_damage import panel_of
    from reverse_check import select_candidates
    from results_config import FINAL_RESULTS
    PANEL_ZH_CACHE.update(PANEL_ZH)

    results = json.loads(FINAL_RESULTS.read_text())["results"]
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}

    cases = []
    for c in select_candidates(results):
        panel = panel_of({"location": c["claim"]}, c["angle"])
        if panel is None:  # RFM-2791左前：主張模糊 → 該方位主 panel（刻意偏差，見檔頭）
            panel = "FB" if "前" in c["angle"] else "RB"
        cases.append({"car": c["car"], "angle": c["angle"], "panel": panel,
                      "claim": c["claim"]})
    # 負控制組：一致性幻覺所在（現行判其有新損，不在候選內，依規格明確加入）
    cases.append({"car": NEGATIVE_CONTROL[0], "angle": NEGATIVE_CONTROL[1], "panel": "RB",
                  "claim": "(負控制組：v4 杜撰主張／盲列舉幻覺位置，人工證實借車照乾淨)"})
    return cases, pairs


def _run_calls(calls: list, workers: int, rpm: int, progress_path: Path, call_fn=None):
    """calls: [{key..., photo, panel}]；斷點續跑＋節流＋原始回應保留。
    call_fn(client, model, photo, panel, panel_zh) 預設為本模組的 enumerate_panel；
    v7（continuous_diff.py）傳入自己的 P8 版本沿用同一套骨架。"""
    from google.genai import errors
    from run_eval_gemini import get_client, Throttle
    call_fn = call_fn or enumerate_panel

    done = {}
    if progress_path.exists():
        for line in progress_path.read_text().splitlines():
            r = json.loads(line)
            if r.get("parsed"):
                done[(r["car"], r["angle"], r["role"], r["model"], r["rep"])] = r
    todo = [c for c in calls
            if (c["car"], c["angle"], c["role"], c["model"], c["rep"]) not in done]
    print(f"呼叫 {len(calls)} 次（已完成 {len(done)}，剩 {len(todo)}），"
          f"預估至少 {len(todo) / rpm:.0f} 分鐘")

    client = get_client()
    throttle = Throttle(rpm)
    plock = threading.Lock()

    def one(c):
        for i in range(4):
            throttle.wait()
            try:
                out = call_fn(client, c["model"], c["photo"], c["panel"],
                              PANEL_ZH_CACHE.get(c["panel"], c["panel"]))
                return {**{k: c[k] for k in ("car", "angle", "role", "model", "rep", "panel")},
                        **out}
            except errors.APIError as e:
                if e.code in (429, 500, 503):
                    time.sleep(20 * (i + 1))
                    continue
                return {**{k: c[k] for k in ("car", "angle", "role", "model", "rep", "panel")},
                        "error": f"{e.code}: {str(e)[:120]}"}
            except Exception as e:
                return {**{k: c[k] for k in ("car", "angle", "role", "model", "rep", "panel")},
                        "error": str(e)[:120]}
        return {**{k: c[k] for k in ("car", "angle", "role", "model", "rep", "panel")},
                "error": "retries exhausted"}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, c) for c in todo]
        for i, fut in enumerate(as_completed(futs)):
            r = fut.result()
            with plock, progress_path.open("a") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n_marks = 0 if r.get("error") else (
                sum(len(c.get("marks") or []) for c in r["parsed"]["cells"])
                if "cells" in r["parsed"] else len(r["parsed"].get("marks") or []))
            mark = ("ERROR " + r["error"][:40]) if r.get("error") else f"{n_marks} marks"
            print(f"  [{i+1:3d}/{len(todo)}] {r['car']:9s} {r['angle']:3s} "
                  f"{r['role']:6s} rep{r['rep']} {r['model'].split('-')[1][:5]:5s} → {mark}", flush=True)
    dedup = {}
    for line in progress_path.read_text().splitlines():
        r = json.loads(line)
        if r.get("parsed"):
            dedup[(r["car"], r["angle"], r["role"], r["model"], r["rep"])] = r
    return list(dedup.values())


def run_stage_a(args):
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
    progress = HERE / "blind_enum_progress_stageA.jsonl"
    if not args.analyze:
        rows = _run_calls(calls, args.workers, args.rpm, progress)
    else:
        rows = [json.loads(l) for l in progress.read_text().splitlines()]
        rows = [r for r in rows if r.get("parsed")]

    stats = {}
    for model in MODELS:
        runs = {}
        for r in rows:
            if r["model"] != model:
                continue
            runs.setdefault((r["car"], r["angle"]), []).append(r["parsed"])
        stats[model] = stage_a_stats(runs)
    out = HERE / "blind_enum_stageA.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=1))
    for model, s in stats.items():
        brief = {k: v for k, v in s.items() if k != "cells_detail"}
        print(f"\n{model}:\n" + json.dumps(brief, ensure_ascii=False, indent=2))
    return stats


def run_stage_b(args):
    cases, pairs = _load_context()
    calls = []
    for c in cases:
        p = pairs[(c["car"], c["angle"])]
        for model in MODELS:
            for role, photo in (("pickup", p["pickup"]), ("return", p["return"])):
                calls.append({"car": c["car"], "angle": c["angle"], "role": role,
                              "model": model, "rep": 0, "panel": c["panel"], "photo": photo})
    random.Random(42).shuffle(calls)   # 隨機交錯借/還順序（可重現；規格 §3.2）
    progress = HERE / "blind_enum_progress_stageB.jsonl"
    _run_calls(calls, args.workers, args.rpm, progress)
    print("Stage B 完成，執行 --stage c 產生差分。")


def run_stage_c(_args):
    cases, _ = _load_context()
    sa_path = HERE / "blind_enum_stageA.json"
    sa = json.loads(sa_path.read_text()) if sa_path.exists() else {}
    # 門檻取兩模型中較保守（較大）者；未標定則停用該訊號
    et = [s["extent_threshold"] for s in sa.values() if s.get("extent_threshold")]
    ct = [s["count_threshold"] for s in sa.values() if s.get("count_threshold")]
    extent_threshold = max(et) if et else EXTENT_THRESHOLD_FALLBACK
    count_threshold = max(ct) if ct else COUNT_THRESHOLD_FALLBACK

    rows = [json.loads(l) for l in (HERE / "blind_enum_progress_stageB.jsonl").read_text().splitlines()]
    idx = {}
    for r in rows:
        if r.get("parsed"):
            idx[(r["car"], r["angle"], r["role"], r["model"])] = r["parsed"]

    per_case, signal_cases = [], []
    for c in cases:
        key = (c["car"], c["angle"])
        sigs, missing = {}, []
        for model in MODELS:
            pk, rt = idx.get((*key, "pickup", model)), idx.get((*key, "return", model))
            if not pk or not rt:
                missing.append(model)
                continue
            sigs[model] = diff_signals(pk, rt, extent_threshold, count_threshold)
        if missing:
            per_case.append({**{k: c[k] for k in ("car", "angle", "panel")},
                             "status": f"missing: {missing}"})
            continue
        final = intersect_models(*[sigs[m] for m in MODELS])
        rec = {**{k: c[k] for k in ("car", "angle", "panel")},
               "final_signal_cells": sorted(final),
               "per_model": {m: {k: sorted(v) for k, v in s.items()}
                             for m, s in sigs.items()}}
        per_case.append(rec)
        if final:
            signal_cases.append(rec)

    is_neg_ctrl = lambda r: (r["car"], r["angle"]) == NEGATIVE_CONTROL
    is_target = lambda r: (r["car"], r["angle"]) == TARGET_MISS
    neg = next((r for r in per_case if is_neg_ctrl(r)), None)
    tgt = next((r for r in per_case if is_target(r)), None)
    n_signals_ex_ctrl = sum(1 for r in signal_cases if not is_neg_ctrl(r))
    verdict = {
        "thresholds": {"extent_cm": extent_threshold, "count": count_threshold},
        "condition_A": {m: s.get("condition_A_triggered") for m, s in sa.items()},
        "condition_B_neg_ctrl_signal": bool(neg and neg.get("final_signal_cells")),
        "condition_C_target_no_signal": bool(tgt and not tgt.get("final_signal_cells")),
        "condition_D_signal_count": n_signals_ex_ctrl,
        "condition_D_triggered": n_signals_ex_ctrl > 8,
        "signal_cases": [f"{r['car']}{r['angle']}:{','.join(r['final_signal_cells'])}"
                         for r in signal_cases],
    }
    out = HERE / "blind_enum_diff.json"
    out.write_text(json.dumps({"verdict": verdict, "cases": per_case},
                              ensure_ascii=False, indent=1))
    print(json.dumps(verdict, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True, choices=["a", "b", "c"])
    ap.add_argument("--analyze", action="store_true", help="stage a：只重算統計不呼叫 API")
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    {"a": run_stage_a, "b": run_stage_b, "c": run_stage_c}[args.stage](args)


if __name__ == "__main__":
    main()
