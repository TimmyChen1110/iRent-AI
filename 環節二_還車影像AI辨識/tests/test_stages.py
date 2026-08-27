"""Prompt 架構規格新增階段的回歸測試——全部零 API 成本、純函式。

覆蓋 taxonomy（共用詞彙）／coverage（Stage 1 合併與查詢）／
diff_new_damage（Stage 4 覆蓋度加權）／disposition（Stage 6 估價分流）／
notify（Stage 7 文案查核）。

這幾支決定了「一筆偵測到的損傷最後會不會被拿去跟用戶索賠」。
改壞了不會有任何流程報錯，只會靜靜地把不該索賠的案件送出去——
Stage 4 的加權尤其是保護用戶的最後一道防線。
"""
import pytest

import taxonomy as T
from coverage import merge_coverage, prior_quality, Q_FULL_TRUST, Q_MIN_CLAIM
from diff_new_damage import (
    weigh, panel_of, match_pre_existing, assess_case,
    Q_FULL_TRUST as D_FULL, Q_MIN_CLAIM as D_MIN, PRIOR_Q_UNKNOWN,
)
from disposition import (
    classify_repair, decide, assess, threshold_for_budget,
    CLAIM_HANDLING_COST, PRICE_BANDS,
)
from notify import verify_grounding


# ---------- taxonomy：共用詞彙 ----------

class TestTaxonomy:
    def test_分區代碼無重複(self):
        assert len(T.PANEL_CODES) == len(set(T.PANEL_CODES))

    def test_每個分區都有中文與材質(self):
        for c in T.PANEL_CODES:
            assert T.PANEL_ZH[c] and T.PANEL_MATERIAL[c]

    def test_方位裁切只回該側分區(self):
        # 左前照不該出現右側分區，否則模型會被誘導幻覺
        left = T.panels_for_angle("左前")
        assert "FF_L" in left and "FD_L" in left
        assert not any(p.endswith("_R") or p.endswith("_FR") or p.endswith("_RR")
                       for p in left)

    def test_未知方位回傳全表(self):
        assert T.panels_for_angle(None) == T.PANEL_CODES
        assert T.panels_for_angle("不存在") == T.PANEL_CODES

    def test_舊中文部位可轉分區代碼(self):
        assert T.part_to_panel("前保險桿") == "FB"
        assert T.part_to_panel("左前葉子板") == "FF_L"

    def test_左右不分部位靠方位補側別(self):
        # part_tagger 的「車燈」不分左右，須用方位還原
        assert T.part_to_panel("車燈", "左前") == "HL_L"
        assert T.part_to_panel("車燈", "右後") == "TL_R"
        assert T.part_to_panel("輪圈/輪胎", "左後") == "WHL_RL"

    def test_無方位的左右不分部位回None(self):
        assert T.part_to_panel("車燈", None) is None

    def test_類型相容組(self):
        assert T.types_compatible("scratch", "scratch")
        assert T.types_compatible("scratch", "scuff")
        assert T.types_compatible("dent", "deformation")
        assert not T.types_compatible("scratch", "dent")
        assert not T.types_compatible("glass_crack", "rim_curb")

    def test_舊中文損傷類型可轉代碼(self):
        assert T.LEGACY_TYPE_TO_CODE["刮痕"] == "scratch"
        assert T.LEGACY_TYPE_TO_CODE["凹陷"] == "dent"

    def test_UV距離(self):
        assert T.uv_distance([0.5, 0.5], [0.5, 0.5]) == 0
        assert T.uv_distance([0.0, 0.0], [0.3, 0.4]) == pytest.approx(0.5)

    def test_UV缺值視為不匹配(self):
        # 舊資料沒有 UV——必須回 inf 而非 0，否則會被誤判為「完全同位置」
        assert T.uv_distance(None, [0.5, 0.5]) == float("inf")
        assert T.uv_distance([0.5], [0.5, 0.5]) == float("inf")

    def test_深度清潔項目都在髒汙代碼表內(self):
        assert set(T.DEEP_CLEAN_ITEMS) <= set(T.COUNTABLE_CODES + T.AREA_CODES)

    def test_信心校準文字含五個區間(self):
        assert T.CONFIDENCE_CALIBRATION.count("\n") == 4


# ---------- Stage 1：覆蓋度合併 ----------

def photo(name, panels, **kw):
    return {"photo": name, "covered_panels": [{"panel": p, "quality": q}
                                              for p, q in panels], **kw}


