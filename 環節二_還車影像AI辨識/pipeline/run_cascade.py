#!/usr/bin/env python3
"""級聯複核層：對快篩結果中的「不確定案件」升級高階模型複核，計算級聯後最終指標。

升級條件（任一）：
  a) 判「無新損」但 no_damage_confidence < NO_DMG_CONF_MIN（可疑漏抓）
  b) 判「有新損」但 max(damage confidence) < DMG_CONF_MIN（可疑誤報）
  c) angle_match = false（快篩認定無法比對，讓高階模型再試一次）

最終判定：升級案件以複核模型為準（跑 N_VOTES 票取多數），其餘沿用快篩。

═══════════════════════════════════════════════════════════════════
★ 效益歸因（2026-08-30 覆核，勿在簡報/文件中誤植）：
  級聯的 Recall +4.7pp（81.0% → 85.7%）**全部來自「換用更強模型」**，
  不是來自多數決。實測只有 1 組被級聯改變判定：
    RDY-6382 左前 — Flash 判 angle_match=false 放棄；Pro 抓到藏在
    「還2」補拍照的左側車門大面積凹陷（conf 0.95），人工重標確認正確。

  多數決本身在本資料集上**未產生任何可測量效益**：
    4 件升級案的票型全是 3:0（false×3 ×3 件、true×3 ×1 件），零分歧。
    temperature=0.1 下同模型同 prompt 重複取樣，輸出高度一致——
    重複呼叫擋得住「單次隨機失誤」，擋不住「模型系統性看錯」。

  更根本的原因見 reverse_check.py 檔頭：**同模型家族的第二意見不是獨立
  意見**。v2/v4/v5 三個不同 prompt 在同樣三張照片（RDL7827/RDU-5572/
  RDW-7085）上編出同樣的假損傷；換 prompt 尚且如此，同 prompt 重跑更無效。

  → 保留 3 票的理由僅為：成本極低（4 件×3=12 次呼叫）的一致性檢查，
    可偵測未來模型/資料變動導致的判定不穩。不得宣稱它提升準確率。
    真要有效的第二意見，需感知獨立的查核者（不同模型家族、純 CV、
    或 photo_chain 跨訂單佐證）。
═══════════════════════════════════════════════════════════════════

用法：python3 run_cascade.py eval_results_gemini_37_flash_v3.json --model gemini-3.1-pro-preview
（複核模型不可用時自動 fallback 到 --fallback-model）
"""
import argparse
import json
import sys
import time
from pathlib import Path

from google.genai import errors

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import (get_client, judge, summarize, Throttle)  # noqa: E402

HERE = Path(__file__).resolve().parent
NO_DMG_CONF_MIN = 0.7
DMG_CONF_MIN = 0.85


def needs_escalation(a: dict) -> str | None:
    if not a["angle_match"]:
        return "無法比對"
    if not a["new_damage_found"]:
        return f"無損低信心({a.get('no_damage_confidence', 1):.2f})" \
            if a.get("no_damage_confidence", 1.0) < NO_DMG_CONF_MIN else None
    mx = max((d["confidence"] for d in a["damages"]), default=0)
    return f"有損低信心({mx:.2f})" if mx < DMG_CONF_MIN else None


def majority(votes: list[dict]) -> dict:
    """多票結果取多數決；new_damage_found 平手時取有損（寧可進人工複核）。"""
    yes = [v for v in votes if v["new_damage_found"]]
    winner_pool = yes if len(yes) * 2 >= len(votes) else [v for v in votes if not v["new_damage_found"]]
    # 同陣營中取信心最高者的完整判定
    def conf(v):
        return max((d["confidence"] for d in v["damages"]), default=v.get("no_damage_confidence", 0))
    return max(winner_pool, key=conf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("results")
    ap.add_argument("--model", default="gemini-3.1-pro-preview")
    ap.add_argument("--fallback-model", default="gemini-3.7-flash")
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--rpm", type=int, default=6)
    args = ap.parse_args()

    data = json.loads(Path(args.results).read_text())
    results = [r for r in data["results"] if r.get("assessment")]
    pairs = {(p["car"], p["angle"]): p for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}

    esc = [(r, reason) for r in results if (reason := needs_escalation(r["assessment"]))]
    print(f"快篩 {len(results)} 組 → 升級複核 {len(esc)} 組 ({len(esc)/len(results):.0%})")
    for r, reason in esc:
        print(f"  {r['car']:9s} {r['angle']} ({r['label'][:3]})  原因: {reason}")

    client = get_client()
    throttle = Throttle(args.rpm)
    model = args.model
    final = {(r["car"], r["angle"]): r["assessment"] for r in results}
    audit = []

    for r, reason in esc:
        pair = pairs[(r["car"], r["angle"])]
        votes = []
        for v in range(args.votes):
            for attempt in range(3):
                throttle.wait()
                try:
                    out = judge(client, model, pair, fewshot=True, include_alt=True)
                    if out.get("assessment"):
                        votes.append(out["assessment"])
                    break
                except errors.APIError as e:
                    if e.code == 404 and model != args.fallback_model:
                        print(f"  複核模型 {model} 不可用(404)，fallback → {args.fallback_model}")
                        model = args.fallback_model
                        continue
                    if e.code in (429, 500, 503):
                        time.sleep(20 * (attempt + 1))
                        continue
                    break
        if not votes:
            audit.append({"case": r["car"] + " " + r["angle"], "reason": reason, "outcome": "複核失敗，沿用快篩"})
            continue
        verdict = majority(votes)
        before = final[(r["car"], r["angle"])]["new_damage_found"]
        final[(r["car"], r["angle"])] = verdict
        flip = "翻轉" if verdict["new_damage_found"] != before else "維持"
        audit.append({"case": r["car"] + " " + r["angle"], "label": r["label"], "reason": reason,
                      "votes": [v["new_damage_found"] for v in votes], "outcome": flip})
        print(f"  ✔ {r['car']} {r['angle']}: {[v['new_damage_found'] for v in votes]} → {flip}")

    cascaded = [{**r, "assessment": final[(r["car"], r["angle"])]} for r in results]
    summary = summarize(cascaded, model)
    out = {"summary": summary, "escalated": len(esc), "review_model": model, "audit": audit,
           "results": cascaded}
    outpath = HERE / (Path(args.results).stem + "_cascaded.json")
    outpath.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\n=== 級聯後最終指標 ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "tokens"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
