"""服務化層回歸測試——零 API 成本。

覆蓋：prompt 凍結（雙向）、v6 旗標紅線、冪等鍵、複核佇列、
§4 小樣本補充條款、提交驗證、訊號健康度基線。
判準與旗標寫錯＝shadow 結束時做出錯誤的接入決策，或紅線被靜默跨越。
"""
import hashlib
import json
from pathlib import Path

import pytest

PIPE = Path(__file__).resolve().parents[1] / "pipeline"


# ---------- Prompt 凍結（服務化規格 §6） ----------

class TestPromptFreeze:
    def test_檔案與程式內模板逐字一致(self):
        # 雙向凍結：改任一邊而沒改另一邊，這裡就會爆
        from blind_enumeration import P7_TEMPLATE
        from shadow_mode import P9_TEMPLATE
        assert (PIPE / "prompts/P7_blind_enumeration.v1.0.txt").read_text() == P7_TEMPLATE
        assert (PIPE / "prompts/P9_review_card.v1.0.txt").read_text() == P9_TEMPLATE

    def test_manifest_hash_通過(self):
        from prompt_manifest import verify_manifest
        assert verify_manifest() == []

    def test_竄改可被偵測(self, tmp_path, monkeypatch):
        import prompt_manifest
        d = tmp_path / "prompts"
        d.mkdir()
        (d / "P7_blind_enumeration.v1.0.txt").write_text("tampered")
        manifest = json.loads((PIPE / "prompts/MANIFEST.json").read_text())
        (d / "MANIFEST.json").write_text(json.dumps(manifest))
        monkeypatch.setattr(prompt_manifest, "PROMPTS_DIR", d)
        problems = prompt_manifest.verify_manifest()
        assert any("hash mismatch" in p for p in problems)
        assert any("missing" in p for p in problems)   # P9 檔不存在
        with pytest.raises(RuntimeError):
            prompt_manifest.assert_frozen()


# ---------- v6 旗標紅線（§1） ----------

class TestFeatureFlag:
    def test_預設off(self):
        import feature_flags
        assert feature_flags.V6_ENABLED is False

    def test_觸發限縮_只在無新損且帶主張時跑(self):
        from feature_flags import should_run_v6
        assert should_run_v6(True, True)["run"] is True
        assert should_run_v6(True, False)["run"] is False    # 無主張案：已驗證零訊號
        assert should_run_v6(False, True)["run"] is False    # 判有新損走索賠路

    def test_flag_off_時只寫入不派送(self):
        from feature_flags import should_run_v6
        g = should_run_v6(True, True, enabled=False)
        assert g["run"] is True and g["dispatch"] is False

    def test_flag_on_才派送(self):
        from feature_flags import should_run_v6
        assert should_run_v6(True, True, enabled=True)["dispatch"] is True


# ---------- 冪等鍵（§5） ----------

class TestIdempotency:
    def test_照片順序不影響鍵(self):
        from inspections_api import idempotency_key
        assert idempotency_key("R1", ["a", "b"]) == idempotency_key("R1", ["b", "a"])

    def test_不同租約或照片不同鍵(self):
        from inspections_api import idempotency_key
        assert idempotency_key("R1", ["a"]) != idempotency_key("R2", ["a"])
        assert idempotency_key("R1", ["a"]) != idempotency_key("R1", ["b"])


# ---------- 複核佇列（§3） ----------

def sig(sid, agreement="pro_only", dispatched=False, verdict=None):
    return {"signal_id": sid, "case_id": sid.rsplit("-", 1)[0], "panel": "RB",
            "signal_cells": [sid[-2:]], "signal_type": "unmatched_mark",
            "signal_types_all": ["unmatched_mark"], "model_agreement": agreement,
            "dispatched": dispatched, "review_flow": "standard",
            "review_verdict": verdict, "review_position_match": None,
            "review_duration_sec": None, "time_to_locate_sec": None,
            "review_free_text": None, "blind_pre_verdict": None,
            "blind_changed_after_card": None}


class TestQueue:
    def test_交集全收_pro抽樣補足(self):
        from shadow_mode import build_queue
        records = [sig(f"D{i}左後-A2", "both", True) for i in range(3)] + \
                  [sig(f"P{i}右後-B{1 + i % 3}") for i in range(30)]
        q = build_queue(records)
        assert len(q) == 13
        assert sum(1 for r in q if r["queue_source"] == "intersection") == 3
        assert sum(1 for r in q if r["queue_source"] == "union_sample") == 10

    def test_抽樣確定性(self):
        from shadow_mode import build_queue
        records = [sig(f"P{i}右後-B1") for i in range(30)]
        a = [r["signal_id"] for r in build_queue(records)]
        b = [r["signal_id"] for r in build_queue(list(reversed(records)))]
        assert a == b   # 與輸入順序無關

    def test_真實資料上為13筆(self):
        from shadow_mode import SIGNALS_PATH, build_queue
        records = [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]
        q = build_queue(records)
        assert sum(1 for r in q if r["queue_source"] == "intersection") == 3
        assert sum(1 for r in q if r["queue_source"] == "union_sample") == 10


# ---------- §4 小樣本補充條款 ----------

