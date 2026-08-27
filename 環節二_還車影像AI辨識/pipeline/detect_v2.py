#!/usr/bin/env python3
"""Stage 2 v2 — 規格版車損偵測 prompt（Prompt 架構規格 §3 Stage 2）。

═══════════════════════════════════════════════════════════════════════
★ 全量 A/B 結論（2026-08-27，141 組跑滿，eval_results_v2full.json）：
  本版本【落敗，不予採用】。results_config.py 維持指向現行判定。
═══════════════════════════════════════════════════════════════════════

對照人工重標（n=138）：
                   Recall      FPR      Precision
  現行 prompt       95.5%      0%        100%       ← 維持採用
  v2 規格版        100%       3.5%       84.6%      ← 落敗

v2 用 4 筆新誤報換到 1 筆真損（RDH-3092）。本專案第一指標是「申訴推翻率」，
誤告用戶是最不可接受的失敗模式，這個交換不划算。

且無法靠信心門檻救回——v2 的誤報都是高信心的：
  門檻 0.75 → Recall 100% / FPR 2.6%
  門檻 0.85 → Recall 90.9% / FPR 0.9%
  門檻 0.90 → Recall 63.6% / FPR 0%    ← 要壓到 0% 誤報，recall 崩到 63.6%
沒有任何操作點優於現行的 95.5%/0%。

人工逐張看圖複驗其中一筆（RDL7827-左前）：v2 宣稱左側裙「大範圍塑膠件破裂、
斷裂外翻與立體變形」，實際照片該處完好——是把輪拱陰影與角度輪廓幻覺成嚴重結構損壞，
並聲稱借車照該處乾淨。**高信心杜撰嚴重損傷**正是會造成錯誤索賠的失敗模式。

保留本檔的價值：
  ① 記錄「規格照抄會變差」這個實測結論，避免日後有人再走一次
  ② ruled_out 的修法確實有效（見下），可移植回現行 prompt
  ③ PreExisting 對稱舉證修法是真正的收穫——現行 prompt 唯一漏抓的 RDH-3092
     也是同一個逃生出口造成的（「既有凹陷與板金變形」），值得單獨移植回現行 prompt
     並重新量測，而不是整包換掉。

⚠ 這是與現行判定【並存】的實驗版本，不會覆蓋任何既有結果檔。

與現行 prompt 的四個結構差異（規格 §0 設計原則）：
  ① 強制先描述後判斷：observation 欄位排在 damage_type 之前。
     JSON 欄位順序即推理順序——模型會依序生成，把描述放前面等同強制它先看清楚再下判斷。
  ② 主動列舉混淆源並要求聲明排除：ruled_out 欄位。
     車損誤判有固定來源（水痕、反光、泥點、陰影、貼紙），與其期待模型自己想到，
     不如明列並要求主動聲明已排除哪些。
  ③ 分區代碼 + UV 正規化座標：讓多視角聚合與跨次差集比對成為可能（現行只有自由文字位置）。
  ④ 信心值校準定義逐字寫入：沒有定義的 confidence 跨圖片不可比，門檻就沒有意義。

用法：
  python3 detect_v2.py --limit 20            # 小樣本冒煙測試
  python3 detect_v2.py --all --rpm 8         # 全 141 組（輸出 eval_results_v2prompt.json）
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

from google.genai import types, errors
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import (  # noqa: E402
    CONFIDENCE_CALIBRATION, CONFIDENCE_PENALTY_FLAGS, DAMAGE_CODES, damage_table,
    panels_for_angle, panels_table, UV_EXPLANATION,
)
from run_eval_gemini import get_client, prep_image, Throttle, summarize, FEWSHOT  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "gemini-3.7-flash"

# 混淆源（規格 §0.4：主動列舉，要求模型聲明已排除）
CONFUSERS = [
    ("water_mark", "水珠、水痕、雨滴殘留"),
    ("reflection", "車身鏡面反射的周圍環境（樹影、燈光、其他車輛輪廓）"),
    ("dirt", "泥點、灰塵條紋、鳥糞"),
    ("sticker", "原廠或營運方張貼的貼紙、標識、車身廣告"),
    ("design_line", "車身線條、鈑件接縫、排水槽等原始設計"),
    ("lens_artifact", "拍攝時的鏡頭髒汙或畫面雜訊"),
]
CONFUSER_CODES = [c for c, _ in CONFUSERS]


# ---------- Schema：欄位順序即推理順序（規格 §0.2） ----------

class DamageV2(BaseModel):
    # ① 先描述——這個欄位必須排第一
    observation: str = Field(description="你實際觀察到的視覺特徵：位置、形狀、長度、顏色、邊緣狀態、周圍表面狀況。只描述看到什麼，不要在這裡下判斷")
    # ② 再定位
    panel: str = Field(description="分區代碼，必須來自提供的代碼表")
    position_uv: list[float] = Field(description="分區內正規化座標 [u, v]，各 0.0~1.0")
    # ③ 最後判斷
    damage_type: str = Field(description=f"損傷類型代碼，必須來自：{DAMAGE_CODES}")
    estimated_size_cm: float = Field(description="估計最長邊長度（公分）")
    depth_assessment: str = Field(description="surface_only | through_paint | substrate_exposed | unknown")
    ruled_out: list[str] = Field(description=f"【只列出本張照片真的存在、而你確實排除掉的】混淆可能，來自：{CONFUSER_CODES}。畫面上根本沒有的東西不要列——例如車身是乾的就不要列 water_mark。全部都列＝沒有在鑑別，這個欄位會被視為無效")
    ruled_out_basis: str = Field(description="針對你列出的混淆源，各用幾個字說明你憑什麼排除它。例如「水痕：痕跡邊緣銳利且不隨水珠分布；反光：換角度的第二張照片同位置仍在」。若 ruled_out 為空則填空字串")
    confidence: float = Field(ge=0, le=1, description="依信心值校準定義給分")
    box_2d: list[int] = Field(description="損傷在【還車照】上的位置 [ymin, xmin, ymax, xmax]，0~1000 正規化，框要緊貼損傷範圍")


class PreExisting(BaseModel):
    """既有損傷也必須提出證據——不可只憑一句「兩張皆可見」就免責。

    實測 RCG2235-右後：v2 把一處真實新損寫成「兩張照片皆可見」而漏掉，
    但人工複驗確認借車照該處乾淨。原因是規格的不對稱謹慎指示（證據不足時
    傾向認定為既有損傷）給了模型一個無需舉證的逃生出口。故在 schema 層
    強制對稱：主張既有損，就要說出在借車照的哪裡看到它。
    """
    description: str = Field(description="既有損傷描述")
    seen_in_pickup_photo: str = Field(description="你在【借車照】的什麼位置看到它？具體描述其在借車照中的外觀與參照物。若其實看不清楚，如實寫「借車照無法確認」")
    pickup_evidence_strength: str = Field(description="clear（借車照明確可見）| faint（隱約可見）| cannot_confirm（借車照無法確認）")


class AssessmentV2(BaseModel):
    angle_match: bool = Field(description="兩張照片是否為同一車輛的同一方位、可有效比對")
    new_damage_found: bool = Field(description="還車照中是否有借車照沒有的新損傷")
    damages: list[DamageV2] = Field(description="新增損傷清單，無則空陣列")
    no_damage_confidence: float = Field(ge=0, le=1, description="判定「無新損」的信心。new_damage_found 為 true 時填 0")
    pre_existing: list[PreExisting] = Field(description="判定為既有損傷者，每一筆都必須說明在借車照的哪裡看到它")
    pre_existing_notes: str = Field(description="既有損傷的一句話總結，無則空字串")
    assessment_limited_by: list[str] = Field(description="影響本次判定可靠度的限制（如某分區強反光），無則空陣列")


def _confuser_table() -> str:
    return "\n".join(f"  {c:16s} {zh}" for c, zh in CONFUSERS)


# 文字 few-shot（規格 §4）。實測發現只給校準定義不夠：模型會把幾乎所有項目
# 都給 0.85 以上，0.40–0.74 這個「疑似」區間形同虛設（v2smoke/v2fix 兩輪皆然，
# 13 筆損傷中 10 筆 ≥0.9、0 筆落在 0.6–0.74）。
# 規格 §4 的處方是掛範例——尤其必須有「證據不足」與「邊界案例」各一組，
# 讓模型看過一次正確的低信心輸出長什麼樣，而不是只讀到區間定義。
CALIBRATION_EXAMPLES = """
【信心值範例】以下示範同樣是「線狀痕跡」，證據強弱不同時應給的信心值：

