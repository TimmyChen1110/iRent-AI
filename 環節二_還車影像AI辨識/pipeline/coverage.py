#!/usr/bin/env python3
"""Stage 1 — 影像盤點與觀測覆蓋度評估（Prompt 架構規格 §3 Stage 1）。

在偵測損傷之前，先問一個不同的問題：這張照片到底「看清楚了」哪些部位？

為什麼需要這層：Stage 4 判定新損時，必須知道【借車照】上該部位拍得多清楚。
上次沒拍清楚的地方，這次就不能算在用戶頭上（規格稱為結構性保障）。
沒有這層，「新損」只能靠模型自陳信心，無法區分「真的沒有」與「根本沒拍到」。

與 quality_gate.py 的分工：
  quality_gate  純 CV、零成本、整張照片的清晰度/曝光 → 擋掉根本不能看的照片
  coverage      VLM、逐分區 → 這張「能看」的照片，各部位分別看得多清楚

輸出 panel_coverage_map 會寫進車況檔（護照），成為下次比對的 prior_q。

用法：
  python3 coverage.py 照片.jpg                    # 單張
  python3 coverage.py 照片.jpg --angle 左前        # 給定方位（裁切分區選項，抑制幻覺）
  python3 coverage.py --pairs                     # 跑 pairs.json 全部借車照（建基準）
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from taxonomy import (  # noqa: E402
    ENV_FLAG_CODES, env_flags_table, panels_for_angle, panels_table, PANEL_ZH,
)
from run_eval_gemini import get_client, prep_image, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "gemini-3.7-flash"

# 覆蓋度分數門檻（規格 §3 Stage 4）
Q_FULL_TRUST = 0.8    # ≥ 此值：信心不折損，可自動處置
Q_MIN_CLAIM = 0.6     # < 此值：無論偵測信心多高，一律僅記錄，不得對用戶主張


# ---------- Schema ----------

class PanelCoverage(BaseModel):
    panel: str = Field(description="分區代碼，必須來自提供的代碼表")
    quality: float = Field(ge=0, le=1, description="觀測品質 0.0~1.0，見評分標準")


class PhotoCoverage(BaseModel):
    viewpoint: str = Field(description="拍攝方位：front | front_left_45 | left | rear_left_45 | rear | rear_right_45 | right | front_right_45 | top | interior | other")
    sharpness: str = Field(description="sharp | slightly_blurred | blurred")
    environment_flags: list[str] = Field(description=f"環境條件，可多選，來自：{ENV_FLAG_CODES}；無則空陣列")
    license_plate_visible: bool = Field(description="車牌是否清楚可辨識")
    license_plate_text: str = Field(description="車牌號碼，看不清楚填空字串")
    covered_panels: list[PanelCoverage] = Field(description="這張照片有效涵蓋的分區及其觀測品質。完全未入鏡的分區不要列出")
    retake_recommended: list[str] = Field(description="建議重拍的分區代碼（該分區入鏡但品質過差），無則空陣列")
    retake_reason: str = Field(description="若建議重拍，一句話說明原因；否則空字串")


SYSTEM = f"""你是車輛影像品質評估員。你的任務不是找出損傷，而是評估這張照片對車輛各部位的「觀測有效性」。

請判斷這張照片有效涵蓋了哪些車體分區，以及每個分區的觀測品質。

【觀測品質評分標準】
1.0  分區完整入鏡，銳利對焦，光線均勻，無反光遮蔽，佔畫面比例足夠可辨識 5mm 級細節
0.8  分區完整入鏡，可辨識 2cm 級損傷，但有輕微模糊、逆光或局部反光
0.6  分區部分入鏡或距離過遠，僅能辨識 5cm 以上的明顯損傷
0.3  分區僅邊緣入鏡、嚴重反光、被物件遮擋，或角度過斜導致表面資訊遺失
0.0  分區完全未入鏡（這種請直接不要列出，不要給 0 分項目）

【必須額外標記的環境條件】
{env_flags_table()}

