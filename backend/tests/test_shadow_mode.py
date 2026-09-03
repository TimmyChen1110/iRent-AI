"""shadow_mode（v6 Shadow Mode 協定）純函式回歸測試——零 API 成本。

判準與停止條件是預先註冊的規則：程式寫錯＝shadow 結束時做出錯誤的
接入決策。歸因、分流、雙穩態分類則決定資料能不能被正確解讀。
"""
import pytest

from shadow_mode import (acceptance_verdict, attribute_wrong_area,
                         bimodality_prevalence, check_stop, classify_stability,
                         enumeration_distance, intersect_vs_union, is_blind,
                         phase1_population, signal_records_for_case)


def cell(name="A1", readable="clear", marks=None):
    return {"cell": name, "readable": readable, "marks": marks or [],
            "uncertain_marks": []}


def mark(extent=5.0, morph="linear"):
    return {"mark_id": "x", "morphology": morph, "description": "d",
            "position_in_cell": "p", "max_extent_cm": extent, "count_within": 1}


def panel(occupied=(), extent=5.0):
    cells = [cell(c, marks=[mark(extent)] if c in occupied else []) for c in
             [f"{a}{b}" for a in "ABC" for b in (1, 2, 3)]]
    return {"panel": "RB", "cells": cells}


# ---------- Step 0′ ----------

class TestBimodality:
    def test_距離為佔用集合Jaccard(self):
        assert enumeration_distance(panel(("A1",)), panel(("A1",))) == 0.0
        assert enumeration_distance(panel(("A1",)), panel(("B2",))) == 1.0
        assert enumeration_distance(panel(("A1", "B2")), panel(("A1",))) == 0.5
        assert enumeration_distance(panel(), panel()) == 0.0

    def test_單穩態(self):
        assert classify_stability([0.0, 0.1, 0.05]) == "monostable"

    def test_雙穩態_低高兩群中間空白(self):
        # RCW1883 型：rep 1/2/5 一組、3/4 一組 → 組內 0、跨組高
        assert classify_stability([0.0, 0.0, 0.9, 0.9, 0.9, 0.0]) == "bimodal"

    def test_不穩定_中間有值(self):
        assert classify_stability([0.0, 0.3, 0.9]) == "unstable"

    def test_盛行率統計(self):
        rows = []
        for rep in range(1, 4):
            occ = ("A1",) if rep < 3 else ("C3",)   # 雙穩態
            rows.append({"car": "X", "angle": "左後", "model": "gemini-3.7-flash",
                         "rep": rep, "parsed": panel(occ)})
            rows.append({"car": "X", "angle": "左後", "model": "gemini-3.1-pro-preview",
                         "rep": rep, "parsed": panel(("A1",))})  # 單穩態
        out = bimodality_prevalence(rows)
        assert out["gemini-3.7-flash"]["bimodal"] == 1
        assert out["gemini-3.1-pro-preview"]["monostable"] == 1


# ---------- 第一期母體 ----------

class TestPopulation:
    def result(self, found=False, notes="", angle="左後"):
        return {"car": "X", "angle": angle,
                "assessment": {"new_damage_found": found, "angle_match": True,
                               "pre_existing_notes": notes}}

    def test_判無新損才入母體(self):
        pop = phase1_population([self.result(found=True), self.result()],
                                lambda d, a: None)
        assert len(pop) == 1

    def test_無主張退回方位主panel(self):
        pop = phase1_population([self.result(angle="左前"), self.result(angle="右後")],
                                lambda d, a: None)
        assert pop[0]["panel"] == "FB" and pop[1]["panel"] == "RB"

    def test_有主張走主張推導(self):
        pop = phase1_population([self.result(notes="左後葉子板刮痕")],
                                lambda d, a: "RF_L")
        assert pop[0]["panel"] == "RF_L"


# ---------- 訊號記錄 ----------

class TestSignalRecords:
    CASE = {"car": "X", "angle": "左後", "panel": "RB", "claim": ""}

    def pm(self, flash_return=("A2",), pro_return=("A2",)):
        return {"gemini-3.7-flash": {"pickup": panel(), "return": panel(flash_return)},
                "gemini-3.1-pro-preview": {"pickup": panel(), "return": panel(pro_return)}}

    def test_交集訊號標派送(self):
        recs = signal_records_for_case(self.CASE, self.pm(), "clean")
        assert len(recs) == 1
        r = recs[0]
        assert r["model_agreement"] == "both" and r["dispatched"] is True
        assert r["signal_type"] == "unmatched_mark"
        assert r["signal_id"] == "X左後-A2"

    def test_聯集記錄但單模型不派送(self):
        recs = signal_records_for_case(self.CASE, self.pm(("A2",), ("C3",)), "clean")
        by = {r["signal_id"]: r for r in recs}
        assert by["X左後-A2"]["model_agreement"] == "flash_only"
        assert by["X左後-C3"]["model_agreement"] == "pro_only"
        assert not any(r["dispatched"] for r in recs)

    def test_無差異無記錄(self):
        pm = {"gemini-3.7-flash": {"pickup": panel(("A1",)), "return": panel(("A1",))},
              "gemini-3.1-pro-preview": {"pickup": panel(), "return": panel()}}
        assert signal_records_for_case(self.CASE, pm, "clean") == []

    def test_相鄰格有記錄時旗標為真(self):
        pm = self.pm()
        pm["gemini-3.7-flash"]["pickup"] = panel(("B2",))   # A2 的相鄰格
        r = signal_records_for_case(self.CASE, pm, "clean")[0]
        assert r["adjacent_cell_has_marks"] is True


