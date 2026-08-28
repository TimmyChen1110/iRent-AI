#!/usr/bin/env python3
"""v6 Shadow Mode — 執行協定落地（不改變任何自動判定，量測訊號實用價值）。

═══════════════════════════════════════════════════════════════════
凍結清單（依協定 §0，shadow 期間任何一項變動即量測失效）：
  P7 prompt 逐字不動（blind_enumeration.P7_TEMPLATE）
  差分門檻 EXTENT 4.62 / COUNT 3 不動
  交集規則維持格位相等
  results_config.py 不碰
  anchored_to 不加進 P7（v7 唯一有效設計，但屬 prompt 變更，須另行驗證）
═══════════════════════════════════════════════════════════════════

模組內容對應協定章節：
  §1 Step 0′  雙穩態盛行率（零 API，用 v6 Stage A 現成 50 次讀數）
  §2 P9       訊號複核說明卡（純文字輸入，不給照片——v5 教訓）
              裁切圖：panel 在原圖中的 bbox 從未定位過，純幾何裁切
              不可行 → 降級為借/還原圖並排（PIL 合成，零模型），
              定位靠 P9 的 where_to_look。已記錄為已知缺口。
  §3 防錨定   20% 盲測分流（signal_id 雜湊決定，可重現）
  §4 記錄欄位 shadow_signals.jsonl（系統端欄位齊；複核回填欄位留空）
  §5 歸因     wrong_area 三類歸因規則寫在 attribute_wrong_area()
  §6 分期     第一期＝對全部 119 筆「判無新損」案跑訊號率
              （30 筆篩選子集的資料直接重用，僅新增 89 案 356 呼叫）
  §7 判準     接入判準與停止條件程式化（acceptance_verdict / check_stop）

═══════════════════════════════════════════════════════════════════
★ Step 0′ ＋ 第一期實測結果（2026-08-28，356 呼叫 0 error）
═══════════════════════════════════════════════════════════════════

【Step 0′ 雙穩態盛行率（shadow_step0p.json）——與空轉率並列的永久基線】
  flash 80%（4/5 照片）、pro 40%（2/5）——超過協定「過半」門檻，
  §5 歸因欄位為必要配備，shadow 的無法歸因假訊號應優先對照此基線。
  度量註記：佔用集合很小（0–1 格）時 Jaccard 是二值的，「單一痕跡
  佔用閃爍」與「整組狀態翻面」（RCW1883 型）會被同一指標捕捉；
  與 v6 Stage A 佔用不一致率（flash 20%/格）互為印證——閃爍主要
  發生在單格層級。

【第一期實際訊號率（shadow_phase1_summary.json）】
  母體＝全部 119 筆「判無新損」案（30 筆重用 v6 資料、新增 89 案）。
  派送（交集）訊號：3 筆——與 30 筆子集完全相同（RDH-3092 真損＋
  RDL7832右前、RDW-7085左前 兩筆已知誤旗）。
  ★ 89 筆無主張案件零新增交集訊號。
  案件訊號率 2.52% vs 子集推估 10% → 推估偏差係數 0.25×——
  協定擔心「可能高出數倍」，實測方向相反：帶既有損主張的案件
  本來就是視覺最忙的鈑面，無主張案件安靜得多。
  用小樣本推估流量時，此係數是「篩選後子集→全流量」的實測校正值。
  聯集端印證空轉基線：單模型訊號 86 筆（flash_only 25／pro_only 61），
  交集濾掉 97%（86/89）。pro_only 遠多於 flash_only——pro 列舉的
  痕跡多而細，交集是把它壓住的機制。
  盲測分流：3 筆派送恰好全落標準流程（雜湊機率 51%，n=3 正常）；
  盲測子集要等訊號累積才有資料。

【已知缺口】
  裁切圖降級為借/還全圖並排：panel 在原圖中的 bbox 從未定位，
  純幾何裁切無從算起；定位靠 P9 的 where_to_look 文字。
  若日後需要真裁切，需先解 panel 定位（quality_gate 軸的工作）。

【第二期煙霧測試結果（2026-08-29，複核者＝用戶本人，n=3）】
  三筆派送訊號全數判 no_damage：確認率 0%、wrong_area 0%、
  耗時中位數 25.3 秒 → 判準落 do_not_integrate 檔。
  ★ 但 n=3 遠低於協定門檻（40 筆或 4 週），此為機制煙霧測試，
    不是正式裁決；正式資料要靠監理台現場實測累積。
  複核過程紀錄：按鍵誤按依複核者文字更正（協定「以文字為準」）；
  首筆耗時 433 秒含摸索工具時間已註記；紅框指引圖（*_看這裡.jpg）
  為手動標註的流程偏離，已記錄。

  ★★ 重大發現：複核者判 RDH-3092「兩邊都有凹痕」，與 relabels.json
  （「借車照可見部分平整、視角半遮」）矛盾。原圖（720×1280）放大
  裁切複驗（scratchpad rdh_*_zoom.jpg，已另存證據）支持複核者：
  借車照油箱蓋左下／門縫一帶【可見鈑面變形與反射扭曲，非平整】；
  還車照的差異是凹陷區多了輪拱上方的白色擦痕。
  → 含義鏈（若 RDH-3092 改判 uncertain/既有）：
    ①現行 prompt 的「既有凹陷與板金變形」可能一直是對的（非漏抓）
    ②reverse_check 對它回 visible 也是對的（非失敗）
    ③v6「抓回唯一漏檢」的頭條主張失去依據——v6 的 A2 訊號抓到的
      是「視角造成的可見度差」而非「新損」；本資料集上 v6 的
      已證實效益歸零，僅存結構性價值（差異送審機制）
    ④現行 prompt 對照人工重標的 Recall 由 95.5%（21/22）變 100%（21/21）
  → 【2026-08-29 定案（用戶決定）】RDH-3092 已改判 uncertain：
    relabels.json 已註記＋指向證據；現行 prompt 對照重標為
    n=137、Recall 21/21=100%、FPR 0%（relabeled_metrics.json 含歷史值）；
    v6 頭條主張已在 README 撤回，活文件（成果摘要／簡報／開工須知／
    training 對照）全數改為新口徑，歷史 A/B 表保留原口徑並加註。

用法：
  python3 shadow_mode.py --step 0p       # 零 API：雙穩態盛行率
  python3 shadow_mode.py --step phase1   # 89 新案 × 4 呼叫（30 案重用 v6 資料）
  python3 shadow_mode.py --step signals  # 零 API：差分＋訊號記錄（聯集記錄、交集派送）
  python3 shadow_mode.py --step cards    # 派送訊號的 P9 說明卡＋並排圖
  python3 shadow_mode.py --step report   # 零 API：現況統計＋判準試算
"""
import argparse
import hashlib
import itertools
import json
import statistics
from pathlib import Path

