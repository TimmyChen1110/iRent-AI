"""continuous_diff（v7 連續座標差分）純函式回歸測試——零 API 成本。

v7 的骨幹：距離匹配（匈牙利＋形態相容＋錨定加權半徑）、距離交集、
聚類估 sigma、空轉率。匹配錯＝把不同痕跡配成同一個（漏訊號）或
把同一痕跡拆成兩個（假訊號），兩個方向都直接傷證偽條件判定。
"""
import pytest

from continuous_diff import (COMPATIBLE, anchored, cluster_marks,
                             diff_continuous, dist, estimate_sigma,
                             intersect_continuous, mark_cell, match_marks,
                             null_rate_v7, pair_radius)


def mk(u=0.5, v=0.5, morph="linear", extent=5.0, anchor="位於門把下方",
       mid="m1"):
    return {"mark_id": mid, "morphology": morph, "description": "d",
            "position_uv": [u, v], "anchored_to": anchor,
            "max_extent_cm": extent, "count_within": 1}


def grid(clear=True, except_cells=()):
    cells = []
    for col in "ABC":
        for row in (1, 2, 3):
            name = f"{col}{row}"
            st = "clear" if clear and name not in except_cells else "reflection_obscured"
            cells.append({"cell": name, "status": st})
    return cells


def panel(marks=None, uncertain=None, grid_cells=None):
    return {"panel": "RB", "marks": marks or [], "uncertain_marks": uncertain or [],
            "readability_grid": grid_cells if grid_cells is not None else grid()}


# ---------- mark_cell / anchored / pair_radius ----------

class TestBasics:
    def test_座標對映格位(self):
        assert mark_cell(mk(0.1, 0.1)) == "A1"
        assert mark_cell(mk(0.5, 0.5)) == "B2"
        assert mark_cell(mk(0.9, 0.9)) == "C3"

    def test_邊界值夾限(self):
        assert mark_cell(mk(1.0, 1.0)) == "C3"
        assert mark_cell(mk(0.0, 0.0)) == "A1"

    def test_無明確參照物視為未錨定(self):
        assert not anchored(mk(anchor="無明確參照物，座標為目視估計"))
        assert not anchored(mk(anchor=""))
        assert anchored(mk(anchor="位於輪拱前緣"))

    def test_錨定加權半徑(self):
        a, b = mk(), mk()
        assert pair_radius(a, b, 0.1) == (0.1, False)
        c = mk(anchor="無明確參照物")
        assert pair_radius(a, c, 0.1) == (pytest.approx(0.15), False)
        r, low = pair_radius(c, mk(anchor="無明確參照物"), 0.1)
        assert r == pytest.approx(0.2) and low is True


# ---------- match_marks ----------

class TestMatch:
    def test_距離內同形態配對(self):
        res = match_marks([mk(0.30, 0.30)], [mk(0.32, 0.31)], base_radius=0.1)
        assert res["matched"] == [(0, 0)] and res["unmatched_return"] == []

    def test_距離外不配對_產生未匹配(self):
        res = match_marks([mk(0.1, 0.1)], [mk(0.8, 0.8)], base_radius=0.1)
        assert res["matched"] == [] and res["unmatched_return"] == [0]

    def test_形態不相容不配對(self):
        res = match_marks([mk(morph="linear")], [mk(morph="edge_gap")], base_radius=0.5)
        assert res["unmatched_return"] == [0]

    def test_跨形態相容組可配對(self):
        # RDH-3092 形態：借車照 contour、還車照 patch → 必須能配對
        res = match_marks([mk(morph="contour")], [mk(morph="patch")], base_radius=0.1)
        assert res["matched"] == [(0, 0)]
        assert ("contour", "patch") in COMPATIBLE

    def test_匈牙利取總距離最小配置(self):
        # p0 離 r1 近、p1 離 r0 近——貪婪會配錯，匈牙利要配對成交叉
        p = [mk(0.10, 0.5, mid="p0"), mk(0.20, 0.5, mid="p1")]
        r = [mk(0.21, 0.5, mid="r0"), mk(0.11, 0.5, mid="r1")]
        res = match_marks(p, r, base_radius=0.15)
        assert set(res["matched"]) == {(0, 1), (1, 0)}

    def test_空清單(self):
        assert match_marks([], [mk()], 0.1)["unmatched_return"] == [0]
        assert match_marks([mk()], [], 0.1)["unmatched_return"] == []


# ---------- diff_continuous ----------