class TestCoverageMerge:
    def test_單張照片(self):
        m = merge_coverage([photo("a.jpg", [("FB", 0.9), ("FD_L", 0.6)])])
        assert m["panels_observed"] == 2
        assert prior_quality(m, "FB") == 0.9

    def test_多張取最佳品質(self):
        m = merge_coverage([photo("a.jpg", [("FB", 0.5)]),
                            photo("b.jpg", [("FB", 0.9)])])
        assert prior_quality(m, "FB") == 0.9

    def test_同分區多張都記錄來源(self):
        m = merge_coverage([photo("a.jpg", [("FB", 0.9)]),
                            photo("b.jpg", [("FB", 0.5)])])
        entry = [c for c in m["panel_coverage_map"] if c["panel"] == "FB"][0]
        assert set(entry["observed_in"]) == {"a.jpg", "b.jpg"}

    def test_錯誤照片被略過(self):
        m = merge_coverage([{"photo": "x", "error": "boom"},
                            photo("a.jpg", [("FB", 0.8)])])
        assert m["panels_observed"] == 1

    def test_查無分區回None(self):
        m = merge_coverage([photo("a.jpg", [("FB", 0.9)])])
        assert prior_quality(m, "ROOF") is None
        assert prior_quality(m, None) is None

    def test_空輸入不炸(self):
        m = merge_coverage([])
        assert m["overall_coverage_score"] == 0.0
        assert m["panels_observed"] == 0

    def test_可信任與不可主張計數(self):
        m = merge_coverage([photo("a.jpg", [("FB", 0.95), ("RB", 0.65), ("TG", 0.3)])])
        assert m["panels_trustworthy"] == sum(
            1 for q in (0.95, 0.65, 0.3) if q >= Q_FULL_TRUST)
        assert m["panels_unclaimable"] == sum(
            1 for q in (0.95, 0.65, 0.3) if q < Q_MIN_CLAIM)


# ---------- Stage 4：覆蓋度加權（保護用戶的核心防線） ----------

class TestWeigh:
    def test_基準清晰高信心可自動處置(self):
        w = weigh(0.95, 0.9)
        assert w["disposition"] == "auto_action" and w["level"] == "P1"
        assert w["claimable"] is True

    def test_基準沒拍清楚一律不得主張(self):
        # 這是整套設計最重要的防線：偵測信心再高也不能算在用戶頭上
        w = weigh(0.99, D_MIN - 0.01)
        assert w["disposition"] == "record_only"
        assert w["claimable"] is False
        assert "不得對用戶主張" in w["reason"]

    def test_基準普通最高只能人工複核(self):
        w = weigh(0.99, (D_MIN + D_FULL) / 2)
        assert w["disposition"] == "human_review" and w["level"] == "P2"

    def test_基準普通時高信心也不會自動處置(self):
        # 折損區間的上限就是 P2，不論偵測多有把握
        for conf in (0.85, 0.95, 1.0):
            assert weigh(conf, D_FULL - 0.01)["disposition"] == "human_review"

    def test_加權信心確實相乘(self):
        assert weigh(0.8, 0.9)["weighted_confidence"] == pytest.approx(0.72)

    def test_查無基準用保守值(self):
        w = weigh(0.9, None)
        assert w["prior_q"] is None
        assert w["weighted_confidence"] == pytest.approx(0.9 * PRIOR_Q_UNKNOWN)

    def test_低信心即使基準清晰也只記錄(self):
        w = weigh(0.3, 1.0)
        assert w["disposition"] == "record_only" and w["claimable"] is False

    def test_門檻邊界(self):
        assert weigh(0.9, D_MIN)["disposition"] != "record_only"   # 恰好等於 → 進複核
        # gate 模式：基準過關後看原始偵測信心，0.9 ≥ 0.85 → 自動處置
        assert weigh(0.9, D_FULL)["disposition"] == "auto_action"
        assert weigh(0.8, D_FULL)["disposition"] == "human_review"  # 信心不足仍降級

    def test_相乘模式在本資料集無法自動處置(self):
        # 規格原文的相乘式：prior_q 實測最大 0.75，0.95×0.75=0.71 永遠 < 0.85。
        # 保留此測試以記錄「為何不用規格原文公式」——這是實測結論，不是實作偷懶。
        assert weigh(0.95, 0.75, mode="multiply")["disposition"] == "human_review"
        assert weigh(0.95, 0.75, mode="gate")["disposition"] == "auto_action"

    def test_相乘模式仍保留可用(self):
        assert weigh(1.0, 1.0, mode="multiply")["disposition"] == "auto_action"


