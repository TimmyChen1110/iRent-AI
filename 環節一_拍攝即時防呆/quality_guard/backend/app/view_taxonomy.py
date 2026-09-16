from enum import Enum
from typing import Optional


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

# 視角分類模型（app/models/view_classifier.pt）的類別字串 → RequiredView。
#
# 這是**直接對應**，不要再加左右對調的「修正」。曾經有一版把車頭兩類對調，那是錯的，
# 原因記在這裡免得有人看到 raw_data 檔名又想「修回去」：
#
# 事實一：`raw_data` 的照片檔名（例如「RCG2235左前 借.jpg」）在**車頭照**上的左右是
#   反的。用幾何檢查任何一張就看得出來：車頭正對鏡頭時，駕駛座（左駕、位於車子左側）
#   會出現在畫面右邊；攝影者往自己左邊移動才會露出車子的**右**側，此時畫面上車頭在右、
#   車身往左延伸。實際檢視 RCX5100左前、RDG8578左前、RCQ6760左前 三張不同車輛的照片，
#   全部都是「車頭在畫面右、車身往左」——也就是車子的**右前角**，跟檔名相反。
#   推測成因：App 叫使用者「去車子左前方拍」，使用者面對車頭站到自己的左邊就按下快門，
#   檔名記的是 App 要求的欄位，不是畫面裡實際的角度。車尾照沒有這個問題（拍車尾時
#   攝影者跟車子同向，兩邊左右一致），實測檔名也確實是對的。
#
# 事實二：訓練資料集（~/Desktop/和泰黑客松/dataset/）是人工目視重新分類的，用的是
#   **車體視角**（車子自己的左邊/右邊），也就是正確的那一套。模型學到的是正確的定義。
#
# 結論：模型輸出本身就是正確答案，直接對應即可。`validation/parse_filename.py` 則
# 負責把檔名的車頭標註修正回車體視角，否則會用錯的真值去評分。
#
# 想重新確認兩邊是否一致：`scripts/check_dataset_label_convention.py`。
VIEW_CLASS_NAME_TO_REQUIRED_VIEW = {
    "左前": RequiredView.LEFT_FRONT,
    "右前": RequiredView.RIGHT_FRONT,
    "左後": RequiredView.LEFT_REAR,
    "右後": RequiredView.RIGHT_REAR,
}


def is_exterior(view: RequiredView) -> bool:
    return view in EXTERIOR_VIEWS


def required_view_for_class_name(class_name: str) -> Optional[RequiredView]:
    """把分類模型輸出的類別字串轉成 RequiredView；認不得就回 None。

    刻意保留這層查表（而不是直接 `RequiredView(class_name)`）：類別字串來自
    checkpoint，訓練資料夾改名就會對不上，查表配合 validate_classifier_classes()
    可以在啟動時就發現，而不是每張照片都安靜地回 UNCERTAIN_VIEW。
    """
    return VIEW_CLASS_NAME_TO_REQUIRED_VIEW.get(class_name.strip())


def validate_classifier_classes(class_names: list[str]) -> None:
    """啟動時檢查分類模型的類別跟本檔的對照表對得起來，對不上就直接失敗。

    寧可在啟動時炸掉（訊息明確、一定會被看到），也不要等到線上跑起來才每張
    照片都因為 label 對不上而回 UNCERTAIN_VIEW，那種錯誤看起來只像模型變差。
    """
    unknown = [name for name in class_names if required_view_for_class_name(name) is None]
    if unknown:
        raise ValueError(
            f"視角分類模型輸出了對照表不認得的類別：{unknown}。"
            f"已知對照：{sorted(VIEW_CLASS_NAME_TO_REQUIRED_VIEW)}。"
            f"若訓練資料夾名稱改過，請同步更新 app/view_taxonomy.py 的 "
            f"VIEW_CLASS_NAME_TO_REQUIRED_VIEW。"
        )