def reviewed(n, verdict="no_damage", dur=40, locate=10, pos="exact", conf_n=0):
    # confirmed 均勻穿插，避免夾具自己觸發「連續 10 筆 no_damage」停止條件
    conf_idx = {round((i + 0.5) * n / conf_n) for i in range(conf_n)} if conf_n else set()
    out = []
    for i in range(n):
        v = "confirmed_damage" if i in conf_idx else verdict
        r = sig(f"S{i}左後-A2", "both", True, v)
        r.update(review_duration_sec=dur, time_to_locate_sec=locate,
                 review_position_match=pos, review_free_text="實際情況")
        out.append(r)
    return out


class TestSupplement:
    def test_n小於15一律樣本不足(self):
        from shadow_mode import acceptance_with_supplement
        assert acceptance_with_supplement(reviewed(14, conf_n=14))["decision"] == "insufficient_sample"

    def test_n15到19_條件全滿足_低優先接入(self):
        from shadow_mode import acceptance_with_supplement
        out = acceptance_with_supplement(reviewed(16, dur=50, locate=10, conf_n=1))
        assert out["decision"] == "integrate_low_priority"
        assert out["clause"] == "small_sample_supplement"
        assert out["duration_median_excl_locate_sec"] == 40   # 扣定位

    def test_n15到19_零confirmed_不接入(self):
        from shadow_mode import acceptance_with_supplement
        assert acceptance_with_supplement(reviewed(16, conf_n=0))["decision"] == "do_not_integrate"

    def test_n15到19_扣定位後仍超過60秒_不接入(self):
        from shadow_mode import acceptance_with_supplement
        out = acceptance_with_supplement(reviewed(16, dur=90, locate=10, conf_n=1))
        assert out["decision"] == "do_not_integrate"

    def test_n達20走原判準(self):
        from shadow_mode import acceptance_with_supplement
        out = acceptance_with_supplement(reviewed(20, dur=50, locate=10, conf_n=6))
        assert out.get("duration_basis") == "excl_locate"
        assert out["decision"] == "integrate"

    def test_扣定位口徑(self):
        from shadow_mode import duration_excl_locate
        assert duration_excl_locate({"review_duration_sec": 48, "time_to_locate_sec": 22}) == 26
        assert duration_excl_locate({"review_duration_sec": 30, "time_to_locate_sec": None}) == 30
        assert duration_excl_locate({"review_duration_sec": None}) is None


# ---------- 提交驗證（後端強制，§3） ----------

class TestValidate:
    def body(self, **kw):
        from review_api import ReviewSubmit
        base = dict(review_verdict="no_damage", review_position_match="exact",
                    review_duration_sec=30.0, review_free_text="兩邊都乾淨")
        base.update(kw)
        return ReviewSubmit(**base)

    def test_合法提交(self):
        from review_api import validate_submission
        assert validate_submission(self.body(), "standard") == []

    def test_free_text必填(self):
        from review_api import validate_submission
        errs = validate_submission(self.body(review_free_text="  "), "standard")
        assert any("free_text" in e for e in errs)

    def test_enum防呆(self):
        from review_api import validate_submission
        assert validate_submission(self.body(review_verdict="yes"), "standard")
        assert validate_submission(self.body(review_position_match="nearby"), "standard")

    def test_blind第一階段只交pre_verdict(self):
        from review_api import ReviewSubmit, validate_submission
        b = ReviewSubmit(blind_pre_verdict="no_damage")
        assert validate_submission(b, "blind") == []
        assert validate_submission(b, "standard")   # 非 blind 不接受


# ---------- 訊號健康度（§7） ----------

class TestHealth:
    def test_第一期資料為綠(self):
        from shadow_mode import SIGNALS_PATH, signal_health
        records = [json.loads(l) for l in SIGNALS_PATH.read_text().splitlines()]
        out = signal_health(records, 119)
        assert out["alerts"] == []

    def test_訊號率倍增觸發告警(self):
        from shadow_mode import signal_health
        records = [sig(f"D{i}左後-A2", "both", True) for i in range(8)]
        out = signal_health(records, 119)
        assert "signal_rate_deviation" in out["alerts"]

    def test_交集過濾率跌破九成觸發(self):
        from shadow_mode import signal_health
        records = [sig("D1左後-A2", "both", True), sig("D2左後-B2", "both", True),
                   sig("P1右後-B1")]
        out = signal_health(records, 119)
        assert "intersection_filter_below_90pct" in out["alerts"]


# ---------- 判讀 API 純函式 ----------

class TestInspection:
    def test_觸發條件萃取(self):
        from inspections_api import extract_trigger
        v = {"final": {"new_damage_found": False, "pre_existing_notes": "後保桿舊損"}}
        no_new, has_claim, _ = extract_trigger(v)
        assert no_new and has_claim
        v2 = {"final": {"new_damage_found": False, "pre_existing_notes": ""}}
        assert extract_trigger(v2)[1] is False
        assert extract_trigger({})[0] is False   # 無判定（gate 擋下）→ 不觸發

    def test_versions每筆必回(self):
        from inspections_api import versions_block
        v = versions_block()
        assert v["prompt_p7"] == "P7-v1.0" and v["threshold"] == "th-v6-4.62-3"
        assert set(v["models"]) == {"flash", "pro"}
