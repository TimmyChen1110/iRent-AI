#!/usr/bin/env python3
"""現場實測入口：任意照片即時判定（不綁資料集，demo 主力）。

跑完整鏈路：① Quality Gate（品質不合格直接擋下並說明原因）
          → ② gemini-3.7-flash 快篩 → ③ 臨界案件升級 Pro 多數決（級聯）
          → ④ 視覺標註（判定與 box_2d 同一次呼叫取得，免費層 RPM 友善）

判定邏輯抽成可複用函式：judge_pair() / judge_interior()，
dashboard/server.py 的 POST /api/judge 直接呼叫，不重寫一份。

用法：
  python3 judge_photos.py 借車照.jpg 還車照.jpg          # 車損比對
  python3 judge_photos.py --interior 車內照.jpg          # 車內整潔
  python3 judge_photos.py 借.jpg 還.jpg --skip-gate      # 品質不合格仍強制判定
輸出：判定 JSON（stdout）＋ 標註後圖片（annotated/live_*_annotated.jpg）
"""
import argparse
import json
import sys
import time
from pathlib import Path

from google.genai import types, errors
from PIL import Image, ImageOps
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from quality_gate import gate  # noqa: E402
from run_eval_gemini import get_client, prep_image, Throttle, SYSTEM as PAIR_SYSTEM  # noqa: E402
from run_cascade import needs_escalation, majority  # noqa: E402
from annotate_damage import draw_annotations, AnnotatedResult, Finding, OUT  # noqa: E402
from classify_interior import SYSTEM as INTERIOR_SYSTEM  # noqa: E402

# iPhone 預設拍 HEIC——現場實測讓評審用手機拍，必須吃得下（註冊一次全 process 生效）
try:
    from pillow_heif import register_heif_opener  # noqa: E402
    register_heif_opener()
except ImportError:
    pass  # 沒裝時 jpg/png 照常，HEIC 會在開檔時報錯

SCREEN_MODEL = "gemini-3.7-flash"
REVIEW_MODEL = "gemini-3.1-pro-preview"


# ---------- Schema：判定 + box_2d 合併（一次呼叫同時拿到判定與標註座標） ----------

class LiveDamage(BaseModel):
    location: str = Field(description="損傷位置，例如：左後葉子板、前保桿下緣")
    type: str = Field(description="損傷類型：刮痕 | 凹陷 | 破損 | 掉漆 | 其他")
    severity: str = Field(description="嚴重度：low | medium | high")
    confidence: float = Field(description="0~1，判定為新損傷的信心")
    reasoning: str = Field(description="一句話：為何判定為新增而非反光/髒污/既有舊損")
    box_2d: list[int] = Field(description="損傷在【還車照】上的位置 [ymin, xmin, ymax, xmax]，座標正規化為 0~1000，框要緊貼損傷範圍")


class LiveAssessment(BaseModel):
    angle_match: bool = Field(description="兩張照片是否為同一車輛的同一方位、可有效比對")
    new_damage_found: bool = Field(description="還車照中是否有借車照沒有的新損傷")
    damages: list[LiveDamage] = Field(description="新損傷清單，無則空陣列")
    no_damage_confidence: float = Field(description="0~1：判定「無新損」的信心。new_damage_found 為 true 時填 0")
    pre_existing_notes: str = Field(description="兩張照片皆存在的既有損傷簡述，無則空字串")


class LiveSpot(BaseModel):
    label: str = Field(description="短標籤，例如：遺留垃圾、液體污漬、泥沙、毛髮、菸蒂")
    severity: str = Field(description="low | medium | high")
    confidence: float = Field(description="0~1")
    description: str = Field(description="一句話中文說明（位置+狀況），將直接顯示在圖上")
    box_2d: list[int] = Field(description="髒污點在照片上的位置 [ymin, xmin, ymax, xmax]，0~1000 正規化，框要緊貼髒污範圍")


class LiveInterior(BaseModel):
    level: str = Field(description="整潔分級：髒汙 | 普通 | 乾淨")
    confidence: float = Field(description="0~1 分級信心")
    findings: list[LiveSpot] = Field(description="具體髒污點清單（乾淨則空陣列）。光影、座椅紋路、固定配備不標")
    reasoning: str = Field(description="一句話說明分級依據")


PAIR_SYSTEM_LIVE = PAIR_SYSTEM + """
8. 每個新損傷除文字說明外，一併回傳其在【還車照】上的精確 box_2d（[ymin,xmin,ymax,xmax]，0~1000 正規化）。框要緊貼損傷範圍，不要框整個部件。"""

INTERIOR_SYSTEM_LIVE = INTERIOR_SYSTEM + """
5. 每個具體髒污點一併回傳精確 box_2d（[ymin,xmin,ymax,xmax]，0~1000 正規化），框要緊貼髒污範圍。"""


# ---------- 核心呼叫（重試 + 複核模型 404 自動 fallback） ----------

