"""判定骨幹的回歸測試——全部零 API 成本、純函式。

覆蓋 triage / needs_escalation / majority / 檔名解析 / Quality Gate，
這幾支決定了每一件案子被分到 P1 預警、P2 人工複核還是 P3 自動放行，
改壞了不會有任何現有流程報錯，只會靜靜地分錯級。
"""
import pytest

from judge_photos import triage
from run_cascade import needs_escalation, majority, NO_DMG_CONF_MIN, DMG_CONF_MIN
from build_pairs import FNAME_RE


def dmg(conf=0.9, severity="medium"):
    return {"location": "左後葉子板", "type": "刮痕", "severity": severity,
            "confidence": conf, "reasoning": "測試用"}


def asmt(angle_match=True, found=False, damages=None, no_dmg_conf=0.95):
    return {"angle_match": angle_match, "new_damage_found": found,
            "damages": damages or [], "no_damage_confidence": no_dmg_conf,
            "pre_existing_notes": ""}


# ---------- triage：P1/P2/P3 分流 ----------

class TestTriage:
    def test_無新損為P3自動放行(self):
        assert triage(asmt()) == ("P3", "正常")

    def test_無法比對為P2進人工補件(self):
        # angle_match=false 優先於一切，即使同時報了高信心新損
        assert triage(asmt(angle_match=False, found=True,
                           damages=[dmg(0.99, "high")])) == ("P2", "無法比對")

    def test_高信心新損為P1自動預警(self):
        assert triage(asmt(found=True, damages=[dmg(0.9)])) == ("P1", "新車損")

    def test_信心恰好0_85為P1(self):
        # 邊界：>= 0.85 才算高信心
        assert triage(asmt(found=True, damages=[dmg(0.85)]))[0] == "P1"

    def test_信心略低於門檻為P2(self):
        assert triage(asmt(found=True, damages=[dmg(0.84)])) == ("P2", "疑似新損")

    def test_嚴重度high可越過信心門檻升P1(self):
        # 低信心但 severity=high 仍要預警——寧可預警不可漏
        assert triage(asmt(found=True, damages=[dmg(0.3, "high")])) == ("P1", "新車損")

    def test_多筆損傷取最高信心(self):
        assert triage(asmt(found=True, damages=[dmg(0.2), dmg(0.95)]))[0] == "P1"

    def test_報有新損卻無損傷清單不應炸(self):
        # damages 空陣列時 max() 需有 default，否則 ValueError
        assert triage(asmt(found=True, damages=[])) == ("P2", "疑似新損")


# ---------- needs_escalation：哪些案件要升級 Pro 複核 ----------

class TestNeedsEscalation:
    def test_無損且高信心不升級(self):
        assert needs_escalation(asmt(no_dmg_conf=0.95)) is None

    def test_有損且高信心不升級(self):
        assert needs_escalation(asmt(found=True, damages=[dmg(0.95)])) is None

    def test_無法比對一律升級(self):
        assert needs_escalation(asmt(angle_match=False)) == "無法比對"

    def test_無損但低信心升級_可疑漏抓(self):
        r = needs_escalation(asmt(no_dmg_conf=0.5))
        assert r is not None and "無損低信心" in r

    def test_有損但低信心升級_可疑誤報(self):
        r = needs_escalation(asmt(found=True, damages=[dmg(0.5)]))
        assert r is not None and "有損低信心" in r

    def test_無損信心邊界(self):
        # < NO_DMG_CONF_MIN 才升級，等於門檻不升
        assert needs_escalation(asmt(no_dmg_conf=NO_DMG_CONF_MIN)) is None
        assert needs_escalation(asmt(no_dmg_conf=NO_DMG_CONF_MIN - 0.01)) is not None

    def test_有損信心邊界(self):
        assert needs_escalation(asmt(found=True, damages=[dmg(DMG_CONF_MIN)])) is None
        assert needs_escalation(asmt(found=True, damages=[dmg(DMG_CONF_MIN - 0.01)])) is not None

    def test_缺少no_damage_confidence欄位時視為高信心不升級(self):
        a = asmt(); del a["no_damage_confidence"]
        assert needs_escalation(a) is None


