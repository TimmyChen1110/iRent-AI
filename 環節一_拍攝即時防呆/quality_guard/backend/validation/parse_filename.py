"""從 raw_data 照片檔名解析真值（車牌號、拍攝角度）。

觀察到的真實命名格式（不一致，需要容錯 regex）：
  RFH7873左後 借.jfif      車牌無 "-"、角度前無空格
  RFM-2791左前 還.jpg      車牌有 "-"、角度前無空格
  RDL-5171 左前 借.jpg     車牌有 "-"、角度前有空格
  RDL-9262右前 還2.jpg     借/還後面有補拍編號
  RCW-8160 車況回報.jfif   沒有角度資訊（車損照片）-> 回傳 None，不計入驗證

「車況回報」類檔案跟車牌拍攝任務無關（是近拍車損的照片，不含角度/借還語意），
一律排除。
"""

from dataclasses import dataclass
from pathlib import Path
import re

from app.view_taxonomy import RequiredView

_ANGLE_TO_VIEW = {
    "左前": RequiredView.LEFT_FRONT,
    "右前": RequiredView.RIGHT_FRONT,
    "左後": RequiredView.LEFT_REAR,
    "右後": RequiredView.RIGHT_REAR,
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
    view: RequiredView
    action: str  # "借" or "還"


def normalize_plate_text(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def parse_filename(path: Path) -> GroundTruth | None:
    match = _FILENAME_PATTERN.match(path.name)
    if not match:
        return None

    plate_text = normalize_plate_text(match.group("plate"))
    view = _ANGLE_TO_VIEW[match.group("angle")]
    action = match.group("action")

    return GroundTruth(path=path, plate_text=plate_text, view=view, action=action)


def iter_ground_truth(*directories: Path):
    for directory in directories:
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            gt = parse_filename(path)
            if gt is not None:
                yield gt