這些條件會影響後續損傷判定的可信度，請務必誠實標記。寧可標記過多，不要遺漏。

【重要】
- 你評的是「看不看得清楚」，不是「有沒有損傷」。一個完好無損但拍得很清楚的門板，quality 應該是 0.9。
- 不要為了讓覆蓋度好看而灌高分。這個分數的用途是保護用戶：分數偏高會導致系統把
  「其實沒拍清楚」的部位當成可信基準，進而誤判用戶造成新損。誠實低估遠優於高估。
- 只列出你確實在畫面中看到的分區。沒入鏡就不要列。"""


def _prompt(angle: str | None) -> str:
    codes = panels_for_angle(angle)
    hint = f"\n\n本張照片的拍攝方位為【{angle}】，預期可見以下分區：" if angle else \
           "\n\n【分區代碼表】（只能使用以下代碼）："
    return SYSTEM + hint + "\n" + panels_table(codes)


def assess_photo(path, angle=None, client=None, throttle=None, model=MODEL) -> dict:
    """單張照片的觀測覆蓋度。回傳 dict（含 covered_panels）。"""
    client = client or get_client()
    throttle = throttle or Throttle(8)
    valid = set(panels_for_angle(angle))
    contents = ["待評估照片：",
                types.Part.from_bytes(data=prep_image(str(path)), mime_type="image/jpeg"),
                "請評估這張照片對各車體分區的觀測有效性。"]
    for attempt in range(3):
        throttle.wait()
        try:
            resp = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_prompt(angle),
                    response_mime_type="application/json",
                    response_schema=PhotoCoverage,
                    temperature=0.1,
                ),
            )
            if resp.parsed:
                out = resp.parsed.model_dump()
                # 模型仍可能吐出代碼表外的分區——直接丟棄，不讓幻覺汙染基準檔
                bad = [p for p in out["covered_panels"] if p["panel"] not in valid]
                out["covered_panels"] = [p for p in out["covered_panels"] if p["panel"] in valid]
                out["environment_flags"] = [f for f in out["environment_flags"] if f in ENV_FLAG_CODES]
                out["retake_recommended"] = [p for p in out["retake_recommended"] if p in valid]
                if bad:
                    out["dropped_invalid_panels"] = [p["panel"] for p in bad]
                out["photo"] = str(path)
                out["angle"] = angle
                return out
        except Exception as e:
            if attempt == 2:
                return {"photo": str(path), "angle": angle, "error": str(e)[:160]}
            time.sleep(10 * (attempt + 1))
    return {"photo": str(path), "angle": angle, "error": "retries exhausted"}


def merge_coverage(photo_results: list[dict]) -> dict:
    """多張照片 → panel_coverage_map（每分區取最佳品質）。"""
    best: dict[str, dict] = {}
    for r in photo_results:
        if r.get("error"):
            continue
        for p in r.get("covered_panels", []):
            cur = best.get(p["panel"])
            if cur is None or p["quality"] > cur["best_quality"]:
                best[p["panel"]] = {"panel": p["panel"], "best_quality": p["quality"],
                                    "observed_in": [r["photo"]]}
            elif r["photo"] not in cur["observed_in"]:
                cur["observed_in"].append(r["photo"])
    cov = sorted(best.values(), key=lambda x: -x["best_quality"])
    scored = [c["best_quality"] for c in cov]
    return {
        "panel_coverage_map": cov,
        "overall_coverage_score": round(sum(scored) / len(scored), 3) if scored else 0.0,
        "panels_observed": len(cov),
        "panels_trustworthy": sum(1 for q in scored if q >= Q_FULL_TRUST),
        "panels_unclaimable": sum(1 for q in scored if q < Q_MIN_CLAIM),
    }


def prior_quality(coverage_map: list[dict] | dict, panel: str | None) -> float | None:
    """查某分區的基準觀測品質（prior_q）。查無資料回傳 None（呼叫端須自行決定保守值）。"""
    if panel is None:
        return None
    items = coverage_map.get("panel_coverage_map", []) if isinstance(coverage_map, dict) else coverage_map
    for c in items:
        if c["panel"] == panel:
            return c["best_quality"]
    return None


# ---------- CLI ----------

def _run_pairs(args):
    """對 pairs.json 全部【借車照】跑覆蓋度 → 建立每案的基準（prior_q 來源）。"""
    pairs = json.loads((HERE / "pairs.json").read_text())["pairs"]
    if args.limit:
        pairs = pairs[: args.limit]
    out_path = HERE / "coverage_baseline.json"
    prog_path = HERE / "coverage_progress.jsonl"

    done: dict[str, dict] = {}
    if prog_path.exists():
        for line in prog_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                done[f"{r['car']}-{r['angle']}"] = r
    todo = [p for p in pairs if f"{p['car']}-{p['angle']}" not in done]
    print(f"借車照覆蓋度：共 {len(pairs)} 組，已完成 {len(done)}，待跑 {len(todo)}", flush=True)
    if todo:
        print(f"預估至少 {len(todo) / args.rpm:.0f} 分鐘（rpm={args.rpm}）", flush=True)

    client = get_client()
    throttle = Throttle(args.rpm)
    lock = threading.Lock()
    for i, p in enumerate(todo):
        r = assess_photo(p["pickup"], angle=p["angle"], client=client, throttle=throttle)
        r.update(car=p["car"], angle=p["angle"], role="pickup")
        key = f"{p['car']}-{p['angle']}"
        done[key] = r
        with lock, prog_path.open("a") as f:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if r.get("error"):
            print(f"  [{i+1}/{len(todo)}] {key} → ERROR {r['error'][:60]}", flush=True)
        else:
            qs = [c["quality"] for c in r["covered_panels"]]
            print(f"  [{i+1}/{len(todo)}] {key} → {len(qs)} 分區，"
                  f"最佳 {max(qs, default=0):.1f}／平均 {sum(qs)/len(qs) if qs else 0:.2f}"
                  f"  {r['environment_flags']}", flush=True)

    # 每案一份 coverage map（單張借車照即該案基準）
    baseline = {}
    for key, r in done.items():
        if r.get("error"):
            baseline[key] = {"error": r["error"], "car": r["car"], "angle": r["angle"]}
            continue
        m = merge_coverage([r])
        m.update(car=r["car"], angle=r["angle"], environment_flags=r["environment_flags"],
                 sharpness=r["sharpness"], source_photo=r["photo"])
        baseline[key] = m
    out_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=1))

    ok = [b for b in baseline.values() if not b.get("error")]
    if ok:
        allq = [c["best_quality"] for b in ok for c in b["panel_coverage_map"]]
        allq.sort()
        pct = lambda q: allq[int(q * (len(allq) - 1))] if allq else 0
        print(f"\n{len(ok)} 案基準寫入 {out_path.name}")
        print(f"分區觀測品質 {len(allq)} 筆：p10={pct(.1):.2f} p50={pct(.5):.2f} p90={pct(.9):.2f}")
        print(f"可完全信任(≥{Q_FULL_TRUST}) {sum(1 for q in allq if q >= Q_FULL_TRUST)/len(allq):.1%}"
              f"／不得主張(<{Q_MIN_CLAIM}) {sum(1 for q in allq if q < Q_MIN_CLAIM)/len(allq):.1%}")


def main():
    ap = argparse.ArgumentParser(description="Stage 1 觀測覆蓋度評估")
    ap.add_argument("photo", nargs="?", help="單張照片路徑")
    ap.add_argument("--angle", help="拍攝方位（左前/左後/右前/右後），裁切分區選項")
    ap.add_argument("--pairs", action="store_true", help="跑 pairs.json 全部借車照建基準")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rpm", type=int, default=8)
    args = ap.parse_args()

    if args.pairs:
        _run_pairs(args)
    elif args.photo:
        r = assess_photo(args.photo, angle=args.angle)
        if not r.get("error"):
            r.update(merge_coverage([r]))
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        ap.error("請給照片路徑，或用 --pairs 跑全資料集")


if __name__ == "__main__":
    main()
