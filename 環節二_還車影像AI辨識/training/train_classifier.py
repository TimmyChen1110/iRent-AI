#!/usr/bin/env python3
"""訓練「還車照單張有無車損」二分類器（ResNet18 微調）。

★ 這是【流程驗證】，不是可上線模型。138 筆樣本（22 正）遠低於實用門檻，
  目的在於把「資料 → 訓練 → 評估 → 匯出」整條路打通並誠實量測，
  等監理台累積到數千筆後，同一支腳本可直接重跑。

方法論上的三個關鍵決定：
  1. GroupKFold by car — 同車 4 方位若跨 train/val 會洩漏（模型認車不認損），
     以車輛分組交叉驗證，並回報 fold 間變異。
  2. 類別不平衡 (15.9% 正) — 用 pos_weight 加權 BCE，而非重採樣；
     評估看 PR-AUC 與 Recall@FPR，不看 accuracy（全猜負就有 84% accuracy）。
  3. 對照基準 — 與現行 VLM 級聯（Recall 85.7% / FPR 3.3%）同一批資料比較，
     否則「訓出來了」沒有意義。

用法：
  python3 train_classifier.py                  # 5-fold 車輛分組交叉驗證
  python3 train_classifier.py --epochs 15
  python3 train_classifier.py --folds 5 --export  # 訓完用全量重訓並匯出權重
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from PIL import Image, ImageOps
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import GroupKFold
from torch.utils.data import DataLoader, Dataset
from torchvision import models, transforms

HERE = Path(__file__).resolve().parent
DATASET = HERE / "dataset.json"
CKPT = HERE / "damage_classifier.pt"

IMG = 224
MEAN, STD = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]


def device():
    if torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


train_tf = transforms.Compose([
    transforms.RandomResizedCrop(IMG, scale=(0.7, 1.0)),
    transforms.RandomHorizontalFlip(),      # 左右側車身鏡像後仍是合理車損照
    transforms.ColorJitter(0.25, 0.25, 0.2, 0.03),   # 對抗光照差異（實測主要干擾源）
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])
eval_tf = transforms.Compose([
    transforms.Resize(int(IMG * 1.14)),
    transforms.CenterCrop(IMG),
    transforms.ToTensor(),
    transforms.Normalize(MEAN, STD),
])


class DamageSet(Dataset):
    """還車照 → 有無車損。EXIF 轉正是必須的：資料集 76% 照片帶未套用的旋轉標記。"""

    def __init__(self, samples, tf):
        self.samples, self.tf = samples, tf

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, i):
        s = self.samples[i]
        im = ImageOps.exif_transpose(Image.open(s["photo"])).convert("RGB")
        return self.tf(im), torch.tensor(float(s["label"]))


def make_model():
    m = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)
    m.fc = nn.Linear(m.fc.in_features, 1)   # 單 logit + BCEWithLogits
    return m


def run_fold(tr, va, epochs, lr, bs, dev, log=print):
    model = make_model().to(dev)
    pos = sum(s["label"] for s in tr)
    neg = len(tr) - pos
    # 正樣本稀少 → 加權而非重採樣（重採樣在 22 筆正樣本上會嚴重過擬合）
    pw = torch.tensor([neg / max(pos, 1)], device=dev)
    crit = nn.BCEWithLogitsLoss(pos_weight=pw)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    dl_tr = DataLoader(DamageSet(tr, train_tf), batch_size=bs, shuffle=True, num_workers=0)
    dl_va = DataLoader(DamageSet(va, eval_tf), batch_size=bs, num_workers=0)

    for ep in range(epochs):
        model.train()
        tot = 0.0
        for x, y in dl_tr:
            x, y = x.to(dev), y.to(dev).unsqueeze(1)
            opt.zero_grad()
            loss = crit(model(x), y)
            loss.backward()
            opt.step()
            tot += loss.item() * x.size(0)
        sched.step()
        if (ep + 1) % 5 == 0 or ep == epochs - 1:
            log(f"      epoch {ep+1:2d}/{epochs}  loss {tot/len(tr):.4f}")

    model.eval()
    probs, ys = [], []
    with torch.no_grad():
        for x, y in dl_va:
            p = torch.sigmoid(model(x.to(dev))).squeeze(1).cpu().numpy()
            probs += p.tolist()
            ys += y.numpy().tolist()
    return model, np.array(probs), np.array(ys)


def metrics_at(probs, ys, thr):
    pred = (probs >= thr).astype(int)
    tp = int(((pred == 1) & (ys == 1)).sum())
    fp = int(((pred == 1) & (ys == 0)).sum())
    fn = int(((pred == 0) & (ys == 1)).sum())
    tn = int(((pred == 0) & (ys == 0)).sum())
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "recall": round(rec, 4), "fpr": round(fpr, 4), "precision": round(prec, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--export", action="store_true", help="交叉驗證後用全量重訓並存權重")
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    if not DATASET.exists():
        raise SystemExit("找不到 dataset.json，請先跑 build_dataset.py")
    d = json.loads(DATASET.read_text())
    samples = d["samples"]
    groups = [s["car"] for s in samples]      # ★ 以車輛分組
    ys_all = np.array([s["label"] for s in samples])
    dev = device()

    print(f"樣本 {len(samples)}（正 {int(ys_all.sum())} / 負 {len(samples)-int(ys_all.sum())}）"
          f"　車輛 {len(set(groups))} 台　device={dev.type}")
    print(f"以【車輛】分 {args.folds} 組交叉驗證（避免同車跨 train/val 洩漏）\n")

    gkf = GroupKFold(n_splits=args.folds)
    oof = np.zeros(len(samples))              # out-of-fold 預測
    t0 = time.time()
    for k, (itr, iva) in enumerate(gkf.split(samples, ys_all, groups), 1):
        tr = [samples[i] for i in itr]
        va = [samples[i] for i in iva]
        npos = sum(s["label"] for s in va)
        print(f"  fold {k}/{args.folds}: train {len(tr)} / val {len(va)}（val 正樣本 {npos}）")
        if npos == 0:
            print("      ⚠ 此 fold 驗證集無正樣本，指標無意義（樣本太少的必然現象）")
        _, probs, yv = run_fold(tr, va, args.epochs, args.lr, args.batch_size, dev)
        oof[iva] = probs

    dur = time.time() - t0
    print(f"\n交叉驗證完成，耗時 {dur/60:.1f} 分鐘")

    # ---- 整體 out-of-fold 評估 ----
    pr_auc = average_precision_score(ys_all, oof)
    roc = roc_auc_score(ys_all, oof)
    base = ys_all.mean()
    print("\n=== Out-of-Fold 評估（全部樣本都當過一次驗證集）===")
    print(f"PR-AUC  {pr_auc:.4f}（隨機基準 = 正樣本比例 {base:.4f}）")
    print(f"ROC-AUC {roc:.4f}")
    print("  ↑ 看 PR-AUC 不看 accuracy：全猜『無車損』就有"
          f" {100*(1-base):.1f}% accuracy，毫無意義")

    print("\n=== 不同門檻下的表現 ===")
    print(f"{'門檻':>6} {'Recall':>8} {'FPR':>8} {'Prec':>8}   混淆矩陣")
    rows = {}
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7):
        m = metrics_at(oof, ys_all, thr)
        rows[thr] = m
        print(f"{thr:>6.2f} {m['recall']:>8.1%} {m['fpr']:>8.1%} {m['precision']:>8.1%}"
              f"   TP{m['TP']:>3} FP{m['FP']:>3} FN{m['FN']:>3} TN{m['TN']:>3}")

    print("\n=== 對照現行 VLM 級聯（同一批資料）===")
    print("VLM 級聯：Recall 85.7% / FPR 3.3%（141 組，對照原始索賠標籤）")
    print("VLM 級聯：Recall 95.5% / FPR 0.0%（138 組，對照人工重標＝本次訓練用的同一份標籤）")
    best = max(rows.values(), key=lambda m: m["recall"] - m["fpr"])
    print(f"本模型最佳：Recall {best['recall']:.1%} / FPR {best['fpr']:.1%}")

    out = {"n": len(samples), "positive": int(ys_all.sum()), "cars": len(set(groups)),
           "folds": args.folds, "epochs": args.epochs,
           "pr_auc": round(pr_auc, 4), "roc_auc": round(roc, 4),
           "random_baseline_pr_auc": round(float(base), 4),
           "thresholds": {str(k): v for k, v in rows.items()},
           "vlm_baseline": {"recall": 0.955, "fpr": 0.0,
                            "note": "同一份人工重標標籤，n=138"},
           "verdict": "流程驗證用；樣本量不足以支撐上線決策",
           "minutes": round(dur / 60, 2)}
    # 保留人工加註的診斷欄位（ablation / diagnosis / caution_on_demo），
    # 否則重跑一次就會被覆蓋掉——這些是解讀指標的必要脈絡
    rp = HERE / "cv_report.json"
    if rp.exists():
        try:
            prev = json.loads(rp.read_text())
            for k in ("ablation", "diagnosis", "caution_on_demo"):
                if k in prev:
                    out.setdefault(k, prev[k])
        except json.JSONDecodeError:
            pass
    rp.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"\n→ cv_report.json")

    if args.export:
        print("\n用全量資料重訓並匯出權重…")
        model, _, _ = run_fold(samples, samples[:1], args.epochs, args.lr,
                               args.batch_size, dev, log=lambda m: None)
        torch.save({"state_dict": model.state_dict(), "img_size": IMG,
                    "mean": MEAN, "std": STD, "arch": "resnet18",
                    "trained_on": {"n": len(samples), "positive": int(ys_all.sum())},
                    "warning": "樣本量不足，僅供流程驗證與 demo，勿用於生產判定"},
                   CKPT)
        print(f"→ {CKPT.name}")


if __name__ == "__main__":
    main()
