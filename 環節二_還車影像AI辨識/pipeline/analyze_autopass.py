#!/usr/bin/env python3
"""Auto Pass KPI：從既有 141 組實測結果統計「AI 自動放行 / 自動預警 / 需人工複核」比例。

分流規則（與 Dashboard、run_cascade 一致）：
  - 無法比對（angle_match=false）        → 人工（補件流程）
  - 有新損且高信心（conf≥0.85 或 high）  → 自動預警（P1，直接進車損流程）
  - 有新損但低信心                        → 人工複核（P2）
  - 無新損                                → 自動放行（P3）

另附誠實檢核：自動放行的案件對照人工重標真值，看漏放幾件。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_cascade import needs_escalation  # noqa: E402

HERE = Path(__file__).resolve().parent

flash = json.loads((HERE / "eval_results_gemini_37_flash_v3.json").read_text())["results"]
final = json.loads((HERE / "eval_results_gemini_37_flash_v3_cascaded.json").read_text())["results"]
relabels = {(r["car"], r["angle"]): r
            for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}


def route(a):
    if not a["angle_match"]:
        return "human", "P2 無法比對"
    if a["new_damage_found"]:
        mx = max((d["confidence"] for d in a["damages"]), default=0)
        hi = any(d["severity"] == "high" for d in a["damages"])
        if mx >= 0.85 or hi:
            return "alert", "P1 自動預警"
        return "human", "P2 疑似新損"
    return "auto", "P3 自動放行"


n = len(final)
# 級聯升級量（Flash 快篩後需要 Pro 複核的比例）
escalated = [r for r in flash if r.get("assessment") and needs_escalation(r["assessment"])]

buckets = {"auto": [], "alert": [], "human": []}
for r in final:
    b, _ = route(r["assessment"])
    buckets[b].append(r)

# 誠實檢核：自動放行的案件，真值（人工重標）是否其實有新損
missed = []
for r in buckets["auto"]:
    rl = relabels.get((r["car"], r["angle"]), {})
    truth = rl.get("relabel", "damage" if r["label"] == "positive" else "no_damage")
    if truth == "damage":
        missed.append(f'{r["car"]} {r["angle"]}')

auto, alert, human = (len(buckets[b]) for b in ("auto", "alert", "human"))
kpi = {
    "n": n,
    "flash_escalated_to_pro": {"count": len(escalated), "pct": round(100 * len(escalated) / n, 1)},
    "auto_pass": {"count": auto, "pct": round(100 * auto / n, 1)},
    "auto_alert_p1": {"count": alert, "pct": round(100 * alert / n, 1)},
    "human_review": {"count": human, "pct": round(100 * human / n, 1)},
    "human_or_alert_pct": round(100 * (human + alert) / n, 1),
    "auto_pass_missed_vs_truth": missed,
}
(HERE / "autopass_kpi.json").write_text(json.dumps(kpi, ensure_ascii=False, indent=1))
print(json.dumps(kpi, ensure_ascii=False, indent=1))
print(f"\n一句話：AI 自動放行 {kpi['auto_pass']['pct']}%、自動預警 {kpi['auto_alert_p1']['pct']}%，"
      f"真正需要人工逐案複核的只有 {kpi['human_review']['pct']}%；"
      f"自動放行 {auto} 件中對照人工重標僅漏 {len(missed)} 件。")