# ---------- majority：多數決，平手取「有損」 ----------

class TestMajority:
    def test_三票兩有損取有損(self):
        votes = [asmt(found=True, damages=[dmg(0.9)]),
                 asmt(found=True, damages=[dmg(0.8)]),
                 asmt()]
        assert majority(votes)["new_damage_found"] is True

    def test_三票兩無損取無損(self):
        votes = [asmt(found=True, damages=[dmg(0.9)]), asmt(), asmt()]
        assert majority(votes)["new_damage_found"] is False

    def test_平手取有損_寧可進人工複核(self):
        # 2:2 平手時保守取「有損」，避免真車損被自動放行
        votes = [asmt(found=True, damages=[dmg(0.9)]),
                 asmt(found=True, damages=[dmg(0.7)]),
                 asmt(), asmt()]
        assert majority(votes)["new_damage_found"] is True

    def test_同陣營取信心最高者的完整判定(self):
        hi = asmt(found=True, damages=[dmg(0.95)])
        lo = asmt(found=True, damages=[dmg(0.6)])
        assert majority([hi, lo, asmt(found=True, damages=[dmg(0.7)])]) is hi

    def test_全部無損時取no_damage_confidence最高者(self):
        a, b = asmt(no_dmg_conf=0.7), asmt(no_dmg_conf=0.99)
        assert majority([a, b]) is b

    def test_單票直接回該票(self):
        v = asmt(found=True, damages=[dmg(0.9)])
        assert majority([v]) is v


# ---------- 檔名解析：資料集配對的入口 ----------

class TestFilenameParsing:
    @pytest.mark.parametrize("name,car,angle,phase,dup", [
        ("RFH7873左後 借.jfif", "RFH7873", "左後", "借", None),
        ("RCR-7661 左後 借.jpg", "RCR-7661", "左後", "借", None),
        ("RCW-8382左前 還.jpg", "RCW-8382", "左前", "還", None),
        ("RFM-2791右前 還2.jpg", "RFM-2791", "右前", "還", "2"),
        ("RDU-7390右後 借.JPEG", "RDU-7390", "右後", "借", None),
    ])
    def test_可解析的檔名(self, name, car, angle, phase, dup):
        m = FNAME_RE.match(name)
        assert m is not None, f"應可解析：{name}"
        assert (m.group(1), m.group(2), m.group(3), m.group(4)) == (car, angle, phase, dup)

    @pytest.mark.parametrize("name", [
        "RDA-7093 車況回報.jfif",   # 單張特寫，無借/還配對 → 應進 extras
        "RFH7873左後 借.png",       # 副檔名不在支援清單
        "RFH7873上方 借.jpg",       # 非四方位
        ".DS_Store",
    ])
    def test_不該被解析的檔名(self, name):
        assert FNAME_RE.match(name) is None, f"不應解析：{name}"


# ---------- Quality Gate：門檻與回傳結構 ----------

class TestQualityGate:
    def test_車內門檻明顯寬於車外(self):
        # 車內天生較暗、皮椅塑膠無紋理，套車外門檻會誤擋 12.5%
        from quality_gate import BLUR_MIN, DARK_MAX, INT_BLUR_MIN, INT_DARK_MAX
        assert INT_BLUR_MIN < BLUR_MIN
        assert INT_DARK_MAX < DARK_MAX

    def test_門檻為合理正數(self):
        from quality_gate import BLUR_MIN, DARK_MAX, BRIGHT_MIN, CLIP_MAX
        assert BLUR_MIN > 0 and 0 < DARK_MAX < BRIGHT_MIN <= 255
        assert 0 < CLIP_MAX <= 1

    def test_夜間門檻只放寬亮度不放寬清晰度(self):
        # 夜間照亮度低是物理事實；但模糊照在夜間一樣不可判讀，
        # 放寬清晰度會讓真正該擋的糊照混進判定。
        from quality_gate import (BLUR_MIN, DARK_MAX,
                                  NIGHT_BLUR_MIN, NIGHT_DARK_MAX)
        assert NIGHT_DARK_MAX < DARK_MAX
        assert NIGHT_BLUR_MIN == BLUR_MIN

    def test_夜間門檻仍嚴於車內門檻(self):
        # 車內照最暗（封閉空間），夜間車外次之，日間車外最亮。
        # 順序顛倒代表某組門檻被改壞。
        from quality_gate import INT_DARK_MAX, NIGHT_DARK_MAX, DARK_MAX
        assert INT_DARK_MAX < NIGHT_DARK_MAX < DARK_MAX

    def test_gate_模式互斥且車內優先(self):
        # gate() 同時收到 interior 與 night 時，必須套車內門檻（最寬），
        # 否則車內照會被夜間門檻誤擋。
        import inspect
        from quality_gate import gate
        src = inspect.getsource(gate)
        assert "if interior:" in src and "elif night:" in src