class TestPanelOf:
    def test_直接給panel優先(self):
        assert panel_of({"panel": "RB", "part": "引擎蓋"}, "左後") == "RB"

    def test_用part標籤(self):
        assert panel_of({"part": "前保險桿"}, "左前") == "FB"

    def test_從location文字推部位(self):
        assert panel_of({"location": "右後保險桿（反光片右側）"}, "右後") == "RB"
        assert panel_of({"location": "左前葉子板下緣"}, "左前") == "FF_L"

    def test_推不出來回None(self):
        assert panel_of({"location": "某處"}, "左前") is None
        assert panel_of({}, None) is None


class TestMatchPreExisting:
    def test_同分區同類型視為既有損(self):
        base = [{"kind": "pre_existing", "part": "後保險桿", "type": "刮痕",
                 "angle": "左後", "id": "D-001"}]
        m = match_pre_existing({"part": "後保險桿", "type": "刮痕"}, base, "左後")
        assert m and m["id"] == "D-001"

    def test_不同分區不匹配(self):
        base = [{"kind": "pre_existing", "part": "引擎蓋", "type": "刮痕",
                 "angle": "左後", "id": "D-001"}]
        assert match_pre_existing({"part": "後保險桿", "type": "刮痕"}, base, "左後") is None

    def test_新損紀錄不當作既有損(self):
        # kind=new 的紀錄不能拿來抵銷新損，否則同一處損傷會自我匹配而消失
        base = [{"kind": "new", "part": "後保險桿", "type": "刮痕",
                 "angle": "左後", "id": "D-001"}]
        assert match_pre_existing({"part": "後保險桿", "type": "刮痕"}, base, "左後") is None

    def test_UV距離超過容許半徑不匹配(self):
        base = [{"kind": "pre_existing", "part": "後保險桿", "type": "刮痕",
                 "angle": "左後", "id": "D-001", "position_uv": [0.1, 0.1]}]
        far = {"part": "後保險桿", "type": "刮痕", "position_uv": [0.9, 0.9]}
        assert match_pre_existing(far, base, "左後") is None
        near = {"part": "後保險桿", "type": "刮痕", "position_uv": [0.12, 0.12]}
        assert match_pre_existing(near, base, "左後") is not None


class TestAssessCase:
    def test_無新損直接P3(self):
        out = assess_case({"new_damage_found": False, "damages": []}, None, "左後")
        assert out["case_level"] == "P3"
        assert out["case_disposition"] == "no_new_damage"

    def test_案件層級取最嚴重那筆(self):
        cov = merge_coverage([photo("a.jpg", [("RB", 0.95), ("RD_L", 0.3)])])
        a = {"new_damage_found": True, "damages": [
            {"location": "左後門", "type": "刮痕", "confidence": 0.9},   # 基準差 → P3
            {"location": "後保險桿", "type": "刮痕", "confidence": 0.95},  # 基準好 → P1
        ]}
        out = assess_case(a, cov, "左後")
        assert out["case_level"] == "P1"

    def test_既有損被標記為非新損(self):
        cov = merge_coverage([photo("a.jpg", [("RB", 0.95)])])
        a = {"new_damage_found": True,
             "damages": [{"location": "後保險桿", "type": "刮痕", "confidence": 0.95}]}
        recs = [{"kind": "pre_existing", "part": "後保險桿", "type": "刮痕",
                 "angle": "左後", "id": "D-009"}]
        out = assess_case(a, cov, "左後", recs)
        d = out["damages"][0]
        assert d["disposition"] == "pre_existing" and d["claimable"] is False

    def test_尺寸與深度必須帶進下游(self):
        # Stage 6 靠 size_cm 決定級距。若 assess_case 沒把它帶下去，
        # 6cm 的小刮痕會被當成「任意尺寸」而落進最貴的級距，系統性高估修理費。
        cov = merge_coverage([photo("a.jpg", [("FD_L", 0.95)])])
        a = {"new_damage_found": True, "damages": [
            {"location": "左前門", "type": "刮痕", "confidence": 0.9,
             "estimated_size_cm": 6, "depth_assessment": "surface_only"}]}
        d = assess_case(a, cov, "左前")["damages"][0]
        assert d["estimated_size_cm"] == 6
        assert d["depth_assessment"] == "surface_only"
        # 端到端：6cm 鈑金刮痕應是局部烤漆 B，不是整片烤漆 C
        assert assess(d, panel=d["panel"], weighted_confidence=0.9)["band"] == "B"

    def test_無覆蓋度資料仍可運作(self):
        a = {"new_damage_found": True,
             "damages": [{"location": "後保險桿", "type": "刮痕", "confidence": 0.95}]}
        out = assess_case(a, None, "左後")
        assert out["coverage_available"] is False
        assert out["damages"][0]["prior_q"] is None


