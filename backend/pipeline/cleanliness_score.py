#!/usr/bin/env python3
"""③ Cleanliness Score：可解釋的車內整潔計分。

兩段式設計：
  1. AI 只做「問題盤點」——從固定類別 enum 找出車內問題與程度（結構化輸出）。
  2. 分數在程式端加權計算（100 分起扣）——權重透明、可調，不用重跑 API。

分級規則：score ≥ 85 乾淨 / 60~84 普通 / < 60 髒汙。
輸出 cleanliness_scores.json，並回報「計分制 vs 既有級聯判定」的一致率當校驗。

用法：python3 cleanliness_score.py             # 全量 80 張（RPM 8 約 10 分）
      python3 cleanliness_score.py --rescore   # 只重算分數（零 API）
"""
import argparse
import json
import sys
from pathlib import Path
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, prep_image, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
PHOTOS = HERE / "interior_photos"
MODEL = "gemini-3.7-flash"

CATEGORIES = ["垃圾", "飲料杯瓶", "食物殘渣", "液體污漬", "泥沙灰塵",
              "菸蒂菸灰", "毛髮", "座椅髒污", "腳踏墊髒污", "遺留物品", "其他"]

# 每類 × 程度(輕微/中等/嚴重) 的扣分權重——透明、可調、零 API 成本
WEIGHTS = {
    "垃圾":     (10, 20, 32), "飲料杯瓶": (10, 18, 28), "食物殘渣": (12, 22, 35),
    "液體污漬": (10, 20, 32), "泥沙灰塵": (5, 12, 24),  "菸蒂菸灰": (18, 30, 45),
    "毛髮":     (6, 12, 22),  "座椅髒污": (8, 16, 28),  "腳踏墊髒污": (5, 10, 20),
    "遺留物品": (8, 14, 22),  "其他":     (5, 10, 18),
}
EXTENTS = ["輕微", "中等", "嚴重"]


class Issue(BaseModel):
    category: Literal[tuple(CATEGORIES)]
    extent: Literal[tuple(EXTENTS)] = Field(description="輕微=零星少量 / 中等=明顯可見 / 嚴重=大量或大面積")
    note: str = Field(description="一句話描述看到什麼、在哪裡")


class Inventory(BaseModel):
    issues: list[Issue] = Field(description="觀察到的所有整潔問題；完全乾淨則空陣列")
    photo_ok: bool = Field(description="照片是否為可判讀的車內照（車外照/全黑照為 false）")


SYSTEM = """你是 iRent 共享汽車的車內整潔盤點員。你會收到一張還車時拍的車內照片。
請盤點照片中所有「整潔問題」，每個問題從固定類別中選一類並標註程度。

準則：
1. 車輛固定配備（兒童座椅、置物盒、原廠腳踏墊本身）不是問題。
2. 光影、座椅紋路、深色內裝反光不是污漬。
3. 前一位用戶遺留的私人物品（雨傘、衣物）歸「遺留物品」。
4. 只列真的看得到的問題；乾淨就回空陣列，不要硬找。
5. 非車內照（拍到車外、全黑無法判讀）→ photo_ok = false。"""


def score_of(issues):
    s = 100
    for it in issues:
        s -= WEIGHTS[it["category"]][EXTENTS.index(it["extent"])]
    return max(0, s)


def level_of(score, issues=()):
    # 規則層優先：嚴重問題或中等以上的污漬/菸蒂直接判髒汙，不看總分
    for it in issues:
        if it["extent"] == "嚴重":
            return "髒汙"
        if it["category"] in ("液體污漬", "菸蒂菸灰", "食物殘渣") and it["extent"] != "輕微":
            return "髒汙"
    return "乾淨" if score >= 85 else ("普通" if score >= 60 else "髒汙")


def rescore():
    rows = [json.loads(l) for l in (HERE / "cleanliness_progress.jsonl").read_text().splitlines()]
    return {r["file"]: r for r in rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--rpm", type=int, default=8)
    args = ap.parse_args()

    items = json.loads((HERE / "interior_sample.json").read_text())
    prog = HERE / "cleanliness_progress.jsonl"
    done = rescore() if prog.exists() else {}

    if not args.rescore:
        client = get_client()
        throttle = Throttle(args.rpm)
        todo = [i for i in items if i["file"] not in done]
        print(f"{len(items)} 張，待盤點 {len(todo)}")
        with prog.open("a") as f:
            for n, item in enumerate(todo):
                throttle.wait()
                try:
                    resp = client.models.generate_content(
                        model=MODEL,
                        contents=[
                            f"車內照（{'前座' if item['type']=='front' else '後座'}）：",
                            types.Part.from_bytes(data=prep_image(str(PHOTOS / item["file"])), mime_type="image/jpeg"),
                            "請盤點整潔問題。",
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM,
                            response_mime_type="application/json",
                            response_schema=Inventory,
                            temperature=0.1,
                        ),
                    )
                except Exception as e:
                    print(f"  ! {item['file']} {str(e)[:80]}")
                    continue
                if not resp.parsed:
                    print(f"  ! {item['file']} no parse")
                    continue
                row = {**{k: item[k] for k in ("order", "car", "type", "file")},
                       **resp.parsed.model_dump()}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                done[row["file"]] = row
                sc = score_of(row["issues"]) if row["photo_ok"] else None
                print(f"  [{n+1:2d}/{len(todo)}] {item['car']:9s} {item['type']:5s} → "
                      f"{'score '+str(sc)+' '+level_of(sc) if sc is not None else '非車內照'} "
                      f"({len(row['issues'])} 項)", flush=True)

    # 計分 + 與既有級聯判定比對
    old = {r["file"]: r for r in json.loads((HERE / "interior_results.json").read_text())["results"]}
    out, agree, comp = [], 0, 0
    for f_, r in done.items():
        sc = score_of(r["issues"]) if r["photo_ok"] else None
        lv = level_of(sc, r["issues"]) if sc is not None else "無法判定"
        o = old.get(f_, {}).get("assessment")
        if o and sc is not None:
            comp += 1
            agree += (lv == o["level"])
        detail = [{**i, "deduction": WEIGHTS[i["category"]][EXTENTS.index(i["extent"])]}
                  for i in r["issues"]]
        out.append({**r, "issues": detail, "score": sc, "level": lv,
                    "cascade_level": o["level"] if o else None})
    out.sort(key=lambda r: (r["score"] is None, r["score"] if r["score"] is not None else 0))
    from collections import Counter
    dist = Counter(r["level"] for r in out)
    summary = {"n": len(out), "distribution": dict(dist),
               "agreement_with_cascade": f"{agree}/{comp}",
               "agreement_pct": round(100 * agree / comp, 1) if comp else None,
               "weights": WEIGHTS}
    (HERE / "cleanliness_scores.json").write_text(
        json.dumps({"summary": summary, "results": out}, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "weights"}, ensure_ascii=False, indent=1))
    print("\n最髒 5 名：")
    for r in [x for x in out if x["score"] is not None][:5]:
        print(f"  {r['score']:3d} {r['level']} {r['car']} {r['type']:5s} — "
              + "；".join(f"{i['category']}({i['extent']})" for i in r["issues"]))


if __name__ == "__main__":
    main()
