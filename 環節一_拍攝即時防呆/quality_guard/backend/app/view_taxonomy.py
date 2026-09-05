from enum import Enum


class RequiredView(str, Enum):
    LEFT_FRONT = "左前"
    RIGHT_FRONT = "右前"
    LEFT_REAR = "左後"
    RIGHT_REAR = "右後"
    FRONT_INTERIOR = "前車內"
    REAR_INTERIOR = "後車內"


EXTERIOR_VIEWS = {
    RequiredView.LEFT_FRONT,
    RequiredView.RIGHT_FRONT,
    RequiredView.LEFT_REAR,
    RequiredView.RIGHT_REAR,
}

INTERIOR_VIEWS = {
    RequiredView.FRONT_INTERIOR,
    RequiredView.REAR_INTERIOR,
}

# 對應 raw_data/車外車內照片上傳清單.xlsx 的 ImageType 欄位（5-9 為車損等其他照片，不在此範圍內）
IMAGE_TYPE_TO_VIEW = {
    1: RequiredView.LEFT_FRONT,
    2: RequiredView.RIGHT_FRONT,
    3: RequiredView.LEFT_REAR,
    4: RequiredView.RIGHT_REAR,
    10: RequiredView.FRONT_INTERIOR,
    11: RequiredView.REAR_INTERIOR,
}


def is_exterior(view: RequiredView) -> bool:
    return view in EXTERIOR_VIEWS