from blind_enumeration import (ALL_CELLS, MODELS, PANEL_ZH_CACHE, _run_calls,
                               cell_map, diff_signals, max_extent)

HERE = Path(__file__).resolve().parent

EXTENT_THRESHOLD = 4.62   # 凍結
COUNT_THRESHOLD = 3       # 凍結
BLIND_RATIO = 0.20

SIGNALS_PATH = HERE / "shadow_signals.jsonl"
CARDS_DIR = HERE / "shadow_cards"

# Step 0′ 分群門檻（預先註冊）：距離 <0.2 視為同狀態、>0.5 視為顯著不同
DIST_LOW, DIST_HIGH = 0.2, 0.5


# ---------- §1 Step 0′：雙穩態盛行率（純函式） ----------

def occupied_cells(panel_result: dict) -> frozenset:
    m = cell_map(panel_result)
    return frozenset(c for c in ALL_CELLS if m[c].get("marks"))


def enumeration_distance(a: dict, b: dict) -> float:
    """兩次列舉的距離：格位佔用集合的 Jaccard 距離。皆空＝0。"""
    sa, sb = occupied_cells(a), occupied_cells(b)
    if not sa and not sb:
        return 0.0
    return 1 - len(sa & sb) / len(sa | sb)


def classify_stability(dists: list) -> str:
    """單穩態：全部低。雙穩態：低群＋高群、中間空白。不穩定：中間有值。"""
    if all(d < DIST_LOW for d in dists):
        return "monostable"
    mid = [d for d in dists if DIST_LOW <= d <= DIST_HIGH]
    low = [d for d in dists if d < DIST_LOW]
    high = [d for d in dists if d > DIST_HIGH]
    if not mid and low and high:
        return "bimodal"
    return "unstable"


