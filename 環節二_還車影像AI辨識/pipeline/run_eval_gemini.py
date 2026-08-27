#!/usr/bin/env python3
"""Stage 2 — Gemini Vision 車損判定評測（與 run_eval.py 相同框架、相同指標）。

用法：
  GEMINI_API_KEY=... python3 run_eval_gemini.py                    # 全量 (gemini-2.5-flash)
  python3 run_eval_gemini.py --model gemini-2.5-pro                # 換模型
  python3 run_eval_gemini.py --limit 6                             # 冒煙測試
  python3 run_eval_gemini.py --list-models                         # 列出你的 key 可用的模型
（無環境變數時會讀取 pipeline/.gemini_key 檔案內容作為 key）

免費額度注意：AI Studio 免費 key 有 RPM 限制，預設 --rpm 8 節流；
付費 key 可拉高 --rpm 與 --workers。
"""
import argparse
import io
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google import genai
from google.genai import types, errors
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent

# ---------- 判定結果 Schema（與 run_eval.py 一致） ----------

class Damage(BaseModel):
    location: str = Field(description="損傷位置，例如：左後葉子板、前保桿下緣")
    type: str = Field(description="損傷類型：刮痕 | 凹陷 | 破損 | 掉漆 | 其他")
    severity: str = Field(description="嚴重度：low | medium | high")
    confidence: float = Field(description="0~1，判定為新損傷的信心")
    reasoning: str = Field(description="一句話：為何判定為新增而非反光/髒污/既有舊損")

class Assessment(BaseModel):
    angle_match: bool = Field(description="兩張照片是否為同一車輛的同一方位、可有效比對")
    new_damage_found: bool = Field(description="還車照中是否有借車照沒有的新損傷")
    damages: list[Damage] = Field(description="新損傷清單，無則空陣列")
    no_damage_confidence: float = Field(description="0~1：判定「無新損」的信心。new_damage_found 為 true 時填 0；照片品質差、有可疑但不確定的區域時應調低")
    pre_existing_notes: str = Field(description="兩張照片皆存在的既有損傷簡述，無則空字串")


# ---------- v4：既有損對稱舉證（★ 全量實測落敗，保留供記錄，勿啟用） ----------
#
# ═══════════════════════════════════════════════════════════════════
# 結論（2026-08-27，141 組跑滿，eval_results_gemini_37_flash_v4.json）：
#   v4 落敗。judge() 預設維持 v4=False，正式判定不使用本變體。
# ═══════════════════════════════════════════════════════════════════
#
# 對照人工重標（n=138）：
#                Recall    FPR     Precision
#   現行 prompt   95.5%    0%       100%      ← 維持採用
#   v4 移植版     95.5%    3.5%     84.0%     ← 落敗
#
# 原始動機：現行 prompt 唯一漏抓的 RDH-3092，失敗方式是模型寫一句「既有凹陷與板金
# 變形」就把真實新損免責掉——「既有損」是個無需舉證的逃生出口。detect_v2 的規格版
# 也栽在同一個洞（RCG2235-右後）。修法是強制說出在借車照哪裡看到它並自評證據強度。
#
# ★ 實測結果與教訓：**強制舉證欄位擋不住幻覺，只會讓幻覺變得更有說服力。**
#   - v4 確實救回 RDH-3092（修法本身有作用）
#   - 但同時把 RCG2235-右後 漏掉了——正是這個修法要防的那種失敗。模型乖乖填了
#     seen_in_pickup_photo：「借車照中右後保桿紅色反光片右側及底部邊角處已存在
#     相同的黑色擦痕」，並自評 pickup_evidence_strength=clear。
#     人工逐張看圖確認：借車照該處乾淨，這段敘述是杜撰的。
#   - 30 筆既有損主張中 **28 筆自評 clear、0 筆 cannot_confirm**——逃生出口沒有
#     被關掉，只是換了個有自信的標籤。自評證據強度這個機制在此模型上無效。
#   - 另新增 4 筆誤報，其中 3 筆（RDL7827、RDU-5572、RDW-7085）與 detect_v2 幻覺的
#     是同一批照片——兩個不同 prompt 在同樣的照片上編出同樣的損傷。
#
# 保留本段程式碼的用途：記錄這個負面結果，避免日後有人再走一次同一條路。
# 若要真正解決漏檢，方向應該是外部驗證（如對既有損主張做第二輪反向查核、
# 或用 photo_chain 跨訂單佐證），而不是在同一次呼叫裡要求模型自我舉證。