# ---------- 分流與歸因 ----------

class TestFlowAndAttribution:
    def test_盲測分流可重現且比例接近兩成(self):
        ids = [f"CASE{i}左後-A{1 + i % 3}" for i in range(500)]
        share = sum(is_blind(s) for s in ids) / len(ids)
        assert 0.12 < share < 0.28
        assert all(is_blind(s) == is_blind(s) for s in ids[:20])

    def test_wrong_area三類歸因(self):
        assert attribute_wrong_area("該位置什麼都沒有，但隔壁格有一道痕") == "boundary_error"
        assert attribute_wrong_area("這裡沒有，但別的地方有明顯痕跡") == "bistable_flip"
        assert attribute_wrong_area("該位置有東西但借車照也有") == "match_failure"
        assert attribute_wrong_area("看不懂") == "unattributed"


# ---------- 停止條件與接入判準 ----------

def rec(verdict=None, pos="exact", dur=30, flow="standard", agreement="both",
        pre=None, changed=None, dispatched=True):
    return {"review_verdict": verdict, "review_position_match": pos,
            "review_duration_sec": dur, "review_flow": flow,
            "model_agreement": agreement, "dispatched": dispatched,
            "blind_pre_verdict": pre, "blind_changed_after_card": changed}


class TestStopConditions:
    def test_無資料不觸發(self):
        assert check_stop([]) == []

    def test_wrong_area超過三成(self):
        rs = [rec("no_damage", pos="wrong_area")] * 4 + [rec("confirmed_damage")] * 6
        assert "wrong_area_over_30pct" in check_stop(rs)

    def test_連續十筆no_damage(self):
        rs = [rec("confirmed_damage")] + [rec("no_damage")] * 10
        assert "ten_consecutive_no_damage" in check_stop(rs)

    def test_說明卡引導性過強(self):
        rs = [rec("confirmed_damage", flow="blind", pre="no_damage", changed=True)] * 5 + \
             [rec("no_damage", flow="blind", pre="no_damage", changed=False)] * 5
        assert "card_over_persuasive" in check_stop(rs)

    def test_單日量超過負擔(self):
        assert "daily_volume_exceeded" in check_stop([], daily_capacity=5,
                                                     daily_signal_count=9)


class TestAcceptance:
    def test_全滿足接入(self):
        rs = [rec("confirmed_damage", dur=40)] * 3 + [rec("no_damage", dur=40)] * 7
        assert acceptance_verdict(rs)["decision"] == "integrate"

    def test_確認率過低不接入(self):
        rs = [rec("confirmed_damage")] + [rec("no_damage")] * 19
        assert acceptance_verdict(rs)["decision"] == "do_not_integrate"

    def test_中間帶且快速複核降級接入(self):
        rs = [rec("confirmed_damage", dur=30)] * 3 + [rec("no_damage", dur=30)] * 17
        assert acceptance_verdict(rs)["decision"] == "integrate_low_priority"

    def test_耗時過長否決一切(self):
        rs = [rec("confirmed_damage", dur=300)] * 10
        assert acceptance_verdict(rs)["decision"] == "do_not_integrate"

    def test_未回填為資料不足(self):
        assert acceptance_verdict([rec()])["decision"] == "insufficient_data"

    def test_只算派送過的記錄(self):
        rs = [rec("confirmed_damage", agreement="flash_only", dispatched=False)] * 5
        assert acceptance_verdict(rs)["decision"] == "insufficient_data"


class TestIntersectVsUnion:
    def test_交集漏訊號達交集命中即建議分層(self):
        rs = [rec("confirmed_damage")] * 2 + \
             [rec("confirmed_damage", agreement="flash_only", dispatched=False)] * 2 + \
             [rec("no_damage", agreement="pro_only", dispatched=False)] * 3
        out = intersect_vs_union(rs)
        assert out["intersection"]["precision"] == 1.0
        assert out["missed_by_intersection"] == 2
        assert out["layering_recommended"] is True


# ---------- 互動複核的寫回 ----------

class TestApplyReview:
    from shadow_mode import apply_review

    def test_只更新目標記錄(self):
        from shadow_mode import apply_review
        rs = [{"signal_id": "A左後-A2", "review_verdict": None},
              {"signal_id": "B右前-C2", "review_verdict": None}]
        out = apply_review(rs, "A左後-A2", {"review_verdict": "confirmed_damage",
                                            "review_duration_sec": 42.0})
        assert out[0]["review_verdict"] == "confirmed_damage"
        assert out[0]["review_duration_sec"] == 42.0
        assert out[1]["review_verdict"] is None

    def test_不存在的id不動任何記錄(self):
        from shadow_mode import apply_review
        rs = [{"signal_id": "A左後-A2", "review_verdict": None}]
        assert apply_review(rs, "X", {"review_verdict": "no_damage"}) == rs