class TestDiffContinuous:
    def test_同痕跡不同讀數在半徑內_無訊號(self):
        p = panel([mk(0.40, 0.60)])
        r = panel([mk(0.44, 0.62)])
        assert diff_continuous(p, r, 0.1, 4.62)["signals"] == []

    def test_還車照新痕跡_佔用訊號(self):
        s = diff_continuous(panel([]), panel([mk()]), 0.1, 4.62)["signals"]
        assert len(s) == 1 and s[0]["type"] == "unmatched_mark"

    def test_延伸增加超過門檻(self):
        p = panel([mk(extent=5)])
        r = panel([mk(0.51, 0.5, extent=15)])
        s = diff_continuous(p, r, 0.1, 4.62)["signals"]
        assert len(s) == 1 and s[0]["type"] == "extent_increase"
        assert s[0]["extent_delta"] == pytest.approx(10)

    def test_非clear格位的痕跡不參與(self):
        # 痕跡落在 B2，B2 反光 → 排除
        p = panel([], grid_cells=grid(except_cells=("B2",)))
        r = panel([mk(0.5, 0.5)], grid_cells=grid())
        assert diff_continuous(p, r, 0.1, 4.62)["signals"] == []

    def test_uncertain不參與(self):
        r = panel(uncertain=[mk()])
        assert diff_continuous(panel(), r, 0.1, 4.62)["signals"] == []

    def test_未錨定新痕跡標低空間信心(self):
        r = panel([mk(anchor="無明確參照物，座標為目視估計")])
        s = diff_continuous(panel(), r, 0.1, 4.62)["signals"]
        assert s[0]["low_spatial_confidence"] is True


# ---------- intersect_continuous（RCG2235 修復點） ----------

class TestIntersect:
    def sig(self, u, v):
        return {"type": "unmatched_mark", "position_uv": [u, v], "morphology": "linear",
                "extent_cm": 5, "description": "", "low_spatial_confidence": False}

    def test_距離內算同一訊號(self):
        # v6 的死法：同一道痕 flash 讀 (0.55,0.45)、pro 讀 (0.48,0.52) 分屬 B2/A2
        out = intersect_continuous([self.sig(0.55, 0.45)], [self.sig(0.48, 0.52)], 0.12)
        assert len(out) == 1 and out[0]["model_agreement"] == "both"

    def test_距離外不交集(self):
        assert intersect_continuous([self.sig(0.1, 0.1)], [self.sig(0.9, 0.9)], 0.12) == []

    def test_空訊號(self):
        assert intersect_continuous([], [self.sig(0.5, 0.5)], 0.12) == []


# ---------- cluster / sigma / 空轉 ----------

class TestSigma:
    def test_重跑聚類與sigma估計(self):
        runs = [[mk(0.40, 0.60)], [mk(0.42, 0.61)], [mk(0.41, 0.59)],
                [mk(0.43, 0.60)], [mk(0.40, 0.62)]]
        s = estimate_sigma({("X", "左後"): runs})
        assert s["n_clusters_used"] == 1
        assert s["sigma_u"] is not None and s["match_radius"] is not None
        assert s["match_radius"] == pytest.approx(
            3 * (s["sigma_u"] ** 2 + s["sigma_v"] ** 2) ** 0.5, abs=1e-3)

    def test_不同痕跡分開聚類(self):
        runs = [[mk(0.1, 0.1), mk(0.9, 0.9)], [mk(0.11, 0.1), mk(0.9, 0.88)]]
        cls = cluster_marks(runs)
        assert len(cls) == 2

    def test_成員不足的cluster不進sigma(self):
        s = estimate_sigma({("X", "左後"): [[mk()], [mk()]]})  # 每 cluster 只有 2 員
        assert s["n_clusters_used"] == 0 and s["match_radius"] is None

    def test_v7空轉率_穩定讀數為零(self):
        reps = [panel([mk(0.40, 0.60)]) for _ in range(3)]
        rows = [{"car": "X", "angle": "左後", "model": m, "rep": i, "parsed": p}
                for m in ("gemini-3.7-flash", "gemini-3.1-pro-preview")
                for i, p in enumerate(reps)]
        nr = null_rate_v7(rows, 0.1, 4.62)
        assert all(v["null_rate"] == 0.0 for v in nr.values())

    def test_v7空轉率_抖動出半徑產生空轉(self):
        reps = [panel([mk(0.1, 0.1)]), panel([mk(0.9, 0.9)])]
        rows = [{"car": "X", "angle": "左後", "model": "gemini-3.7-flash",
                 "rep": i, "parsed": p} for i, p in enumerate(reps)]
        nr = null_rate_v7(rows, 0.05, 4.62)
        assert nr["gemini-3.7-flash"]["null_rate"] == 1.0
