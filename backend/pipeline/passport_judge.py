#!/usr/bin/env python3
"""護照感知判定實驗：判定時附上車輛損傷護照的既有損清單，
讓 AI 專注回答「護照之外有沒有新東西」。

用法：python3 passport_judge.py --car RDH-3092 --angle 左後 --votes 3
"""
import argparse
import json
import sys
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, prep_image, Assessment, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent

SYSTEM = """你是 iRent 共享汽車的車況比對專家。你會收到同一台車、同一方位的借車照與還車照，
以及該車的【損傷護照】——已登錄的既有損傷清單。

任務：判斷還車照中是否存在【護照上沒有、借車照也沒有】的新增車損。

準則：
1. 護照上已登錄的損傷是已知事實，不需要重新判斷、不算新增；你只需專注找「新的東西」。
2. 光線反射、水痕、髒污、倒影不是車損。
3. 找到疑似新損時，確認它不在護照清單描述的位置範圍內；同位置但明顯擴大/加重也算新增。
4. no_damage_confidence 誠實反映把握程度。"""


def judge_with_passport(client, model, pair, passport_notes, votes=3):
    throttle = Throttle(8)
    results = []
    for _ in range(votes):
        throttle.wait()
        resp = client.models.generate_content(
            model=model,
            contents=[
                f"方位：{pair['angle']}。\n【損傷護照】該車已登錄既有損傷：\n{passport_notes}\n",
                "第一張＝借車照：",
                types.Part.from_bytes(data=prep_image(pair["pickup"]), mime_type="image/jpeg"),
                "第二張＝還車照：",
                types.Part.from_bytes(data=prep_image(pair["return"]), mime_type="image/jpeg"),
                "請判斷是否有護照之外的新增損傷。",
            ],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM,
                response_mime_type="application/json",
                response_schema=Assessment,
                temperature=0.1,
            ),
        )
        if resp.parsed:
            results.append(resp.parsed)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car", required=True)
    ap.add_argument("--angle", required=True)
    ap.add_argument("--votes", type=int, default=3)
    ap.add_argument("--model", default="gemini-3.7-flash")
    args = ap.parse_args()

    pairs = {(p["car"], p["angle"]): p for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}
    passports = json.loads((HERE / "passports.json").read_text())
    pair = pairs[(args.car, args.angle)]

    p = passports.get(args.car, {"records": []})
    notes = "\n".join(f"- [{r['id']}] {r['angle']} {r['location']}（{r['type']}）"
                      for r in p["records"] if r["kind"] == "pre_existing") or "（無既有損登錄）"
    print(f"護照既有損：\n{notes}\n")

    client = get_client()
    votes = judge_with_passport(client, args.model, pair, notes, args.votes)
    found = [v for v in votes if v.new_damage_found]
    print(f"判定 {len(votes)} 票：{len(found)} 票有新損 / {len(votes)-len(found)} 票無")
    for v in votes:
        if v.new_damage_found:
            for d in v.damages:
                print(f"  ★ {d.location} | {d.type} | conf={d.confidence:.2f} — {d.reasoning}")
        else:
            print(f"  － 無新損 (no_damage_conf={v.no_damage_confidence:.2f})")


if __name__ == "__main__":
    main()