class PreExistingClaim(BaseModel):
    description: str = Field(description="既有損傷描述")
    seen_in_pickup_photo: str = Field(description="你在【借車照】的什麼位置看到它？具體描述其在借車照中的外觀與參照物。若其實看不清楚，如實寫「借車照無法確認」")
    pickup_evidence_strength: str = Field(description="clear（借車照明確可見）| faint（隱約可見）| cannot_confirm（借車照無法確認）")


class DamageV4(Damage):
    ruled_out_basis: str = Field(description="你憑什麼排除反光／水痕／髒污？各用幾個字說明判別依據，例如「水痕：痕跡邊緣銳利不隨水珠分布；反光：換角度仍在」")


class AssessmentV4(BaseModel):
    angle_match: bool = Field(description="兩張照片是否為同一車輛的同一方位、可有效比對")
    new_damage_found: bool = Field(description="還車照中是否有借車照沒有的新損傷")
    damages: list[DamageV4] = Field(description="新損傷清單，無則空陣列")
    no_damage_confidence: float = Field(description="0~1：判定「無新損」的信心。new_damage_found 為 true 時填 0；照片品質差、有可疑但不確定的區域時應調低")
    pre_existing: list[PreExistingClaim] = Field(description="判定為既有損傷者，每一筆都必須說明在借車照的哪裡看到它")
    pre_existing_notes: str = Field(description="既有損傷的一句話總結，無則空字串")

SYSTEM = """你是 iRent 共享汽車的車況比對專家。你會收到同一台車、同一方位的兩張照片：
一張是「借車時」拍攝，一張是「還車時」拍攝（還車可能有補拍第二張）。

任務：判斷還車照中是否存在借車照所沒有的【新增車損】（刮痕、凹陷、破損、掉漆）。

判定準則：
1. 只有「還車照有、借車照沒有」的損傷才算新增車損。兩張照片都存在的是既有舊損，記在 pre_existing_notes，不算。
2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。
3. 照片為使用者手持拍攝，角度與距離會有差異，比對時要在兩張照片中找到對應的車身部位再比較。
4. 先確認兩張照片拍的是車輛的【同一側、同一方位】：若一張是右前、另一張是左前（或損傷部位只在其中一張入鏡），angle_match 必須設 false，【嚴禁跨側比對】不同部位。
5. 寧可保守：confidence 反映真實把握程度，不確定的可疑差異給低 confidence 而非直接不報。
6. 判定「無新損」時，用 no_damage_confidence 誠實表達把握程度：照片清晰、確定無損給高分；光線差、有難以確認的可疑處給低分。
7. 若開頭附有「損傷樣態參考照」，僅用於認識真實車損的樣子，與本案車輛無關，不得當作比對對象。"""


# v4 = 現行 SYSTEM 逐字保留 + 只加兩項（detect_v2 全量 A/B 證實有效的部分）：
#   ① 準則 1 補上「既有損也要舉證」
#   ② 準則 2 補上「說明憑什麼排除」
# 其餘一字未改，確保 A/B 差異能單獨歸因。
SYSTEM_V4 = SYSTEM.replace(
    "1. 只有「還車照有、借車照沒有」的損傷才算新增車損。兩張照片都存在的是既有舊損，記在 pre_existing_notes，不算。",
    "1. 只有「還車照有、借車照沒有」的損傷才算新增車損。兩張照片都存在的是既有舊損，記在 pre_existing，不算。\n"
    "   ⚠ 主張「既有損」同樣需要證據：每一筆都必須在 seen_in_pickup_photo 具體說出你在借車照的哪個位置看到它。\n"
    "   若你其實無法在借車照確認該處，必須誠實填 cannot_confirm，並把它當成低信心新損列入 damages 交人工複核，\n"
    "   而不是逕自寫成既有損。把新損誤記為既有損＝漏檢，與誤報同樣是系統失敗。",
).replace(
    "2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。",
    "2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。\n"
    "   每筆新損都要在 ruled_out_basis 說明你憑什麼排除這些可能——只列你真的排除掉的，不要空泛地全部宣稱一遍。",
)


