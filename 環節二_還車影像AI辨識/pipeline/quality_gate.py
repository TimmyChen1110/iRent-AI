#!/usr/bin/env python3
"""① Image Quality Gate：上傳當下即時檢核照片品質，不合格直接要求重拍。

純 CV、零 API 成本、單張 <50ms，可放在 App 端或上傳 API 上：
  - 清晰度：灰階 Laplacian 變異數（低 = 模糊/失焦）
  - 曝光：亮度直方圖（過暗 / 過曝）

門檻用全資料集分位數校準（抓最差的尾巴），並驗證已知爛照
（RDZ-0187 過暗模糊、無法人工複驗的存疑案例）會被攔下。

用法：python3 quality_gate.py            # 跑 pairs.json 全部照片 + 統計
      python3 quality_gate.py 照片路徑    # 單張檢核
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

HERE = Path(__file__).resolve().parent

# 門檻（由本資料集 282 張借還照分位數校準，見 __main__ 統計輸出）
BLUR_MIN = 60.0      # Laplacian variance；低於此值 → 模糊
DARK_MAX = 55.0      # 平均亮度；低於此值 → 過暗
BRIGHT_MIN = 235.0   # 過曝：平均亮度高於此值
CLIP_MAX = 0.35      # 過曝：≥250 的像素占比高於此值

# 車內照專用門檻。來源只能由歷史 80 張「車內照欄位」候選影像反向推定——原始校準腳本/
# 輸出未保存，以下數字為分位數指紋比對的高信度推論，非可重現的原始紀錄：該批次亮度
# p10≈47（車外門檻 55 僅計過暗條件會擋 10/80=12.5%）、Laplacian p5≈16、最低 1.4，
# 門檻設在 ~p1 只擋無法判讀的尾巴（重放攔 3/80≈4%）。後續模型 photo_ok 判定中
# 24 張為 photo_ok=True、56 張為 photo_ok=False（模型輸出，非人工 Ground Truth）；
# 歷史重放中 24 張 photo_ok=True 影像被本 gate 擋下 0 張——此僅描述 gate 與 photo_ok
# 分組的重放關係，因缺完整人工 Ground Truth，不代表 false-reject rate 為 0。
INT_BLUR_MIN = 8.0
INT_DARK_MAX = 15.0


def measure(path, max_w=1280):
    """回傳 (sharpness, brightness, highlight_clip)。與判定 pipeline 相同的前處理。"""
    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)))
    g = np.asarray(im, dtype=np.uint8)
    sharp = cv2.Laplacian(g, cv2.CV_64F).var()
    bright = float(g.mean())
    clip = float((g >= 250).mean())
    return sharp, bright, clip


def gate(path, interior=False):
    """回傳 (通過?, 原因列表, 數值)。原因供 App 端顯示重拍提示。
    interior=True 時改用車內照門檻（車內天生較暗、表面平滑，車外門檻會誤擋 12.5%）。"""
    blur_min, dark_max = (INT_BLUR_MIN, INT_DARK_MAX) if interior else (BLUR_MIN, DARK_MAX)
    sharp, bright, clip = measure(path)
    reasons = []
    if sharp < blur_min:
        reasons.append(f"照片模糊（清晰度 {sharp:.0f} < {blur_min:.0f}），請對焦後重拍")
    if bright < dark_max:
        reasons.append(f"照片過暗（亮度 {bright:.0f} < {dark_max:.0f}），請開閃光或移到亮處重拍")
    if bright > BRIGHT_MIN or clip > CLIP_MAX:
        reasons.append("照片過曝，請避開強光直射重拍")
    return not reasons, reasons, {"sharpness": round(sharp, 1),
                                  "brightness": round(bright, 1),
                                  "highlight_clip": round(clip, 3)}


def main():
    if len(sys.argv) > 1:
        ok, reasons, m = gate(sys.argv[1])
        print(json.dumps({"pass": ok, "reasons": reasons, **m}, ensure_ascii=False, indent=1))
        return

    pairs = json.loads((HERE / "pairs.json").read_text())["pairs"]
    photos = sorted({p["pickup"] for p in pairs} | {p["return"] for p in pairs})
    rows = []
    for f in photos:
        ok, reasons, m = gate(f)
        rows.append({"file": Path(f).name, "pass": ok, "reasons": reasons, **m})

    sharps = sorted(r["sharpness"] for r in rows)
    brights = sorted(r["brightness"] for r in rows)
    pct = lambda arr, q: arr[int(q * (len(arr) - 1))]
    fails = [r for r in rows if not r["pass"]]
    out = {
        "n": len(rows),
        "thresholds": {"blur_min": BLUR_MIN, "dark_max": DARK_MAX,
                       "bright_min": BRIGHT_MIN, "clip_max": CLIP_MAX},
        "sharpness_pctile": {"p1": pct(sharps, .01), "p5": pct(sharps, .05),
                             "p50": pct(sharps, .50)},
        "brightness_pctile": {"p1": pct(brights, .01), "p5": pct(brights, .05),
                              "p50": pct(brights, .50)},
        "fail_count": len(fails),
        "fail_pct": round(100 * len(fails) / len(rows), 1),
        "fails": fails,
    }
    (HERE / "quality_gate_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"{len(rows)} 張檢核，攔下 {len(fails)} 張（{out['fail_pct']}%）")
    print("清晰度分位 p1/p5/p50:", out["sharpness_pctile"])
    print("亮度分位   p1/p5/p50:", out["brightness_pctile"])
    for r in fails:
        print(f"  ✗ {r['file']}  sharp={r['sharpness']} bright={r['brightness']}  → {r['reasons']}")


if __name__ == "__main__":
    main()
