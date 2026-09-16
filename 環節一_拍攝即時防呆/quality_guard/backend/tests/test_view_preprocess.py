"""前處理的幾何性質——這些是「訓練/推論不一致」最容易破的地方。

不需要模型檔，純幾何。
"""

import numpy as np
import pytest
import torch
from PIL import Image

from app.checks.view_preprocess import (
    LEGACY_CENTER_CROP,
    LETTERBOX,
    LETTERBOX_FILL,
    Letterbox,
    RandomAspectCrop,
    build_eval_transform,
    build_eval_transform_for_checkpoint,
    letterbox,
    load_image_upright,
)


def _gradient(width: int, height: int) -> Image.Image:
    """左右有明顯差異的圖，方便檢查「左右兩端有沒有被裁掉」。"""
    row = np.linspace(0, 255, width, dtype=np.uint8)
    return Image.fromarray(np.tile(row, (height, 1))).convert("RGB")


@pytest.mark.parametrize("size", [(1280, 720), (720, 1280), (800, 800), (450, 800)])
def test_letterbox_輸出恆為正方形(size):
    assert letterbox(_gradient(*size), 224).size == (224, 224)


def test_letterbox_保留左右兩端_不像_centercrop_把橫幅裁掉一半():
    """letterbox 換掉 CenterCrop 的全部理由：橫幅照片的左右兩端要留著。

    16:9 橫幅走 Resize(256)+CenterCrop(224) 只會留下中間 49% 的寬度，而判斷
    四角關係的線索多半就在被裁掉的那兩端。
    """
    wide = _gradient(1600, 900)
    out = np.asarray(letterbox(wide, 224).convert("L")).astype(int)

    # 補邊在上下，中間那幾列才是原圖內容。
    middle = out[out.shape[0] // 2]
    content = middle[middle != LETTERBOX_FILL[0]]
    # 原圖最左是 0、最右是 255，兩端都活著才代表視野完整。
    assert content.min() <= 5
    assert content.max() >= 250


def test_letterbox_補邊在短邊_且置中():
    tall = _gradient(400, 800)
    out = np.asarray(letterbox(tall, 224))
    fill = np.array(LETTERBOX_FILL)
    # 左右兩側應該是補邊，上下不是。
    assert np.allclose(out[112, 0], fill, atol=1)
    assert np.allclose(out[112, -1], fill, atol=1)
    assert not np.allclose(out[0, 112], fill, atol=1)


def test_letterbox_不改變原始長寬比():
    """圓形不能被壓成橢圓——被拉扁的車子跟真實照片是兩個分布。"""
    canvas = Image.new("RGB", (1200, 600), (0, 0, 0))
    array = np.asarray(canvas).copy()
    yy, xx = np.mgrid[0:600, 0:1200]
    array[(xx - 600) ** 2 + (yy - 300) ** 2 < 150**2] = 255
    out = np.asarray(Letterbox(224)(Image.fromarray(array)).convert("L")) > 128

    rows = np.where(out.any(axis=1))[0]
    cols = np.where(out.any(axis=0))[0]
    height = rows[-1] - rows[0]
    width = cols[-1] - cols[0]
    assert abs(width - height) <= 2, f"圓被壓成 {width}x{height}"


def test_random_aspect_crop_不超出原圖範圍():
    source = _gradient(1280, 720)
    for _ in range(50):
        crop = RandomAspectCrop()(source)
        assert 0 < crop.size[0] <= 1280
        assert 0 < crop.size[1] <= 720


def test_random_aspect_crop_會產生直式與橫式兩種取景():
    """長寬比增強要真的涵蓋兩種握法，否則等於沒加。"""
    source = _gradient(1000, 1000)
    ratios = [RandomAspectCrop()(source).size[0] / RandomAspectCrop()(source).size[1]
              for _ in range(200)]
    assert any(r > 1.3 for r in ratios), "沒有產生橫式取景"
    assert any(r < 0.77 for r in ratios), "沒有產生直式取景"


def test_eval_transform_輸出張量形狀正確():
    tensor = build_eval_transform(224, [0.5] * 3, [0.5] * 3)(_gradient(1280, 720))
    assert tensor.shape == (3, 224, 224)


def test_checkpoint_沒有_preprocess_欄位時退回舊前處理():
    """舊的 .pt 必須繼續用舊 transform，不能被新程式碼靜默換掉。"""
    legacy = {"image_size": 224, "normalize_mean": [0.5] * 3, "normalize_std": [0.5] * 3}
    transform = build_eval_transform_for_checkpoint(legacy)
    # 舊版是 Resize(256)+CenterCrop：正方形輸入不會有補邊，但長方形輸入會被裁掉兩端。
    wide = np.asarray(transform(_gradient(1600, 900)))
    assert wide.shape == (3, 224, 224)
    fill = torch.tensor(LETTERBOX_FILL, dtype=torch.float32) / 255 * 2 - 1
    corner = torch.tensor(wide[:, 0, 0])
    assert not torch.allclose(corner, fill, atol=0.02), "舊 transform 不該產生 letterbox 補邊"


def test_checkpoint_前處理版本無法辨識時直接報錯():
    with pytest.raises(ValueError, match="無法辨識"):
        build_eval_transform_for_checkpoint(
            {"preprocess": "某個未來版本", "image_size": 224,
             "normalize_mean": [0.5] * 3, "normalize_std": [0.5] * 3}
        )


def test_兩個前處理版本常數不相等():
    assert LETTERBOX != LEGACY_CENTER_CROP


def test_load_image_upright_套用_exif_轉正(tmp_path):
    """EXIF Orientation=6 的圖要被轉正——訓練端第一/二版就是漏了這步。"""
    path = tmp_path / "exif6.jpg"
    image = _gradient(1280, 720)
    exif = image.getexif()
    exif[274] = 6  # Orientation
    image.save(path, exif=exif)

    assert Image.open(path).size == (1280, 720)  # 像素本身是橫的
    assert load_image_upright(path).size == (720, 1280)  # 讀進來已經轉正