def bimodality_prevalence(rows: list) -> dict:
    """rows：v6 Stage A progress。每（照片, 模型）10 對距離 → 分類。"""
    out = {}
    for model in MODELS:
        by_case = {}
        for r in rows:
            if r.get("parsed") and r["model"] == model:
                by_case.setdefault((r["car"], r["angle"]), []).append(r["parsed"])
        photos = {}
        for key, reps in by_case.items():
            dists = [round(enumeration_distance(a, b), 3)
                     for a, b in itertools.combinations(reps, 2)]
            photos["".join(key)] = {"distances": sorted(dists),
                                    "class": classify_stability(dists)}
        n = len(photos)
        out[model] = {
            "photos": photos,
            "bimodal": sum(1 for p in photos.values() if p["class"] == "bimodal"),
            "unstable": sum(1 for p in photos.values() if p["class"] == "unstable"),
            "monostable": sum(1 for p in photos.values() if p["class"] == "monostable"),
            "bimodal_rate": round(sum(1 for p in photos.values()
                                      if p["class"] == "bimodal") / n, 3) if n else None,
        }
    return out


# ---------- §6 第一期：母體與訊號 ----------

def phase1_population(results: list, panel_of_fn) -> list:
    """本層的真實流量＝全部「判無新損」案件（帶不帶既有損主張都算）。

    目標 panel：有主張者由主張文字推（與 v6 一致）；
    無主張者退回方位主 panel（前→FB、後→RB，預先註冊）。
    """
    out = []
    for r in results:
        a = r.get("assessment")
        if not a or a.get("new_damage_found"):
            continue
        notes = (a.get("pre_existing_notes") or "").strip()
        panel = panel_of_fn({"location": notes}, r["angle"]) if notes else None
        if panel is None:
            panel = "FB" if "前" in r["angle"] else "RB"
        out.append({"car": r["car"], "angle": r["angle"], "panel": panel,
                    "claim": notes, "angle_match": a.get("angle_match", True)})
    return out


def signal_records_for_case(case: dict, per_model_parsed: dict, relabel: str) -> list:
    """單案 → 訊號記錄（協定 §4 系統端欄位）。聯集記錄、交集標派送。

    granularity：一格一筆記錄（signal_cells 恆為單格；跨格情境由
    adjacent_cell_has_marks 與 P9 的相鄰格段落承接）。
    """
    sigs = {m: diff_signals(per_model_parsed[m]["pickup"], per_model_parsed[m]["return"],
                            EXTENT_THRESHOLD, COUNT_THRESHOLD) for m in MODELS}
    flash, pro = sigs[MODELS[0]], sigs[MODELS[1]]
    records = []
    for cell in sorted(flash["any"] | pro["any"]):
        in_f, in_p = cell in flash["any"], cell in pro["any"]
        agreement = "both" if in_f and in_p else ("flash_only" if in_f else "pro_only")
        types = []
        for kind, mapped in (("occupancy", "unmatched_mark"),
                             ("extent", "extent_increase"), ("count", "count_increase")):
            if any(cell in sigs[m][kind] for m in MODELS):
                types.append(mapped)
        deltas, pk_counts, rt_counts = [], {}, {}
        for m in MODELS:
            pm = cell_map(per_model_parsed[m]["pickup"])[cell]
            rm = cell_map(per_model_parsed[m]["return"])[cell]
            pk_counts[m] = len(pm.get("marks") or [])
            rt_counts[m] = len(rm.get("marks") or [])
            ep, er = max_extent(pm), max_extent(rm)
            if ep is not None and er is not None:
                deltas.append(er - ep)
        adjacent = _adjacent_cells(cell)
        adj_marks = any(cell_map(per_model_parsed[m][role])[c].get("marks")
                        for m in MODELS for role in ("pickup", "return")
                        for c in adjacent)
        sid = f"{case['car']}{case['angle']}-{cell}"
        records.append({
            "signal_id": sid,
            "case_id": f"{case['car']}{case['angle']}",
            "panel": case["panel"],
            "signal_cells": [cell],
            "signal_type": types[0] if types else None,
            "signal_types_all": types,
            "model_agreement": agreement,
            "extent_delta_cm": round(max(deltas), 2) if deltas else None,
            "pickup_cell_mark_count": pk_counts,
            "return_cell_mark_count": rt_counts,
            "adjacent_cell_has_marks": bool(adj_marks),
            "review_flow": "blind" if is_blind(sid) else "standard",
            "dispatched": agreement == "both",
            "relabel_ground_truth": relabel,   # shadow 分析用；正式部署無此欄
            # ---- 複核回填（第二期，由人填寫）----
            "review_verdict": None,
            "review_position_match": None,
            "review_duration_sec": None,
            "review_free_text": None,
            "blind_pre_verdict": None,
            "blind_changed_after_card": None,
        })
    return records


