"""檔名解析。

注意：車頭兩類的 `view` 跟檔名寫的相反，那是刻意的修正——raw_data 的檔名把車頭的
左右寫反了（幾何證據見 validation/parse_filename.py 的 _ANGLE_TO_VIEW）。
`view_as_named` 保留檔名原文。
"""

from pathlib import Path

from app.view_taxonomy import RequiredView
from validation.parse_filename import normalize_plate_text, parse_filename


def test_parses_no_dash_no_space():
    gt = parse_filename(Path("RFH7873左後 借.jfif"))
    assert gt is not None
    assert gt.plate_text == "RFH7873"
    assert gt.view == RequiredView.LEFT_REAR  # 車尾標註正確，不修正
    assert gt.view_as_named == "左後"
    assert gt.action == "借"


def test_parses_dash_no_space():
    gt = parse_filename(Path("RFM-2791左前 還.jpg"))
    assert gt is not None
    assert gt.plate_text == "RFM2791"
    assert gt.view == RequiredView.RIGHT_FRONT  # 檔名寫「左前」，畫面實際是右前角
    assert gt.view_as_named == "左前"
    assert gt.action == "還"


def test_parses_dash_with_space():
    gt = parse_filename(Path("RDL-5171 左前 借.jpg"))
    assert gt is not None
    assert gt.plate_text == "RDL5171"
    assert gt.view == RequiredView.RIGHT_FRONT
    assert gt.view_as_named == "左前"


def test_parses_retake_suffix():
    gt = parse_filename(Path("RDL-9262右前 還2.jpg"))
    assert gt is not None
    assert gt.plate_text == "RDL9262"
    assert gt.view == RequiredView.LEFT_FRONT  # 檔名寫「右前」，畫面實際是左前角
    assert gt.view_as_named == "右前"
    assert gt.action == "還"


def test_skips_damage_report_files():
    assert parse_filename(Path("RCW-8160 車況回報.jfif")) is None


def test_normalize_plate_text_strips_dash_and_uppercases():
    assert normalize_plate_text("rdu-7390") == "RDU7390"
