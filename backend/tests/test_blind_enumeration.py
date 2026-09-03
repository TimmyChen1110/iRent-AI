"""blind_enumeration（v6 盲列舉差分）純函式回歸測試——零 API 成本。

差分骨幹錯了，Stage B 的 API 錢就白花：格位可比對性錯＝拿反光格當證據；
訊號邏輯錯＝證偽條件 B/C/D 的判定全部失真。
"""
import pytest

from blind_enumeration import (ALL_CELLS, cell_map, comparable_cells,
                               diff_signals, intersect_models, max_extent,
                               stage_a_stats)


def cell(name="A1", readable="clear", marks=None, uncertain=None):
    return {"cell": name, "readable": readable, "marks": marks or [],
            "uncertain_marks": uncertain or []}


def mark(extent=5.0, morphology="linear", count=1):
    return {"mark_id": "x", "morphology": morphology, "description": "d",
            "position_in_cell": "p", "max_extent_cm": extent,
            "count_within": count, "spans_cells": []}


def panel(cells):
    return {"panel": "RB", "cells": cells}


# ---------- cell_map / comparable_cells ----------

class TestCellMap:
    def test_缺格補為不可判讀而非可比對(self):
        m = cell_map(panel([cell("A1")]))
        assert set(m) == set(ALL_CELLS)
        assert m["B2"]["readable"] == "out_of_frame"

    def test_只有兩邊皆clear的格位可比對(self):
        p = panel([cell("A1"), cell("A2", "reflection_obscured"), cell("A3")])
        r = panel([cell("A1"), cell("A2"), cell("A3", "too_dark")])
        assert comparable_cells(p, r) == {"A1"}


# ---------- max_extent ----------

class TestMaxExtent:
    def test_無痕跡為零(self):
        assert max_extent(cell()) == 0.0

    def test_取最大值(self):
        assert max_extent(cell(marks=[mark(3), mark(8)])) == 8

    def test_有痕跡但全無數值_回None不可量測(self):
        # null extent（無比例尺）不能當 0，否則會偽造「延伸增加」訊號
        assert max_extent(cell(marks=[mark(None)])) is None


# ---------- diff_signals ----------

class TestDiffSignals:
    def test_佔用新增訊號(self):
        p = panel([cell("A1")])
        r = panel([cell("A1", marks=[mark()])])
        s = diff_signals(p, r, extent_threshold=3, count_threshold=2)
        assert s["occupancy"] == {"A1"} and s["any"] == {"A1"}

    def test_幻覺兩邊都出現_差分為零(self):
        # v6 核心假設：一致性幻覺自我抵消
        p = panel([cell("A1", marks=[mark(5)])])
        r = panel([cell("A1", marks=[mark(5)])])
        assert diff_signals(p, r, 3, 2)["any"] == set()

    def test_延伸增加超過門檻(self):
        p = panel([cell("A1", marks=[mark(5)])])
        r = panel([cell("A1", marks=[mark(12)])])
        s = diff_signals(p, r, extent_threshold=3, count_threshold=99)
        assert s["extent"] == {"A1"}
        # 未超過門檻不觸發
        r2 = panel([cell("A1", marks=[mark(7)])])
        assert diff_signals(p, r2, 3, 99)["any"] == set()

    def test_延伸無法量測時不產生延伸訊號(self):
        p = panel([cell("A1", marks=[mark(5)])])
        r = panel([cell("A1", marks=[mark(None)])])
        assert diff_signals(p, r, 3, 99)["extent"] == set()

    def test_數量增加達門檻(self):
        p = panel([cell("A1", marks=[mark()])])
        r = panel([cell("A1", marks=[mark(), mark(), mark()])])
        assert diff_signals(p, r, 999, 2)["count"] == {"A1"}

    def test_不可判讀格位不參與任何訊號(self):
        p = panel([cell("A1", "reflection_obscured")])
        r = panel([cell("A1", marks=[mark()])])
        assert diff_signals(p, r, 3, 2)["any"] == set()

    def test_uncertain_marks不納入差分(self):
        p = panel([cell("A1")])
        r = panel([cell("A1", uncertain=[mark()])])
        assert diff_signals(p, r, 3, 2)["any"] == set()

    def test_門檻未標定時該類訊號停用(self):
        p = panel([cell("A1", marks=[mark(1)])])
        r = panel([cell("A1", marks=[mark(50), mark(50), mark(50)])])
        s = diff_signals(p, r, extent_threshold=None, count_threshold=None)
        assert s["extent"] == set() and s["count"] == set()


# ---------- intersect_models ----------

class TestIntersect:
    def test_取交集不取聯集(self):
        a = {"any": {"A1", "B2"}}
        b = {"any": {"B2", "C3"}}
        assert intersect_models(a, b) == {"B2"}


# ---------- stage_a_stats（證偽條件 A 與門檻推導） ----------

class TestStageA:
    def runs(self, occupied_pattern, extents=None):
        """單一 case、A1 格位依 pattern 佔用，其餘格位穩定為空。"""
        reps = []
        for i, occ in enumerate(occupied_pattern):
            cells = [cell(c) for c in ALL_CELLS if c != "A1"]
            e = (extents or [5.0] * len(occupied_pattern))[i]
            cells.append(cell("A1", marks=[mark(e)] if occ else []))
            reps.append(panel(cells))
        return {("CAR", "左後"): reps}

    def test_佔用穩定_不觸發條件A(self):
        s = stage_a_stats(self.runs([True] * 5))
        assert s["occupancy_inconsistent"] == 0
        assert s["condition_A_triggered"] is False

    def test_佔用抖動計為不一致(self):
        s = stage_a_stats(self.runs([True, False, True, True, False]))
        assert s["occupancy_inconsistent"] == 1
        assert s["count_varying_cells"] == 1

    def test_超過兩成不一致觸發條件A(self):
        # 9 格中 A1 不一致 = 1/9 ≈ 11% 不觸發；再加兩格不一致 → 3/9 = 33% 觸發
        runs = self.runs([True, False, True, True, False])
        for extra in ("B1", "B2"):
            for i, rep in enumerate(runs[("CAR", "左後")]):
                for c in rep["cells"]:
                    if c["cell"] == extra and i % 2 == 0:
                        c["marks"] = [mark()]
        s = stage_a_stats(runs)
        assert s["occupancy_inconsistent"] == 3
        assert s["condition_A_triggered"] is True

    def test_延伸標準差與門檻推導(self):
        s = stage_a_stats(self.runs([True] * 5, extents=[4, 5, 6, 5, 5]))
        assert s["extent_std_median"] is not None
        assert s["extent_threshold"] == pytest.approx(3 * s["extent_std_median"])

    def test_計數穩定時門檻為2(self):
        s = stage_a_stats(self.runs([True] * 5))
        assert s["count_threshold"] == 2

    def test_readable翻面另計不進佔用統計(self):
        runs = self.runs([True] * 5)
        runs[("CAR", "左後")][0]["cells"] = [
            c if c["cell"] != "B3" else cell("B3", "reflection_obscured")
            for c in runs[("CAR", "左後")][0]["cells"]]
        s = stage_a_stats(runs)
        assert s["readable_flip_cells"] == 1
        assert s["condition_A_triggered"] is False
