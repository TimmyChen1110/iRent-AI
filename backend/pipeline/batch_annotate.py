#!/usr/bin/env python3
"""為 Dashboard 案例批次產生標註框資料（box_2d）→ dashboard_annotations.json

範圍：v3+級聯判定「有新損」的車外配對 + F2 判定「髒汙」的車內照。
"""
import json
import sys
import time
from pathlib import Path

from google.genai import errors

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, prep_image, Throttle  # noqa: E402
from annotate_damage import analyze, EXT_SYSTEM, INT_SYSTEM    # noqa: E402
from results_config import FINAL_RESULTS, INTERIOR_RESULTS   # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "gemini-3.7-flash"

pairs = {(p["car"], p["angle"]): p for p in json.loads((HERE / "pairs.json").read_text())["pairs"]}
casc = json.loads(FINAL_RESULTS.read_text())["results"]
interior = json.loads(INTERIOR_RESULTS.read_text())["results"]

jobs = []  # (case_id, mode, args)
for r in casc:
    if r["assessment"]["new_damage_found"]:
        jobs.append((f'{r["car"]}-{r["angle"]}', "ext", pairs[(r["car"], r["angle"])]))
for r in interior:
    if r["assessment"]["level"] == "髒汙":
        jobs.append((f'F2-{r["car"]}-{r["type"]}', "int", r))

client = get_client()
throttle = Throttle(8)
out = {}
print(f"{len(jobs)} 個案例待標註")
for i, (cid, mode, arg) in enumerate(jobs):
    for attempt in range(3):
        throttle.wait()
        try:
            if mode == "ext":
                res = analyze(client, MODEL, [
                    ("第一張＝借車照：", prep_image(arg["pickup"])),
                    ("第二張＝還車照：", prep_image(arg["return"])),
                ], EXT_SYSTEM)
            else:
                res = analyze(client, MODEL, [
                    ("車內照：", prep_image(str(HERE / "interior_photos" / arg["file"]))),
                ], INT_SYSTEM)
            if res:
                out[cid] = res.model_dump()
                print(f"  [{i+1:2d}/{len(jobs)}] {cid}: {len(res.findings)} 處", flush=True)
            break
        except errors.APIError as e:
            if e.code in (429, 500, 503):
                time.sleep(20 * (attempt + 1)); continue
            print(f"  [{i+1:2d}/{len(jobs)}] {cid}: ERROR {e.code}", flush=True)
            break

(HERE / "dashboard_annotations.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
print(f"完成：{len(out)}/{len(jobs)} → dashboard_annotations.json")