def _adjacent_cells(cell: str) -> list:
    c, r = ord(cell[0]) - 65, int(cell[1])
    out = []
    for dc in (-1, 0, 1):
        for dr in (-1, 0, 1):
            if dc == dr == 0:
                continue
            nc, nr = c + dc, r + dr
            if 0 <= nc <= 2 and 1 <= nr <= 3:
                out.append(f"{'ABC'[nc]}{nr}")
    return out


# ---------- §3 防錨定分流 ----------

def is_blind(signal_id: str) -> bool:
    """20% 盲測，signal_id 雜湊決定——可重現、與案件難度無關。"""
    h = int(hashlib.sha256(signal_id.encode()).hexdigest(), 16)
    return (h % 100) < BLIND_RATIO * 100


# ---------- §5 wrong_area 歸因 ----------

WRONG_AREA_RULES = [
    ("boundary_error", ("隔壁", "相鄰", "旁邊那格", "邊界")),
    ("bistable_flip", ("別的地方", "其他位置", "另一處", "完全不同")),
    ("match_failure", ("借車照也有", "本來就有", "兩張都有")),
]


def attribute_wrong_area(free_text: str) -> str:
    """依協定 §5 用複核者描述分類。對不上任何規則 → unattributed（人工歸因）。"""
    t = free_text or ""
    for label, kws in WRONG_AREA_RULES:
        if any(k in t for k in kws):
            return label
    return "unattributed"


# ---------- §6 停止條件、§7 接入判準（純函式） ----------

def check_stop(records: list, daily_capacity: int = None,
               daily_signal_count: int = None) -> list:
    """回傳被觸發的停止條件清單（空＝繼續）。只看已回填複核的記錄。"""
    done = [r for r in records if r.get("review_verdict")]
    triggered = []
    if daily_capacity is not None and daily_signal_count is not None \
            and daily_signal_count > daily_capacity:
        triggered.append("daily_volume_exceeded")
    wa = [r for r in done if r.get("review_position_match") == "wrong_area"]
    if done and len(wa) / len(done) > 0.30:
        triggered.append("wrong_area_over_30pct")
    tail = [r.get("review_verdict") for r in done[-10:]]
    if len(tail) == 10 and all(v == "no_damage" for v in tail):
        triggered.append("ten_consecutive_no_damage")
    blind = [r for r in done if r.get("review_flow") == "blind"
             and r.get("blind_pre_verdict") == "no_damage"]
    flipped = [r for r in blind if r.get("review_verdict") == "confirmed_damage"
               and r.get("blind_changed_after_card")]
    if blind and len(flipped) / len(blind) > 0.40:
        triggered.append("card_over_persuasive")
    return triggered


def acceptance_verdict(records: list) -> dict:
    """協定 §7 三檔判準。只算已回填且曾派送（交集）的記錄。"""
    done = [r for r in records if r.get("dispatched") and r.get("review_verdict")]
    if not done:
        return {"decision": "insufficient_data", "n": 0}
    n = len(done)
    conf = sum(1 for r in done if r["review_verdict"] == "confirmed_damage") / n
    wa = sum(1 for r in done if r.get("review_position_match") == "wrong_area") / n
    durs = [r["review_duration_sec"] for r in done if r.get("review_duration_sec") is not None]
    med = statistics.median(durs) if durs else None
    stats = {"n": n, "confirmed_rate": round(conf, 3), "wrong_area_rate": round(wa, 3),
             "duration_median_sec": med}
    if conf < 0.10 or wa > 0.30 or (med is not None and med > 150):
        return {**stats, "decision": "do_not_integrate"}
    if conf >= 0.25 and wa <= 0.15 and med is not None and med <= 90:
        return {**stats, "decision": "integrate"}
    if 0.10 <= conf < 0.25 and med is not None and med <= 60:
        return {**stats, "decision": "integrate_low_priority"}
    return {**stats, "decision": "inconclusive_extend_shadow"}


