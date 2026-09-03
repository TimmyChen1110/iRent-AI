#!/usr/bin/env python3
"""車輛損傷護照建檔：把還車判定結果歸戶到「車輛」的終身損傷檔案。

資料來源：
  - eval_results_..._cascaded.json  → 新損紀錄（責任＝本單）
  - assessments.pre_existing_notes  → 既有損紀錄（責任＝早於觀測期）
  - dashboard_annotations.json      → 標註框座標
  - relabels.json                   → 人工複驗狀態
  - 車外車內照片上傳清單.xlsx        → 真實訂單號（可對上的 6 台車）

輸出：passports.json（每台車一份護照）
"""
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from results_config import FINAL_RESULTS  # noqa: E402

DATA = HERE.parents[1] / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"

casc = json.loads(FINAL_RESULTS.read_text())["results"]
ann = json.loads((HERE / "dashboard_annotations.json").read_text())
relabels = {(r["car"], r["angle"]): r for r in json.loads((HERE / "relabels.json").read_text())["relabels"]}


def real_orders():
    """從上傳清單撈出各車的真實訂單（時間取檔名內時間戳）。"""
    z = zipfile.ZipFile(DATA / "車外車內照片上傳清單.xlsx")
    N = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    ss = ["".join(t.text or "" for t in si.iter(N + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml"))]
    rows = ET.fromstring(z.read("xl/worksheets/sheet1.xml")).find(N + "sheetData")
    out = {}
    for r in list(rows)[1:]:
        d = {}
        for c in r:
            v = c.find(N + "v")
            if v is None: continue
            d[re.sub(r"\d", "", c.get("r"))] = ss[int(v.text)] if c.get("t") == "s" else v.text
        m = re.search(r"_(\d{8})(\d{6})\.", d.get("D", ""))
        if not m: continue
        ts = f"{m.group(1)[:4]}-{m.group(1)[4:6]}-{m.group(1)[6:]} {m.group(2)[:2]}:{m.group(2)[2:4]}"
        car = d.get("B", "").replace("-", "")
        out.setdefault(car, {})[d.get("A")] = ts
    return out


orders = real_orders()

passports = {}
for r in casc:
    car, angle = r["car"], r["angle"]
    a = r["assessment"]
    key = f"{car}-{angle}"
    p = passports.setdefault(car, {"car": car, "records": []})
    rl = relabels.get((car, angle), {})

    # 真實訂單（時間最早的一筆當本單示意）
    o = orders.get(car.replace("-", ""))
    if o:
        oid, ots = sorted(o.items(), key=lambda kv: kv[1])[0]
        first_seen = {"order": oid, "time": ots, "source": "還車判定（真實訂單）"}
    else:
        first_seen = {"order": f"BATCH-2026-04", "time": "2026-04（資料集批次）", "source": "還車判定"}

    # 新損：判定 + 標註框
    if a["new_damage_found"]:
        boxes = (ann.get(key) or {}).get("findings", [])
        for i, d in enumerate(a["damages"]):
            box = boxes[i]["box_2d"] if i < len(boxes) else None
            p["records"].append({
                "id": f"D-{len(p['records'])+1:03d}",
                "kind": "new", "status": "open",
                "angle": angle, "location": d["location"], "type": d["type"],
                "severity": d["severity"], "confidence": d["confidence"],
                "box_2d": box, "reasoning": d["reasoning"],
                "first_seen": first_seen, "evidence_case": key,
                "verified": rl.get("relabel") == "damage",
                "liable_order": first_seen["order"],
            })
    # 既有損：登錄但責任在前期
    note = (a.get("pre_existing_notes") or "").strip()
    if note and "無法" not in note and len(note) > 4:
        p["records"].append({
            "id": f"D-{len(p['records'])+1:03d}",
            "kind": "pre_existing", "status": "open",
            "angle": angle, "location": note[:60], "type": "既有損傷", "severity": "record",
            "confidence": None, "box_2d": None, "reasoning": note,
            "first_seen": {"order": "早於觀測期", "time": "借車照已存在", "source": "借車照登錄"},
            "evidence_case": key, "verified": False, "liable_order": "前期（觀測期前）",
        })

# 只留有紀錄的車
passports = {k: v for k, v in passports.items() if v["records"]}
for car, p in passports.items():
    p["open_new"] = sum(1 for r in p["records"] if r["kind"] == "new")
    p["pre_existing"] = sum(1 for r in p["records"] if r["kind"] == "pre_existing")
    p["real_orders"] = orders.get(car.replace("-", ""), {})

# 保留 part_tagger.py 標好的部位標籤：本腳本會整份重建 passports.json，
# 若不回填，重跑一次就會抹掉 59 筆部位標籤（約 60 次 API 呼叫的成果），
# 且 Dashboard 護照分頁的部位統計表會整個空掉。
# 來源優先序：part_progress.jsonl（權威快取）→ 既有 passports.json（快取遺失時的備援）。
def _restore_parts(passports):
    tags = {}
    prev = HERE / "passports.json"
    if prev.exists():  # 備援：從上一版護照撈（快取被清時仍不致遺失）
        try:
            for car, pp in json.loads(prev.read_text()).items():
                for rec in pp.get("records", []):
                    if rec.get("part"):
                        tags[(car, rec["id"])] = (rec["part"], rec.get("part_confidence"))
        except (json.JSONDecodeError, AttributeError):
            pass
    prog = HERE / "part_progress.jsonl"
    if prog.exists():  # 權威來源：覆蓋備援
        for line in prog.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            tags[(r["car"], r["rec_id"])] = (r["part"], r.get("confidence"))
    n = 0
    for car, pp in passports.items():
        for rec in pp["records"]:
            t = tags.get((car, rec["id"]))
            if t:
                rec["part"], rec["part_confidence"] = t
                n += 1
    return n


_n_parts = _restore_parts(passports)

(HERE / "passports.json").write_text(json.dumps(passports, ensure_ascii=False, indent=1))
print(f"{len(passports)} 台車建立護照，回填 {_n_parts} 筆部位標籤")
for car, p in sorted(passports.items(), key=lambda kv: -kv[1]["open_new"]):
    tag = f"（{len(p['real_orders'])} 筆真實訂單）" if p["real_orders"] else ""
    print(f"  {car:9s} 新損 {p['open_new']} 筆 / 既有損 {p['pre_existing']} 筆 {tag}")