# ---------- Stage 6：估價與處置 ----------

class TestClassifyRepair:
    def test_小刮痕拋光級距A(self):
        r = classify_repair("scratch", size_cm=3, panel="FD_L")
        assert r["repair_action"] == "拋光" and r["band"] == "A"

    def test_中刮痕局部烤漆級距B(self):
        r = classify_repair("scratch", size_cm=12, panel="FD_L")
        assert r["band"] == "B"

    def test_長刮痕整片烤漆級距C(self):
        r = classify_repair("scratch", size_cm=40, panel="FD_L")
        assert r["band"] == "C"

    def test_塑膠件刮痕走保桿修補(self):
        # 同樣是刮痕，塑膠保桿與鈑金門板的維修方式不同
        r = classify_repair("scratch", size_cm=3, panel="FB")
        assert r["repair_action"] == "保桿修補烤漆" and r["band"] == "B"

    def test_凹陷伴隨破漆升級為C(self):
        small = classify_repair("dent", size_cm=5, panel="FD_L")
        assert small["band"] == "B"
        deep = classify_repair("dent", size_cm=5, panel="FD_L",
                               depth="substrate_exposed")
        assert deep["band"] == "C" and deep["repair_action"] == "鈑金＋烤漆"

    def test_裂痕換件級距D(self):
        assert classify_repair("crack", panel="RB")["band"] == "D"

    def test_玻璃小缺口修補大裂換件(self):
        assert classify_repair("glass_chip", size_cm=1)["band"] == "A"
        assert classify_repair("glass_crack")["band"] == "D"

    def test_接受舊中文類型(self):
        r = classify_repair("刮痕", size_cm=3, panel="FD_L")
        assert r["damage_type"] == "scratch"

    def test_尺寸未知不會誤判為小損(self):
        # size_cm=None 不該落進「≤5cm 拋光」這種最輕的級距
        r = classify_repair("scratch", size_cm=None, panel="FD_L")
        assert r["band"] != "A"

    def test_每個損傷類型都有規則(self):
        for code in T.DAMAGE_CODES:
            r = classify_repair(code, size_cm=10, panel="FB")
            assert r["band"] in PRICE_BANDS


class TestDecide:
    def _repair(self, band="B"):
        lo, hi = PRICE_BANDS[band]["range"]
        return {"band": band, "estimate_twd": [lo, hi], "repair_action": "測試"}

    def test_高信心中級距自動處置(self):
        d = decide(0.9, self._repair("B"))
        assert d["disposition"] == "auto_action" and d["level"] == "P1"

    def test_低價損傷不值得索賠(self):
        # 級距 A 中位 750 < 800 處理成本 → 主動放棄
        d = decide(0.99, self._repair("A"))
        assert d["disposition"] == "waive_not_worth_claiming"
        assert d["claimable"] is False

    def test_覆蓋度不足優先於一切(self):
        d = decide(0.99, self._repair("D"), coverage_blocked=True)
        assert d["disposition"] == "record_only" and d["claimable"] is False

    def test_中信心進複核(self):
        d = decide(0.7, self._repair("C"))
        assert d["disposition"] == "human_review" and d["level"] == "P2"

    def test_低信心僅記錄(self):
        d = decide(0.3, self._repair("C"))
        assert d["disposition"] == "record_only"

    def test_處理成本門檻一致(self):
        lo, hi = PRICE_BANDS["A"]["range"]
        assert (lo + hi) / 2 < CLAIM_HANDLING_COST, "級距A應低於索賠處理成本"

    def test_assess整合(self):
        out = assess({"type": "刮痕", "estimated_size_cm": 12}, panel="FD_L",
                     weighted_confidence=0.9)
        assert out["band"] == "B" and out["disposition"] == "auto_action"

    def test_assess以加權信心為準(self):
        # 原始信心 0.95 但加權後 0.5——必須用加權值決策
        out = assess({"type": "刮痕", "estimated_size_cm": 12, "confidence": 0.95},
                     panel="FD_L", weighted_confidence=0.5)
        assert out["disposition"] != "auto_action"


class TestThresholdBudget:
    def test_超出負荷會被指出(self):
        out = threshold_for_budget(120, 8, fpr=0.033, positive_rate=0.149, recall=0.857)
        assert out["within_budget"] is False
        assert "超出負荷" in out["recommendation"]

    def test_預算充足建議調降門檻(self):
        out = threshold_for_budget(50, 100, fpr=0.033, positive_rate=0.149, recall=0.857)
        assert out["within_budget"] is True
        assert "調降門檻" in out["recommendation"]

    def test_零容量不炸(self):
        out = threshold_for_budget(120, 0, fpr=0.033, positive_rate=0.149, recall=0.857)
        assert out["utilization"] == "n/a"


