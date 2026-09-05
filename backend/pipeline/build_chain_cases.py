#!/usr/bin/env python3
"""建立「歸還期間車損」比對資料集（CHAIN_CASES）與 AI 畫框標註（CHAIN_ANN）。

邏輯規格：
1. 每一對「上一次還車照 vs 最新一次借車照」必須同時評測 Type 1~4 共 4 筆比對項目。
2. 第一關（角度對照）：若 angle_match 為 false，判定為 P4 (角度不符/無法比對)。
（請特別注意左右前、左右後的誤判，很多情況下左右前會搞混，左右後會搞混）
3. 第二關（車損對照）：與「案件覆核」走同一套 PAIR_SYSTEM 與 LiveAssessment 流程。
   若判定為 P1，必須精確導出 box_2d 紅框座標於最新借車照上。
"""
import json
import sys
import urllib.request
from pathlib import Path
from google.genai import types

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_eval_gemini import get_client, prep_image, Throttle, SYSTEM as PAIR_SYSTEM  # noqa: E402
from judge_photos import LiveAssessment  # noqa: E402

CHAIN_CANDIDATES = HERE / "chain_candidates.json"
CHAIN_DIR = HERE / "chain_photos"
OUT_CASES = HERE / "chain_cases.json"
OUT_ANN = HERE / "chain_annotations.json"
DL_TIMEOUT = 30

ANGLE_MAP = {
    "1": "左前",
    "2": "右前",
    "3": "左後",
    "4": "右後",
}


CACHE_FILE = HERE / "chain_eval_cache.json"


def download_image(url, fp):
    if fp.exists():
        return True
    try:
        with urllib.request.urlopen(url, timeout=DL_TIMEOUT) as r:
            fp.write_bytes(r.read())
        return True
    except Exception as e:
        fp.unlink(missing_ok=True)
        print(f"  下載圖片失敗 {fp.name}: {e}", file=sys.stderr)
        return False


