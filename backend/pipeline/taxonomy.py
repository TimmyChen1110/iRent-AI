#!/usr/bin/env python3
"""共用詞彙表（Prompt 架構規格 §2）：分區代碼、損傷類型、信心校準、車內區域、髒汙元素。

這是 Stage 1~5 的共同語言。所有 prompt 的代碼表都由本模組產生文字，
避免同一份代碼表在多個 prompt 裡各抄一份而逐漸走鐘（曾發生過判定來源不一致的教訓，
見 results_config.py）。

設計取捨（與規格的差異，刻意為之）：
  - 規格列出 40+ 個分區代碼（含 ROOF/TRK/WS 等）。本資料集只有四方位（左前/左後/右前/右後）
    側向照，車頂、擋風玻璃、後車廂根本不會入鏡。PANELS 保留完整代碼表供未來擴充，
    但 panels_for_angle() 會依方位裁切成該視角「可能看得到」的子集餵給模型——
    給模型不可能出現的選項只會誘發幻覺。
  - part_tagger.py 已有一套 17 類中文部位 enum，且已標好 59 筆（約 60 次 API 呼叫的成果）。
    PART_TO_PANEL 提供對應，讓既有護照資料能無痛升級到分區代碼，不必重跑。

用法：
    from taxonomy import PANELS, panels_table, CONFIDENCE_CALIBRATION, panels_for_angle
"""

# ---------- §2.1 車體外觀分區代碼 ----------
# (代碼, 中文, 材質)
PANELS: list[tuple[str, str, str]] = [
    ("FB", "前保桿", "塑膠"),
    ("RB", "後保桿", "塑膠"),
    ("HOOD", "引擎蓋", "鈑金"),
    ("TG", "尾門／行李廂蓋", "鈑金"),
    ("GRILLE", "水箱罩", "塑膠"),
    ("ROOF", "車頂", "鈑金"),
    ("HL_L", "左頭燈", "燈殼"),
    ("HL_R", "右頭燈", "燈殼"),
    ("TL_L", "左尾燈", "燈殼"),
    ("TL_R", "右尾燈", "燈殼"),
    ("FF_L", "左前葉子板", "鈑金"),
    ("FF_R", "右前葉子板", "鈑金"),
    ("RF_L", "左後葉子板", "鈑金"),
    ("RF_R", "右後葉子板", "鈑金"),
    ("FD_L", "左前門", "鈑金"),
    ("FD_R", "右前門", "鈑金"),
    ("RD_L", "左後門", "鈑金"),
    ("RD_R", "右後門", "鈑金"),
    ("SS_L", "左側裙", "塑膠"),
    ("SS_R", "右側裙", "塑膠"),
    ("MIR_L", "左後視鏡", "塑膠"),
    ("MIR_R", "右後視鏡", "塑膠"),
    ("WS", "前擋風玻璃", "玻璃"),
    ("RW", "後擋風玻璃", "玻璃"),
    ("WG_FL", "左前車窗", "玻璃"),
    ("WG_FR", "右前車窗", "玻璃"),
    ("WG_RL", "左後車窗", "玻璃"),
    ("WG_RR", "右後車窗", "玻璃"),
    ("WHL_FL", "左前輪圈", "鋁圈"),
    ("WHL_FR", "右前輪圈", "鋁圈"),
    ("WHL_RL", "左後輪圈", "鋁圈"),
    ("WHL_RR", "右後輪圈", "鋁圈"),
    ("TIRE_FL", "左前輪胎", "橡膠"),
    ("TIRE_FR", "右前輪胎", "橡膠"),
    ("TIRE_RL", "左後輪胎", "橡膠"),
    ("TIRE_RR", "右後輪胎", "橡膠"),
    ("LP_F", "前車牌", "金屬"),
    ("LP_R", "後車牌", "金屬"),
]