# ---------- Stage 7：文案查核 ----------

def _out(body="您好，還車檢查發現左後保桿有刮痕。", **over):
    base = {
        "user_notification": {"title": "通知", "body": body,
                              "evidence_note": "有取車照可對比", "dispute_channel_note": "可申訴"},
        "cs_brief": {"summary": "S", "confidence_note": "C", "coverage_caveat": "V",
                     "recommended_action": "review", "dispute_risk": "high",
                     "dispute_risk_reason": "R"},
        "work_order": {"type": "repair", "priority": "normal", "items": [],
                       "special_tools": [], "estimated_minutes": 30},
    }
    base["user_notification"].update(over)
    return base


class TestGrounding:
    def test_正常文案通過(self):
        assert verify_grounding(_out(), {"damages": []})["passed"]

    def test_歸咎性表述被攔(self):
        g = verify_grounding(_out(body="這是你造成的刮痕"), {"damages": []})
        assert not g["passed"] and any("歸咎" in p for p in g["problems"])

    def test_用戶通知含信心分數被攔(self):
        g = verify_grounding(_out(body="刮痕，信心 0.92"), {"damages": []})
        assert any("信心分數" in p for p in g["problems"])

    def test_用戶通知含內部代碼被攔(self):
        g = verify_grounding(_out(body="於 FD_L 發現刮痕"), {"damages": []})
        assert any("分區代碼" in p for p in g["problems"])

    def test_過長被攔(self):
        g = verify_grounding(_out(body="字" * 200), {"damages": []})
        assert any("過長" in p for p in g["problems"])

    def test_杜撰金額被攔(self):
        # 最危險的幻覺：模型自行算出一個不在估價區間內的數字
        case = {"damages": [{"estimate_twd": [1500, 5000]}]}
        g = verify_grounding(_out(body="預估 3,200 元"), case)
        assert not g["passed"] and any("未經授權的金額" in p for p in g["problems"])

    def test_區間內金額可通過(self):
        case = {"damages": [{"estimate_twd": [1500, 5000]}]}
        g = verify_grounding(_out(body="預估 1,500 至 5,000 元"), case)
        assert g["passed"]


class TestSeverityBand:
    """換件級距（D）須受 severity 調節——見 classify_repair docstring。

    現行判定的「破損」同時涵蓋「大燈碎裂、卡榫脫落」與「一條裂痕、接縫變寬」。
    只看類型會讓後者也報 12,000–40,000 元的換件價。
    """

    def test_高嚴重度破損維持換件D(self):
        r = classify_repair("破損", panel="FB", severity="high")
        assert r["band"] == "D" and r["repair_action"] == "換件"

    def test_中嚴重度破損降為修補C(self):
        r = classify_repair("破損", panel="FB", severity="medium")
        assert r["band"] == "C"
        assert r["estimate_twd"][1] < 40000

    def test_未給嚴重度維持原規則(self):
        assert classify_repair("破損", panel="FB")["band"] == "D"

    def test_非D級距不受影響(self):
        # 小刮痕不會因為 severity=high 就升級
        assert classify_repair("scratch", size_cm=3, panel="FD_L", severity="high")["band"] == "A"

    def test_assess會帶入severity(self):
        out = assess({"type": "破損", "severity": "medium"}, panel="FB", weighted_confidence=0.9)
        assert out["band"] == "C"


class TestMaterialSpecificRepair:
    """非鈑件材質的刮痕不可套用鈑件維修邏輯。

    曾產生「左後輪圈：刮痕修復（整片烤漆）」這種現場人員看不懂的派工單——
    輪圈是鋁圈，不能像鈑件那樣烤漆。
    """

    def test_輪圈刮痕走輪圈整新(self):
        r = classify_repair("刮痕", panel="WHL_RL")
        assert r["material"] == "鋁圈" and "輪圈" in r["repair_action"]
        assert "烤漆" not in r["repair_action"]

    def test_玻璃與燈殼不烤漆(self):
        for panel in ("WG_FL", "HL_L", "WS"):
            assert "烤漆" not in classify_repair("刮痕", panel=panel)["repair_action"]

    def test_鈑金仍走烤漆(self):
        assert "烤漆" in classify_repair("刮痕", size_cm=30, panel="FD_L")["repair_action"]

    def test_塑膠保桿走保桿修補(self):
        assert classify_repair("刮痕", panel="FB")["repair_action"] == "保桿修補烤漆"