def intersect_vs_union(records: list) -> dict:
    """交集 vs 聯集 precision 與交集漏掉的真訊號（需複核回填後才有意義）。"""
    done = [r for r in records if r.get("review_verdict")]
    conf = lambda rs: sum(1 for r in rs if r["review_verdict"] == "confirmed_damage")
    both = [r for r in done if r["model_agreement"] == "both"]
    single = [r for r in done if r["model_agreement"] != "both"]
    missed = conf(single)
    return {
        "intersection": {"n": len(both), "confirmed": conf(both),
                         "precision": round(conf(both) / len(both), 3) if both else None},
        "union": {"n": len(done), "confirmed": conf(done),
                  "precision": round(conf(done) / len(done), 3) if done else None},
        "missed_by_intersection": missed,
        "layering_recommended": bool(both) and missed >= conf(both),
    }


# ---------- §2 P9 說明卡 ----------

P9_TEMPLATE = """你要把一組車輛表面痕跡的比對結果，整理成供人工複核使用的說明卡。

【你的職責邊界】
你收到的是兩份已完成的表面痕跡記錄，以及系統計算出的差異。
你的任務只有一件事：把這些資料整理成複核人員能快速理解的文字。

你不得做以下任何一件事：
- 判斷這是不是真的損傷
- 推測痕跡的成因或類型（不要說「刮痕」「凹陷」「碰撞」）
- 評估嚴重程度或修理費用
- 加入資料中沒有的任何內容
- 表達你對這個差異是否成立的看法

若資料本身不完整或互相矛盾，如實指出，不要自行補齊。

【撰寫要求】
說明卡分三段：

第一段「看哪裡」
用記錄中的 position_in_cell 與 description 原文，描述複核者該把注意力
放在畫面的哪個位置。若記錄中提到可辨識的參照物，優先使用。
若記錄未提供足夠的定位資訊，明說「記錄未提供精確位置」。

第二段「差在哪」
並列借車照與還車照該格的記錄內容。
若是 unmatched_mark 型訊號，說明還車照多了什麼、借車照該格的內容為何。
若是 extent_increase 型訊號，說明兩邊的延伸讀數各是多少。
使用記錄的原始描述文字，不要改寫成判定性語言。

第三段「注意事項」
列出可能影響複核的因素，僅限資料中可見者：
- 該格在任一張照片的判讀狀態不是 clear
- 相鄰格位有形態相近的記錄（可能是同一道痕跡的跨格延伸）
- 兩個模型的記錄描述有明顯出入
- 借車照該格原本就有多筆記錄（疊加情境，較難判斷）
若無上述任何一項，此段寫「無」。

【語氣】
中性、描述性。使用「記錄顯示」「還車照的記錄中出現」這類措辭，
不要使用「發現了」「新增了損傷」這類已下結論的措辭。

data_gaps 用於記錄輸入資料本身的缺漏或矛盾，例如某個必要欄位為 null、
兩個模型的記錄無法對應。若無則給空陣列。
reviewer_note 一律為：「本卡片為系統偵測到的待驗證差異，非判定結果。請依實際照片判斷。」"""