# ---------- v5：只加 ruled_out_basis（★ 全量實測落敗，四次中最差，勿啟用） ----------
#
# ═══════════════════════════════════════════════════════════════════
# 結論（141 組跑滿，eval_results_gemini_37_flash_v5.json）：v5 落敗，且是四次中最差。
#   judge() 預設維持 v5=False。
# ═══════════════════════════════════════════════════════════════════
#
# 對照人工重標（n=138）：
#                Recall    FPR     Precision
#   現行 prompt   95.5%    0%       100%      ← 維持採用
#   v5            81.8%    2.6%     85.7%     ← 落敗（7 組翻轉全是退步，0 改善）
#
# 原始假設：v4 落敗是「既有損對稱舉證」造成的，而 ruled_out_basis 在 v2 全量測試中
# 表現良好（全部勾滿 100% → 2.45/6，每筆有具體理由），值得單獨採用。
#
# ★ 這個假設被推翻，而且結果比 v4 更差（Recall 95.5% → 81.8%，掉 13.7pp）。
#
# ★★ 四次實驗最重要的結論：**要求模型解釋自己的推理，會讓推理本身變差。**
#   v5 只加了一個「說明你憑什麼排除反光／水痕」的欄位——它完全不碰任何判定準則，
#   純粹是要求模型把已經做過的思考寫出來。結果 Recall 掉了 13.7pp。
#   合理推測：強迫模型為每筆損傷產出「排除理由」，等於誘導它去論證「這是真損」，
#   於是對本來就該低調處理的模糊痕跡也編出一套說詞（誤報 +3），
#   同時把注意力從「比對」轉移到「說明」（漏抓 +3）。
#
# 對外呈現的可解釋性應該由【判定之後】的層產生（disposition.py 的規則表理由、
# notify.py 的客服說明），而不是在判定當下要求模型自我解釋。
#   這也是為什麼 S6/S7 是純加分而 v2/v4/v5 全部落敗——差別在於有沒有動到判定本身。

class DamageV5(Damage):
    ruled_out_basis: str = Field(description="你憑什麼排除反光／水痕／髒污？各用幾個字說明判別依據，例如「水痕：痕跡邊緣銳利不隨水珠分布；反光：換角度仍在」。只列你真的排除掉的，不要空泛地全部宣稱一遍")


class AssessmentV5(BaseModel):
    angle_match: bool = Field(description="兩張照片是否為同一車輛的同一方位、可有效比對")
    new_damage_found: bool = Field(description="還車照中是否有借車照沒有的新損傷")
    damages: list[DamageV5] = Field(description="新損傷清單，無則空陣列")
    no_damage_confidence: float = Field(description="0~1：判定「無新損」的信心。new_damage_found 為 true 時填 0；照片品質差、有可疑但不確定的區域時應調低")
    pre_existing_notes: str = Field(description="兩張照片皆存在的既有損傷簡述，無則空字串")


# 現行 SYSTEM 逐字保留，只在準則 2 補一句要求說明排除依據。
SYSTEM_V5 = SYSTEM.replace(
    "2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。",
    "2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。\n"
    "   每筆新損都要在 ruled_out_basis 說明你憑什麼排除這些可能——只列你真的排除掉的，不要空泛地全部宣稱一遍。",
)