PANEL_CODES = [c for c, _, _ in PANELS]
PANEL_ZH = {c: zh for c, zh, _ in PANELS}
PANEL_MATERIAL = {c: m for c, _, m in PANELS}

# 四方位各自「可能入鏡」的分區。資料集為手持側向斜角照，
# 例如「左前」照通常涵蓋前保桿、左前葉子板、左前門、左頭燈、左前輪。
ANGLE_PANELS: dict[str, list[str]] = {
    "左前": ["FB", "GRILLE", "HOOD", "HL_L", "FF_L", "FD_L", "SS_L", "MIR_L",
             "WG_FL", "WHL_FL", "TIRE_FL", "WS", "LP_F"],
    "右前": ["FB", "GRILLE", "HOOD", "HL_R", "FF_R", "FD_R", "SS_R", "MIR_R",
             "WG_FR", "WHL_FR", "TIRE_FR", "WS", "LP_F"],
    "左後": ["RB", "TG", "TL_L", "RF_L", "RD_L", "SS_L", "WG_RL",
             "WHL_RL", "TIRE_RL", "RW", "LP_R", "ROOF"],
    "右後": ["RB", "TG", "TL_R", "RF_R", "RD_R", "SS_R", "WG_RR",
             "WHL_RR", "TIRE_RR", "RW", "LP_R", "ROOF"],
}


def panels_for_angle(angle: str | None) -> list[str]:
    """該方位可能入鏡的分區代碼。未知方位回傳全表（不裁切）。"""
    return ANGLE_PANELS.get(angle or "", PANEL_CODES)


def panels_table(codes: list[str] | None = None) -> str:
    """產生餵給 prompt 的分區代碼表文字。"""
    codes = codes or PANEL_CODES
    return "\n".join(f"  {c:9s} {PANEL_ZH[c]}（{PANEL_MATERIAL[c]}）" for c in codes)


# part_tagger.py 的 17 類中文 enum → 分區代碼。
# 左右不分的類別（車燈、後視鏡、輪圈/輪胎）對應到 None，需靠方位再細分。
PART_TO_PANEL: dict[str, str | None] = {
    "前保險桿": "FB", "後保險桿": "RB", "引擎蓋": "HOOD", "後車廂蓋": "TG", "車頂": "ROOF",
    "左前門": "FD_L", "左後門": "RD_L", "右前門": "FD_R", "右後門": "RD_R",
    "左前葉子板": "FF_L", "右前葉子板": "FF_R", "左後葉子板": "RF_L", "右後葉子板": "RF_R",
    "車燈": None, "後視鏡": None, "輪圈/輪胎": None, "其他": None,
}

# 左右不分的部位，依方位補上側別
_SIDE_SUFFIXED = {
    "車燈": {"左前": "HL_L", "右前": "HL_R", "左後": "TL_L", "右後": "TL_R"},
    "後視鏡": {"左前": "MIR_L", "右前": "MIR_R", "左後": "MIR_L", "右後": "MIR_R"},
    "輪圈/輪胎": {"左前": "WHL_FL", "右前": "WHL_FR", "左後": "WHL_RL", "右後": "WHL_RR"},
}


def part_to_panel(part: str | None, angle: str | None = None) -> str | None:
    """把 part_tagger 的中文部位轉成分區代碼；需要側別時用 angle 補。"""
    if not part:
        return None
    if part in _SIDE_SUFFIXED:
        return _SIDE_SUFFIXED[part].get(angle or "")
    return PART_TO_PANEL.get(part)


