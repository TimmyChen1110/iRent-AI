"""reverse_check（既有損主張反向查核）的純函式回歸測試——零 API 成本。

這一層的骨幹是三支純函式：候選挑選、旗標映射、對照重標的統計。
挑錯候選＝該查的沒查（逃生出口漏網）；映射錯＝cannot_determine 被當成立。
"""
import json
from pathlib import Path

import pytest

from reverse_check import (REVIEW_VERDICTS, VERDICTS, needs_review,
                           select_candidates, summarize_reverse)


def result(car="RDH-3092", angle="左後", label="positive", found=False,
           notes="既有凹陷與板金變形", assessment=True):
    if not assessment:
        return {"car": car, "angle": angle, "label": label, "error": "boom"}
    return {"car": car, "angle": angle, "label": label,
            "assessment": {"angle_match": True, "new_damage_found": found,
                           "damages": [], "no_damage_confidence": 0.9,
                           "pre_existing_notes": notes}}


# ---------- select_candidates：逃生出口高風險集合的挑選 ----------

class TestSelectCandidates:
    def test_判無損且有既有損主張_入選(self):
        out = select_candidates([result()])
        assert len(out) == 1
        assert out[0]["car"] == "RDH-3092"
        assert out[0]["claim"] == "既有凹陷與板金變形"

    def test_判有新損_不選(self):
        # 判有新損者走索賠複核路，不是逃生出口
        assert select_candidates([result(found=True)]) == []

    def test_無主張文字_不選(self):
        assert select_candidates([result(notes="")]) == []
        assert select_candidates([result(notes="   ")]) == []

    def test_判定失敗的案件_跳過(self):
        assert select_candidates([result(assessment=False)]) == []

    def test_真實結果檔上_挑出30筆含RDH3092(self):
        # 鎖住對現行 FINAL_RESULTS 的實際行為：30 筆候選、目標案例在內
        p = Path(__file__).resolve().parents[1] / "pipeline" / \
            "eval_results_gemini_37_flash_v3_cascaded.json"
        cands = select_candidates(json.loads(p.read_text())["results"])
        assert len(cands) == 30
        assert ("RDH-3092", "左後") in {(c["car"], c["angle"]) for c in cands}


# ---------- needs_review：verdict → 旗標 ----------

class TestNeedsReview:
    def test_visible_主張成立不送審(self):
        assert not needs_review("visible")

    def test_not_visible_送審(self):
        assert needs_review("not_visible")

    def test_cannot_determine_送審(self):
        # 借車照拍不到該處＝主張本來就沒有影像根據（RDH-3092 的形狀）
        assert needs_review("cannot_determine")

    def test_映射窮盡所有verdict(self):
        assert REVIEW_VERDICTS < set(VERDICTS)
        assert set(VERDICTS) - REVIEW_VERDICTS == {"visible"}


# ---------- summarize_reverse：對照人工重標 ----------

class TestSummarize:
    RELABELS = {("A", "左後"): "clean", ("B", "右後"): "damage",
                ("C", "右後"): "uncertain", ("D", "左前"): "clean"}

    def rows(self):
        return [
            {"car": "A", "angle": "左後", "verdict": "visible"},
            {"car": "B", "angle": "右後", "verdict": "cannot_determine"},
            {"car": "C", "angle": "右後", "verdict": "not_visible"},
            {"car": "D", "angle": "左前", "verdict": "not_visible"},
            {"car": "E", "angle": "右前", "error": "boom"},
        ]

    def test_攔截與成本分開計(self):
        s = summarize_reverse(self.rows(), self.RELABELS)
        assert s["checked"] == 4 and s["errors"] == 1
        assert s["flagged"] == 3
        assert s["caught_true_damage"] == ["B右後"]      # 攔到逃生出口
        assert s["caught_uncertain"] == ["C右後"]        # 本該人工看的
        assert s["false_flags_on_clean"] == ["D左前"]    # 白付成本
        assert s["clean_flag_rate"] == 0.5               # 2 clean 中 1 被標

    def test_全數成立時零旗標(self):
        rows = [{"car": "A", "angle": "左後", "verdict": "visible"}]
        s = summarize_reverse(rows, self.RELABELS)
        assert s["flagged"] == 0 and s["false_flags_on_clean"] == []

    def test_無clean樣本時rate為None不除零(self):
        rows = [{"car": "B", "angle": "右後", "verdict": "visible"}]
        assert summarize_reverse(rows, self.RELABELS)["clean_flag_rate"] is None
