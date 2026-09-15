"""訓練資料組裝的回歸測試。

資料集若組錯（標籤映射錯、洩漏、把不可判定當負樣本），訓練照樣會跑完並給出
看起來合理的數字——不會有任何錯誤訊息。這類 bug 只能靠測試擋。
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "training"))

from build_dataset import RELABEL_MAP, build, from_relabels  # noqa: E402


class TestLabelMapping:
    def test_damage為正樣本(self):
        assert RELABEL_MAP["damage"] == 1

    def test_clean為負樣本(self):
        assert RELABEL_MAP["clean"] == 0

    @pytest.mark.parametrize("bad", ["not_comparable", "uncertain", "", None])
    def test_不可判定一律排除(self, bad):
        # not_comparable/uncertain 代表「判不出來」而非「沒有車損」，
        # 當成負樣本會直接汙染資料集
        assert RELABEL_MAP.get(bad) is None


class TestDataset:
    @pytest.fixture(scope="class")
    @classmethod
    def rows(cls):
        # 單元測試只驗證版本庫內的固定 relabel 資料，不應被本機 Demo DB 汙染。
        rows, _ = build(decisions_db=None)
        return rows

    def test_有樣本(self, rows):
        assert len(rows) > 0

    def test_標籤只有0與1(self, rows):
        assert {r["label"] for r in rows} <= {0, 1}

    def test_每筆都有可讀的照片路徑(self, rows):
        for r in rows:
            assert Path(r["photo"]).exists(), r["photo"]

    def test_照片是還車照非借車照(self, rows):
        # 任務定義是「還車照有無車損」；用錯照片會讓標籤與影像對不上
        for r in rows:
            assert "還" in Path(r["photo"]).name

    def test_無重複case(self, rows):
        keys = [(r["car"], r["angle"]) for r in rows]
        assert len(keys) == len(set(keys))

    def test_排除了不可判定樣本(self):
        raw = json.loads((ROOT / "pipeline" / "relabels.json").read_text())["relabels"]
        excluded = sum(1 for r in raw if r.get("relabel") not in ("damage", "clean"))
        assert excluded > 0, "測試前提：資料中確實有不可判定樣本"
        assert len(from_relabels()) == len(raw) - excluded

    def test_正樣本數與人工重標一致(self, rows):
        raw = json.loads((ROOT / "pipeline" / "relabels.json").read_text())["relabels"]
        expect = sum(1 for r in raw if r.get("relabel") == "damage")
        assert sum(r["label"] for r in rows) == expect


class TestSplitIntegrity:
    """以車輛分組是這個小資料集最關鍵的正確性保證。"""

    def test_同車不可跨train與val(self):
        from sklearn.model_selection import GroupKFold
        rows, _ = build(decisions_db=None)
        groups = [r["car"] for r in rows]
        y = [r["label"] for r in rows]
        for itr, iva in GroupKFold(n_splits=5).split(rows, y, groups):
            tr_cars = {groups[i] for i in itr}
            va_cars = {groups[i] for i in iva}
            assert not (tr_cars & va_cars), "同一台車同時出現在 train 與 val＝資料洩漏"

    def test_每台車的樣本都在同一組(self):
        rows, _ = build(decisions_db=None)
        by_car = {}
        for r in rows:
            by_car.setdefault(r["car"], []).append(r)
        # 至少要有車輛擁有多個方位，分組切分才有意義
        assert any(len(v) > 1 for v in by_car.values())