def build_p9_payload(record: dict, per_model_parsed: dict) -> str:
    """訊號記錄 → P9 的結構化輸入文字。只給結構化資料，不給照片。"""
    cell = record["signal_cells"][0]

    def cell_text(role):
        parts = []
        for m in MODELS:
            cm = cell_map(per_model_parsed[m][role])[cell]
            tag = m.split("-")[1]
            if not cm.get("marks"):
                parts.append(f"[{tag}] （無記錄）")
            for mk in cm.get("marks") or []:
                parts.append(f"[{tag}] {mk.get('morphology')}｜位置：{mk.get('position_in_cell')}｜"
                             f"延伸：{mk.get('max_extent_cm')}cm｜描述：{mk.get('description')}")
        return "\n".join(parts)

    def readable(role):
        return " / ".join(f"{m.split('-')[1]}:{cell_map(per_model_parsed[m][role])[cell].get('readable')}"
                          for m in MODELS)

    adj_lines = []
    for c in _adjacent_cells(cell):
        for role in ("pickup", "return"):
            for m in MODELS:
                for mk in cell_map(per_model_parsed[m][role])[c].get("marks") or []:
                    adj_lines.append(f"{c}（{'借' if role == 'pickup' else '還'}車照，"
                                     f"{m.split('-')[1]}）：{mk.get('morphology')}｜{mk.get('description')}")
    return f"""【輸入資料】
分區：{record['panel']}（{PANEL_ZH_CACHE.get(record['panel'], record['panel'])}）
訊號格位：{cell}
訊號類型：{'、'.join(record['signal_types_all'])}
模型一致性：{record['model_agreement']}

借車照該格記錄：
{cell_text('pickup')}

還車照該格記錄：
{cell_text('return')}

該格判讀狀態：借車 {readable('pickup')} ／ 還車 {readable('return')}

相鄰格位記錄（供複核者判斷是否為跨格痕跡）：
{chr(10).join(adj_lines) if adj_lines else '（相鄰格位皆無記錄）'}

signal_id：{record['signal_id']}"""


def generate_p9_card(client, model: str, payload: str) -> dict:
    from typing import Optional
    from google.genai import types
    from pydantic import BaseModel

    class Card(BaseModel):
        signal_id: str
        where_to_look: str
        what_differs: str
        caveats: list[str]
        data_gaps: list[str]
        reviewer_note: str

    resp = client.models.generate_content(
        model=model, contents=[payload],
        config=types.GenerateContentConfig(
            system_instruction=P9_TEMPLATE, response_mime_type="application/json",
            response_schema=Card, temperature=0),
    )
    if not resp.parsed:
        raise ValueError("parse failed")
    return resp.parsed.model_dump()


def side_by_side(pickup_path: str, return_path: str, out_path: Path, height=720):
    """借/還原圖並排（純幾何，零模型）。panel bbox 未定位 → 全圖降級，見檔頭。"""
    from PIL import Image, ImageOps
    ims = []
    for p in (pickup_path, return_path):
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        im = im.resize((int(im.width * height / im.height), height))
        ims.append(im)
    canvas = Image.new("RGB", (ims[0].width + ims[1].width + 8, height), "white")
    canvas.paste(ims[0], (0, 0))
    canvas.paste(ims[1], (ims[0].width + 8, 0))
    canvas.save(out_path, quality=88)


# ---------- 步驟 ----------

def _load_enum_index():
    """第一期列舉資料索引：{(car,angle): {model: {'pickup':…, 'return':…}}}"""
    idx = {}
    for line in (HERE / "shadow_progress_phase1.jsonl").read_text().splitlines():
        r = json.loads(line)
        if r.get("parsed"):
            idx.setdefault((r["car"], r["angle"]), {}).setdefault(
                r["model"], {})[r["role"]] = r["parsed"]
    return idx


def _population():
    from diff_new_damage import panel_of
    from results_config import FINAL_RESULTS
    from taxonomy import PANEL_ZH
    PANEL_ZH_CACHE.update(PANEL_ZH)
    results = json.loads(FINAL_RESULTS.read_text())["results"]
    return phase1_population(results, panel_of)


