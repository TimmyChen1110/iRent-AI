"""Stage 3：視角分類器 + 命名對照表。"""

import cv2
import numpy as np
import pytest

from app.checks.view_classifier import classify_corner, get_classes
from app.view_taxonomy import (
    VIEW_CLASS_NAME_TO_REQUIRED_VIEW,
    RequiredView,
    required_view_for_class_name,
    validate_classifier_classes,
)
from validation.parse_filename import parse_filename


def test_mapping_is_a_bijection_onto_the_four_exterior_views():
    assert set(VIEW_CLASS_NAME_TO_REQUIRED_VIEW.values()) == {
        RequiredView.LEFT_FRONT,
        RequiredView.RIGHT_FRONT,
        RequiredView.LEFT_REAR,
        RequiredView.RIGHT_REAR,
    }


def test_model_labels_map_straight_through():
    """模型輸出即正確答案，不要在這裡「修正」左右。

    曾經有一版把車頭兩類對調，理由是 raw_data 檔名跟模型輸出不一致——但實際錯的是
    檔名（車頭左右寫反了，幾何證據見 app/view_taxonomy.py 與
    validation/parse_filename.py），對調反而把對的翻成錯的。檔名的修正屬於驗證資料的
    事，由 parse_filename 負責，不該動模型輸出。
    """
    assert required_view_for_class_name("左前") is RequiredView.LEFT_FRONT
    assert required_view_for_class_name("右前") is RequiredView.RIGHT_FRONT
    assert required_view_for_class_name("左後") is RequiredView.LEFT_REAR
    assert required_view_for_class_name("右後") is RequiredView.RIGHT_REAR


def test_filename_ground_truth_corrects_front_but_not_rear():
    """驗證真值那一側才是需要修正的地方，而且只修車頭。"""
    from pathlib import Path as _Path

    from validation.parse_filename import parse_filename as _parse

    front = _parse(_Path("RCG2235左前 借.jpg"))
    assert front is not None
    assert front.view_as_named == "左前"
    assert front.view is RequiredView.RIGHT_FRONT  # 畫面實際是車子的右前角

    rear = _parse(_Path("RCG2235左後 借.jpg"))
    assert rear is not None
    assert rear.view_as_named == "左後"
    assert rear.view is RequiredView.LEFT_REAR  # 車尾標註正確，不修正


def test_unknown_class_name_maps_to_none():
    assert required_view_for_class_name("車頂") is None


def test_validate_classifier_classes_rejects_unknown_labels():
    with pytest.raises(ValueError, match="對照表不認得"):
        validate_classifier_classes(["左前", "車頂"])


def test_checkpoint_classes_all_map(view_model_available):
    if not view_model_available:
        pytest.skip("視角分類模型不存在")
    validate_classifier_classes(get_classes())


def test_classify_corner_on_known_photo(view_model_available, sample_left_rear_photo):
    if not view_model_available:
        pytest.skip("視角分類模型不存在")

    image = cv2.imread(str(sample_left_rear_photo))
    assert image is not None

    classification = classify_corner(image)
    assert classification.label in get_classes()
    assert 0.0 <= classification.confidence <= 1.0
    assert len(classification.probabilities) == len(get_classes())
    # 機率由高到低排序，且 top-1 就是 label
    assert classification.probabilities[0][0] == classification.label
    assert classification.probabilities == sorted(
        classification.probabilities, key=lambda item: item[1], reverse=True
    )
    assert sum(p for _, p in classification.probabilities) == pytest.approx(1.0, abs=1e-4)

    # 車尾標註正確，所以這張「左後」的預測應該就是「左後」。
    ground_truth = parse_filename(sample_left_rear_photo)
    assert ground_truth is not None
    assert required_view_for_class_name(classification.label) is ground_truth.view


def test_classify_corner_accepts_bgr_ndarray(view_model_available):
    if not view_model_available:
        pytest.skip("視角分類模型不存在")
    noise = np.random.default_rng(0).integers(0, 255, (480, 640, 3), dtype=np.uint8)
    classification = classify_corner(noise)
    assert classification.label in get_classes()