def _call(client, model, contents, system, schema, throttle, retries=3, fallback=None):
    for i in range(retries):
        throttle.wait()
        try:
            resp = client.models.generate_content(
                model=model, contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_schema=schema,
                    temperature=0.1,
                ),
            )
            if resp.parsed:
                return model, resp.parsed
        except errors.APIError as e:
            if e.code == 404 and fallback and model != fallback:
                model = fallback
                continue
            if e.code in (429, 500, 503):
                time.sleep(15 * (i + 1))
                continue
            raise
    raise RuntimeError(f"{model} 判定失敗（重試已用盡）")


def _run_gate(photos: dict, interior=False) -> dict:
    """photos: {名稱: 路徑}。回傳各照品質檢核結果。"""
    out = {}
    for name, p in photos.items():
        ok, reasons, m = gate(str(p), interior=interior)
        out[name] = {"pass": ok, "reasons": reasons, **m}
    return out


def triage(a: dict):
    """P1/P2/P3 分流（與 dashboard build_cases 同一套規則）。"""
    if not a["angle_match"]:
        return "P2", "無法比對"
    if a["new_damage_found"]:
        mx = max((d["confidence"] for d in a["damages"]), default=0)
        hi = any(d["severity"] == "high" for d in a["damages"])
        return ("P1", "新車損") if (mx >= 0.85 or hi) else ("P2", "疑似新損")
    return "P3", "正常"


# ---------- 車損比對（借照 vs 還照） ----------

def judge_pair(pickup, ret, client=None, votes=3, rpm=8, skip_gate=False, log=lambda m: None):
    """回傳 (result_dict, 標註後 PIL Image 或 None)。"""
    t0 = time.time()
    result = {"mode": "pair", "pickup": str(pickup), "return": str(ret)}

    # ① Quality Gate
    gates = _run_gate({"pickup": pickup, "return": ret})
    result["gate"] = gates
    result["gate_pass"] = all(g["pass"] for g in gates.values())
    log(f"① Quality Gate：借車照 {'✓' if gates['pickup']['pass'] else '✗'}／還車照 {'✓' if gates['return']['pass'] else '✗'}")
    if not result["gate_pass"] and not skip_gate:
        result.update(verdict="retake", level="P2", kind="品質不合格",
                      elapsed_s=round(time.time() - t0, 1))
        return result, None

    # ② 快篩
    client = client or get_client()
    throttle = Throttle(rpm)
    contents = [
        "方位：未知（請先自行確認兩張照片是否為同一車輛的同一方位）。第一張＝借車照：",
        types.Part.from_bytes(data=prep_image(str(pickup)), mime_type="image/jpeg"),
        "第二張＝還車照：",
        types.Part.from_bytes(data=prep_image(str(ret)), mime_type="image/jpeg"),
        "請比對並輸出判定結果。",
    ]
    used, parsed = _call(client, SCREEN_MODEL, contents, PAIR_SYSTEM_LIVE, LiveAssessment, throttle)
    screening = parsed.model_dump()
    result["screening"] = {"model": used, "assessment": screening}
    log(f"② 快篩（{used}）：{'偵測到新損' if screening['new_damage_found'] else '無法比對' if not screening['angle_match'] else '未發現新損'}")

    # ③ 級聯：臨界案件升級 Pro 多數決
    final = screening
    result["cascade"] = None
    reason = needs_escalation(screening)
    if reason:
        log(f"③ 臨界案件（{reason}）→ 升級 {REVIEW_MODEL} {votes} 票多數決")
        vlist, model = [], REVIEW_MODEL
        for _ in range(votes):
            try:
                model, pv = _call(client, model, contents, PAIR_SYSTEM_LIVE, LiveAssessment,
                                  throttle, fallback=SCREEN_MODEL)
                vlist.append(pv.model_dump())
            except Exception as e:
                log(f"   複核一票失敗：{str(e)[:80]}")
        if vlist:
            final = majority(vlist)
            result["cascade"] = {"reason": reason, "model": model,
                                 "votes": [v["new_damage_found"] for v in vlist],
                                 "flipped": final["new_damage_found"] != screening["new_damage_found"]}
            log(f"   投票 {[v['new_damage_found'] for v in vlist]} → {'翻轉' if result['cascade']['flipped'] else '維持'}")
    result["final"] = final
    result["level"], result["kind"] = triage(final)
    result["verdict"] = ("damage" if final["new_damage_found"]
                         else "uncomparable" if not final["angle_match"] else "clean")

    # ④ 視覺標註（座標已隨判定取得，零額外 API）
    findings = [Finding(box_2d=d["box_2d"], label=d["type"], severity=d["severity"],
                        confidence=d["confidence"], description=f"{d['location']}：{d['reasoning']}")
                for d in final["damages"] if len(d.get("box_2d") or []) == 4]
    summary = (f"偵測到 {len(findings)} 處新增車損" if final["new_damage_found"]
               else "兩張照片無法有效比對" if not final["angle_match"] else "未發現新增車損")
    target = ImageOps.exif_transpose(Image.open(ret)).convert("RGB")
    annotated = draw_annotations(target, AnnotatedResult(findings=findings, summary=summary))
    log(f"④ 視覺標註 {len(findings)} 處")
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result, annotated