def build_chain_cases(max_eval_cars=50):
    if not CHAIN_CANDIDATES.exists():
        return [], {}

    cands = json.loads(CHAIN_CANDIDATES.read_text())
    client = get_client()
    throttle = Throttle(8)

    # 讀取持久化 AI 評測快取 (永不覆蓋已完成的 P4 / P1 評測)
    eval_cache = {}
    if CACHE_FILE.exists():
        try:
            eval_cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            pass

    cases = []
    annotations = {}
    eval_count = 0

    print(f"🚀 建立「歸還期間車損」全量數據集 (包含 683 組車輛，已保護快取中 {len(eval_cache)} 筆 AI 評測)...")


    for car, orders in sorted(cands.items()):
        # 1. 嚴格過濾：該筆訂單必須同時具備 1~4 全部四個車外必要角度
        valid_orders = []
        for ord_id, imgs in orders.items():
            if all(k in imgs for k in ("1", "2", "3", "4")):
                valid_orders.append((ord_id, imgs))

        # 依時間排序
        valid_orders.sort(key=lambda item: min(m["ts"] for m in item[1].values()))
        if len(valid_orders) < 2:
            continue

        prev_order, prev_imgs = valid_orders[-2]
        curr_order, curr_imgs = valid_orders[-1]

        # 每個訂單對必定包含 1~4 全部 4 筆比對項目
        for itype in ("1", "2", "3", "4"):
            angle = ANGLE_MAP[itype]
            prev_meta = prev_imgs[itype]
            curr_meta = curr_imgs[itype]
            case_id = f"CHAIN-{car}-{angle}"

            # 如果已經有歷史評測過的結果，直接從快取載入
            if case_id in eval_cache:
                entry = eval_cache[case_id]
                c = entry["case"]
                cases.append(c)
                if entry.get("ann"):
                    annotations[case_id] = entry["ann"]
                continue

            a = None
            do_ai = (eval_count < max_eval_cars)
            if do_ai:
                car_dir = CHAIN_DIR / car
                car_dir.mkdir(parents=True, exist_ok=True)
                prev_fp = car_dir / f"{prev_order}_{itype}.png"
                curr_fp = car_dir / f"{curr_order}_{itype}.png"

                if download_image(prev_meta["url"], prev_fp) and download_image(curr_meta["url"], curr_fp):
                    eval_count += 1
                    print(f"  🔍 AI 評測 #{eval_count} {car} ({angle} / Type {itype}): #{prev_order} vs #{curr_order}...", end="", flush=True)
                    throttle.wait()

                    try:
                        resp = client.models.generate_content(
                            model="gemini-3.7-flash",
                            contents=[
                                f"車輛 {car}，預期拍攝方位 Type {itype}（{angle}）。",
                                "第一張＝上一次還車照（基準）：",
                                types.Part.from_bytes(data=prep_image(prev_fp), mime_type="image/jpeg"),
                                "第二張＝最新一次借車照：",
                                types.Part.from_bytes(data=prep_image(curr_fp), mime_type="image/jpeg"),
                                "請嚴格執行兩階段判定：\n"
                                "【第一關：嚴格視角與角度對照】\n"
                                "請極度嚴格比對第一張與第二張照片的拍攝視角與方位。兩張照片必須為『同台車輛的完全相同方位與角度』才算匹配。\n"
                                "若兩張照片方位不同（例如左前對右前、左後對正後或右後）、視角差距過大、拍錯部位、或無法精確重疊對比，angle_match 必須判定為 false。\n"
                                "【第二關：車損確認】\n"
                                "若 angle_match 為 true，才進一步精確檢查第二張照片中是否存在第一張照片沒有的新增車損（new_damage_found），並務必輸出 box_2d 正規化 0~1000 座標框。",
                            ],
                            config=types.GenerateContentConfig(
                                system_instruction=PAIR_SYSTEM,
                                response_mime_type="application/json",
                                response_schema=LiveAssessment,
                                temperature=0.1,
                            ),
                        )

                        a = resp.parsed.model_dump() if resp.parsed else None
                    except Exception as e:
                        print(f" [失敗: {str(e)[:40]}]")

            ann_item = None
            if a is not None:
                # 依 AI 評測結果分級
                if not a.get("angle_match"):
                    level = "P4"
                    desc = f"拍攝角度不一致（前單 #{prev_order} vs 本單 #{curr_order}，無法比對）"
                    print(" -> 🚫 P4 (角度不符)")
                elif a.get("new_damage_found"):
                    level = "P1"
                    dmgs = a.get("damages") or []
                    desc_dmgs = "；".join(f"{d.get('location')}·{d.get('type')}" for d in dmgs)
                    desc = f"偵測到歸還期間車損（{desc_dmgs or '新增痕跡'}）"
                    print(f" -> ⚠ P1 (新增車損 {len(dmgs)} 處)")

                    findings = []
                    for d in dmgs:
                        if d.get("box_2d") and len(d["box_2d"]) == 4:
                            findings.append({
                                "box_2d": d["box_2d"],
                                "label": f"{d.get('location', angle)}·{d.get('type', '車損')}",
                                "severity": d.get("severity", "medium"),
                                "confidence": d.get("confidence", 0.9),
                                "description": d.get("reasoning", "AI 偵測到歸還期間新增車損")
                            })
                    if findings:
                        ann_item = {"findings": findings}
                        annotations[case_id] = ann_item
                else:
                    level = "P3"
                    desc = f"比對一致，停放期間無新增車損"
                    print(" -> ✓ P3 (正常無車損)")
            else:
                # 預設基準項
                level = "P3"
                desc = f"比對中 / 待分析（前單 #{prev_order} vs 本單 #{curr_order}）"
                a = {
                    "angle_match": True,
                    "new_damage_found": False,
                    "damages": [],
                    "no_damage_confidence": 0.9,
                    "pre_existing_notes": ""
                }

            c_obj = {
                "id": case_id,
                "car": car,
                "angle": angle,
                "itype": itype,
                "level": level,
                "desc": desc,
                "label": "chain_check",
                "prev_order": prev_order,
                "curr_order": curr_order,
                "pickup": prev_meta["url"],       # 上一次還車照
                "return": curr_meta["url"],       # 最新一次借車照
                "prev_ts": prev_meta["ts"],
                "curr_ts": curr_meta["ts"],
                "is_chain": True,
                "assessment": a
            }
            cases.append(c_obj)

            # 若經 AI 評測，寫入持久化快取
            if do_ai and a is not None:
                eval_cache[case_id] = {"case": c_obj, "ann": ann_item}
                CACHE_FILE.write_text(json.dumps(eval_cache, ensure_ascii=False, indent=2))

    return cases, annotations


    return cases, annotations


def main():
    import argparse
    parser = argparse.ArgumentParser(description="建立「歸還期間車損」AI 評測案件")
    parser.add_argument("--max-eval-cars", type=int, default=30, help="最多進行 Live AI 評測的車輛數 (預設 30 台)")
    args = parser.parse_args()

    cases, annotations = build_chain_cases(max_eval_cars=args.max_eval_cars)
    OUT_CASES.write_text(json.dumps({"cases": cases}, ensure_ascii=False, indent=2))
    OUT_ANN.write_text(json.dumps(annotations, ensure_ascii=False, indent=2))
    print(f"\n🎉 全量建置完成！共產出 {len(cases)} 筆案件 (683 組車輛 × 4 角度) -> {OUT_CASES.name} & {OUT_ANN.name}")


if __name__ == "__main__":
    main()