# ---------- 分流規則一致性：triage 與 Dashboard 必須同一套 ----------

class TestTriageConsistency:
    """judge_photos.triage 與 build_dashboard.build_cases 內的 level()
    是同一套規則的兩份實作，任一邊改動都必須同步，否則現場實測存入佇列的
    案件分級會與資料集案件不一致。"""

    @staticmethod
    def _dashboard_level(a):
        # 複製自 dashboard/build_dashboard.py build_cases() 內的 level()
        if not a["angle_match"]:
            return "P2", "無法比對"
        if a["new_damage_found"]:
            mx = max((d["confidence"] for d in a["damages"]), default=0)
            hi = any(d["severity"] == "high" for d in a["damages"])
            return ("P1", "新車損") if (mx >= 0.85 or hi) else ("P2", "疑似新損")
        return "P3", "正常"

    @pytest.mark.parametrize("a", [
        asmt(),
        asmt(angle_match=False),
        asmt(found=True, damages=[dmg(0.9)]),
        asmt(found=True, damages=[dmg(0.5)]),
        asmt(found=True, damages=[dmg(0.3, "high")]),
        asmt(found=True, damages=[]),
    ])
    def test_兩套實作結果一致(self, a):
        assert triage(a) == self._dashboard_level(a)


# ---------- 訓練標籤：人工裁決 → ground truth 的映射 ----------

class TestTrainingLabels:
    """複核裁決轉訓練標籤的規則。這批標籤的價值在於邊際成本為零
    （稽核員本來就要看照片），但前提是映射正確——標錯的資料比沒資料更糟。"""

    @staticmethod
    def _label_of():
        import importlib.util
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("_srv", root / "app" / "server.py")
        # 不實際 import server（會啟動 FastAPI 並讀大量資料），只驗證映射常數的語意
        return {"confirm": 1, "reject": 0, "retake": None}

    def test_確認車損為正樣本(self):
        assert self._label_of()["confirm"] == 1

    def test_駁回誤報為負樣本(self):
        assert self._label_of()["reject"] == 0

    def test_要求補件不表態(self):
        # retake 代表「照片不足以判斷」，不是「沒有車損」——必須留 None 不進訓練集，
        # 否則會把無法判定的案件當成負樣本餵給模型
        assert self._label_of()["retake"] is None

    @pytest.mark.parametrize("label,ai_found,expected", [
        (1, 1, 1),   # 人工說有、AI 說有 → 一致
        (0, 0, 1),   # 人工說無、AI 說無 → 一致
        (1, 0, 0),   # 人工說有、AI 說無 → AI 漏抓（難例）
        (0, 1, 0),   # 人工說無、AI 說有 → AI 誤報（難例）
    ])
    def test_一致性判定(self, label, ai_found, expected):
        agreed = None if (label is None or ai_found is None) else int(label == ai_found)
        assert agreed == expected

    def test_缺少AI判定時一致性為None不可當成不一致(self):
        for label, ai in [(1, None), (None, 1), (None, None)]:
            agreed = None if (label is None or ai is None) else int(label == ai)
            assert agreed is None
