#!/usr/bin/env python3
"""② 車體部位定位：把護照上每筆損傷紀錄歸到固定部位分類（enum），
供後台拉出「部位 × 異常 × 嚴重度 × 新舊 × 責任單」結構化表格。

做法：對既有損傷紀錄（passports.json）逐筆送 Flash——附上證據照片與損傷描述，
要求從固定部位清單中選一個。只跑有紀錄的案件（約 60 筆），不動已驗證的判定結果。

輸出：直接把 part / part_confidence 寫回 passports.json。
（進度存 part_progress.jsonl，可中斷續跑。）
"""
import json
import sys
from pathlib import Path
from typing import Literal

from google.genai import types
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pairs_io import load_pairs  # noqa: E402
from run_eval_gemini import get_client, prep_image, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "gemini-3.7-flash"

PARTS = [
    "前保險桿", "後保險桿", "引擎蓋", "後車廂蓋", "車頂",
    "左前門", "左後門", "右前門", "右後門",
    "左前葉子板", "右前葉子板", "左後葉子板", "右後葉子板",
    "車燈", "後視鏡", "輪圈/輪胎", "其他",
]


class PartTag(BaseModel):
    part: Literal[tuple(PARTS)] = Field(description="損傷主要所在的車體部位")
    confidence: float = Field(ge=0, le=1)


SYSTEM = """你是車體部位分類專家。你會收到一張車輛照片、拍攝方位、以及一筆損傷描述。
請判斷該損傷主要位於哪個車體部位（從固定清單中選一個）。
若損傷橫跨多部位，選面積最大／描述最主要的那個。判斷不了時選「其他」並降低信心。"""


def angle_of(case_id, angles=("左前", "左後", "右前", "右後")):
    for a in angles:
        if case_id.endswith(a):
            return case_id[: -len(a)].rstrip("-"), a
    raise ValueError(case_id)


def main():
    pairs = {(p["car"], p["angle"]): p
             for p in load_pairs()}
    passports = json.loads((HERE / "passports.json").read_text())

    prog_path = HERE / "part_progress.jsonl"
    done = {}
    if prog_path.exists():
        for line in prog_path.read_text().splitlines():
            r = json.loads(line)
            done[(r["car"], r["rec_id"])] = r

    todo = []
    for car, p in passports.items():
        for rec in p["records"]:
            if (car, rec["id"]) not in done:
                todo.append((car, rec))
    print(f"{sum(len(p['records']) for p in passports.values())} 筆紀錄，待標 {len(todo)} 筆")

    client = get_client()
    throttle = Throttle(8)
    with prog_path.open("a") as f:
        for i, (car, rec) in enumerate(todo):
            pcar, angle = angle_of(rec["evidence_case"])
            pair = pairs[(pcar, angle)]
            photo = pair["return"] if rec["kind"] == "new" else pair["pickup"]
            throttle.wait()
            try:
                resp = client.models.generate_content(
                    model=MODEL,
                    contents=[
                        f"拍攝方位：{angle}。損傷描述：{rec['location']}（{rec['type']}）。"
                        f"{'此為還車照中的新增損傷。' if rec['kind']=='new' else '此為借車照上已存在的既有損傷。'}",
                        types.Part.from_bytes(data=prep_image(photo), mime_type="image/jpeg"),
                        "請判斷此損傷所在的車體部位。",
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM,
                        response_mime_type="application/json",
                        response_schema=PartTag,
                        temperature=0.1,
                    ),
                )
            except Exception as e:
                print(f"  ! {car} {rec['id']} 失敗：{e}")
                continue
            if not resp.parsed:
                print(f"  ! {car} {rec['id']} 無解析結果")
                continue
            row = {"car": car, "rec_id": rec["id"],
                   "part": resp.parsed.part, "confidence": resp.parsed.confidence}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            print(f"  [{i+1}/{len(todo)}] {car} {rec['id']} {rec['kind']:12s} → {resp.parsed.part} ({resp.parsed.confidence:.2f})")
            done[(car, rec["id"])] = row

    # 寫回護照
    n = 0
    for car, p in passports.items():
        for rec in p["records"]:
            row = done.get((car, rec["id"]))
            if row:
                rec["part"] = row["part"]
                rec["part_confidence"] = row["confidence"]
                n += 1
    (HERE / "passports.json").write_text(json.dumps(passports, ensure_ascii=False, indent=1))
    print(f"寫回 {n} 筆部位標籤 → passports.json")


if __name__ == "__main__":
    main()
