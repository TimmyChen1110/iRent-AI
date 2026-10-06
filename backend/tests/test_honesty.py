"""資料誠實性回歸測試——零 API 成本。

原則：每一個顯示給使用者的 AI 結果、信心值、統計數字，都必須有真實模型輸出
或真實資料庫內容支持。未評測案件不得偽裝成已評測，缺失的信心不得用假值回填。
這批測試鎖住 2026-09-05 清理的問題，防止假資料回歸：
  - chain_cases.json 曾有 2,702 筆未評測案件被硬填假 assessment 標成 P3
  - server.py 曾對 CHAIN 案件硬編 ai_conf=0.88 污染 decision_events
  - 前端曾以 `|| 0.85` 回填缺失信心
"""
import json
from pathlib import Path

import pytest

PIPE = Path(__file__).resolve().parents[1] / "pipeline"
APP = Path(__file__).resolve().parents[1] / "app"

CHAIN = json.loads((PIPE / "chain_cases.json").read_text())
CASES = CHAIN["cases"]
SERVER_SRC = (APP / "server.py").read_text()


# ---------- chain_cases.json 資料誠實性 ----------

class TestChainData:
    def test_每筆案件都有評測狀態(self):
        assert all(c.get("evaluation_status") in ("evaluated", "pending", "failed")
                   for c in CASES)

    def test_未評測案件無假assessment(self):
        for c in CASES:
            if c["evaluation_status"] != "evaluated":
                assert c["assessment"] is None, f'{c["id"]} 未評測卻帶 assessment'

    def test_未評測案件無假confidence(self):
        for c in CASES:
            if c["evaluation_status"] != "evaluated":
                assert "confidence" not in json.dumps(c.get("assessment") or {})

    def test_未評測案件不得標P級(self):
        for c in CASES:
            if c["evaluation_status"] != "evaluated":
                assert c["level"] is None, f'{c["id"]} 未評測卻標 {c["level"]}'

    def test_evaluated案件保留真實assessment(self):
        ev = [c for c in CASES if c["evaluation_status"] == "evaluated"]
        assert ev, "至少要有已評測案件"
        for c in ev:
            assert c["assessment"] is not None and c["level"] in ("P1", "P2", "P3", "P4")

    def test_evaluated的信心值非單一假值(self):
        # 真模型輸出的 no_damage_confidence 應有變異；全部相同=灌水指紋
        confs = {c["assessment"].get("no_damage_confidence")
                 for c in CASES
                 if c["evaluation_status"] == "evaluated" and c.get("level") == "P3"}
        assert len(confs) > 1, f"P3 信心全為 {confs}，疑似填充值"

    def test_summary只統計evaluated(self):
        s = CHAIN["summary"]
        assert s["total"] == len(CASES)
        assert s["by_status"]["evaluated"] == sum(
            1 for c in CASES if c["evaluation_status"] == "evaluated")
        assert sum(s["evaluated_by_level"].values()) == s["by_status"]["evaluated"]

    def test_舊灌水指紋不存在(self):
        raw = (PIPE / "chain_cases.json").read_text()
        assert "比對中 / 待分析" not in raw


# ---------- 生成器邏輯（chain_summary 純函式） ----------

class TestChainSummary:
    def test_failed不計入AI分布(self):
        from build_chain_cases import chain_summary
        cases = [
            {"evaluation_status": "evaluated", "level": "P3"},
            {"evaluation_status": "failed", "level": None},
            {"evaluation_status": "pending", "level": None},
        ]
        s = chain_summary(cases)
        assert s["by_status"] == {"evaluated": 1, "pending": 1, "failed": 1}
        assert s["evaluated_by_level"] == {"P3": 1}   # failed/pending 不算正常


# ---------- server：snapshot 不得偽造信心 ----------

class TestChainSnapshot:
    def test_pending案件snapshot全空(self):
        import server
        pend = next(c["id"] for c in CASES if c["evaluation_status"] == "pending")
        snap = server._case_snapshot(pend)
        assert snap["mode"] == "chain"
        assert snap["ai_conf"] is None
        assert snap["ai_found"] is None
        assert snap["ai_level"] is None
        assert snap["assessment"] is None

    def test_evaluated案件conf來自模型或None(self):
        import server
        for c in CASES:
            if c["evaluation_status"] != "evaluated":
                continue
            snap = server._case_snapshot(c["id"])
            dmgs = (c["assessment"] or {}).get("damages") or []
            if dmgs:
                assert snap["ai_conf"] == max(d.get("confidence") or 0 for d in dmgs)
            else:
                assert snap["ai_conf"] is None   # 無損傷 → 無單一信心可言，不硬編

    def test_原始碼無硬編088(self):
        assert '"ai_conf": 0.88' not in SERVER_SRC


# ---------- 前端誠實性（原始碼指紋） ----------

# TestFrontend（舊 vanilla 3D 監理台 dashboard_shell.html 的文案檢查）已隨該 UI 於 2026-10-06 退役移除；
# 正式管理者介面為 fleet-ops-center，其文案由前端自身的 tsc/eslint/build 把關。
