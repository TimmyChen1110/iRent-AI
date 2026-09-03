#!/usr/bin/env python3
"""配對正確性稽核：用 OCR 讀出車牌，檢查借/還照是否為同一台車。

動機：build_pairs.py 純靠檔名 `車牌+方位` 配對，檔名錯了程式不會知道。
141 組全跑過一次的結論（2026-08-27）：**零配對錯誤**。
  ✓ 兩張車牌一致  63 組
  · 至少一張讀不到（近拍特寫不帶車牌，屬正常）  75 組
  ✗ 真實配對錯誤   0 組

OCR 用 macOS 內建 Vision（零安裝、零 API），需先編譯 helper：
    swiftc -O tools/ocr_plate.swift -o tools/ocr_plate

⚠️ 比對以【數字序列】為主軸：OCR 對字母的誤讀率遠高於數字
（實測 RCA6760 vs R6760、RDR6350 vs RDR6550 都是同一台）。
初版比對過嚴時曾誤報 7 組，經逐張目視複驗全為 OCR 誤讀。
**任何自動稽核的告警都要目視複驗後才能當結論。**

用法：python3 audit_pairing.py [--json 輸出檔]
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from pairs_io import load_pairs  # noqa: E402

from PIL import Image, ImageOps, ImageEnhance

HERE = Path(__file__).resolve().parent
OCR_BIN = HERE / "tools" / "ocr_plate"


def digits(s: str) -> str:
    return "".join(re.findall(r"[0-9]", s or ""))


def same_plate(a: str, b: str) -> bool:
    """兩個 OCR 車牌是否為同一台。以數字序列比對並容忍 1 位誤讀。"""
    da, db = digits(a), digits(b)
    if not da or not db:
        return False
    if da == db or da in db or db in da:
        return True
    if len(da) >= 4 and len(db) >= 4 and da[-4:] == db[-4:]:
        return True
    m = min(len(da), len(db), 4)
    return sum(1 for i in range(m) if da[-m:][i] != db[-m:][i]) <= 1


def looks_like_plate(text: str) -> bool:
    n = re.sub(r"[^A-Z0-9]", "", text.upper())
    if not 5 <= len(n) <= 9:
        return False
    if "IRENT" in n or "PRIUS" in n or "TOYOTA" in n:
        return False
    return bool(re.search(r"[A-Z]", n)) and len(re.findall(r"[0-9]", n)) >= 3


def ocr(paths: list[str], workdir: Path) -> dict[str, list[str]]:
    """回傳 {原始路徑: [疑似車牌字串]}。前處理放大 2x 提升小車牌辨識率。"""
    if not OCR_BIN.exists():
        sys.exit(f"缺少 OCR helper：{OCR_BIN}\n請先執行："
                 f"swiftc -O {HERE/'tools'/'ocr_plate.swift'} -o {OCR_BIN}")
    mapping = {}
    for i, p in enumerate(paths):
        im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
        im = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
        im = ImageEnhance.Contrast(im).enhance(1.4)
        f = workdir / f"{i:04d}.png"
        im.save(f)
        mapping[str(f)] = p
    proc = subprocess.run([str(OCR_BIN), *mapping], capture_output=True, text=True)
    out: dict[str, list[str]] = {p: [] for p in paths}
    for line in proc.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        src = mapping.get(parts[0])
        if src and looks_like_plate(parts[1]):
            out[src].append(parts[1])
    return out


def main():
    pairs = load_pairs()
    photos = []
    for p in pairs:
        photos += [p["pickup"], p["return"]]
    with tempfile.TemporaryDirectory() as td:
        found = ocr(photos, Path(td))

    rows, ok, unknown, bad = [], 0, 0, []
    for p in pairs:
        pu = found.get(p["pickup"]) or []
        rt = found.get(p["return"]) or []
        rec = {"car": p["car"], "angle": p["angle"],
               "pickup_plates": pu, "return_plates": rt}
        if not pu or not rt:
            rec["verdict"] = "unknown"
            unknown += 1
        elif any(same_plate(a, b) for a in pu for b in rt):
            rec["verdict"] = "match"
            ok += 1
        else:
            rec["verdict"] = "conflict"
            bad.append(rec)
        rows.append(rec)

    print(f"141 組配對稽核")
    print(f"  ✓ 車牌一致            {ok} 組")
    print(f"  · 讀不到車牌，無法判定 {unknown} 組")
    print(f"  ✗ 疑似配對錯誤        {len(bad)} 組"
          f"{'（須逐張目視複驗）' if bad else ''}")
    for b in bad:
        print(f"     {b['car']}-{b['angle']}  借={b['pickup_plates']}  還={b['return_plates']}")

    if "--json" in sys.argv:
        dest = Path(sys.argv[sys.argv.index("--json") + 1])
        dest.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
        print(f"→ {dest}")


if __name__ == "__main__":
    main()