def get_client() -> genai.Client:
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        keyfile = HERE / ".gemini_key"
        if keyfile.exists():
            key = keyfile.read_text().strip()
    if not key:
        sys.exit("找不到 API key：請設定 GEMINI_API_KEY 或建立 pipeline/.gemini_key")
    return genai.Client(api_key=key)


class Throttle:
    """全域 RPM 節流（免費額度友善）。"""
    def __init__(self, rpm: int):
        self.interval = 60.0 / max(rpm, 1)
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self):
        with self.lock:
            now = time.time()
            if now < self.next_t:
                delay = self.next_t - now
                self.next_t += self.interval
            else:
                delay = 0.0
                self.next_t = now + self.interval
        if delay:
            time.sleep(delay)


def prep_image(path: str, max_w: int = 1280) -> bytes:
    """EXIF 方向轉正（資料集 76% 照片帶 Orientation=6）＋ 限寬後重新編碼。"""
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# Few-shot 損傷樣態參考照：取自「車況回報」特寫（該 8 台車無借/還配對，與評測集零重疊）
DATA_ROOT = HERE.parents[1] / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"
FEWSHOT = [
    DATA_ROOT / "進行索賠資料" / "RDA-7093 車況回報.jfif",
    DATA_ROOT / "進行索賠資料" / "RDE-9932 車況回報.jfif",
]


def judge(client: genai.Client, model: str, pair: dict, fewshot=False, include_alt=False,
          v4=False, v5=False) -> dict:
    """v4=True 改用 SYSTEM_V4 + AssessmentV4（既有損對稱舉證 + ruled_out_basis）。
    預設 False——現行實測數字由預設路徑產生，不可動。"""
    img = lambda p, w=1280: types.Part.from_bytes(data=prep_image(str(p), w), mime_type="image/jpeg")
    contents = []
    if fewshot:
        contents.append("【損傷樣態參考照】以下是其他車輛真實車損的特寫範例，僅供認識損傷樣態，與本案無關：")
        contents += [img(p, 900) for p in FEWSHOT if p.exists()]
        contents.append("——以下開始本案比對——")
    contents += [
        f"方位：{pair['angle']}。第一張＝借車照：",
        img(pair["pickup"]),
        "第二張＝還車照：",
        img(pair["return"]),
    ]
    if include_alt and pair.get("return_alt"):
        contents += ["第三張＝還車補拍照（同方位第二張）：", img(pair["return_alt"])]
    contents.append("請比對並輸出判定結果。")
    resp = client.models.generate_content(
        model=model,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_V5 if v5 else SYSTEM_V4 if v4 else SYSTEM,
            response_mime_type="application/json",
            response_schema=AssessmentV5 if v5 else AssessmentV4 if v4 else Assessment,
            temperature=0.1,
        ),
    )
    out: Assessment = resp.parsed
    um = resp.usage_metadata
    return {
        "car": pair["car"], "angle": pair["angle"], "label": pair["label"],
        "assessment": out.model_dump() if out else None,
        "usage": {
            "input": um.prompt_token_count or 0,
            "output": (um.candidates_token_count or 0) + (um.thoughts_token_count or 0),
        },
    }


def judge_with_retry(client, model, pair, throttle, retries=4, fewshot=False, include_alt=False,
                     v4=False, v5=False):
    for i in range(retries):
        throttle.wait()
        try:
            return judge(client, model, pair, fewshot=fewshot, include_alt=include_alt,
                         v4=v4, v5=v5)
        except errors.APIError as e:
            if e.code in (429, 500, 503):
                time.sleep(20 * (i + 1))
                continue
            return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
                    "error": f"{e.code}: {str(e)[:120]}"}
        except Exception as e:  # 解析失敗等
            return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
                    "error": str(e)[:120]}
    return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"], "error": "retries exhausted (rate limit)"}


PRICES = {  # USD per MTok (input, output)，付費層級參考價；免費 key 成本為 0
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}


