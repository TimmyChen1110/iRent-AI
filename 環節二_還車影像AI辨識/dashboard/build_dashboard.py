#!/usr/bin/env python3
"""組裝複核後台 Dashboard：shell 模板 + 資料區塊 + three.js → 單一自包含 HTML。

資料全部從 pipeline/ 的實測結果與照片即時生成（縮圖轉 base64 內嵌）。
輸出：irent-review-dashboard.html（約 4.6MB），可直接發佈為 Artifact。

用法：python3 build_dashboard.py
"""
import base64
import io
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"


def thumb(path, w=480, q=55, exif=True):
    im = Image.open(path)
    if exif:
        im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    im = im.resize((w, int(im.height * w / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode()


def build_cases():
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((PIPE / "pairs.json").read_text())["pairs"]}
    data = json.loads((PIPE / "eval_results_v2_exif.json").read_text())["results"]

    def level(a):
        if not a["angle_match"]:
            return "P2", "無法比對"
        if a["new_damage_found"]:
            mx = max((d["confidence"] for d in a["damages"]), default=0)
            hi = any(d["severity"] == "high" for d in a["damages"])
            return ("P1", "新車損") if (mx >= 0.85 or hi) else ("P2", "疑似新損")
        return "P3", "正常"

    # 全部正樣本 + 有預警的負樣本 + 6 組乾淨對照
    sel, clean_quota = [], 6
    for r in data:
        a = r.get("assessment")
        if not a:
            continue
        lv, kind = level(a)
        keep = r["label"] == "positive" or lv != "P3"
        if not keep and clean_quota > 0:
            keep = True
            clean_quota -= 1
        if keep:
            sel.append((r, lv, kind))

    cases = []
    for r, lv, kind in sel:
        p = pairs[(r["car"], r["angle"])]
        cases.append({
            "id": f'{r["car"]}-{r["angle"]}',
            "car": r["car"], "angle": r["angle"], "level": lv, "kind": kind,
            "truth": "claimed" if r["label"] == "positive" else "unclaimed",
            "assessment": r["assessment"],
            "pickup": thumb(p["pickup"]), "ret": thumb(p["return"]),
        })
    order = {"P1": 0, "P2": 1, "P3": 2}
    cases.sort(key=lambda c: (order[c["level"]], c["car"]))
    return cases


def build_f2cases():
    data = json.loads((PIPE / "interior_results.json").read_text())["results"]
    by = {r["file"]: r for r in data}
    scores = {}
    sf = PIPE / "cleanliness_scores.json"
    if sf.exists():
        scores = {r["file"]: r for r in json.loads(sf.read_text())["results"]}
    picks = [
        ("H47353140_10_20260422165538.png", "P1"),  # 髒汙 寶特瓶（Pro 翻轉）
        ("H47352286_11_20260422153644.png", "P1"),  # 髒汙 衛生紙
        ("H47347748_11_20260422054929.png", "P1"),  # 髒汙 碎屑污漬（人工確認）
    ]
    mis = [r for r in data if "無法" in r["assessment"]["reasoning"]][:1]
    clean = [r for r in data if r["assessment"]["level"] == "乾淨"][:2]
    cases = [{"r": by[f], "level": lv, "kind": "車內髒汙"} for f, lv in picks]
    cases += [{"r": r, "level": "P2", "kind": "分類錯置"} for r in mis]
    cases += [{"r": r, "level": "P3", "kind": "車內正常"} for r in clean]

    out = []
    for c in cases:
        r = c["r"]
        a = r["assessment"]
        out.append({
            "id": f"F2-{r['car']}-{r['type']}",
            "car": r["car"], "angle": "前車內" if r["type"] == "front" else "後車內",
            "level": c["level"], "kind": c["kind"], "f2": True,
            "truth": "interior",
            "assessment": {
                "level": a["level"], "confidence": a["confidence"],
                "issues": a["issues"], "reasoning": a["reasoning"],
                "reviewed": bool(r.get("reviewed")),
                "flash_level": (r.get("flash_assessment") or {}).get("level"),
                "score": (scores.get(r["file"]) or {}).get("score"),
                "score_items": (scores.get(r["file"]) or {}).get("issues"),
            },
            "photo": thumb(PIPE / "interior_photos" / r["file"], exif=False),
        })
    return out


def main():
    blocks = [
        "const CASES=" + json.dumps(build_cases(), ensure_ascii=False) + ";",
        "const F2CASES=" + json.dumps(build_f2cases(), ensure_ascii=False) + ";",
        "const ANNOTATIONS=" + (PIPE / "dashboard_annotations.json").read_text() + ";",
        "const PASSPORT_DATA=" + (PIPE / "passports.json").read_text() + ";",
    ]
    shell = (HERE / "dashboard_shell.html").read_text()
    three = (HERE / "three.min.js").read_text()
    html = (shell
            .replace("<!--DATA-->", "\n".join(f"<script>{b}</script>" for b in blocks))
            .replace("<!--THREE-->", f"<script>{three}</script>"))
    out = HERE / "irent-review-dashboard.html"
    out.write_text(html)
    print(f"assembled {len(html)/1e6:.2f} MB → {out.name}")

    ok = True
    for i, s in enumerate(re.findall(r"<script>(.*?)</script>", html, re.S)):
        p = HERE / f"_chk{i}.js"
        p.write_text(s)
        r = subprocess.run(["node", "--check", str(p)], capture_output=True, text=True)
        if r.returncode:
            ok = False
            print("block", i, r.stderr[:300])
        p.unlink()
    print("syntax all OK" if ok else "SYNTAX FAIL")


if __name__ == "__main__":
    main()
