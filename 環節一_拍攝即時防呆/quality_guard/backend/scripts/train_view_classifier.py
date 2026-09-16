"""訓練「左前/右前/左後/右後」四角視角分類器（transfer learning, MobileNetV2）。

輸入資料夾結構（ImageFolder 格式）：
    dataset/train/{左前,右前,左後,右後}/*.jpg
    dataset/val/{左前,右前,左後,右後}/*.jpg

不用一般的 RandomHorizontalFlip：水平翻轉會把「左前」變成視覺上的「右前」，
若沿用同一個 label 會直接教模型錯誤的左右對應。改用下面 MirrorAugmentDataset，
翻轉時同步把 label 換成對面的類別（左前<->右前、左後<->右後），只用在 train，
專門針對第一版訓練發現的「前後分得出來、左右常搞混」問題加資料。
旋轉/裁切/色彩擾動不影響左右前後語意，可以放心用一般做法。

第二版另外解凍 MobileNetV2 features 最後幾個 block 一起微調（用比分類頭更小的
learning rate），讓模型有能力學到左右側這種更細緻的視覺差異，而不是完全依賴
凍結的 ImageNet 預訓練特徵。

## 第三版改了兩件跟「手機怎麼拿」有關的事（見 app/checks/view_preprocess.py）

1. **EXIF 轉正**：`ImageFolder` 預設的 PIL loader 不套 EXIF，但推論端的
   `cv2.imdecode` 會套。第一/二版因此有 293/578 張（51%）訓練樣本是橫躺著
   餵進模型的，推論時卻永遠拿到正立圖。改用 `load_image_upright` 當 loader。
2. **letterbox 取代 CenterCrop**：`Resize(256)+CenterCrop(224)` 保留的畫面
   範圍取決於原圖長寬比，橫幅照片的左右兩端（判斷四角的關鍵線索）會被裁掉。
   改成補邊成正方形，並加上 `RandomAspectCrop` 讓模型看過各種長寬比的取景。

用法：
    cd backend && .venv/bin/python scripts/train_view_classifier.py
    cd backend && .venv/bin/python scripts/train_view_classifier.py --output /tmp/try.pt
"""
import argparse
import os
import random
import sys
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import datasets, models
from torchvision.transforms import functional as TF

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.checks.view_preprocess import (  # noqa: E402  (要先設好 sys.path)
    LETTERBOX,
    build_eval_transform,
    build_train_transform,
    load_image_upright,
)

ROOT = BACKEND_DIR.parent
# 訓練資料集刻意不進 repo（幾百張真實車輛照片）。預設找 quality_guard/dataset，
# 放在別處就用 IRENT_VIEW_DATASET 指過去，比照 config.py 的模型路徑慣例。
DATASET_DIR = Path(os.environ.get("IRENT_VIEW_DATASET") or ROOT / "dataset").expanduser()
OUTPUT_PATH = BACKEND_DIR / "app" / "models" / "view_classifier.pt"

IMAGE_SIZE = 224
BATCH_SIZE = 16
EPOCHS = 30
HEAD_LR = 1e-3
BACKBONE_LR = 1e-4
UNFREEZE_LAST_N_BLOCKS = 3
# 試過解凍 8 個 block(1.99M/2.23M 參數可訓練):389 張訓練圖對這個容量來說太少,
# val_acc 衝到可疑的 100%(跟資料量還小時第一次過擬合的模式一模一樣),train_acc
# 同時衝到 97%+、val_loss 壓到 0.02-0.04,判斷是背答案而不是真的學會判斷左右。
# 在資料量明顯再擴大(例如 500+ 台不重複車輛)之前,先維持解凍 3 層,靠擴充資料
# 而不是加模型容量來改善準確率。
MIRROR_PROB = 0.5
SEED = 42

IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]

LEFT_RIGHT_SWAP_NAMES = {
    "左前": "右前", "右前": "左前",
    "左後": "右後", "右後": "左後",
}


class MirrorAugmentDataset(Dataset):
    """在 train 時以 MIRROR_PROB 機率水平翻轉圖片，並把 label 換成對面類別。"""

    def __init__(self, image_folder: datasets.ImageFolder, transform, mirror_prob: float):
        self.samples = image_folder.samples
        self.loader = image_folder.loader
        self.transform = transform
        self.mirror_prob = mirror_prob
        self.classes = image_folder.classes
        self.swap_idx = {
            image_folder.class_to_idx[name]: image_folder.class_to_idx[swap_name]
            for name, swap_name in LEFT_RIGHT_SWAP_NAMES.items()
        }

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index):
        path, label = self.samples[index]
        img = self.loader(path)
        if random.random() < self.mirror_prob:
            img = TF.hflip(img)
            label = self.swap_idx[label]
        return self.transform(img), label