範例一（高信心 0.88）
  observation: 「左前門下緣有一道約 12 公分水平線狀痕跡，邊緣銳利不規則，
              中央可見底層灰色素材色，與周圍平整白色漆面對比明顯；
              借車照同一位置（門把下方、飾條上方）為完整平滑漆面」
  → 形態明確、位置可在借車照對照、不易與汙漬混淆 → confidence 0.88

範例二（邊界案例 0.62）
  observation: 「右後保桿有一道淡色線狀痕跡，長約 5 公分，邊緣柔和不銳利，
              顏色與周圍水痕相近，無法確認是否有深度；該處另有數滴水珠」
  → 可見但形態不明確，且存在被誤認為水痕的可能 → confidence 0.62
  ruled_out 不應包含 water_mark（因為根本沒排除掉）

範例三（證據不足，不輸出）
  observation: 「左後葉子板疑似有痕跡，但該區域整片強反光，
              表面資訊幾乎完全遺失，無法判斷是刮痕、倒影還是髒汙」
  → 證據不足 → 不列入 damages，改記入 assessment_limited_by

請確實使用整個信心區間。若你所有項目都給 0.85 以上，代表你沒有在區分證據強弱。
"""


def build_system(angle: str | None, env_flags: list[str] | None = None) -> str:
    env_flags = env_flags or []
    penalty = set(env_flags) & CONFIDENCE_PENALTY_FLAGS
    env_block = (f"\n\n【本次拍攝環境】\n{', '.join(env_flags)}\n"
                 + ("⚠ 含 surface_wet 或 strong_reflection：請對所有線狀痕跡的信心值降低一級。\n"
                    if penalty else "")) if env_flags else ""

    return f"""你是 iRent 共享汽車的車損檢測員。你會收到同一台車、同一方位的兩張照片：
