#!/usr/bin/env python3
"""Stage 7 — 多對象文案生成（Prompt 架構規格 §3 Stage 7）。

同一份判定結果，三個對象需要完全不同的語氣與詳略度：
  用戶     中性、不歸咎、不含術語與分數，附申訴管道
  客服     資訊密集，30 秒能決定核可與否，含信心/覆蓋度/爭議風險
  現場人員  工作指示，帶什麼工具、花多久，不需要判定邏輯

本階段不接觸影像，只吃前面階段的結構化結果——因此可用純文字模型，成本最低。

【防幻覺設計】
文案階段最大的風險是模型「補充」結構化資料裡沒有的內容（例如自行推測損傷成因、
杜撰金額）。除了在 prompt 中明令禁止，verify_grounding() 會在生成後做程式面檢查：
金額必須出現在輸入的估價區間內、不得出現歸咎性字眼。

用法：
  python3 notify.py --demo                     # 用範例資料跑一次
  python3 notify.py --case RCR-7661-左後        # 對真實案件生成
"""
import argparse
import json
import re
import sys
from pathlib import Path

from google.genai import types
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_eval_gemini import get_client, Throttle  # noqa: E402

HERE = Path(__file__).resolve().parent
MODEL = "gemini-3.7-flash"

# 歸咎性字眼：出現即視為違反規則（規格：不使用「你造成」「你弄的」等表述）
BLAME_PATTERNS = [r"你造成", r"你弄", r"你撞", r"你的疏失", r"您造成", r"您弄",
                  r"肇事", r"過失", r"賠償責任在"]


class UserNotification(BaseModel):
    title: str = Field(description="通知標題，簡短中性")
    body: str = Field(description="通知內文，120 字以內。中性、就事論事，說明發現什麼、依據為何、接下來會怎樣。不得使用歸咎性表述，不得出現技術術語、信心分數、內部代碼")
    evidence_note: str = Field(description="一句話說明判定依據（例如有取車照片可對比）")
    dispute_channel_note: str = Field(description="一句話說明如何申訴")


class CSBrief(BaseModel):
    summary: str = Field(description="案件摘要，資訊密集，可用內部代碼與分數")
    confidence_note: str = Field(description="判定信心說明，含原始信心與加權後信心")
    coverage_caveat: str = Field(description="觀測覆蓋度狀況與其對本案判定的影響；若基準拍攝品質不足須明說")
    recommended_action: str = Field(description="approve | review | reject")
    dispute_risk: str = Field(description="low | medium | high")
    dispute_risk_reason: str = Field(description="爭議風險判斷理由")


class WorkOrder(BaseModel):
    type: str = Field(description="cleaning | repair | both")
    priority: str = Field(description="urgent | normal")
    items: list[str] = Field(description="具體工作項目與所在區域")
    special_tools: list[str] = Field(description="所需特殊工具或耗材，無則空陣列")
    estimated_minutes: int = Field(description="預估工時（分鐘）")


class Notifications(BaseModel):
    user_notification: UserNotification
    cs_brief: CSBrief
    work_order: WorkOrder


SYSTEM = """你要根據車輛檢查結果，為三個不同對象生成通知文案。

【共同規則】
- 使用繁體中文，台灣用語
- 只陳述結構化資料中確實存在的內容，不得補充或推測。資料裡沒有的細節（損傷成因、
  發生時間、責任歸屬）一律不得出現
- 不使用「你造成」「你弄的」「肇事」「過失」等歸咎性表述
- 涉及金額時，只給資料中提供的區間，並註明以實際估價為準。不得自行計算或改寫金額

【對象一：用戶通知】
語氣中性、就事論事，重點在讓用戶知道發生什麼、依據是什麼、接下來會怎樣。
必須包含：發現的項目、判定依據（有取車照片對比可佐證）、申訴管道。
必須避免：技術術語、信心分數、內部代碼、分區英文代碼。
長度控制在 120 字以內。

【對象二：客服工作說明】
語氣簡潔、資訊密集，重點在讓客服 30 秒內能判斷該不該核可。
必須包含：判定信心、觀測覆蓋度狀況、模型的原始描述、建議處置、爭議風險提示。
可以使用內部代碼與分數。
若基準（借車照）對該部位的觀測品質不足，必須在 coverage_caveat 明確警告，
並將 dispute_risk 提高——這種案件若強行索賠，用戶申訴極可能成立。

【對象三：清潔或維修派工單】
語氣為工作指示，重點在讓現場人員知道要帶什麼工具、預計花多久。
必須包含：具體項目與所在區域、所需特殊處理、預估工時。
不需要包含：信心分數、判定邏輯、用戶資訊。

【dispute_risk 判定準則】
high    基準觀測品質不足、損傷位於易爭議部位（保桿角落、輪圈）、或加權信心 < 0.7
medium  信心中等，或損傷細微不易在照片上辨識
low     基準清晰、損傷明確、多角度一致"""


