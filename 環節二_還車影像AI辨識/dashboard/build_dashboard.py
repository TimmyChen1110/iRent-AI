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
import sys
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent
PIPE = HERE.parent / "pipeline"
sys.path.insert(0, str(PIPE))

from results_config import FINAL_RESULTS, INTERIOR_RESULTS  # noqa: E402


def pair_url(path):
    return "/photos/pair/" + quote(Path(path).name)


def interior_url(fname):
    return "/photos/interior/" + quote(fname)


def car_model_block():
    """GLTFLoader + 車輛 GLB（base64 內嵌，CC0：Kenney Car Kit hatchback）。缺檔時回空字串（前端自動退回程式拼建車）。"""
    loader, glb = HERE / "GLTFLoader.js", HERE / "car.glb"
    if not (loader.exists() and glb.exists()):
        return ""
    b64 = base64.b64encode(glb.read_bytes()).decode()
    return f"<script>{loader.read_text()}</script>\n<script>const CAR_GLB_B64=\"{b64}\";</script>"


def thumb(path, w=480, q=55, exif=True):
    im = Image.open(path)
    if exif:
        im = ImageOps.exif_transpose(im)
    im = im.convert("RGB")
    im = im.resize((w, int(im.height * w / im.width)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q)
    return base64.b64encode(buf.getvalue()).decode()


def _pricing(a: dict, angle: str) -> dict | None:
    """S6：對判定結果算出維修動作、級距與估價區間（disposition.py，零 API）。

    判定回答「有沒有損傷」，這層回答「所以要花多少錢、值不值得追」。
    失敗回 None——估價是加值，不能拖垮 Dashboard 產出。
    """
    if not (a or {}).get("new_damage_found"):
        return None
    try:
        import disposition                       # noqa: PLC0415
        from diff_new_damage import panel_of     # noqa: PLC0415
        items, lo, hi = [], 0, 0
        for d in a.get("damages") or []:
            it = disposition.assess(d, panel=panel_of(d, angle))
            it["location"] = d.get("location")
            items.append(it)
            if it.get("claimable"):
                lo += it["estimate_twd"][0]
                hi += it["estimate_twd"][1]
        return {"items": items, "total_estimate_twd": [lo, hi],
                "claimable_count": sum(1 for i in items if i.get("claimable")),
                "waived_count": sum(1 for i in items
                                    if i.get("disposition") == "waive_not_worth_claiming"),
                "note": "級距示意區間，實際以維修廠估價為準"}
    except Exception:
        return None


def build_cases(embed=True):
    """embed=True 時照片轉 base64 內嵌（單檔版）；False 時給 /photos/ URL（server 版）。"""
    pairs = {(p["car"], p["angle"]): p
             for p in json.loads((PIPE / "pairs.json").read_text())["pairs"]}
    data = json.loads(FINAL_RESULTS.read_text())["results"]

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
            # S6 估價與處置（純規則零 API）——客服複核時真正需要的是「所以要花多少錢」
            "pricing": _pricing(r["assessment"], r["angle"]),
            "pickup": thumb(p["pickup"]) if embed else pair_url(p["pickup"]),
            "ret": thumb(p["return"]) if embed else pair_url(p["return"]),
        })
    order = {"P1": 0, "P2": 1, "P3": 2}
    cases.sort(key=lambda c: (order[c["level"]], c["car"]))
    return cases


def build_f2cases(embed=True):
    data = json.loads(INTERIOR_RESULTS.read_text())["results"]
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
            "photo": thumb(PIPE / "interior_photos" / r["file"], exif=False) if embed else interior_url(r["file"]),
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
            .replace("<!--THREE-->", f"<script>{three}</script>")
            .replace("<!--CARMODEL-->", car_model_block()))
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
