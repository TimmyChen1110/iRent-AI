#!/usr/bin/env python3
"""評測結果分析：列出混淆矩陣、誤報 (FP) 與漏抓 (FN) 案例的判定理由，
並依 confidence 門檻掃描 Recall / FPR 曲線（供預警分級調參）。

用法：python3 analyze_eval.py eval_results_gemini_37_flash.json
"""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1] if len(sys.argv) > 1 else "eval_results_gemini_37_flash.json")
data = json.loads(path.read_text())
results = [r for r in data["results"] if r.get("assessment")]

print("=== SUMMARY ===")
print(json.dumps(data["summary"], ensure_ascii=False, indent=2))


def top_conf(r):
    ds = r["assessment"]["damages"]
    return max((d["confidence"] for d in ds), default=0.0)


fps = [r for r in results if r["label"] == "negative" and r["assessment"]["new_damage_found"]]
fns = [r for r in results if r["label"] == "positive" and not r["assessment"]["new_damage_found"]]

print(f"\n=== 誤報 FP ({len(fps)}) ===")
for r in sorted(fps, key=top_conf, reverse=True):
    for d in r["assessment"]["damages"]:
        print(f"  {r['car']} {r['angle']}  conf={d['confidence']:.2f}  {d['location']}/{d['type']}/{d['severity']}")
        print(f"      理由: {d['reasoning']}")

print(f"\n=== 漏抓 FN ({len(fns)}) ===")
for r in fns:
    a = r["assessment"]
    print(f"  {r['car']} {r['angle']}  angle_match={a['angle_match']}  既有損傷備註: {a['pre_existing_notes'][:80]}")

# confidence 門檻掃描：new_damage_found 且 max(confidence) >= t 才觸發預警
print("\n=== confidence 門檻掃描（預警觸發條件：判定新損 且 conf>=t） ===")
pos = [r for r in results if r["label"] == "positive"]
neg = [r for r in results if r["label"] == "negative"]
print(f"{'t':>5} {'Recall':>8} {'FPR':>8} {'FP數':>5}")
for t in [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]:
    flag = lambda r: r["assessment"]["new_damage_found"] and top_conf(r) >= t
    tp = sum(map(flag, pos))
    fp = sum(map(flag, neg))
    print(f"{t:>5.1f} {tp / len(pos):>8.2%} {fp / len(neg):>8.2%} {fp:>5}")

# 角度校驗統計
mismatch = [r for r in results if not r["assessment"]["angle_match"]]
print(f"\nangle_match=False（模型認為無法有效比對）: {len(mismatch)} 組")
for r in mismatch:
    print(f"  {r['car']} {r['angle']} ({r['label']})")