def build_transforms():
    """一律走 app/checks/view_preprocess.py，跟推論端共用同一份實作。"""
    return (
        build_train_transform(IMAGE_SIZE, IMAGENET_MEAN, IMAGENET_STD),
        build_eval_transform(IMAGE_SIZE, IMAGENET_MEAN, IMAGENET_STD),
    )


def build_model(num_classes: int, unfreeze_last_n: int = UNFREEZE_LAST_N_BLOCKS) -> nn.Module:
    model = models.mobilenet_v2(weights=models.MobileNet_V2_Weights.DEFAULT)
    for param in model.features.parameters():
        param.requires_grad = False
    if unfreeze_last_n > 0:
        for block in model.features[-unfreeze_last_n:]:
            for param in block.parameters():
                param.requires_grad = True
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


def build_optimizer(model: nn.Module) -> torch.optim.Optimizer:
    head_params = list(model.classifier.parameters())
    backbone_params = [p for p in model.features.parameters() if p.requires_grad]
    return torch.optim.Adam([
        {"params": head_params, "lr": HEAD_LR},
        {"params": backbone_params, "lr": BACKBONE_LR},
    ])


def run_epoch(model, loader, device, criterion, optimizer=None):
    is_train = optimizer is not None
    model.train(is_train)

    total_loss = 0.0
    correct = 0
    total = 0
    confusion = torch.zeros(len(loader.dataset.classes), len(loader.dataset.classes), dtype=torch.long)

    with torch.set_grad_enabled(is_train):
        for images, labels in loader:
            images, labels = images.to(device), labels.to(device)
            outputs = model(images)
            loss = criterion(outputs, labels)

            if is_train:
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            total_loss += loss.item() * images.size(0)
            preds = outputs.argmax(dim=1)
            correct += (preds == labels).sum().item()
            total += images.size(0)
            for t, p in zip(labels.view(-1), preds.view(-1)):
                confusion[t.long(), p.long()] += 1

    return total_loss / total, correct / total, confusion


def parse_args():
    parser = argparse.ArgumentParser(description="訓練四角視角分類器")
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH,
                        help="checkpoint 輸出路徑（預設覆寫正式模型，想試訓練請指到別處）")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    return parser.parse_args()


def main():
    args = parse_args()
    random.seed(SEED)
    torch.manual_seed(SEED)

    if not (args.dataset / "train").is_dir():
        raise SystemExit(
            f"找不到訓練資料集：{args.dataset / 'train'}\n"
            f"資料集刻意不進 repo，請用 --dataset 或環境變數 IRENT_VIEW_DATASET 指到實際位置。"
        )

    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    print(f"使用裝置: {device}")

    train_tf, val_tf = build_transforms()
    # loader=load_image_upright：套 EXIF 轉正，跟推論端的 cv2.imdecode 對齊。
    train_folder = datasets.ImageFolder(args.dataset / "train", loader=load_image_upright)
    val_ds = datasets.ImageFolder(args.dataset / "val", transform=val_tf, loader=load_image_upright)
    train_ds = MirrorAugmentDataset(train_folder, transform=train_tf, mirror_prob=MIRROR_PROB)

    print(f"train: {len(train_ds)} 張（含鏡像增量, 每次 epoch 約半數會被翻轉+換標籤）, val: {len(val_ds)} 張")
    print(f"類別對應: {train_folder.class_to_idx}")
    assert train_folder.classes == val_ds.classes, "train/val 類別資料夾不一致"

    train_loader = DataLoader(train_ds, batch_size=BATCH_SIZE, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=BATCH_SIZE, shuffle=False)

    model = build_model(num_classes=len(train_folder.classes)).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = build_optimizer(model)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"可訓練參數: {trainable:,} / {total_params:,}")

    best_val_acc = 0.0
    best_state = None
    best_confusion = None

    for epoch in range(1, args.epochs + 1):
        train_loss, train_acc, _ = run_epoch(model, train_loader, device, criterion, optimizer)
        val_loss, val_acc, val_confusion = run_epoch(model, val_loader, device, criterion)

        marker = ""
        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            best_confusion = val_confusion
            marker = " <- best"

        print(
            f"epoch {epoch:02d}: train_loss={train_loss:.3f} train_acc={train_acc:.3f} "
            f"val_loss={val_loss:.3f} val_acc={val_acc:.3f}{marker}"
        )

    print(f"\n最佳 val_acc: {best_val_acc:.3f}")
    print(f"類別順序: {train_folder.classes}")
    print("混淆矩陣（列=真實, 欄=預測）:")
    print(best_confusion)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "state_dict": best_state,
        "classes": train_folder.classes,
        "image_size": IMAGE_SIZE,
        "normalize_mean": IMAGENET_MEAN,
        "normalize_std": IMAGENET_STD,
        # 推論端照這個欄位決定建哪一版 transform。改前處理一定要同步改這個字串，
        # 否則新權重會被舊 transform 餵，準確率無聲下降。
        "preprocess": LETTERBOX,
    }, args.output)
    print(f"\n模型已存到: {args.output}")


if __name__ == "__main__":
    main()
