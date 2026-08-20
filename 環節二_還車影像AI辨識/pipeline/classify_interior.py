#!/usr/bin/env python3
"""F2 — 車內整潔程度分級（髒汙/普通/乾淨）。

快篩：gemini-3.7-flash 全量三級分類。
複核：判「髒汙」或 confidence<0.7 者升級 Pro 模型確認後才算數（控誤報，
      對應架構 §04：髒汙須 Opus/Pro 級複核確認才觸發 P1 預警）。

用法：python3 classify_interior.py            # interior_sample.json 全量
      python3 classify_interior.py --limit 6  # 冒煙
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from google.genai import types, errors
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, prep_image, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
PHOTOS = HERE / "interior_photos"


class InteriorAssessment(BaseModel):
    level: str = Field(description="整潔分級：髒汙 | 普通 | 乾淨")
    confidence: float = Field(description="0~1 分級信心")
    issues: list[str] = Field(description="觀察到的具體問題（垃圾、污漬、泥沙、毛髮等），乾淨則空陣列")
    reasoning: str = Field(description="一句話說明分級依據")


SYSTEM = """你是 iRent 共享汽車的車內整潔檢查員。你會收到一張還車時拍攝的車內照片（前座或後座）。

請將整潔程度分為三級：
- 髒汙（須立即清潔）：明顯垃圾、食物殘渣、液體污漬、大面積泥沙、菸蒂、成撮毛髮等，會直接影響下一位租客的觀感或產生異味風險。
- 普通：少量灰塵、輕微使用痕跡（腳踏墊些許沙土、座椅輕微壓痕），不影響下一位用戶正常使用。
- 乾淨：無可見髒污，狀態良好。

注意：
1. 車輛固定配備（兒童座椅、置物盒、原廠腳踏墊本身）不是髒汙。
2. 光影、座椅材質紋路、深色內裝的正常反光不是污漬。
3. 手持拍攝角度歪斜、局部視角是常態，就照片可見範圍判定。
4. confidence 誠實反映把握程度：照片過暗、過糊、視角太侷限時應調低。"""


def classify(client, model: str, item: dict) -> dict:
    resp = client.models.generate_content(
        model=model,
        contents=[
            f"車內照（{'前座' if item['type']=='front' else '後座'}）：",
            types.Part.from_bytes(data=prep_image(str(PHOTOS / item["file"])), mime_type="image/jpeg"),
            "請判定整潔分級。",
        ],
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=InteriorAssessment,
            temperature=0.1,
        ),
    )
    out = resp.parsed
    um = resp.usage_metadata
    return {**{k: item[k] for k in ("order", "car", "type", "file")},
            "assessment": out.model_dump() if out else None,
            "usage": {"input": um.prompt_token_count or 0,
                      "output": (um.candidates_token_count or 0) + (um.thoughts_token_count or 0)}}


def classify_with_retry(client, model, item, throttle, retries=4):
    for i in range(retries):
        throttle.wait()
        try:
            return classify(client, model, item)
        except errors.APIError as e:
            if e.code in (429, 500, 503):
                time.sleep(20 * (i + 1)); continue
            return {**item, "error": f"{e.code}: {str(e)[:100]}"}
        except Exception as e:
            return {**item, "error": str(e)[:100]}
    return {**item, "error": "retries exhausted"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--review-model", default="gemini-3.1-pro-preview")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rpm", type=int, default=8)
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    items = json.loads((HERE / "interior_sample.json").read_text())
    if args.limit:
        items = items[: args.limit]

    progress = HERE / "interior_progress.jsonl"
    results = []
    if progress.exists():
        for line in progress.read_text().splitlines():
            r = json.loads(line)
            if r.get("assessment"):
                results.append(r)
    done = {r["file"] for r in results}
    todo = [i for i in items if i["file"] not in done]
    if done:
        print(f"續跑：已完成 {len(results)}，剩 {len(todo)}")

    client = get_client()
    throttle = Throttle(args.rpm)
    plock = threading.Lock()
    print(f"快篩 model={args.model} photos={len(todo)} rpm={args.rpm}")
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(classify_with_retry, client, args.model, it, throttle) for it in todo]
        for i, fut in enumerate(as_completed(futs)):
            r = fut.result()
            results.append(r)
            with plock, progress.open("a") as f:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            a = r.get("assessment")
            tagtxt = f"{a['level']}({a['confidence']:.2f})" if a else "ERROR " + r.get("error", "")[:40]
            print(f"  [{i+1:2d}/{len(todo)}] {r['car']:9s} {r['type']:5s} → {tagtxt}", flush=True)

    # 複核：髒汙或低信心 → Pro 確認
    esc = [r for r in results if r.get("assessment") and
           (r["assessment"]["level"] == "髒汙" or r["assessment"]["confidence"] < 0.7)]
    print(f"\n升級複核 {len(esc)} 張 → {args.review_model}")
    review_model = args.review_model
    for r in esc:
        item = {k: r[k] for k in ("order", "car", "type", "file")}
        for attempt in range(3):
            throttle.wait()
            try:
                rr = classify(client, review_model, item)
                if rr.get("assessment"):
                    r["flash_assessment"] = r["assessment"]
                    r["assessment"] = rr["assessment"]
                    r["reviewed"] = True
                    chg = "翻轉" if rr["assessment"]["level"] != r["flash_assessment"]["level"] else "維持"
                    print(f"  ✔ {r['car']} {r['type']}: {r['flash_assessment']['level']} → {rr['assessment']['level']} ({chg})")
                break
            except errors.APIError as e:
                if e.code == 404 and review_model != args.model:
                    review_model = args.model
                    continue
                if e.code in (429, 500, 503):
                    time.sleep(20 * (attempt + 1)); continue
                break

    ok = [r for r in results if r.get("assessment")]
    from collections import Counter
    dist = Counter(r["assessment"]["level"] for r in ok)
    tot_in = sum(r["usage"]["input"] for r in ok if r.get("usage"))
    tot_out = sum(r["usage"]["output"] for r in ok if r.get("usage"))
    summary = {
        "model": args.model, "review_model": review_model,
        "classified": len(ok), "errors": len(results) - len(ok),
        "distribution": dict(dist),
        "reviewed": sum(1 for r in ok if r.get("reviewed")),
        "tokens": {"input": tot_in, "output": tot_out},
    }
    (HERE / "interior_results.json").write_text(
        json.dumps({"summary": summary, "results": ok}, ensure_ascii=False, indent=1))
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
