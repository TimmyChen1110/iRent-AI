#!/usr/bin/env python3
"""B — 對 photo_chain 候選照片跑純 CV 品質門檻（零 API 成本）。

用途：在送 VLM 判讀前，先用 quality_gate 攔掉不可判讀的照片，
      並量化「這批新資料有多少張根本不值得送 API」。

預設只掃已下載的 chain_photos/（零網路）；--download N 會補抓 N 台車的照片。
輸出 gate_chain_results.json。
"""
import argparse
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_gate import gate  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAIN_DIR = HERE / "chain_photos"
OUT = HERE / "gate_chain_results.json"
DL_TIMEOUT = 30      # 秒；單張照片下載逾時
DL_WORKERS = 8       # 並行下載數（純網路 I/O，不佔 API 額度）


def _fetch(job):
    """下載單張；回傳 (成功?, 說明)。"""
    url, fp = job
    if fp.exists():
        return True, None
    try:
        # 必須設 timeout：Azure Blob 偶有連線不回應，
        # urlretrieve 預設無逾時會永久掛住整個掃描（實測卡 23 分鐘）
        with urllib.request.urlopen(url, timeout=DL_TIMEOUT) as r:
            data = r.read()
        fp.write_bytes(data)
        return True, None
    except Exception as e:
        fp.unlink(missing_ok=True)   # 不留半截檔，下次可重試
        return False, f"{fp.parent.name}/{fp.name}: {e}"


def download(cars, workers=DL_WORKERS):
    """補抓指定車輛的照片（沿用 photo_chain 的 blob URL）。

    純網路 I/O，不佔任何 API 額度，故可並行；下載為冪等，中斷後重跑即續傳。
    """
    cands = json.loads((HERE / "chain_candidates.json").read_text())
    jobs = []
    for car in cars:
        d = CHAIN_DIR / car
        d.mkdir(parents=True, exist_ok=True)
        for order, itypes in cands[car].items():
            for itype, meta in itypes.items():
                jobs.append((meta["url"], d / f"{order}_{itype}.png"))

    todo = [j for j in jobs if not j[1].exists()]
    print(f"  待下載 {len(todo)} 張（已有 {len(jobs) - len(todo)} 張）", file=sys.stderr)

    got = fail = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, (ok, err) in enumerate(ex.map(_fetch, todo), 1):
            if ok:
                got += 1
            else:
                fail += 1
                print(f"  下載失敗 {err}", file=sys.stderr)
            if i % 100 == 0:
                print(f"  下載 {i}/{len(todo)}", file=sys.stderr)
    if fail:
        print(f"  （{fail} 張失敗，重跑可續傳）", file=sys.stderr)
    return got


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--download", type=int, default=0,
                    help="補抓前 N 台候選車的照片再掃描（0=只掃已下載的）")
    ap.add_argument("--night", action="store_true",
                    help="套夜間車外門檻（照片鏈含大量夜間路邊還車照，日間門檻會誤擋 6.7%%）")
    args = ap.parse_args()

    if args.download:
        cands = json.loads((HERE / "chain_candidates.json").read_text())
        # 固定排序取前 N 台，與 photo_chain.sweep 一致、可重現
        picks = sorted(cands, key=lambda c: (-len(cands[c]), c))[:args.download]
        print(f"補抓 {len(picks)} 台車的照片（逾時 {DL_TIMEOUT}s，可中斷續跑）…", file=sys.stderr)
        n = download(picks)
        print(f"  新增 {n} 張", file=sys.stderr)

    photos = sorted(CHAIN_DIR.rglob("*.png"))
    print(f"掃描 {len(photos)} 張…", file=sys.stderr)

    results, blocked = [], 0
    for i, p in enumerate(photos, 1):
        ok, reasons, m = gate(p, night=args.night)
        if not ok:
            blocked += 1
        results.append({
            "car": p.parent.name,
            "file": p.name,
            "pass": ok,
            "reasons": reasons,
            "metrics": m,
        })
        if i % 50 == 0:
            print(f"  {i}/{len(photos)}", file=sys.stderr)

    n = len(results)
    summary = {
        "scanned": n,
        "passed": n - blocked,
        "blocked": blocked,
        "block_rate": round(100 * blocked / n, 1) if n else 0.0,
        "cars": len({r["car"] for r in results}),
        "threshold": "night" if args.night else "day",
    }
    OUT.write_text(json.dumps({"summary": summary, "results": results},
                              ensure_ascii=False, indent=1))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