def build_context(case: dict) -> str:
    """把各階段結構化結果整理成 prompt 輸入。"""
    return json.dumps(case, ensure_ascii=False, indent=1)


def generate(case: dict, client=None, throttle=None, model=MODEL) -> dict:
    client = client or get_client()
    throttle = throttle or Throttle(8)
    contents = ["【檢查結果】\n" + build_context(case),
                "\n請為三個對象生成通知文案。"]
    throttle.wait()
    resp = client.models.generate_content(
        model=model, contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM,
            response_mime_type="application/json",
            response_schema=Notifications,
            temperature=0.3,   # 文案略高於 0，避免三個對象語氣雷同
        ),
    )
    out = resp.parsed.model_dump()
    out["grounding_check"] = verify_grounding(out, case)
    return out


def verify_grounding(out: dict, case: dict) -> dict:
    """程式面查核：金額是否落在給定區間、是否出現歸咎字眼。

    模型可能「補充」資料中沒有的內容——這是文案階段最大的風險，
    尤其金額與責任歸屬會直接造成客訴。故不只靠 prompt 約束，生成後再驗一次。
    """
    problems = []
    text_all = json.dumps(out, ensure_ascii=False)

    for pat in BLAME_PATTERNS:
        if re.search(pat, text_all):
            problems.append(f"出現歸咎性表述：{pat}")

    # 用戶通知不得含信心分數或英文分區代碼
    ub = out["user_notification"]["body"]
    if re.search(r"0\.\d{2}", ub):
        problems.append("用戶通知含信心分數")
    if re.search(r"\b(FB|RB|FD_[LR]|RD_[LR]|FF_[LR]|RF_[LR]|WHL_\w+)\b", ub):
        problems.append("用戶通知含內部分區代碼")
    if len(ub) > 130:
        problems.append(f"用戶通知過長（{len(ub)} 字 > 120）")

    # 金額必須來自輸入的估價區間
    allowed = set()
    for d in case.get("damages", []):
        for v in (d.get("estimate_twd") or []):
            allowed.add(int(v))
    if allowed:
        for m in re.findall(r"([\d,]{3,})\s*元", text_all):
            n = int(m.replace(",", ""))
            if n not in allowed:
                problems.append(f"出現未經授權的金額：{n} 元（允許：{sorted(allowed)}）")

    return {"passed": not problems, "problems": problems}


DEMO_CASE = {
    "case_id": "RCR-7661-左後",
    "vehicle": "RCR-7661",
    "new_damage_found": True,
    "damages": [{
        "location": "左後保險桿下緣", "panel": "RB", "panel_zh": "後保桿",
        "damage_type": "scratch", "damage_type_zh": "刮痕",
        "observation": "左後保險桿下緣約 15 公分水平線狀白色痕跡，中央可見底層素材色",
        "estimated_size_cm": 15, "raw_confidence": 0.92,
        "prior_q": 0.72, "weighted_confidence": 0.66,
        "repair_action": "保桿修補烤漆", "band": "B", "estimate_twd": [1500, 5000],
        "disposition": "human_review",
        "reason": "基準觀測品質偏低（prior_q=0.72），信心折損為 0.66，須人工複核確認",
    }],
    "coverage": {"panel": "RB", "best_quality": 0.72,
                 "environment_flags": ["strong_reflection"],
                 "note": "借車照該部位有強反光，觀測品質偏低"},
    "interior": {"level": "普通", "estimated_cleaning_minutes": 12,
                 "items": ["前排地墊有輕微泥沙", "杯架有飲料殘漬"]},
}


def main():
    ap = argparse.ArgumentParser(description="Stage 7 多對象文案生成")
    ap.add_argument("--demo", action="store_true", help="用範例案件跑一次")
    ap.add_argument("--case", help="案件 ID（車牌-方位），從 stage4_impact.json 讀取")
    args = ap.parse_args()

    if args.demo:
        case = DEMO_CASE
    elif args.case:
        impact = HERE / "stage4_impact.json"
        if not impact.exists():
            sys.exit("找不到 stage4_impact.json——請先執行 diff_new_damage.py --apply")
        rows = {r["case"]: r for r in json.loads(impact.read_text())["rows"]}
        row = rows.get(args.case)
        if not row:
            sys.exit(f"找不到案件 {args.case}")
        case = {"case_id": args.case, "vehicle": args.case.rsplit("-", 1)[0],
                "new_damage_found": row["detected"], "damages": row["damages"],
                "case_level": row["case_level"], "disposition": row["case_disposition"]}
    else:
        ap.error("請指定 --demo 或 --case")

    out = generate(case)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    g = out["grounding_check"]
    print(("\n✔ 查核通過" if g["passed"] else "\n✘ 查核未過：" + "；".join(g["problems"])),
          file=sys.stderr)


if __name__ == "__main__":
    main()
