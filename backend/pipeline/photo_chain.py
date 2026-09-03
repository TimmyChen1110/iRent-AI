#!/usr/bin/env python3
"""⑥ Photo-chain：跨訂單車況鏈——比對基準改用「同車前一單的還車照」。

治兩個根本問題：
  1. 借車照拍錯側／品質差 → 唯一 FN（RDH-3092）與多組排除案例的成因。
     前一單還車照與本單還車照都由「在意車況的還車流程」產生，品質與角度更一致。
  2. 責任歸屬：A 用戶造成的損傷若當單漏抓，下一單用 chain 仍可定位到
     「首次出現於哪一單」——配合損傷護照完成責任回溯。

資料：車外車內照片上傳清單.xlsx 中 1,126 台車有 ≥2 筆訂單的車外照（Azure Blob 可下載）。

用法：python3 photo_chain.py --car RDL-8265          # 下載 + 鏈式判定
      python3 photo_chain.py --car RDL-8265 --votes 3
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, prep_image, Assessment, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
CHAIN_DIR = HERE / "chain_photos"
DL_TIMEOUT = 30   # 秒；單張照片下載逾時（見 download() 註解）

SYSTEM = """你是 iRent 共享汽車的車況比對專家。你會收到同一台車的兩張還車照：
第一張是「前一筆訂單」還車時拍的（基準），第二張是「本筆訂單」還車時拍的。

任務：判斷本單還車照中，是否存在前一單還車照沒有的【新增車損】。
若有，該損傷即發生於本筆訂單期間，責任歸屬明確。

準則：
1. 兩張照片拍攝方位應相同；若明顯不同方位，angle_match = false。
2. 光線反射、水痕、髒污、倒影不是車損。
3. 基準照已存在的損傷不算新增。
4. no_damage_confidence 誠實反映把握程度。"""


def download(car):
    cands = json.loads((HERE / "chain_candidates.json").read_text())
    orders = cands[car]
    d = CHAIN_DIR / car
    d.mkdir(parents=True, exist_ok=True)
    files = {}
    for order, itypes in orders.items():
        for itype, meta in itypes.items():
            fp = d / f"{order}_{itype}.png"
            if not fp.exists():
                # 必須設 timeout：Azure Blob 偶有連線不回應，urlretrieve 預設
                # 無逾時會永久掛住整趟掃描（gate_chain 實測卡 23 分鐘）
                try:
                    with urllib.request.urlopen(meta["url"], timeout=DL_TIMEOUT) as r:
                        data = r.read()
                    fp.write_bytes(data)
                except Exception as e:
                    fp.unlink(missing_ok=True)   # 不留半截檔，下次可重試
                    print(f"  下載失敗 {car}/{order}_{itype}: {e}", file=sys.stderr)
                    continue
            files.setdefault(order, {})[itype] = {"path": str(fp), "ts": meta["ts"], "guess": meta.get("guess")}
    return files


def sweep(n, model):
    """掃描模式：抽 n 台多訂單車各做一輪 1 票鏈式比對，找跨單新損案例。"""
    cands = json.loads((HERE / "chain_candidates.json").read_text())
    # 優先挑「每單都有 4 方位」的車，比對面最完整；固定排序取前 n 台（可重現）
    good = sorted(c for c, orders in cands.items()
                  if len(orders) >= 2 and all(len(v) >= 4 for v in orders.values()))
    picks = good[:n]
    print(f"掃描 {len(picks)} 台（候選 {len(good)} 台）：{', '.join(picks)}")
    hits = []
    for car in picks:
        try:
            r = run_chain(car, 1, model)
        except Exception as e:
            print(f"  ! {car}: {str(e)[:80]}")
            continue
        liable = [x for x in r if x["liable_order"]]
        if liable:
            hits.append(car)
    print(f"\n掃描完成：{len(hits)} 台偵測到跨單新損 → {hits}")
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--car", default="RDL-8265")
    ap.add_argument("--votes", type=int, default=1)
    ap.add_argument("--model", default="gemini-3.7-flash")
    ap.add_argument("--sweep", type=int, default=0, help="掃描 N 台多訂單車找跨單新損")
    args = ap.parse_args()

    if args.sweep:
        sweep(args.sweep, args.model)
        return
    run_chain(args.car, args.votes, args.model)


def run_chain(car, votes_n, model):
    files = download(car)
    orders = sorted(files, key=lambda o: min(m["ts"] for m in files[o].values()))
    print(f"{car}：{len(orders)} 筆訂單 → 鏈 {' → '.join('#' + o for o in orders)}")

    client = get_client()
    throttle = Throttle(8)
    results = []
    for prev, curr in zip(orders, orders[1:]):
        common = sorted(set(files[prev]) & set(files[curr]))
        print(f"\n=== #{prev} → #{curr}（{len(common)} 個方位可比對）===")
        for itype in common:
            a, b = files[prev][itype], files[curr][itype]
            votes = []
            for _ in range(votes_n):
                throttle.wait()
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=[
                            f"車輛 {car}，上傳分類（可能有誤）：{b.get('guess')}。",
                            "第一張＝前一單還車照（基準）：",
                            types.Part.from_bytes(data=prep_image(a["path"]), mime_type="image/jpeg"),
                            "第二張＝本單還車照：",
                            types.Part.from_bytes(data=prep_image(b["path"]), mime_type="image/jpeg"),
                            "請判斷本單是否有新增車損。",
                        ],
                        config=types.GenerateContentConfig(
                            system_instruction=SYSTEM,
                            response_mime_type="application/json",
                            response_schema=Assessment,
                            temperature=0.1,
                        ),
                    )
                except Exception as e:
                    print(f"  ! ImageType {itype}: {str(e)[:80]}")
                    continue
                if resp.parsed:
                    votes.append(resp.parsed.model_dump())
            if not votes:
                continue
            found = [v for v in votes if v["new_damage_found"]]
            v0 = (found or votes)[0]
            tag = "⚠ 新損" if len(found) > len(votes) / 2 else ("角度不符" if not v0["angle_match"] else "無新損")
            detail = "；".join(f"{d['location']}·{d['type']}({d['confidence']:.2f})" for d in v0["damages"]) \
                if found else f"no_dmg_conf={v0['no_damage_confidence']:.2f}"
            print(f"  ImageType {itype}（{b.get('guess')}）: {tag} — {detail}")
            results.append({"car": car, "prev": prev, "curr": curr, "itype": itype,
                            "guess": b.get("guess"), "votes": votes,
                            "liable_order": curr if len(found) > len(votes) / 2 else None})
    out = HERE / f"chain_results_{car.replace('-', '')}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1))
    liable = [r for r in results if r["liable_order"]]
    print(f"\n共 {len(results)} 組鏈式比對，{len(liable)} 組偵測到新損（責任單已標定）→ {out.name}")
    return results


if __name__ == "__main__":
    main()
