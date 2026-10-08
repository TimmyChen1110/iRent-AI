import sys
from pathlib import Path
import torch
from ultralytics import YOLO
import coremltools as ct

# 權重路徑
pt_path = Path("app_models/detect/best.pt")
output_path = Path("app_models/coreml/PlateDetector.mlpackage")

print(f"載入 YOLO 模型: {pt_path} ...")
yolo = YOLO(str(pt_path))
torch_model = yolo.model.fuse().eval()  # 融合 Conv+BN 並切換為 eval 模式

# 取得模型定義的類別名稱（車牌通常是 1 類）
class_labels = list(yolo.names.values())
print(f"模型類別: {class_labels} (共 {len(class_labels)} 類)")

# 建立 Dummy Input (Batch=1, C=3, H=640, W=640)
sample_input = torch.rand(1, 3, 640, 640)

# 將 PyTorch 模型進行 TorchScript Trace
print("正在 Trace PyTorch 模型...")
traced_model = torch.jit.trace(torch_model, sample_input, strict=False)

# 轉換為 Core ML (包含 1/255.0 縮放，以 RGB 格式輸入)
print("正在轉換為 Core ML (加入 scale=1/255.0)...")
mlmodel = ct.convert(
    traced_model,
    inputs=[
        ct.ImageType(
            name="image",
            shape=sample_input.shape,
            scale=1.0 / 255.0,
            color_layout=ct.colorlayout.RGB,
        )
    ],
    convert_to="mlprogram",
    minimum_deployment_target=ct.target.iOS16,
)

# 儲存
output_path.parent.mkdir(parents=True, exist_ok=True)
if output_path.exists():
    import shutil
    shutil.rmtree(output_path)

mlmodel.save(str(output_path))
print(f"✅ 成功匯出無 NMS 缺陷的標準 Core ML 模型至: {output_path}")