# ---------- §2.3 損傷類型代碼 ----------
DAMAGE_TYPES: list[tuple[str, str, str]] = [
    ("scratch", "刮痕", "線狀，漆面表層，可能露出底漆或素材色"),
    ("scuff", "擦撞磨損", "面狀，多見於保桿角落，通常伴隨異色轉印"),
    ("dent", "凹陷", "鈑面變形，靠反射線扭曲判斷，漆面可能完好"),
    ("chip", "掉漆／石擊", "點狀，直徑通常小於 10mm"),
    ("crack", "裂痕", "塑膠件斷裂或延伸性裂縫"),
    ("missing_part", "缺件", "飾條、蓋板、字標缺失"),
    ("deformation", "變形", "大範圍結構性變形"),
    ("glass_crack", "玻璃裂", "玻璃延伸性裂紋"),
    ("glass_chip", "玻璃缺口", "玻璃點狀受擊點"),
    ("rim_curb", "輪圈路緣刮", "輪圈外緣環狀磨損"),
    ("tire_damage", "輪胎損傷", "鼓包、割傷、胎壁破損"),
]

DAMAGE_CODES = [c for c, _, _ in DAMAGE_TYPES]
DAMAGE_ZH = {c: zh for c, zh, _ in DAMAGE_TYPES}

# 舊 schema 的中文損傷類型 → 代碼（既有 141 組結果升級用）
LEGACY_TYPE_TO_CODE = {
    "刮痕": "scratch", "凹陷": "dent", "破損": "crack", "掉漆": "chip", "其他": "scratch",
}

# §3 相容組：合併與差集比對時視為同類
COMPATIBLE_GROUPS: list[set[str]] = [
    {"scratch", "scuff"},
    {"dent", "deformation"},
    {"chip", "scratch"},
    {"glass_crack", "glass_chip"},
]


def types_compatible(a: str, b: str) -> bool:
    """兩個損傷類型是否視為同一處損傷的合理變體。"""
    if a == b:
        return True
    return any(a in g and b in g for g in COMPATIBLE_GROUPS)


def damage_table() -> str:
    return "\n".join(f"  {c:14s} {zh}——{note}" for c, zh, note in DAMAGE_TYPES)


# ---------- §2.4 信心值校準定義 ----------
# 逐字寫進每個 prompt。沒有這段，跨圖片的 confidence 不可比，門檻就沒有意義。
CONFIDENCE_CALIBRATION = """0.90 – 1.00  損傷邊界清晰，且在兩張以上不同視角的照片中位置一致
0.75 – 0.89  單一視角中清晰可見，形態明確，不易與汙漬或反光混淆
0.60 – 0.74  可見但形態不完全明確，或存在被誤認為汙漬／反光的可能
0.40 – 0.59  疑似，需要人工確認
0.00 – 0.39  證據不足，不應輸出為損傷項目"""


# ---------- §2.2 分區內正規化座標 ----------
UV_EXPLANATION = """每個分區內以 (u, v) 表示位置：
  u = 水平方向，0.0 為車頭側、1.0 為車尾側
  v = 垂直方向，0.0 為上緣、1.0 為下緣
這組座標與拍攝視角無關——不論從哪個角度拍，同一處損傷的 (u,v) 應該一致。
不需要精準到小數點後三位，只要能穩定落在同一個 0.1 網格內即可。"""

# 比對容許半徑（§2.2）
UV_MATCH_RADIUS = 0.12


def uv_distance(a, b) -> float:
    """兩個 (u,v) 的歐氏距離。任一為 None 時回傳 inf（不匹配）。"""
    if not a or not b or len(a) != 2 or len(b) != 2:
        return float("inf")
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


# ---------- §2.5 車內區域代碼 ----------
INTERIOR_ZONES: list[tuple[str, str]] = [
    ("DASH", "儀表台"), ("FLR_F", "前排地墊"),
    ("DRV", "駕駛座椅"), ("FLR_R", "後排地墊"),
    ("PSG", "副駕座椅"), ("TRK", "後車廂"),
    ("RS_L", "後座椅左"), ("RS_C", "後座椅中"), ("RS_R", "後座椅右"),
    ("DOOR_F", "前門內飾板"), ("DOOR_R", "後門內飾板"),
    ("CUP", "杯架"), ("CEIL", "車頂內襯"),
]
ZONE_CODES = [c for c, _ in INTERIOR_ZONES]
ZONE_ZH = {c: zh for c, zh in INTERIOR_ZONES}


