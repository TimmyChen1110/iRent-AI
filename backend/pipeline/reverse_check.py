#!/usr/bin/env python3
"""既有損主張的第二輪反向查核（外部驗證層，判定後執行，不動判定本身）。

═══════════════════════════════════════════════════════════════════
背景：現行 prompt 唯一漏抓 RDH-3092 的失敗方式，是模型寫一句「既有凹陷與
板金變形」就把真實新損免責——「既有損」是無需舉證的逃生出口。四次 prompt
改寫（v2/v4/v5/detect_v2）試圖在【同一次呼叫裡】要求舉證，全部落敗：
強制舉證欄位擋不住幻覺（v4 對 RCG2235 杜撰「借車照已存在相同擦痕」並自評
clear），要求解釋推理反而讓推理變差（v5 Recall 掉 13.7pp）。

本模組走的是唯一未證偽的方向——外部驗證：
  對每筆「判無新損＋帶既有損主張」的案件，發起一次獨立呼叫，
  【只給借車照】（不給還車照、不給原判定脈絡），只問一件事：
  「這張照片中，這段描述所指的痕跡是否確實可見？」

  假說：既有損幻覺的成因是模型看著還車照的損傷，把它「合理化」進借車照。
  拿掉還車照，查核者沒有可合理化的錨點，杜撰的主張就無法通過。

程式端映射（judgment 不變，只加旗標）：
  visible           → 主張成立，維持原判定
  not_visible       → unproven_pre_existing，送人工複核
  cannot_determine  → unproven_pre_existing，送人工複核
                      （借車照拍不到該處＝主張本來就不該成立）

實驗設計（141 組現行結果中的 30 筆候選，ground truth 來自 relabels.json）：
  28 筆 relabel=clean     → 被標旗＝白付的人工複核成本，愈少愈好
   1 筆 relabel=damage    → RDH-3092，被標旗＝成功攔到逃生出口
   1 筆 relabel=uncertain → RDZ-0187，被標旗＝合理（本來就該人工看原圖）

═══════════════════════════════════════════════════════════════════
★ 全量實測結果（2026-08-28，30 筆候選跑滿 ×2 模型）：外部驗證證偽。
  這是第五次嘗試解 RDH-3092 型漏檢，第五次失敗。勿再嘗試第六次同路線。
═══════════════════════════════════════════════════════════════════

  gemini-3.7-flash 與 gemini-3.1-pro-preview 結果幾乎一致
  （reverse_check_results.json / reverse_check_results_pro.json）：
    攔截逃生出口：0/2 ——
      RDH-3092  → visible。該區借車照舊損密集，「有既有凹陷」主張本身為真，
                  真相是【新凹陷疊在真舊損上】。主張文字查核在結構上攔不到
                  「真舊損掩護真新損」型。
      RCG2235-右後（v4 杜撰主張的追加探針）→ 兩個模型都回 visible。
                  連人工證實借車照乾淨的杜撰主張都確認得出來。
    攔到的 4 筆旗標全是取景/覆蓋問題：RDZ-0187（正確送審）＋
      3 筆 clean 誤旗（10.7%），全為 cannot_determine——
      這個軸 quality_gate / coverage 已經在管。

  ★ 病因確認（盲列舉對照探針，不給主張只問「這區有哪些痕跡」）：
    兩個模型在無提示下都在 RCG2235 借車照反光片旁「看見」人工確認
    不存在的刮痕（flash:「反光片旁/擦傷」、pro:「反光片下方/刮痕」）。
    不是確認偏誤，是【模型家族層級的一致性感知錯誤】——與 v2/v4
    在相同照片編出相同損傷同源。

  ★ 核心教訓：**同模型家族的第二意見不是獨立意見。** 查核者與被查核者
    共享同一套感知偏誤，錯誤會被「獨立呼叫」原樣複現。外部驗證要有效，
    查核者必須在感知上獨立：不同家族的模型、純 CV 證據、或
    photo_chain 跨訂單的結構性佐證（後者是目前唯一剩下的路線，
    且已有 RDE-0180 成功案例）。

  本模組保留用途：①負面結果的可重現記錄 ②若日後接入不同家族模型
  當查核者，骨架（候選挑選/旗標映射/對照重標統計）可直接沿用，
  tests/test_reverse_check.py 已鎖住這三支純函式。

  ★ 後續（2026-08-28）：v6 盲列舉差分（blind_enumeration.py）實測存活，
    RDH-3092 由差分訊號抓回。上述教訓修正為：同家族查核在【命題確認】
    形態下無效；【盲列舉＋差分】形態下一致性感知錯誤自我抵消、可運作。
    候選挑選函式 select_candidates() 已被 v6 沿用為本層入口。

用法：
  python3 reverse_check.py                # 對 FINAL_RESULTS 的候選全跑
  python3 reverse_check.py --limit 3      # 冒煙測試
  python3 reverse_check.py --results eval_results_xxx.json --tag xxx
（key 讀取與節流沿用 run_eval_gemini；斷點續跑寫 reverse_check_progress*.jsonl）
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent

# ---------- 純函式（零 API，tests/test_reverse_check.py 覆蓋） ----------

VERDICTS = ("visible", "not_visible", "cannot_determine")
REVIEW_VERDICTS = frozenset({"not_visible", "cannot_determine"})


def select_candidates(results: list) -> list:
    """挑出「判無新損＋帶既有損主張」的案件——逃生出口的高風險集合。

    判有新損者不選（那是索賠主張，走的是另一條人工複核路）；
    無主張文字者不選（沒有可查核的對象）。
    """
    out = []
    for r in results:
        a = r.get("assessment")
        if not a:
            continue
        if a.get("new_damage_found"):
            continue
        notes = (a.get("pre_existing_notes") or "").strip()
        if not notes:
            continue
        out.append({"car": r["car"], "angle": r["angle"], "label": r["label"],
                    "claim": notes})
    return out


def needs_review(verdict: str) -> bool:
    """查核結論 → 是否標 unproven_pre_existing 送人工。

    cannot_determine 也要送：借車照拍不到該處，代表「既有損」主張
    本來就沒有影像根據，正是 RDH-3092（借車照視角半遮）的形狀。
    """
    return verdict in REVIEW_VERDICTS


def summarize_reverse(rows: list, relabels: dict) -> dict:
    """對照人工重標，算攔截與成本。relabels: {(car, angle): relabel_str}"""
    done = [r for r in rows if r.get("verdict") in VERDICTS]
    flagged = [r for r in done if needs_review(r["verdict"])]
    def _bucket(rs):
        b = {"clean": [], "damage": [], "uncertain": [], "unknown": []}
        for r in rs:
            b[relabels.get((r["car"], r["angle"]), "unknown")].append(f"{r['car']}{r['angle']}")
        return b
    fb = _bucket(flagged)
    n_clean = sum(1 for r in done if relabels.get((r["car"], r["angle"])) == "clean")
    return {
        "checked": len(done),
        "errors": len(rows) - len(done),
        "flagged": len(flagged),
        "caught_true_damage": fb["damage"],        # 攔到的逃生出口（希望＝全部）
        "caught_uncertain": fb["uncertain"],       # 本來就該人工看的
        "false_flags_on_clean": fb["clean"],       # 白付的複核成本
        "clean_flag_rate": round(len(fb["clean"]) / n_clean, 4) if n_clean else None,
    }


# ---------- API 呼叫 ----------

SYSTEM_REVERSE = """你會看到一張共享汽車「借車時」拍攝的照片，以及一段對車上某處痕跡的描述。
這段描述來自另一個流程，可能正確也可能錯誤，與你無關。
你的唯一任務：判斷這張照片中，描述所指的位置是否確實可見所描述的痕跡。

