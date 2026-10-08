#!/usr/bin/env python3
"""在還車照上圈出損傷／髒污位置並加中文說明標註。

車外模式：借+還照送模型 → 模型回傳每個新損傷在【還車照】上的 box_2d → 畫框+編號+說明
車內模式：單張車內照 → 圈出每個髒污點

用法：
  python3 annotate_damage.py --car RFB5176 --angle 右後          # 車外配對
  python3 annotate_damage.py --interior interior_photos/xxx.png  # 車內單張
輸出： pipeline/annotated/<車牌>_<方位>_annotated.jpg
"""
import argparse
import json
import sys
from pathlib import Path

from google.genai import types
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pairs_io import load_pairs  # noqa: E402
from run_eval_gemini import get_client, prep_image  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "annotated"
OUT.mkdir(exist_ok=True)
FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
# Noto TTC 的第 3 個字型為繁體中文；macOS 則沿用原本的黑體。
FONT_CANDIDATES = (
    (FONT, 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 3),
    ("DejaVuSans.ttf", 0),
)


def _load_font(size: int):
    """跨平台載入標註字型，缺少系統字型時保留分析結果。"""
    for path, index in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            continue
    # Pillow 10.1+ 的內建字型支援指定大小；舊版仍可退回基本字型。
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


# ---------- Schema：每個標註點含 box_2d（[ymin,xmin,ymax,xmax]，0~1000 正規化） ----------

class Finding(BaseModel):
    box_2d: list[int] = Field(description="損傷/髒污在【最後一張照片】上的位置 [ymin, xmin, ymax, xmax]，座標正規化為 0~1000")
    label: str = Field(description="短標籤，例如：刮痕、凹陷、掉漆、遺留垃圾、液體污漬")
    severity: str = Field(description="low | medium | high")
    confidence: float = Field(description="0~1")
    description: str = Field(description="一句話中文說明（位置+狀況），將直接顯示在圖上")

class AnnotatedResult(BaseModel):
    findings: list[Finding] = Field(description="標註點清單，無則空陣列")
    summary: str = Field(description="整體結論一句話")


EXT_SYSTEM = """你是車況比對專家。第一張是借車照、第二張是還車照（同車同方位）。
找出「還車照有、借車照沒有」的新增車損（刮痕/凹陷/破損/掉漆）。
每個新損傷回傳其在【還車照】上的精確 box_2d（[ymin,xmin,ymax,xmax]，0~1000）。
框要緊貼損傷範圍，不要框整個部件。反光、水痕、髒污、既有舊損不標。"""

INT_SYSTEM = """你是車內整潔檢查員。找出這張車內照中的髒污點（垃圾、食物殘渣、液體污漬、泥沙、毛髮、菸蒂）。
每個髒污點回傳精確 box_2d（[ymin,xmin,ymax,xmax]，0~1000）。框要緊貼髒污範圍。
光影、座椅紋路、固定配備不標。"""


def analyze(client, model, images, system):
    contents = []
    for cap, data in images:
        contents.append(cap)
        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
    contents.append("請標註並輸出。")
    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=AnnotatedResult,
            temperature=0.1,
        ),
    )
    return resp.parsed


def draw_annotations(img: Image.Image, result: AnnotatedResult) -> Image.Image:
    img = img.convert("RGB")
    W, H = img.size
    d = ImageDraw.Draw(img, "RGBA")
    label_size = max(20, W // 36)
    number_size = max(22, W // 30)
    f_lbl = _load_font(label_size)
    f_num = _load_font(number_size)

    RED = (214, 40, 40)
    for i, fd in enumerate(result.findings, 1):
        y0, x0, y1, x1 = fd.box_2d
        # 0~1000 正規化 → 像素
        bx0, by0 = x0 * W // 1000, y0 * H // 1000
        bx1, by1 = x1 * W // 1000, y1 * H // 1000
        # 框（雙線加粗）
        for w in range(4):
            d.rounded_rectangle([bx0 - w, by0 - w, bx1 + w, by1 + w], radius=8, outline=RED)
        # 編號圓標
        r = number_size
        cx, cy = bx0, max(by0 - r - 6, 4)
        d.ellipse([cx, cy, cx + r + 10, cy + r + 10], fill=RED)
        d.text((cx + 5 + r // 4, cy + 1), str(i), font=f_num, fill=(255, 255, 255))

    # 底部說明列（半透明黑底白字，超寬自動換行）
    def wrap(text, max_w):
        out, cur = [], ""
        for ch in text:
            if d.textlength(cur + ch, font=f_lbl) > max_w:
                out.append(cur)
                cur = "　"  # 續行縮排
            cur += ch
        out.append(cur)
        return out

    raw = ([f"{i}. {fd.label}（{fd.severity}, {fd.confidence:.2f}）：{fd.description}"
            for i, fd in enumerate(result.findings, 1)]
           if result.findings else ["未發現需標註的異常"])
    lines = [seg for line in raw for seg in wrap(line, W - 28)]
    lh = label_size + 10
    pad = 14
    box_h = lh * len(lines) + pad * 2
    d.rectangle([0, H - box_h, W, H], fill=(0, 0, 0, 185))
    for j, line in enumerate(lines):
        d.text((pad, H - box_h + pad + j * lh), line, font=f_lbl, fill=(255, 255, 255))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car")
    ap.add_argument("--angle")
    ap.add_argument("--interior", help="車內照路徑（單張模式）")
    ap.add_argument("--model", default="gemini-3.7-flash")
    args = ap.parse_args()

    client = get_client()
    if args.interior:
        path = Path(args.interior)
        target = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        result = analyze(client, args.model, [("車內照：", prep_image(str(path)))], INT_SYSTEM)
        out = OUT / f"{path.stem}_annotated.jpg"
    else:
        pairs = {(p["car"], p["angle"]): p for p in load_pairs()}
        p = pairs[(args.car, args.angle)]
        target = ImageOps.exif_transpose(Image.open(p["return"])).convert("RGB")
        result = analyze(client, args.model, [
            ("第一張＝借車照：", prep_image(p["pickup"])),
            ("第二張＝還車照：", prep_image(p["return"])),
        ], EXT_SYSTEM)
        out = OUT / f"{args.car}_{args.angle}_annotated.jpg"

    annotated = draw_annotations(target, result)
    annotated.save(out, quality=88)
    print(f"標註 {len(result.findings)} 處 → {out}")
    print("總結：", result.summary)
    for i, fd in enumerate(result.findings, 1):
        print(f"  {i}. {fd.label} {fd.box_2d} conf={fd.confidence:.2f} — {fd.description}")


if __name__ == "__main__":
    main()