def zones_table() -> str:
    return "\n".join(f"  {c:8s} {zh}" for c, zh in INTERIOR_ZONES)


# ---------- §2.6 髒汙元素代碼 ----------
COUNTABLE_ITEMS: list[tuple[str, str]] = [
    ("beverage_cup", "飲料杯"), ("bottle", "瓶罐"), ("food_wrapper", "食物包裝"),
    ("food_residue", "食物殘渣"), ("paper_trash", "紙屑"), ("cigarette_butt", "菸蒂"),
    ("tissue", "面紙"), ("bag", "袋子"), ("personal_item", "個人物品（遺留物）"),
]
AREA_ITEMS: list[tuple[str, str]] = [
    ("liquid_stain", "液體漬"), ("mud_sand", "泥沙"), ("hair_fur", "毛髮或寵物毛"),
    ("crumbs", "碎屑"), ("oil_grease", "油汙"), ("sticky_residue", "黏性殘留"),
    ("ash", "菸灰"), ("vomit", "嘔吐物"),
]
COUNTABLE_CODES = [c for c, _ in COUNTABLE_ITEMS]
AREA_CODES = [c for c, _ in AREA_ITEMS]
SOIL_ZH = {c: zh for c, zh in COUNTABLE_ITEMS + AREA_ITEMS}

COVERAGE_LEVELS = ["none", "spot", "patch", "extensive"]
COVERAGE_DEFINITION = """none      未見
spot      點狀或零星，佔該區域面積 5% 以下
patch     片狀，佔該區域面積 5–25%
extensive 大面積，佔該區域面積 25% 以上"""

# §5 高成本項目：無論面積大小都強制深度清潔（清潔成本遠高於視覺佔比）
DEEP_CLEAN_ITEMS = ["liquid_stain", "vomit", "hair_fur", "cigarette_butt", "ash", "sticky_residue"]


def soil_table() -> str:
    return ("可數物件（count）：\n"
            + "\n".join(f"  {c:16s} {zh}" for c, zh in COUNTABLE_ITEMS)
            + "\n面積性汙染（coverage）：\n"
            + "\n".join(f"  {c:16s} {zh}" for c, zh in AREA_ITEMS))


# ---------- §1 環境條件旗標 ----------
ENVIRONMENT_FLAGS: list[tuple[str, str]] = [
    ("surface_wet", "車身有水珠、水痕或明顯潮濕"),
    ("low_light", "夜間或地下停車場光源不足"),
    ("strong_reflection", "車身反射周圍環境造成大面積亮斑"),
    ("heavy_soil", "車身覆蓋泥沙或灰塵，可能遮蔽既有損傷"),
    ("obstruction", "有其他車輛、柱子、人員遮擋"),
]
ENV_FLAG_CODES = [c for c, _ in ENVIRONMENT_FLAGS]
ENV_FLAG_ZH = {c: zh for c, zh in ENVIRONMENT_FLAGS}

# 會使線狀痕跡可信度下降的環境（§ Stage 2：信心值降低一級）
CONFIDENCE_PENALTY_FLAGS = {"surface_wet", "strong_reflection"}


def env_flags_table() -> str:
    return "\n".join(f"  {c:20s} {zh}" for c, zh in ENVIRONMENT_FLAGS)


if __name__ == "__main__":
    print(f"分區 {len(PANELS)} 個／損傷類型 {len(DAMAGE_TYPES)} 種／"
          f"車內區域 {len(INTERIOR_ZONES)} 個／髒汙元素 "
          f"{len(COUNTABLE_ITEMS) + len(AREA_ITEMS)} 類")
    for a in ANGLE_PANELS:
        print(f"  {a}：{len(panels_for_angle(a))} 個可能入鏡分區")
