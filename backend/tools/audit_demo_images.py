#!/usr/bin/env python3
"""掃描專案內所有車輛照片 → 品質／車牌／借還車配對分析 → Demo 候選車輛 → 產出
  DEMO_IMAGE_AUDIT.md、DEMO_VEHICLE_CANDIDATES.md（repo 根）與 backend/app/DEMO_IMAGE_MANIFEST.json（Demo Vehicle Registry 讀取）。

資料來源（全部沿用既有紀錄，不猜測）：
  - 借／還階段與角度：資料集檔名（「RCG2235左前 借.jpg」）→ pipeline/pairs.json（build_pairs.py 產生的既有配對紀錄）
  - 品質：pipeline/quality_gate.py（Laplacian 清晰度、亮度、過曝；chain 照片用 gate_chain_results.json 快取）
  - 車牌：Core ML PlateDetector + PlateOCR（與 iOS App 同模型，macOS 批次執行；結果 JSONL 由 --ocr 指定）
  - 角度一致性／可比對性：eval_results_gemini_37_flash_v3_cascaded.json 的 angle_match、relabels.json 的人工重標
  - chain_photos：跨訂單「還車照鏈」（photo_chain.py），同一台車不同訂單的還車照，不是同一租約的借／還配對
原始照片不修改、不複製；manifest 只記相對路徑與既有供圖 URL（/photos/pair/<檔名>）。

用法：python3 backend/tools/audit_demo_images.py --ocr <ocr.jsonl> [--top 5]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PIPE = REPO / "backend" / "pipeline"
sys.path.insert(0, str(PIPE))
from pairs_io import load_pairs, to_rel  # noqa: E402
from quality_gate import gate  # noqa: E402

DATASET = REPO / "iRent - 運用 AI 打造 iRent 智能車況管家：優化租還車體驗與營運效率"
CHAIN = REPO / "環節二_還車影像AI辨識" / "pipeline" / "chain_photos"
INTERIOR = PIPE / "interior_photos"
STAGE1 = REPO / "環節一_拍攝即時防呆" / "app_models"
UPLOADS = REPO / "backend" / "app" / "inspection_uploads"
EXTS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}
NAME_RE = re.compile(r"^(?P<plate>[A-Z]{2,3}-?\d{4})(?P<angle>左前|右前|左後|右後)(?P<n>\d?)\s*(?P<stage>借|還)")
ANGLES = ("左前", "右前", "左後", "右後")
# 車型：資料集未記錄；以下為由照片車尾／車頭標誌目視判讀（明確標示，非紀錄）
VISUAL_MODEL = {"RDG-9853": "Toyota Prius c（車尾標誌目視判讀）", "RFH-8122": "Honda Fit（車尾標誌目視判讀）",
                "RCG-2235": "Toyota Yaris（既有示範租約設定）"}
WEIGHTS = {"plate_clarity": 0.30, "before_completeness": 0.20, "after_completeness": 0.20,
           "angle_consistency": 0.15, "usability": 0.15}


def norm_plate(p: str | None) -> str:
    return "".join(c for c in (p or "").upper() if c.isalnum())


def fmt_plate(raw: str) -> str:
    raw = norm_plate(raw)
    m = re.match(r"^([A-Z]{2,3})(\d{4})$", raw)
    return f"{m.group(1)}-{m.group(2)}" if m else raw


def rel(p: Path) -> str:
    return str(p.resolve().relative_to(REPO))


def load_ocr(path: Path | None) -> dict[str, dict]:
    out = {}
    if path and path.exists():
        for line in path.read_text().splitlines():
            try:
                r = json.loads(line)
                out[r["image"]] = r
            except json.JSONDecodeError:
                pass
    return out


def inventory() -> dict[str, list[Path]]:
    groups = {
        "dataset_negative": sorted((DATASET / "沒有進行索賠").glob("*")),
        "dataset_positive": sorted((DATASET / "進行索賠資料").glob("*")),
        "interior_candidates": sorted(INTERIOR.glob("*")) if INTERIOR.exists() else [],
        "stage1_samples": sorted(STAGE1.glob("*.jpg")) if STAGE1.exists() else [],
        "chain_photos": sorted(CHAIN.rglob("*")) if CHAIN.exists() else [],
        "inspection_uploads": sorted(UPLOADS.rglob("*")) if UPLOADS.exists() else [],
    }
    return {k: [p for p in v if p.is_file() and p.suffix.lower() in EXTS] for k, v in groups.items()}


def chain_angle_map() -> dict[str, str]:
    try:
        cases = json.loads((PIPE / "chain_cases.json").read_text())["cases"]
        return {c["itype"]: c["angle"] for c in cases if c.get("itype") and c.get("angle")}
    except Exception:
        return {}


def chain_gate_cache() -> dict[str, dict]:
    try:
        return {r["file"]: r for r in json.loads((PIPE / "gate_chain_results.json").read_text())["results"]}
    except Exception:
        return {}


def eval_index() -> dict[tuple[str, str], dict]:
    try:
        res = json.loads((PIPE / "eval_results_gemini_37_flash_v3_cascaded.json").read_text())["results"]
        return {(r["car"], r["angle"]): r for r in res}
    except Exception:
        return {}


def relabel_index() -> dict[tuple[str, str], dict]:
    try:
        return {(r["car"], r["angle"]): r for r in json.loads((PIPE / "relabels.json").read_text())["relabels"]}
    except Exception:
        return {}


def interior_index() -> dict[str, dict]:
    try:
        return {r["file"]: r for r in json.loads((PIPE / "interior_results.json").read_text())["results"]}
    except Exception:
        return {}


def analyze_photo(p: Path, group: str, ocr: dict, chain_gate: dict, chain_angles: dict, interior_idx: dict) -> dict:
    r = rel(p)
    item = {"image": r, "group": group, "bytes": p.stat().st_size, "plate_from_record": None, "angle": None,
            "angle_source": None, "stage": None, "stage_source": None}
    if group.startswith("dataset"):
        m = NAME_RE.match(p.name)
        if m:
            item.update(plate_from_record=fmt_plate(m.group("plate")), angle=m.group("angle"), angle_source="filename",
                        stage="pickup" if m.group("stage") == "借" else "return", stage_source="filename(借/還)",
                        retake=bool(m.group("n")))
        else:
            mm = re.match(r"^([A-Z]{2,3}-?\d{4})", p.name)
            item.update(plate_from_record=fmt_plate(mm.group(1)) if mm else None, stage="unknown",
                        stage_source="filename（車況回報單張，無借/還標記）")
    elif group == "chain_photos":
        order, itype = p.stem.split("_", 1) if "_" in p.stem else (p.stem, "")
        item.update(plate_from_record=p.parent.name, angle=chain_angles.get(itype), angle_source="chain itype",
                    stage="return", stage_source="photo_chain（跨訂單還車照）", order=order)
    elif group == "interior_candidates":
        meta = interior_idx.get(p.name) or {}
        item.update(plate_from_record=meta.get("car"), stage="unknown", stage_source="上傳清單（車內照欄位，70% 實為車外照）",
                    interior_assessment=(meta.get("assessment") or {}).get("level"),
                    interior_photo_ok=(meta.get("assessment") or {}).get("photo_ok"))
    elif group == "stage1_samples":
        item.update(stage="unknown", stage_source="環節一自備測試照")
    elif group == "inspection_uploads":
        item.update(stage_source="App 上傳副本（來源為上列資料集照片或 Demo 拍攝）", derived=True)
    # 品質
    if group == "chain_photos" and p.name in chain_gate:
        g = chain_gate[p.name]
        item["quality"] = {"pass": g["pass"], "reasons": g["reasons"], **g["metrics"], "source": "gate_chain_results.json"}
    elif group != "inspection_uploads":
        try:
            ok, reasons, m = gate(str(p), interior=(group == "interior_candidates"))
            item["quality"] = {"pass": ok, "reasons": reasons, **m, "source": "quality_gate.py"}
        except Exception as e:
            item["quality"] = {"pass": None, "reasons": [f"無法讀取：{type(e).__name__}"], "source": "quality_gate.py"}
    # 車牌
    o = ocr.get(r)
    if o:
        text = o.get("plate_text")
        expected = item["plate_from_record"]
        if o["status"] == "recognized" and expected:
            match = norm_plate(text) == norm_plate(expected)
            status = "VERIFIED" if match else "MISMATCH_NEEDS_REVIEW"
        elif o["status"] == "recognized":
            status = "RECOGNIZED_UNLABELED_NEEDS_REVIEW"
        else:
            status = "UNREADABLE"
        item["plate"] = {"ocr_text": text, "ocr_confidence": o.get("ocr_confidence"), "detection_confidence": o.get("detection_confidence"),
                         "ocr_status": o["status"], "verification": status, "engine": "coreml PlateDetector+PlateOCR（與 App 同模型）"}
    else:
        item["plate"] = {"ocr_status": "not_run", "verification": "NOT_RUN"}
    # 內容判斷（可觀測的事實，不猜）
    item["shows_vehicle"] = ("probable" if (item.get("plate", {}).get("ocr_status") == "recognized" or item.get("angle")) else "unknown")
    item["usable_for_inspection"] = bool((item.get("quality") or {}).get("pass")) and item.get("plate", {}).get("verification") == "VERIFIED"
    return item


def build_vehicles(photos: list[dict], evals: dict, relabels: dict) -> list[dict]:
    pairs = load_pairs()
    by_rel = {p["image"]: p for p in photos}
    cars: dict[str, dict] = {}

    def car_entry(plate: str) -> dict:
        key = fmt_plate(plate)
        if key not in cars:
            cars[key] = {"plate": key, "vehicle_model": VISUAL_MODEL.get(key), "model_note": "資料集未記錄車型" + ("；" + VISUAL_MODEL[key] if key in VISUAL_MODEL else ""), "photos": [], "pairs": [],
                         "before_count": 0, "after_count": 0, "chain_count": 0, "other_count": 0}
        return cars[key]

    for ph in photos:
        if not ph.get("plate_from_record") or ph.get("derived"):
            continue
        c = car_entry(ph["plate_from_record"])
        c["photos"].append(ph["image"])
        if ph["group"].startswith("dataset") and ph["stage"] == "pickup":
            c["before_count"] += 1
        elif ph["group"].startswith("dataset") and ph["stage"] == "return":
            c["after_count"] += 1
        elif ph["group"] == "chain_photos":
            c["chain_count"] += 1
        else:
            c["other_count"] += 1

    for pr in pairs:
        key = fmt_plate(pr["car"])
        c = car_entry(key)
        pk, rt = by_rel.get(to_rel(pr["pickup"]) if False else _rel_from_pair(pr["pickup"])), by_rel.get(_rel_from_pair(pr["return"]))
        ev = evals.get((pr["car"], pr["angle"])) or {}
        rl = relabels.get((pr["car"], pr["angle"])) or {}
        a = ev.get("assessment") or {}
        both_verified = bool(pk and rt and pk["plate"]["verification"] == "VERIFIED" and rt["plate"]["verification"] == "VERIFIED")
        one_verified = bool(pk and rt and (pk["plate"]["verification"] == "VERIFIED" or rt["plate"]["verification"] == "VERIFIED"))
        if both_verified:
            verification = "VERIFIED"           # 既有紀錄（檔名）＋ 兩張 OCR 皆讀到同一車牌
        elif one_verified and not any(x and x["plate"]["verification"] == "MISMATCH_NEEDS_REVIEW" for x in (pk, rt)):
            verification = "RECORD_ONLY_PARTIAL_OCR"   # 檔名配對 + 其中一張 OCR 確認，另一張讀不到
        elif any(x and x["plate"]["verification"] == "MISMATCH_NEEDS_REVIEW" for x in (pk, rt)):
            verification = "UNVERIFIED_PAIR_OCR_MISMATCH"
        else:
            verification = "UNVERIFIED_PAIR"
        c["pairs"].append({
            "angle": pr["angle"], "label": pr["label"], "pickup": _rel_from_pair(pr["pickup"]), "return": _rel_from_pair(pr["return"]),
            "return_alt": _rel_from_pair(pr["return_alt"]) if pr.get("return_alt") else None,
            "pair_source": "pairs.json（build_pairs.py 由資料集檔名建立）",
            "pickup_quality_pass": (pk or {}).get("quality", {}).get("pass"), "return_quality_pass": (rt or {}).get("quality", {}).get("pass"),
            "ai_angle_match": a.get("angle_match"), "ai_new_damage_found": a.get("new_damage_found"),
            "ai_no_damage_confidence": a.get("no_damage_confidence"), "ai_level": ev.get("level"),
            "human_relabel": rl.get("relabel"), "human_note": rl.get("note"),
            "pair_verification": verification,
        })

    out = []
    for c in cars.values():
        exterior = [by_rel[r] for r in c["photos"] if by_rel[r]["group"].startswith("dataset") and by_rel[r].get("angle")]
        verified = [p for p in exterior if p["plate"]["verification"] == "VERIFIED"]
        plate_clarity = (sum(p["plate"]["ocr_confidence"] or 0 for p in verified) / len(exterior)) if exterior else 0.0
        before_angles = {p["angle"] for p in exterior if p["stage"] == "pickup" and (p.get("quality") or {}).get("pass")}
        after_angles = {p["angle"] for p in exterior if p["stage"] == "return" and (p.get("quality") or {}).get("pass")}
        angle_match = sum(1 for pr in c["pairs"] if pr["ai_angle_match"] is True)
        usable = sum(1 for pr in c["pairs"] if pr["human_relabel"] in ("clean", "damage"))
        scores = {"plate_clarity": round(plate_clarity, 3), "before_completeness": round(len(before_angles) / 4, 3),
                  "after_completeness": round(len(after_angles) / 4, 3), "angle_consistency": round(min(angle_match, 4) / 4, 3),
                  "usability": round(min(usable, 4) / 4, 3)}
        total = sum(scores[k] * w for k, w in WEIGHTS.items())
        verified_pairs = [pr for pr in c["pairs"] if pr["pair_verification"] == "VERIFIED"]
        c.update(scores=scores, total_score=round(total * 100, 1),
                 angles_before=sorted(before_angles), angles_after=sorted(after_angles),
                 verified_pair_angles=sorted(pr["angle"] for pr in verified_pairs),
                 complete_pair=(len(verified_pairs) == 4),
                 plate_ocr_summary={"exterior_photos": len(exterior), "ocr_verified": len(verified),
                                    "mismatch": sum(1 for p in exterior if p["plate"]["verification"] == "MISMATCH_NEEDS_REVIEW"),
                                    "unreadable": sum(1 for p in exterior if p["plate"]["verification"] == "UNREADABLE")},
                 damage_angles=[pr["angle"] for pr in c["pairs"] if pr["human_relabel"] == "damage"])
        c["reasons"] = _reasons(c, scores, verified_pairs)
        out.append(c)
    out.sort(key=lambda c: (-c["total_score"], c["plate"]))
    return out


def _rel_from_pair(p: str | None) -> str | None:
    if not p:
        return None
    q = Path(p)
    if q.is_absolute():
        return rel(q)
    return rel(DATASET / p)


def _reasons(c: dict, s: dict, verified_pairs: list[dict]) -> list[str]:
    r = []
    if c["complete_pair"]:
        r.append("4 個角度都有借／還配對，且兩張照片的 Core ML OCR 皆讀出同一車牌")
    elif verified_pairs:
        r.append(f"{len(verified_pairs)} 個角度有 OCR 雙向確認的借／還配對（{'、'.join(pr['angle'] for pr in verified_pairs)}）")
    if s["angle_consistency"] >= 0.75:
        r.append("AI 評測 angle_match 一致")
    if c["damage_angles"]:
        r.append(f"人工重標有真實新損（{'、'.join(c['damage_angles'])}）→ 可展示「偵測到新增車損」")
    elif s["usability"] >= 0.75:
        r.append("人工重標全部可判定（clean）→ 可展示「未發現新損」正常流程")
    if c["plate_ocr_summary"]["mismatch"]:
        r.append(f"{c['plate_ocr_summary']['mismatch']} 張 OCR 與檔名車牌不符，待人工確認")
    return r


def write_outputs(inv: dict, photos: list[dict], vehicles: list[dict], top: int, ocr_path: Path | None) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    manifest = {
        "name": "iRent Demo 照片／車輛對應（DEMO_IMAGE_MANIFEST）",
        "generated_at": now, "generator": "backend/tools/audit_demo_images.py",
        "sources": {k: len(v) for k, v in inv.items()},
        "weights": WEIGHTS,
        "notes": [
            "借／還階段與角度來自資料集檔名（既有 pairs.json 紀錄）；車頭照（左前／右前）檔名左右與畫面實際角度相反（見環節一 README），此處保留檔名欄位。",
            "pair_verification=VERIFIED 表示兩張照片 Core ML OCR 都讀到與檔名相同車牌；其餘為 Unverified Pair，需人工確認。",
            "chain_photos 為跨訂單還車照鏈（同車不同訂單），不是同一租約的借／還配對；interior_candidates 的借／還階段不明。",
            "照片為比賽提供之非公開營運照片，只能在隊內／評審範圍使用；manifest 不含絕對路徑。",
        ],
        "vehicles": vehicles,
        "photos": photos,
    }
    (REPO / "backend" / "app" / "DEMO_IMAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))

    # ---- AUDIT.md ----
    by_group = defaultdict(list)
    for p in photos:
        by_group[p["group"]].append(p)
    lines = [f"# DEMO_IMAGE_AUDIT — 專案內車輛照片掃描與品質分析\n", f"產生時間：{now}（`backend/tools/audit_demo_images.py`）\n",
             "## 1. 照片盤點\n", "| 來源 | 張數 | 說明 |", "|---|---:|---|"]
    desc = {"dataset_negative": "比賽資料集「沒有進行索賠」：30 台車 × 4 方位 × 借／還（檔名即借還紀錄）",
            "dataset_positive": "比賽資料集「進行索賠資料」：28 台車的爭議方位借／還配對 + 8 張單張車況回報",
            "interior_candidates": "上傳清單「車內照」欄位下載的 80 張（既有分析：56 張實為車外照）",
            "stage1_samples": "環節一 app_models 自備測試照",
            "chain_photos": "photo_chain 跨訂單還車照（Azure Blob 下載、git-ignored）",
            "inspection_uploads": "App／Demo 上傳的副本（來源即上列照片；不另計入候選）"}
    for k, v in inv.items():
        lines.append(f"| {k} | {len(v)} | {desc.get(k, '')} |")
    lines.append(f"| **合計** | **{sum(len(v) for v in inv.values())}** | |")
    lines += ["\n掃描範圍：repo 內所有 JPG/JPEG/PNG/HEIC/WEBP（排除 node_modules、.venv、DerivedData、App icon、/ops 靜態匯出）。原始照片未修改、未複製。\n",
              "## 2. 品質與車牌分析方法\n",
              "- 品質：`pipeline/quality_gate.py`（清晰度 Laplacian ≥ 60、亮度 ≥ 55、過曝檢查；車內照用車內門檻；chain 照用 `gate_chain_results.json` 既有結果）。",
              "- 車牌：Core ML `PlateDetector` + `PlateOCR`（與 iOS App 同模型）批次執行；OCR 讀不出者標 UNREADABLE，與檔名不符者標 MISMATCH_NEEDS_REVIEW，**不自行猜測**。",
              "- 角度：資料集檔名欄位（車頭照左右與畫面相反）；chain 照由 itype 對應；未標註者為 null。",
              "- 借還配對：只採既有 `pairs.json`（檔名 借/還）；AI `angle_match` 與人工 `relabels.json` 用來評估可比對性。\n",
              "## 3. 各來源分析結果\n"]
    for k, items in by_group.items():
        if not items:
            continue
        q_pass = sum(1 for p in items if (p.get("quality") or {}).get("pass"))
        q_fail = sum(1 for p in items if (p.get("quality") or {}).get("pass") is False)
        vs = defaultdict(int)
        for p in items:
            vs[p["plate"]["verification"]] += 1
        lines.append(f"### {k}（{len(items)} 張）\n")
        lines.append(f"- 品質閘門：通過 {q_pass}、未通過 {q_fail}、未評估 {len(items) - q_pass - q_fail}")
        lines.append("- 車牌驗證：" + "、".join(f"{a} {b}" for a, b in sorted(vs.items())))
        fails = [p for p in items if (p.get('quality') or {}).get('pass') is False][:8]
        if fails:
            lines.append("- 未通過範例：" + "；".join(f"`{Path(p['image']).name}`（{'/'.join(p['quality']['reasons'])[:40]}）" for p in fails))
        lines.append("")
    lines += ["## 4. 借／還配對驗證\n", "| 車牌 | 配對角度 | VERIFIED | 部分 OCR | OCR 不符 | 無法驗證 | 人工重標 damage 角度 |", "|---|---|---:|---:|---:|---:|---|"]
    for c in vehicles:
        if not c["pairs"]:
            continue
        cnt = defaultdict(int)
        for pr in c["pairs"]:
            cnt[pr["pair_verification"]] += 1
        lines.append(f"| {c['plate']} | {'、'.join(pr['angle'] for pr in c['pairs'])} | {cnt['VERIFIED']} | {cnt['RECORD_ONLY_PARTIAL_OCR']} | {cnt['UNVERIFIED_PAIR_OCR_MISMATCH']} | {cnt['UNVERIFIED_PAIR']} | {'、'.join(c['damage_angles']) or '—'} |")
    lines += ["\n## 5. 未解決／待人工確認\n",
              "- OCR 與檔名不符的照片（MISMATCH_NEEDS_REVIEW）與讀不到車牌的照片（UNREADABLE）列於 manifest `photos[].plate.verification`，未納入 VERIFIED 配對。",
              "- `進行索賠資料/*車況回報.jpg` 8 張為單張回報照，無借／還對照，不列為配對。",
              "- interior_candidates 80 張的借／還階段無紀錄，只作車內整潔 Demo 素材。",
              "- chain_photos 為跨訂單還車照，不當作同一租約的借車前照片。",
              "- 資料集未記錄車型，Demo 車輛的車型欄位標示「資料集未記錄」，不臆測。"]
    (REPO / "DEMO_IMAGE_AUDIT.md").write_text("\n".join(lines) + "\n")

    # ---- CANDIDATES.md ----
    lines = ["# DEMO_VEHICLE_CANDIDATES — 最適合 Demo 的候選車輛\n", f"產生時間：{now}。評分權重：車牌清晰度 30%、借車前完整度 20%、還車後完整度 20%、前後角度一致性 15%、車況辨識可用性 15%。\n",
             "只計資料集借／還配對（既有 pairs.json）。`完整前後配對` = 4 個角度都有配對且兩張 OCR 皆讀到同一車牌。\n",
             f"## 前 {top} 名\n",
             "| 名次 | 車牌 | 照片數 | 借車前 | 還車後 | 可辨識角度（借／還） | 品質評分 | 完整前後配對 | 適合 Demo 的原因 |", "|---:|---|---:|---:|---:|---|---:|:---:|---|"]
    for i, c in enumerate(vehicles[:top], 1):
        lines.append(f"| {i} | {c['plate']} | {len(c['photos'])} | {c['before_count']} | {c['after_count']} | {'、'.join(c['angles_before'])} ／ {'、'.join(c['angles_after'])} | {c['total_score']} | {'是' if c['complete_pair'] else '否（' + '、'.join(c['verified_pair_angles']) + '）'} | {'；'.join(c['reasons']) or '—'} |")
    lines += ["\n### 分項分數\n", "| 車牌 | 車牌清晰度 | 借前完整 | 還後完整 | 角度一致 | 可用性 | 總分 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for c in vehicles[:top]:
        s = c["scores"]
        lines.append(f"| {c['plate']} | {s['plate_clarity']} | {s['before_completeness']} | {s['after_completeness']} | {s['angle_consistency']} | {s['usability']} | {c['total_score']} |")
    lines += ["\n### 逐角度配對（前 5 名）\n"]
    for c in vehicles[:top]:
        lines.append(f"**{c['plate']}**（{c['model_note']}）\n")
        lines.append("| 角度 | 借車前 | 還車後 | 品質（借／還） | AI angle_match | 人工重標 | 配對驗證 |")
        lines.append("|---|---|---|---|---|---|---|")
        for pr in c["pairs"]:
            lines.append(f"| {pr['angle']} | `{Path(pr['pickup']).name}` | `{Path(pr['return']).name}` | {pr['pickup_quality_pass']}／{pr['return_quality_pass']} | {pr['ai_angle_match']} | {pr['human_relabel'] or '—'} | {pr['pair_verification']} |")
        lines.append("")
    dmg = sorted([c for c in vehicles if c["damage_angles"]], key=lambda c: -c["total_score"])[:5]
    lines += ["## 車損展示候選（人工重標為真實新損的配對）\n",
              "| 車牌 | 總分 | damage 角度 | 該角度配對驗證 | AI 判定 | 人工備註 |", "|---|---:|---|---|---|---|"]
    for c in dmg:
        for pr in c["pairs"]:
            if pr["human_relabel"] == "damage":
                lines.append(f"| {c['plate']} | {c['total_score']} | {pr['angle']} | {pr['pair_verification']} | new_damage={pr['ai_new_damage_found']} | {(pr['human_note'] or '')[:60]} |")
    lines.append("")
    complete = [c for c in vehicles if c["complete_pair"]]
    lines += ["## 全部有完整（4 角度 VERIFIED）配對的車輛\n", "、".join(c["plate"] for c in complete) or "（無）", "",
              "## 本次選定\n",
              "- **RDG-9853**（第 1 名）：主要影像辨識 Demo 車，4 角借／還 VERIFIED、人工重標全 clean → 展示正常流程。",
              "- **RFH-8122**（車損展示）：右後角借／還 VERIFIED 且人工重標 damage（保桿右下近輪拱擦痕）→ 展示「偵測到新增車損」；左前角 OCR 與檔名不符、左後 not_comparable，照實標示。",
              "- **RFY-1753**（使用者指定的固定 Demo 車）：專案內**沒有**任何 RFY-1753 的照片，保留為「只能即時拍攝」的 Demo 車，不虛構照片。",
              "",
              "## 缺少的素材\n",
              "- 資料集只有車外四角借／還照，沒有同一租約的車內借／還照（車內 Demo 素材只能用 interior_candidates，階段不明）。",
              "- 「進行索賠」車輛只有爭議角度的配對（1–2 個角度），無法做四角完整 Demo。",
              "- 所有車輛的車型資料集皆未記錄。"]
    (REPO / "DEMO_VEHICLE_CANDIDATES.md").write_text("\n".join(lines) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr", type=Path, default=None, help="ocr_batch 產生的 JSONL")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()
    inv = inventory()
    ocr = load_ocr(args.ocr)
    chain_angles, chain_gate, interior_idx = chain_angle_map(), chain_gate_cache(), interior_index()
    photos = []
    for group, files in inv.items():
        for p in files:
            photos.append(analyze_photo(p, group, ocr, chain_gate, chain_angles, interior_idx))
    vehicles = build_vehicles(photos, eval_index(), relabel_index())
    write_outputs(inv, photos, vehicles, args.top, args.ocr)
    print(f"photos={len(photos)} vehicles={len(vehicles)} ocr_records={len(ocr)}")
    for c in vehicles[:args.top]:
        print(c["plate"], c["total_score"], "complete" if c["complete_pair"] else c["verified_pair_angles"], c["damage_angles"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