# ---------- 車內整潔（單張） ----------

def judge_interior(photo, client=None, rpm=8, skip_gate=False, log=lambda m: None):
    """回傳 (result_dict, 標註後 PIL Image 或 None)。"""
    t0 = time.time()
    result = {"mode": "interior", "photo": str(photo)}

    gates = _run_gate({"photo": photo}, interior=True)  # 車內專用門檻（車外門檻會誤擋 12.5%）
    result["gate"] = gates
    result["gate_pass"] = gates["photo"]["pass"]
    log(f"① Quality Gate：{'✓' if result['gate_pass'] else '✗'}")
    if not result["gate_pass"] and not skip_gate:
        result.update(verdict="retake", level="P2", kind="品質不合格",
                      elapsed_s=round(time.time() - t0, 1))
        return result, None

    client = client or get_client()
    throttle = Throttle(rpm)
    contents = [
        "還車車內照：",
        types.Part.from_bytes(data=prep_image(str(photo)), mime_type="image/jpeg"),
        "請判定整潔分級並標註髒污點。",
    ]
    used, parsed = _call(client, SCREEN_MODEL, contents, INTERIOR_SYSTEM_LIVE, LiveInterior, throttle)
    screening = parsed.model_dump()
    result["screening"] = {"model": used, "assessment": screening}
    log(f"② 快篩（{used}）：{screening['level']}（{screening['confidence']:.2f}）")

    # 級聯：判髒汙或低信心 → Pro 複核確認（與 classify_interior 同一套規則）
    final = screening
    result["cascade"] = None
    if screening["level"] == "髒汙" or screening["confidence"] < 0.7:
        log(f"③ 臨界案件 → 升級 {REVIEW_MODEL} 複核")
        try:
            model, pv = _call(client, REVIEW_MODEL, contents, INTERIOR_SYSTEM_LIVE, LiveInterior,
                              throttle, fallback=SCREEN_MODEL)
            final = pv.model_dump()
            result["cascade"] = {"reason": "髒汙須複核確認" if screening["level"] == "髒汙" else f"低信心({screening['confidence']:.2f})",
                                 "model": model, "flipped": final["level"] != screening["level"]}
            log(f"   複核（{model}）：{final['level']}（{'翻轉' if result['cascade']['flipped'] else '維持'}）")
        except Exception as e:
            log(f"   複核失敗，沿用快篩：{str(e)[:80]}")
    result["final"] = final
    result["level"] = "P1" if final["level"] == "髒汙" else "P3"
    result["kind"] = {"髒汙": "車內髒汙", "普通": "車內正常", "乾淨": "車內正常"}.get(final["level"], "車內")
    result["verdict"] = "dirty" if final["level"] == "髒汙" else "clean"

    findings = [Finding(**f) for f in final["findings"] if len(f.get("box_2d") or []) == 4]
    target = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    annotated = draw_annotations(target, AnnotatedResult(
        findings=findings, summary=f"整潔分級：{final['level']}"))
    log(f"④ 視覺標註 {len(findings)} 處")
    result["elapsed_s"] = round(time.time() - t0, 1)
    return result, annotated


# ---------- CLI ----------

def main():
    ap = argparse.ArgumentParser(description="任意照片即時判定（不綁資料集）")
    ap.add_argument("photos", nargs="*", help="借車照 還車照（兩張，車損比對模式）")
    ap.add_argument("--interior", help="車內照路徑（單張模式）")
    ap.add_argument("--skip-gate", action="store_true", help="品質不合格仍強制判定")
    ap.add_argument("--votes", type=int, default=3, help="級聯複核票數")
    ap.add_argument("--rpm", type=int, default=8, help="每分鐘請求上限（免費 key 建議 ≤10）")
    ap.add_argument("--out", help="標註圖輸出路徑（預設 annotated/live_<檔名>_annotated.jpg）")
    args = ap.parse_args()

    log = lambda m: print(m, file=sys.stderr, flush=True)  # noqa: E731 進度走 stderr，stdout 保持純 JSON
    if args.interior:
        result, img = judge_interior(args.interior, rpm=args.rpm, skip_gate=args.skip_gate, log=log)
        stem = Path(args.interior).stem
    elif len(args.photos) == 2:
        result, img = judge_pair(*args.photos, votes=args.votes, rpm=args.rpm,
                                 skip_gate=args.skip_gate, log=log)
        stem = Path(args.photos[1]).stem
    else:
        ap.error("用法：judge_photos.py 借車照 還車照，或 --interior 車內照")

    if img is not None:
        out = Path(args.out) if args.out else OUT / f"live_{stem}_annotated.jpg"
        img.save(out, quality=88)
        result["annotated"] = str(out)
        log(f"標註圖 → {out}")
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