def step_0p(_args):
    rows = [json.loads(l) for l in
            (HERE / "blind_enum_progress_stageA.jsonl").read_text().splitlines()]
    out = bimodality_prevalence(rows)
    (HERE / "shadow_step0p.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    for model, s in out.items():
        brief = {k: v for k, v in s.items() if k != "photos"}
        print(model, json.dumps(brief, ensure_ascii=False))
        for pid, p in s["photos"].items():
            print(f"    {pid:14s} {p['class']:10s} {p['distances']}")


def step_phase1(args):
    pop = _population()
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}
    progress = HERE / "shadow_progress_phase1.jsonl"
    # 30 筆候選已在 v6 Stage B 跑過（P7 逐字相同）——直接重用，不重複呼叫
    if not progress.exists():
        keys = {(c["car"], c["angle"]) for c in pop}
        reused = []
        for line in (HERE / "blind_enum_progress_stageB.jsonl").read_text().splitlines():
            r = json.loads(line)
            if r.get("parsed") and (r["car"], r["angle"]) in keys:
                reused.append(line)
        progress.write_text("\n".join(reused) + ("\n" if reused else ""))
        print(f"重用 v6 Stage B 資料 {len(reused)} 筆")
    calls = []
    for c in pop:
        p = pairs[(c["car"], c["angle"])]
        for model in MODELS:
            for role, photo in (("pickup", p["pickup"]), ("return", p["return"])):
                calls.append({"car": c["car"], "angle": c["angle"], "role": role,
                              "model": model, "rep": 0, "panel": c["panel"], "photo": photo})
    import random
    random.Random(44).shuffle(calls)
    _run_calls(calls, args.workers, args.rpm, progress)
    print("第一期列舉完成，執行 --step signals。")


def step_signals(_args):
    pop = _population()
    idx = _load_enum_index()
    rel = {(r["car"], r["angle"]): r["relabel"]
           for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}
    records, missing = [], []
    for c in pop:
        key = (c["car"], c["angle"])
        pm = idx.get(key, {})
        if not all(m in pm and {"pickup", "return"} <= set(pm[m]) for m in MODELS):
            missing.append("".join(key))
            continue
        records += signal_records_for_case(c, pm, rel.get(key, "?"))
    SIGNALS_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records)
                            + ("\n" if records else ""))
    disp = [r for r in records if r["dispatched"]]
    by_case = {r["case_id"] for r in disp}
    n_pop = len(pop) - len(missing)
    summary = {
        "population": n_pop, "missing_enum": missing,
        "union_signal_records": len(records),
        "dispatched_records": len(disp),
        "dispatched_cases": sorted(by_case),
        "case_signal_rate": round(len(by_case) / n_pop, 4) if n_pop else None,
        "subset_estimate_reference": round(3 / 30, 4),
        "blind_share_of_dispatched": round(
            sum(1 for r in disp if r["review_flow"] == "blind") / len(disp), 3) if disp else None,
        "agreement_breakdown": {
            k: sum(1 for r in records if r["model_agreement"] == k)
            for k in ("both", "flash_only", "pro_only")},
    }
    (HERE / "shadow_phase1_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def step_cards(args):
    from run_eval_gemini import get_client
    idx = _load_enum_index()
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}
    _population()  # 填 PANEL_ZH_CACHE
    records = [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]
    CARDS_DIR.mkdir(exist_ok=True)
    client = get_client()
    n = 0
    for r in records:
        if not r["dispatched"]:
            continue
        card_path = CARDS_DIR / f"{r['signal_id']}.json"
        img_path = CARDS_DIR / f"{r['signal_id']}.jpg"
        key = tuple([r["case_id"][:-2], r["case_id"][-2:]])
        if not card_path.exists():
            payload = build_p9_payload(r, idx[key])
            card = generate_p9_card(client, args.model, payload)
            card["signal_id"] = r["signal_id"]   # 以系統端為準
            card_path.write_text(json.dumps(card, ensure_ascii=False, indent=1))
            n += 1
        if not img_path.exists():
            p = pairs[key]
            side_by_side(p["pickup"], p["return"], img_path)
        print(f"  {r['signal_id']}  ({r['review_flow']})")
    print(f"新生成 {n} 張說明卡 → {CARDS_DIR.name}/")


def step_report(_args):
    records = [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]
    print(json.dumps({
        "stop_conditions_triggered": check_stop(records),
        "acceptance": acceptance_verdict(records),
        "intersect_vs_union": intersect_vs_union(records),
    }, ensure_ascii=False, indent=2))


# ---------- 互動式複核（第二期，由真人執行） ----------

VERDICT_KEYS = {"1": "confirmed_damage", "2": "no_damage", "3": "cannot_determine"}
POSITION_KEYS = {"1": "exact", "2": "approximate", "3": "wrong_area", "4": "n/a"}


