from pathlib import Path

from app.view_taxonomy import RequiredView
from validation.parse_filename import normalize_plate_text, parse_filename


def test_parses_no_dash_no_space():
    gt = parse_filename(Path("RFH7873左後 借.jfif"))
    assert gt is not None
    assert gt.plate_text == "RFH7873"
    assert gt.view == RequiredView.LEFT_REAR
    assert gt.action == "借"


def test_parses_dash_no_space():
    gt = parse_filename(Path("RFM-2791左前 還.jpg"))
    assert gt is not None
    assert gt.plate_text == "RFM2791"
    assert gt.view == RequiredView.LEFT_FRONT
    assert gt.action == "還"


def test_parses_dash_with_space():
    gt = parse_filename(Path("RDL-5171 左前 借.jpg"))
    assert gt is not None
    assert gt.plate_text == "RDL5171"
    assert gt.view == RequiredView.LEFT_FRONT


def test_parses_retake_suffix():
    gt = parse_filename(Path("RDL-9262右前 還2.jpg"))
    assert gt is not None
    assert gt.plate_text == "RDL9262"
    assert gt.view == RequiredView.RIGHT_FRONT
    assert gt.action == "還"


def test_skips_damage_report_files():
    assert parse_filename(Path("RCW-8160 車況回報.jfif")) is None


def test_normalize_plate_text_strips_dash_and_uppercases():
    assert normalize_plate_text("rdu-7390") == "RDU7390"