第一張是「借車時」拍攝（基準），第二張是「還車時」拍攝。

任務：找出還車照中【借車照所沒有】的新增車體損傷。

【重要原則】
1. 對每一個候選項目，你必須先在 observation 欄位寫出你實際觀察到的視覺特徵，
   再給出 damage_type 判定。順序不可顛倒——先看清楚，再下判斷。
2. 只有「還車照有、借車照沒有」的損傷才算新增。兩張都存在的是既有舊損，
   記在 pre_existing，不列入 damages。
   ⚠ 主張「既有損」同樣需要證據：你必須在 seen_in_pickup_photo 具體說出
   你在借車照的哪個位置看到它。若你其實無法在借車照確認該處，
   就必須誠實填 cannot_confirm，並將它列為 damages 中的低信心新損候選，
   而不是逕自寫成既有損。把新損誤記為既有損＝漏檢，同樣是系統失敗。
3. 若你不確定某個痕跡是損傷還是汙漬／反光，請如實輸出並給予對應的低信心值，
   不要略過，也不要硬性歸類。
4. 先確認兩張照片拍的是【同一側、同一方位】：若方位不同或損傷部位只在其中一張入鏡，
   angle_match 必須設 false，【嚴禁跨側比對】不同部位。
5. 照片為使用者手持拍攝，角度與距離會有差異，比對時要先在兩張照片中找到對應的
   車身部位再比較。

【必須主動排除的混淆源】
以下情況「不是」車體損傷，即使外觀近似，也不得列為損傷：
{_confuser_table()}

對每個輸出項目，你必須在 ruled_out 欄位聲明你已考慮並排除了哪些混淆可能。

【分區代碼表】（panel 只能使用以下代碼）
{panels_table(panels_for_angle(angle))}

【分區內正規化座標】
{UV_EXPLANATION}

【損傷類型代碼】（damage_type 只能使用以下代碼）
{damage_table()}

【信心值校準定義】
{CONFIDENCE_CALIBRATION}
{CALIBRATION_EXAMPLES}{env_block}
【兩種錯誤的後果】
誤判為新損：用戶會被要求為他沒有造成的損傷付費，造成實質損害。
漏判為既有：真實損傷無人負責，成本轉嫁給下一位用戶或營運方，
            且系統會誤把「已有損傷」當成基準，汙染這台車往後所有比對。

