"""Live 車內判定的 photo_ok 有效性契約（Issue 6 修復的回歸鎖）。

背景：LiveInterior 過去無輸入有效性欄位，任何非「髒汙」level 都被折疊成
P3「車內正常」——語意無效輸入（如車外照）會以完整成功樣貌輸出（silent
semantic failure）。修復後 photo_ok=false 具最高優先權，且 Flash 判 false
須經 Pro 確認一次、Pro 為準。

全部用 mock 的 structured result 測 backend mapping / cascade 契約，
不呼叫 Gemini、不把歷史模型輸出當 expected。
"""
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
import judge_photos as jp  # noqa: E402


class FakeParsed:
    def __init__(self, d):
        self._d = d

    def model_dump(self):
        return dict(self._d)


def iv(photo_ok=True, level="乾淨", conf=0.9, invalid_reason=""):
    """一筆合法的 LiveInterior structured result。"""
    return {"photo_ok": photo_ok, "invalid_reason": invalid_reason,
            "level": level, "confidence": conf, "findings": [], "reasoning": "測試"}


@pytest.fixture
def photo(tmp_path):
    p = tmp_path / "interior.jpg"
    Image.new("RGB", (32, 32), (120, 120, 120)).save(p)
    return str(p)


def run_interior(monkeypatch, photo, responses, gate_pass=True):
    """以 mock _call / _run_gate 執行 judge_interior，回傳 (result, annotated, 呼叫的模型序列)。"""
    calls = []

    def fake_call(client, model, contents, system, schema, throttle, retries=3, fallback=None):
        assert schema is jp.LiveInterior
        d = responses[len(calls)]
        calls.append(model)
        return model, FakeParsed(d)

    monkeypatch.setattr(jp, "_call", fake_call)
    monkeypatch.setattr(jp, "_run_gate",
                        lambda photos, interior=False: {"photo": {"pass": gate_pass, "reasons": []}})
    result, annotated = jp.judge_interior(photo, client=object())
    return result, annotated, calls


class TestValidFlow:
    def test_A_有效且乾淨_維持P3且不升級(self, monkeypatch, photo):
        result, _, calls = run_interior(monkeypatch, photo, [iv(True, "乾淨", 0.9)])
        assert result["level"] == "P3" and result["verdict"] == "clean"
        assert len(calls) == 1 and calls[0] == jp.SCREEN_MODEL

    def test_B_有效且髒汙_照舊升級Pro後P1(self, monkeypatch, photo):
        result, _, calls = run_interior(
            monkeypatch, photo, [iv(True, "髒汙", 0.9), iv(True, "髒汙", 0.95)])
        assert result["level"] == "P1" and result["verdict"] == "dirty"
        assert calls == [jp.SCREEN_MODEL, jp.REVIEW_MODEL]


class TestValidityCascade:
    def test_C_Flash判false_必升Pro恰一次(self, monkeypatch, photo):
        _, _, calls = run_interior(
            monkeypatch, photo, [iv(False, invalid_reason="疑似車外"), iv(True, "乾淨", 0.9)])
        assert calls == [jp.SCREEN_MODEL, jp.REVIEW_MODEL]

    def test_D_雙判false_P2retake且無標註(self, monkeypatch, photo):
        result, annotated, _ = run_interior(
            monkeypatch, photo, [iv(False), iv(False, invalid_reason="車外照")])
        assert result["verdict"] == "retake" and result["level"] == "P2"
        assert result["kind"] == "無法判讀車內照"
        assert result["retake_reason"] == "photo_invalid"
        assert annotated is None

    def test_E_Flash誤判false_Pro翻案後採Pro整潔結果(self, monkeypatch, photo):
        result, _, _ = run_interior(
            monkeypatch, photo, [iv(False), iv(True, "乾淨", 0.9)])
        assert result["level"] == "P3" and result["verdict"] == "clean"
        assert result["final"]["photo_ok"] is True

    def test_F_低信心升級後Pro判false_P2retake(self, monkeypatch, photo):
        result, _, calls = run_interior(
            monkeypatch, photo, [iv(True, "乾淨", 0.5), iv(False, invalid_reason="幾乎無車內區域")])
        assert calls == [jp.SCREEN_MODEL, jp.REVIEW_MODEL]
        assert result["verdict"] == "retake" and result["retake_reason"] == "photo_invalid"

    def test_G_核心回歸_false加怪異level絕不得變P3(self, monkeypatch, photo):
        # 修復前的 bug：任何非「髒汙」level 都折疊成 P3/clean
        result, _, _ = run_interior(
            monkeypatch, photo, [iv(False, level="外觀正常"), iv(False, level="???")])
        assert result["level"] != "P3" and result["verdict"] != "clean"
        assert result["verdict"] == "retake" and result["level"] == "P2"

    def test_I_Flash判false且Pro呼叫失敗_保守retake(self, monkeypatch, photo):
        calls = []

        def fake_call(client, model, contents, system, schema, throttle, retries=3, fallback=None):
            calls.append(model)
            if len(calls) == 1:
                return model, FakeParsed(iv(False, invalid_reason="疑似車外"))
            raise RuntimeError("Pro 掛了")

        monkeypatch.setattr(jp, "_call", fake_call)
        monkeypatch.setattr(jp, "_run_gate",
                            lambda photos, interior=False: {"photo": {"pass": True, "reasons": []}})
        result, annotated = jp.judge_interior(photo, client=object())
        assert result["verdict"] == "retake" and result["retake_reason"] == "photo_invalid"
        assert annotated is None


class TestGateMarker:
    def test_gate失敗仍走舊語意並帶gate標記(self, monkeypatch, photo):
        def no_call(*a, **k):
            raise AssertionError("gate 失敗不應呼叫模型")

        monkeypatch.setattr(jp, "_call", no_call)
        monkeypatch.setattr(jp, "_run_gate",
                            lambda photos, interior=False: {"photo": {"pass": False, "reasons": ["過暗"]}})
        result, annotated = jp.judge_interior(photo, client=object())
        assert result["verdict"] == "retake" and result["kind"] == "品質不合格"
        assert result["retake_reason"] == "gate"
        assert annotated is None
