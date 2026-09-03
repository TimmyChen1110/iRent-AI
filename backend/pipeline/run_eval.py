#!/usr/bin/env python3
"""Stage 2 — Claude Vision 車損判定評測。

對 pairs.json 的 141 組借/還配對執行新車損判定，計算：
  - 正樣本召回率 Recall（索賠資料 28 台車中可配對的 21 組）
  - 負樣本誤報率 FPR（30 台未索賠車的 120 組配對）
  - 實際 token 用量與成本

用法：
  ANTHROPIC_API_KEY=sk-... python3 run_eval.py                 # 全量 (Opus 5)
  python3 run_eval.py --model claude-haiku-4-5                 # Haiku 級聯測試
  python3 run_eval.py --limit 6                                # 冒煙測試
（無環境變數時會讀取 pipeline/.anthropic_key 檔案內容作為 key）
"""
import argparse
import base64
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from pairs_io import load_pairs  # noqa: E402

import anthropic
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent

# ---------- 判定結果 Schema (Structured Outputs) ----------

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
    pre_existing_notes: str = Field(description="兩張照片皆存在的既有損傷簡述，無則空字串")

SYSTEM = """你是 iRent 共享汽車的車況比對專家。你會收到同一台車、同一方位的兩張照片：
第一張是「借車時」拍攝，第二張是「還車時」拍攝。

任務：判斷還車照中是否存在借車照所沒有的【新增車損】（刮痕、凹陷、破損、掉漆）。

判定準則：
1. 只有「還車照有、借車照沒有」的損傷才算新增車損。兩張照片都存在的是既有舊損，記在 pre_existing_notes，不算。
2. 以下不是車損，嚴禁誤報：光線反射、水痕雨漬、灰塵泥沙髒污、樹影/物體倒影、影像壓縮雜訊、拍攝角度造成的變形。
3. 照片為使用者手持拍攝，角度與距離會有差異，比對時要在兩張照片中找到對應的車身部位再比較。
4. 若兩張照片明顯不是同一方位或無法有效比對，angle_match 設為 false。
5. 寧可保守：confidence 反映真實把握程度，不確定的可疑差異給低 confidence 而非直接不報。"""


def b64(path: str) -> str:
    return base64.standard_b64encode(Path(path).read_bytes()).decode()


def get_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        keyfile = HERE / ".anthropic_key"
        if keyfile.exists():
            key = keyfile.read_text().strip()
    if not key:
        sys.exit("找不到 API key：請設定 ANTHROPIC_API_KEY 或建立 pipeline/.anthropic_key")
    return anthropic.Anthropic(api_key=key)


def judge(client: anthropic.Anthropic, model: str, pair: dict) -> dict:
    msg = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": f"方位：{pair['angle']}。第一張＝借車照："},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(pair["pickup"])}},
                {"type": "text", "text": "第二張＝還車照："},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64(pair["return"])}},
                {"type": "text", "text": "請比對並輸出判定結果。"},
            ],
        }],
        output_format=Assessment,
    )
    out: Assessment = msg.parsed_output
    u = msg.usage
    return {
        "car": pair["car"], "angle": pair["angle"], "label": pair["label"],
        "assessment": out.model_dump() if out else None,
        "usage": {
            "input": u.input_tokens, "output": u.output_tokens,
            "cache_write": u.cache_creation_input_tokens or 0,
            "cache_read": u.cache_read_input_tokens or 0,
        },
    }


def judge_with_retry(client, model, pair, retries=3):
    for i in range(retries):
        try:
            return judge(client, model, pair)
        except (anthropic.RateLimitError, anthropic.InternalServerError):
            time.sleep(15 * (i + 1))
        except anthropic.APIStatusError as e:
            return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"],
                    "error": f"{e.status_code}: {e.message}"}
    return {"car": pair["car"], "angle": pair["angle"], "label": pair["label"], "error": "retries exhausted"}


PRICES = {  # USD per MTok: (input, output, cache_write, cache_read)
    "claude-opus-5": (5, 25, 6.25, 0.5),
    "claude-haiku-4-5": (1, 5, 1.25, 0.1),
}


def summarize(results: list, model: str) -> dict:
    done = [r for r in results if r.get("assessment")]
    errors = [r for r in results if r.get("error")]
    pos = [r for r in done if r["label"] == "positive"]
    neg = [r for r in done if r["label"] == "negative"]
    tp = sum(1 for r in pos if r["assessment"]["new_damage_found"])
    fn = len(pos) - tp
    fp = sum(1 for r in neg if r["assessment"]["new_damage_found"])
    tn = len(neg) - fp

    tot = {k: sum(r["usage"][k] for r in done) for k in ("input", "output", "cache_write", "cache_read")}
    p_in, p_out, p_cw, p_cr = PRICES.get(model, PRICES["claude-opus-5"])
    cost = (tot["input"] * p_in + tot["output"] * p_out +
            tot["cache_write"] * p_cw + tot["cache_read"] * p_cr) / 1e6

    return {
        "model": model,
        "evaluated": len(done), "errors": len(errors),
        "confusion": {"TP": tp, "FN": fn, "FP": fp, "TN": tn},
        "recall": round(tp / len(pos), 4) if pos else None,
        "false_positive_rate": round(fp / len(neg), 4) if neg else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "tokens": tot,
        "cost_usd": round(cost, 4),
        "cost_per_pair_usd": round(cost / len(done), 5) if done else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="claude-opus-5")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 組（正負各半）")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    pairs = load_pairs()
    if args.limit:
        pos = [p for p in pairs if p["label"] == "positive"][: args.limit // 2]
        neg = [p for p in pairs if p["label"] == "negative"][: args.limit - len(pos)]
        pairs = pos + neg

    client = get_client()
    print(f"model={args.model}  pairs={len(pairs)}  workers={args.workers}")
    t0 = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(judge_with_retry, client, args.model, p): p for p in pairs}
        for i, fut in enumerate(as_completed(futs)):
            r = fut.result()
            results.append(r)
            a = r.get("assessment")
            verdict = ("ERROR " + r["error"][:60]) if r.get("error") else \
                      ("★新損" if a["new_damage_found"] else "－無損")
            print(f"  [{i+1:3d}/{len(pairs)}] {r['car']:9s} {r['angle']} ({r['label'][:3]}) → {verdict}")

    summary = summarize(results, args.model)
    tag = args.model.replace("claude-", "").replace("-", "_")
    (HERE / f"eval_results_{tag}.json").write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1))
    print(f"\n完成，耗時 {time.time() - t0:.0f}s")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