兩者都是失敗。不要用「一律從寬認定為既有損」來規避判斷。
證據不足時的正確做法是：給【低信心值】並列入 damages 交人工複核，
而不是把它藏進既有損。信心值就是你表達不確定的工具——請確實使用
0.40–0.74 這個區間，不要把所有項目都給 0.85 以上。"""


def judge_v2(client, pair: dict, model=MODEL, fewshot=True, include_alt=True,
             env_flags=None) -> dict:
    img = lambda p, w=1280: types.Part.from_bytes(data=prep_image(str(p), w),
                                                  mime_type="image/jpeg")
    contents = []
    if fewshot:
        contents.append("【損傷樣態參考照】以下是其他車輛真實車損的特寫範例，"
                        "僅供認識損傷樣態，與本案無關，不得當作比對對象：")
        contents += [img(p, 900) for p in FEWSHOT if p.exists()]
        contents.append("——以下開始本案比對——")
    contents += [f"方位：{pair['angle']}。第一張＝借車照（基準）：", img(pair["pickup"]),
                 "第二張＝還車照：", img(pair["return"])]
    if include_alt and pair.get("return_alt"):
        contents += ["第三張＝還車補拍照（同方位第二張）：", img(pair["return_alt"])]
    contents.append("請比對並輸出判定結果。")

    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=build_system(pair["angle"], env_flags),
            response_mime_type="application/json",
            response_schema=AssessmentV2,
            temperature=0.1,
        ),
    )
    out = resp.parsed
    um = resp.usage_metadata
    a = out.model_dump() if out else None
    if a:
        a = sanitize(a, pair["angle"])
    return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
            "assessment": a,
            "usage": {"input": um.prompt_token_count or 0,
                      "output": (um.candidates_token_count or 0) + (um.thoughts_token_count or 0)}}


def sanitize(a: dict, angle: str | None) -> dict:
    """丟棄代碼表外的幻覺值，並夾住 UV 範圍。"""
    valid_panels = set(panels_for_angle(angle))
    clean = []
    for d in a.get("damages", []):
        if d.get("panel") not in valid_panels:
            d["panel_invalid"] = d.get("panel")
            d["panel"] = None
        if d.get("damage_type") not in DAMAGE_CODES:
            d["damage_type"] = "scratch"
        uv = d.get("position_uv") or []
        d["position_uv"] = [min(1.0, max(0.0, float(x))) for x in uv[:2]] if len(uv) >= 2 else None
        d["ruled_out"] = [r for r in (d.get("ruled_out") or []) if r in CONFUSER_CODES]
        clean.append(d)
    a["damages"] = clean

    # 無憑據的「既有損」主張＝漏檢風險（見 PreExisting docstring 的 RCG2235 案例）。
    # 不自動改判（那會製造假陽性），但標記出來讓級聯層與人工複核優先看。
    unproven = [p for p in (a.get("pre_existing") or [])
                if p.get("pickup_evidence_strength") in ("cannot_confirm", "faint")]
    a["unproven_pre_existing"] = unproven
    if unproven and not a.get("new_damage_found"):
        a["review_flag"] = ("宣稱既有損但借車照無法確認（%d 筆）——可能為漏檢"
                            % len(unproven))
    return a


def judge_with_retry(client, pair, throttle, model=MODEL, retries=4, **kw):
    for i in range(retries):
        throttle.wait()
        try:
            return judge_v2(client, pair, model=model, **kw)
        except errors.APIError as e:
            if e.code in (429, 500, 503):
                time.sleep(20 * (i + 1))
                continue
            return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
                    "error": f"{e.code}: {str(e)[:120]}"}
        except Exception as e:
            return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
                    "error": str(e)[:120]}
    return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
            "error": "retries exhausted"}


def main():
    ap = argparse.ArgumentParser(description="Stage 2 v2 規格版偵測 prompt")
    ap.add_argument("--all", action="store_true", help="跑全部 141 組")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 組（正負均衡取樣）")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--tag", default="v2prompt")
    ap.add_argument("--no-fewshot", action="store_true")
    args = ap.parse_args()

    pairs = json.loads((HERE / "pairs.json").read_text())["pairs"]
    if args.limit:
        pos = [p for p in pairs if p["label"] == "positive"][: max(1, args.limit // 2)]
        neg = [p for p in pairs if p["label"] == "negative"][: args.limit - len(pos)]
        pairs = pos + neg
    elif not args.all:
        ap.error("請指定 --all 或 --limit N")

    # 載入 Stage 1 環境旗標（若已跑過覆蓋度基準）
    cov_path = HERE / "coverage_baseline.json"
    cov = json.loads(cov_path.read_text()) if cov_path.exists() else {}

    prog_path = HERE / f"eval_progress_{args.tag}.jsonl"
    results = []
    if prog_path.exists():
        for line in prog_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("assessment"):
                    results.append(r)
    done = {(r["car"], r["angle"]) for r in results}
    todo = [p for p in pairs if (p["car"], p["angle"]) not in done]
    print(f"v2 prompt：{len(pairs)} 組，已完成 {len(results)}，待跑 {len(todo)}"
          f"（預估 ≥{len(todo)/args.rpm:.0f} 分鐘）", flush=True)

    client = get_client()
    throttle = Throttle(args.rpm)
    lock = threading.Lock()
    for i, p in enumerate(todo):
        env = (cov.get(f"{p['car']}-{p['angle']}") or {}).get("environment_flags")
        r = judge_with_retry(client, p, throttle, model=args.model,
                             fewshot=not args.no_fewshot, env_flags=env)
        results.append(r)
        with lock, prog_path.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        a = r.get("assessment")
        v = ("ERROR " + r["error"][:50]) if r.get("error") else \
            ("★新損" if a["new_damage_found"] else "－無損" if a["angle_match"] else "？無法比對")
        print(f"  [{i+1:3d}/{len(todo)}] {r['car']:9s} {r['angle']} ({r['label'][:3]}) → {v}",
              flush=True)

    summary = summarize(results, args.model)
    out = HERE / f"eval_results_{args.tag}.json"
    out.write_text(json.dumps({"summary": summary, "prompt_version": "v2_spec",
                               "results": results}, ensure_ascii=False, indent=1))
    print(f"\n寫入 {out.name}")
    print(json.dumps({k: v for k, v in summary.items() if k != "tokens"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
