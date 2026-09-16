"""視角分類器的影像前處理——**訓練腳本與推論服務共用同一份實作**。

會有這個模組，是因為前處理不一致的失敗是無聲的：模型照樣回一個看起來正常的
機率分布，準確率卻悄悄掉幾個百分點，沒有任何錯誤訊息。第一版把
`Resize(256) → CenterCrop(224)` 各自抄一份在 `scripts/train_view_classifier.py`、
`app/checks/view_classifier.py`、`scripts/classify_tool.py` 三個地方，任何一邊
「順手優化」就會踩到。改成從這裡 import。

## 為什麼從 CenterCrop 換成 letterbox（補邊成正方形）

`Resize(256) → CenterCrop(224)` 保留的畫面範圍**取決於原圖長寬比**：

    直立 720x1280  → Resize 後 256x455 → 裁掉上下，寬度保留 100%
    橫幅 1280x720  → Resize 後 455x256 → 裁掉左右，**寬度只剩 49%**

判斷四角關係的線索（車頭/車尾哪一端朝鏡頭、輪子的相對位置）多半在畫面左右
兩端，橫幅照片剛好把它們裁掉。對 98 張 val 實測（第一版模型）：

    直立輸入                      0.990
    裁成 16:9 橫幅 + CenterCrop   0.888   <- 掉 10 個百分點
    裁成 16:9 橫幅 + letterbox    0.949   <- 光是不裁掉左右就補回 6 成

letterbox 把短邊補灰邊成正方形再縮到 224，保留範圍與長寬比無關，直拍橫拍走
同一條路。代價是主體變小一點，用訓練時的長寬比增強（`RandomAspectCrop`）補回來。

## EXIF 方向

`load_image_upright()` 會套 `ImageOps.exif_transpose`。這不是可選的細節：
`cv2.imdecode`（推論端 API 用的）**會**自動套 EXIF，而 PIL 的
`Image.open`（訓練端 `ImageFolder` 用的）**不會**。第一版訓練因此有 51% 的
樣本（293/578 張是 1280x720 + EXIF Orientation=6 的直拍照）是橫躺著餵進模型的，
推論時卻永遠拿到正立圖——訓練與推論的分布從一開始就對不起來。
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Sequence

from PIL import Image, ImageOps
from torchvision import transforms

# checkpoint 的 `preprocess` 欄位值。推論端照這個字串決定要建哪一組 transform，
# 舊的 .pt 沒有這個欄位就當成 LEGACY_CENTER_CROP——寧可用舊前處理跑舊權重，
# 也不要讓新程式碼靜默地拿新前處理去餵舊模型。
LETTERBOX = "letterbox_v2"
LEGACY_CENTER_CROP = "resize_centercrop_v1"

# 補邊顏色。用中性灰而不是純黑：純黑跟夜間照片的背景難以區分，模型可能把
# 「畫面下緣是黑的」學成夜拍的特徵。114 沿用 YOLO letterbox 的慣例值。
LETTERBOX_FILL = (114, 114, 114)


def load_image_upright(path: str | Path) -> Image.Image:
    """讀檔並依 EXIF 轉正，回傳 RGB。給 `ImageFolder(loader=...)` 用。"""
    with Image.open(path) as image:
        return ImageOps.exif_transpose(image).convert("RGB")


def letterbox(image: Image.Image, size: int, fill: Sequence[int] = LETTERBOX_FILL) -> Image.Image:
    """短邊補灰邊成正方形後縮到 size×size，保留完整視野與原始長寬比。"""
    width, height = image.size
    side = max(width, height)
    if width != height:
        canvas = Image.new("RGB", (side, side), tuple(fill))
        canvas.paste(image, ((side - width) // 2, (side - height) // 2))
        image = canvas
    return image.resize((size, size), Image.BILINEAR)


class Letterbox:
    """`letterbox()` 的 transform 包裝，好放進 `transforms.Compose`。"""

    def __init__(self, size: int, fill: Sequence[int] = LETTERBOX_FILL):
        self.size = size
        self.fill = fill

    def __call__(self, image: Image.Image) -> Image.Image:
        return letterbox(image, self.size, self.fill)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(size={self.size})"


class RandomAspectCrop:
    """隨機裁一塊子畫面，**面積比例與長寬比都隨機**。

    跟 `transforms.RandomResizedCrop` 的差別在輸出：那個會把裁下來的區域強制
    縮成正方形（把畫面拉扁/拉長），這裡維持裁下來的長寬比、交給後面的
    letterbox 補邊。目的是讓模型看過各種長寬比的取景，而不是學會辨認「被拉扁
    的車子」。

    ratio 範圍 0.5–2.0 涵蓋常見手機的 9:16 直拍到 16:9 橫拍。
    """

    def __init__(
        self,
        area: tuple[float, float] = (0.65, 1.0),
        ratio: tuple[float, float] = (0.5, 2.0),
        attempts: int = 10,
    ):
        self.area = area
        self.ratio = ratio
        self.attempts = attempts

    def __call__(self, image: Image.Image) -> Image.Image:
        width, height = image.size
        for _ in range(self.attempts):
            target_area = random.uniform(*self.area) * width * height
            aspect = random.uniform(*self.ratio)
            crop_w = int(round((target_area * aspect) ** 0.5))
            crop_h = int(round((target_area / aspect) ** 0.5))
            if 0 < crop_w <= width and 0 < crop_h <= height:
                left = random.randint(0, width - crop_w)
                top = random.randint(0, height - crop_h)
                return image.crop((left, top, left + crop_w, top + crop_h))
        # 取樣不到合法的裁切框（極端長寬比的原圖）就整張用，不要硬裁。
        return image


class RandomRotate90:
    """以機率 p 把整張圖轉 90° 或 270°，**label 不變**。

    四角類別講的是「車相對鏡頭的姿態」——左前就是拍到車的左前角，把相機轉 90 度
    拍同一個角落，它還是左前。所以旋轉跟水平翻轉不同，不需要換 label。

    為什麼需要這個增強：第一/二版模型有 51% 訓練樣本因為 EXIF bug 是橫躺的，
    意外換來了旋轉容忍度（整批轉 90 度只掉 2 個百分點）。第三版修好 EXIF 之後
    訓練集全是正立圖，那份容忍度就消失了——實測橫躺輸入的準確率從 0.878 掉到
    0.327。方向防護網（checks/orientation.py）擋得住絕大多數情況，但那條路徑
    依賴車牌偵測成功；這個增強是第二道保險，讓模型自己也不那麼怕轉。

    只轉 90/270 不轉 180：手機橫拿會產生前者，上下顛倒拿幾乎不會發生，
    不值得為它多花模型容量。
    """

    def __init__(self, p: float = 0.25):
        self.p = p

    def __call__(self, image: Image.Image) -> Image.Image:
        if random.random() < self.p:
            return image.rotate(random.choice((90, 270)), expand=True)
        return image


def build_eval_transform(image_size: int, mean: Sequence[float], std: Sequence[float]):
    """推論／驗證用：不含任何隨機性。"""
    return transforms.Compose([
        Letterbox(image_size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])


def build_train_transform(image_size: int, mean: Sequence[float], std: Sequence[float]):
    """訓練用：長寬比／取景／小角度旋轉／色彩擾動。

    水平翻轉**不在這裡**——翻轉會把「左前」變成視覺上的「右前」，必須同步換
    label，那段在 `train_view_classifier.py` 的 `MirrorAugmentDataset`。

    旋轉的填色刻意跟 letterbox 同一個灰：兩者都會產生填充區域，用同一個顏色
    模型才不會把「角落有黑三角」當成額外線索。
    """
    return transforms.Compose([
        RandomRotate90(),
        RandomAspectCrop(),
        Letterbox(image_size),
        transforms.RandomRotation(5, fill=list(LETTERBOX_FILL)),
        transforms.ColorJitter(brightness=0.2, contrast=0.2, saturation=0.15),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])


def build_legacy_eval_transform(image_size: int, mean: Sequence[float], std: Sequence[float]):
    """第一版的 `Resize(256) → CenterCrop`，只給載入舊 checkpoint 時用。"""
    return transforms.Compose([
        transforms.Resize(256),
        transforms.CenterCrop(image_size),
        transforms.ToTensor(),
        transforms.Normalize(mean, std),
    ])


def build_eval_transform_for_checkpoint(checkpoint: dict):
    """依 checkpoint 記錄的前處理版本建對應的 transform。"""
    kind = checkpoint.get("preprocess", LEGACY_CENTER_CROP)
    args = (checkpoint["image_size"], checkpoint["normalize_mean"], checkpoint["normalize_std"])
    if kind == LETTERBOX:
        return build_eval_transform(*args)
    if kind == LEGACY_CENTER_CROP:
        return build_legacy_eval_transform(*args)
    raise ValueError(
        f"checkpoint 記錄的前處理版本無法辨識：{kind!r}。"
        f"已知的有 {LETTERBOX!r} 與 {LEGACY_CENTER_CROP!r}。"
    )