def summarize(results: list, model: str) -> dict:
    done = [r for r in results if r.get("assessment")]
    errors_ = [r for r in results if r.get("error")]
    pos = [r for r in done if r["label"] == "positive"]
    neg = [r for r in done if r["label"] == "negative"]
    tp = sum(1 for r in pos if r["assessment"]["new_damage_found"])
    fn = len(pos) - tp
    fp = sum(1 for r in neg if r["assessment"]["new_damage_found"])
    tn = len(neg) - fp
    tot = {k: sum(r["usage"][k] for r in done) for k in ("input", "output")}
    p_in, p_out = next((v for k, v in PRICES.items() if model.startswith(k)), (0, 0))
    cost = (tot["input"] * p_in + tot["output"] * p_out) / 1e6
    return {
        "model": model,
        "evaluated": len(done), "errors": len(errors_),
        "confusion": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
        "recall": round(tp / len(pos), 4) if pos else None,
        "false_positive_rate": round(fp / len(neg), 4) if neg else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "tokens": tot,
        "cost_usd_paid_tier": round(cost, 4),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-2.5-flash")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 組（正負各半）")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--rpm", type=int, default=8, help="每分鐘請求上限（免費 key 建議 ≤10）")
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--fewshot", action="store_true", help="附上損傷樣態參考照")
    ap.add_argument("--v4", action="store_true",
                    help="用 SYSTEM_V4（既有損對稱舉證 + ruled_out_basis）——已證實落敗，僅供對照")
    ap.add_argument("--v5", action="store_true",
                    help="用 SYSTEM_V5（只加 ruled_out_basis，不動判定準則）")
    ap.add_argument("--include-alt", action="store_true", help="還2 補拍照一併判讀")
    ap.add_argument("--tag", default="", help="輸出檔名後綴（版本標記）")
    args = ap.parse_args()

    client = get_client()
    if args.list_models:
        for m in client.models.list():
            if "generateContent" in (m.supported_actions or []):
                print(m.name)
        return

    pairs = json.loads((HERE / "pairs.json").read_text())["pairs"]
    if args.limit:
        pos = [p for p in pairs if p["label"] == "positive"][: args.limit // 2]
        neg = [p for p in pairs if p["label"] == "negative"][: args.limit - len(pos)]
        pairs = pos + neg

    # 斷點續跑：逐筆寫入 progress JSONL，重跑時跳過已完成者
    tag = args.model.replace("-", "_").replace(".", "") + (f"_{args.tag}" if args.tag else "")
    progress = HERE / f"eval_progress_{tag}.jsonl"
    results = []
    if progress.exists():
        for line in progress.read_text().splitlines():
            r = json.loads(line)
            if r.get("assessment"):
                results.append(r)
    done_keys = {(r["car"], r["angle"]) for r in results}
    todo = [p for p in pairs if (p["car"], p["angle"]) not in done_keys]
    if done_keys:
        print(f"續跑：已完成 {len(results)} 組，剩 {len(todo)} 組")

    est_min = len(todo) / args.rpm
    print(f"model={args.model}  pairs={len(todo)}  rpm={args.rpm}  預估至少 {est_min:.0f} 分鐘")
    throttle = Throttle(args.rpm)
    t0 = time.time()
    plock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_with_retry, client, args.model, p, throttle,
                          fewshot=args.fewshot, include_alt=args.include_alt,
                          v4=args.v4, v5=args.v5): p for p in todo}
        for i, fut in enumerate(as_completed(futs)):
            r = fut.result()
            results.append(r)
            with plock, progress.open("a") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            a = r.get("assessment")
            verdict = ("ERROR " + r["error"][:60]) if r.get("error") else \
                      ("★新損" if a["new_damage_found"] else "－無損")
            print(f"  [{i+1:3d}/{len(todo)}] {r['car']:9s} {r['angle']} ({r['label'][:3]}) → {verdict}", flush=True)

    summary = summarize(results, args.model)
    (HERE / f"eval_results_{tag}.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1))
    print(f"\n完成，耗時 {(time.time() - t0) / 60:.1f} 分鐘")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