verdict 規則：
- visible：該位置在照片中清楚入鏡，且確實可見所描述的痕跡。
- not_visible：該位置在照片中清楚入鏡，但看不到所描述的痕跡。
- cannot_determine：該位置未入鏡、僅部分入鏡、被遮擋、過暗、解析度不足
  或被反光覆蓋，無法確認。

只依據這張照片作答。不要推測照片外的情況，不要因為描述寫得肯定就傾向 visible。"""


def check_claim(client, model: str, pickup_path: str, claim: str) -> str:
    """單筆反向查核：只給借車照，回 verdict 字串。"""
    from google.genai import types
    from pydantic import BaseModel, Field
    from run_eval_gemini import prep_image

    class ReverseCheck(BaseModel):
        verdict: str = Field(description="visible | not_visible | cannot_determine")

    resp = client.models.generate_content(
        model=model,
        contents=[
            "借車照：",
            types.Part.from_bytes(data=prep_image(pickup_path), mime_type="image/jpeg"),
            f"描述：{claim}\n請判定 verdict。",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_REVERSE,
            response_mime_type="application/json",
            response_schema=ReverseCheck,
            temperature=0.1,
        ),
    )
    v = resp.parsed.verdict.strip() if resp.parsed else ""
    if v not in VERDICTS:
        raise ValueError(f"unexpected verdict: {v!r}")
    return v


def check_with_retry(client, model, cand, pickup_path, throttle, retries=4):
    from google.genai import errors
    for i in range(retries):
        throttle.wait()
        try:
            v = check_claim(client, model, pickup_path, cand["claim"])
            return {**cand, "verdict": v, "review_flag": needs_review(v)}
        except errors.APIError as e:
            if e.code in (429, 500, 503):
                time.sleep(20 * (i + 1))
                continue
            return {**cand, "error": f"{e.code}: {str(e)[:120]}"}
        except Exception as e:
            return {**cand, "error": str(e)[:120]}
    return {**cand, "error": "retries exhausted (rate limit)"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--results", default="", help="判定結果檔（預設 results_config.FINAL_RESULTS）")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--tag", default="", help="輸出檔名後綴")
    args = ap.parse_args()

    from run_eval_gemini import get_client, Throttle
    from results_config import FINAL_RESULTS

    results_path = Path(args.results) if args.results else FINAL_RESULTS
    results = json.loads(results_path.read_text())["results"]
    cands = select_candidates(results)
    if args.limit:
        cands = cands[: args.limit]

    pairs = {(p["car"], p["angle"]): p for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}
    relabels = {(r["car"], r["angle"]): r["relabel"]
                for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}

    tag = f"_{args.tag}" if args.tag else ""
    progress = HERE / f"reverse_check_progress{tag}.jsonl"
    rows = []
    if progress.exists():
        rows = [json.loads(l) for l in progress.read_text().splitlines()]
        rows = [r for r in rows if r.get("verdict")]
    done_keys = {(r["car"], r["angle"]) for r in rows}
    todo = [c for c in cands if (c["car"], c["angle"]) not in done_keys]
    print(f"候選 {len(cands)} 筆（已完成 {len(rows)}），model={args.model}，"
          f"預估至少 {len(todo) / args.rpm:.0f} 分鐘")

    client = get_client()
    throttle = Throttle(args.rpm)
    plock = threading.Lock()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(check_with_retry, client, args.model, c,
                          pairs[(c["car"], c["angle"])]["pickup"], throttle): c for c in todo}
        for i, fut in enumerate(as_completed(futs)):
            r = fut.result()
            rows.append(r)
            with plock, progress.open("a") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            mark = ("ERROR " + r["error"][:50]) if r.get("error") else \
                   ("⚑送審 " + r["verdict"] if r["review_flag"] else "✓成立")
            rl = relabels.get((r["car"], r["angle"]), "?")
            print(f"  [{i+1:2d}/{len(todo)}] {r['car']:9s} {r['angle']:3s} ({rl:9s}) → {mark}", flush=True)

    summary = summarize_reverse(rows, relabels)
    out = HERE / f"reverse_check_results{tag}.json"
    out.write_text(json.dumps({"summary": summary, "model": args.model,
                               "results": rows}, ensure_ascii=False, indent=1))
    print(f"\n寫入 {out.name}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