def apply_review(records: list, signal_id: str, review: dict) -> list:
    """把單筆複核結果寫進記錄清單（純函式，tests 覆蓋）。"""
    out = []
    for r in records:
        if r["signal_id"] == signal_id:
            r = {**r, **review}
        out.append(r)
    return out


def _save(records):
    SIGNALS_PATH.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                      for r in records) + "\n")


def _ask(prompt, keys):
    while True:
        v = input(prompt).strip()
        if v in keys:
            return keys[v]
        print(f"  請輸入 {'/'.join(keys)}")


def step_review(_args):
    """逐筆複核派送訊號：開並排圖 → 顯示 P9 卡（盲測流程先問後看卡）→
    計時 → 寫回 shadow_signals.jsonl。全部完成後自動出 report。

    計時定義：從說明卡（盲測：從圖）呈現到 verdict 輸入完成；
    free_text 打字時間不計入。
    """
    import subprocess
    import time as _time
    records = [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]
    todo = [r for r in records if r["dispatched"] and not r.get("review_verdict")]
    if not todo:
        print("沒有待複核的派送訊號。現況：")
        return step_report(_args)
    print(f"待複核 {len(todo)} 筆。判定選項：1=確認損傷 2=無損傷 3=無法判定\n"
          f"位置符合：1=準確 2=大致 3=錯誤區域 4=不適用\n")
    for i, r in enumerate(todo):
        sid = r["signal_id"]
        card_path = CARDS_DIR / f"{sid}.json"
        img_path = CARDS_DIR / f"{sid}.jpg"
        card = json.loads(card_path.read_text()) if card_path.exists() else None
        print(f"\n━━━ [{i + 1}/{len(todo)}] {sid}  分區 {r['panel']}  "
              f"訊號 {'/'.join(r['signal_types_all'])}  流程 {r['review_flow']} ━━━")
        if img_path.exists():
            subprocess.run(["open", str(img_path)], check=False)
            print(f"（已開啟並排圖：左＝借車照、右＝還車照）")
        review = {}
        if r["review_flow"] == "blind" and card:
            t0 = _time.time()
            print("【盲測】先只看圖：兩張照片在此區域是否有差異？")
            review["blind_pre_verdict"] = _ask("  盲測判定 (1/2/3)：", VERDICT_KEYS)
            print("\n--- 現在顯示說明卡 ---")
        if card:
            print(f"看哪裡：{card['where_to_look']}\n差在哪：{card['what_differs']}")
            for c_ in card.get("caveats") or []:
                print(f"注意：{c_}")
            print(f"（{card['reviewer_note']}）")
        if r["review_flow"] != "blind":
            t0 = _time.time()
        review["review_verdict"] = _ask("最終判定 (1/2/3)：", VERDICT_KEYS)
        review["review_position_match"] = _ask("位置符合 (1/2/3/4)：", POSITION_KEYS)
        review["review_duration_sec"] = round(_time.time() - t0, 1)
        if r["review_flow"] == "blind":
            review["blind_changed_after_card"] = (
                review["review_verdict"] != review["blind_pre_verdict"])
        while True:
            ft = input("訊號指向的位置上實際有什麼？（必填）：").strip()
            if ft:
                review["review_free_text"] = ft
                break
        if review["review_position_match"] == "wrong_area":
            print(f"  歸因：{attribute_wrong_area(review['review_free_text'])}")
        records = apply_review(records, sid, review)
        _save(records)
        print(f"  ✓ 已存（{review['review_duration_sec']} 秒）")
    print("\n全部完成。判準結果：")
    step_report(_args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--step", required=True,
                    choices=["0p", "phase1", "signals", "cards", "review", "report"])
    ap.add_argument("--model", default="gemini-3.7-flash", help="P9 說明卡用模型")
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()
    try:
        {"0p": step_0p, "phase1": step_phase1, "signals": step_signals,
         "cards": step_cards, "review": step_review, "report": step_report}[args.step](args)
    except KeyboardInterrupt:
        print("\n已中斷。已回答的複核都已存檔，重跑 --step review 會從未答的繼續。")


if __name__ == "__main__":
    main()
