"""從 raw_data 照片檔名解析真值（車牌號、拍攝角度）。

觀察到的真實命名格式（不一致，需要容錯 regex）：
  RFH7873左後 借.jfif      車牌無 "-"、角度前無空格
  RFM-2791左前 還.jpg      車牌有 "-"、角度前無空格
  RDL-5171 左前 借.jpg     車牌有 "-"、角度前有空格
  RDL-9262右前 還2.jpg     借/還後面有補拍編號
  RCW-8160 車況回報.jfif   沒有角度資訊（車損照片）-> 回傳 None，不計入驗證

「車況回報」類檔案跟車牌拍攝任務無關（是近拍車損的照片，不含角度/借還語意），
一律排除。

⚠️ 檔名的「車頭」左右標註是錯的，本模組會修正——見 _ANGLE_TO_VIEW 的說明。
"""

from dataclasses import dataclass
from pathlib import Path
import re

from app.view_taxonomy import RequiredView

# ⚠️ 檔名的「車頭」左右是反的，這裡修正回車體視角。
#
# 證據（幾何）：車頭正對鏡頭時，駕駛座（左駕、位於車子左側）會出現在畫面右邊；
# 攝影者要往自己左邊移動才會露出車子的**右**側，此時畫面上車頭在右、車身往左延伸。
# 實際檢視 RCX5100左前、RDG8578左前、RCQ6760左前（三台不同車輛）全部符合「車頭在
# 畫面右、車身往左」——都是車子的**右前角**，跟檔名相反。RCG2235右前 則相反，是左前角。
#
# 證據（交叉比對）：`scripts/check_dataset_label_convention.py` 把人工目視分類過的
# 訓練資料集對回這些原始檔案（相關係數 1.0 的完全比對），車頭兩類 96/98 張是交叉的、
# 車尾兩類 87/87 張一致。
#
# 推測成因：App 要使用者「去車子左前方拍」，使用者面對車頭站到自己的左邊就按快門，
# 檔名記的是 App 要求的欄位，不是畫面裡實際拍到的角度。車尾照沒這個問題，因為拍車尾
# 時攝影者跟車子同向，兩邊的左右一致——實測車尾標註也確實正確，所以只修正車頭兩類。
_ANGLE_TO_VIEW = {
    "左前": RequiredView.RIGHT_FRONT,  # 檔名寫左前，畫面實際是車子的右前角
    "右前": RequiredView.LEFT_FRONT,  # 檔名寫右前，畫面實際是車子的左前角
    "左後": RequiredView.LEFT_REAR,  # 車尾標註正確，原樣採用
    "右後": RequiredView.RIGHT_REAR,
}

# 檔名原文（未修正）→ 需要時可以回頭對照原始標註
_ANGLE_AS_WRITTEN_IN_FILENAME = {
    "左前": "左前", "右前": "右前", "左後": "左後", "右後": "右後",
}

_FILENAME_PATTERN = re.compile(
    r"^(?P<plate>[A-Z]{2,3}-?\d{3,4})\s*"
    r"(?P<angle>左前|右前|左後|右後)\s*"
    r"(?P<action>借|還)\d*"
    r"\.(?P<ext>jpe?g|jfif)$",
    re.IGNORECASE,
)


@dataclass
class GroundTruth:
    path: Path
    plate_text: str  # 正規化後（大寫、去掉 "-"）
    view: RequiredView  # 已修正成車體視角（車頭兩類跟檔名相反，見上方說明）
    view_as_named: str  # 檔名原本寫的角度，供對照/除錯
    action: str  # "借" or "還"


def normalize_plate_text(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def parse_filename(path: Path) -> GroundTruth | None:
    match = _FILENAME_PATTERN.match(path.name)
    if not match:
        return None

    plate_text = normalize_plate_text(match.group("plate"))
    angle = match.group("angle")
    view = _ANGLE_TO_VIEW[angle]
    action = match.group("action")

    return GroundTruth(
        path=path,
        plate_text=plate_text,
        view=view,
        view_as_named=_ANGLE_AS_WRITTEN_IN_FILENAME[angle],
        action=action,
    )


def iter_ground_truth(*directories: Path):
    for directory in directories:
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            gt = parse_filename(path)
            if gt is not None:
                yield gt
