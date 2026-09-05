"""本地測試工具：上傳任意一張照片,回傳目前訓練好的視角分類器的預測結果。

只在本機執行,用來手動抽測 view_classifier.pt 的實際表現,不是正式服務。

用法:
    cd backend && ../.venv/bin/python -m uvicorn scripts.classify_tool:app --port 8009
    瀏覽器開 http://127.0.0.1:8009/
"""
import io
from pathlib import Path

import torch
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse
from PIL import Image
from torch import nn
from torchvision import models, transforms

BACKEND_DIR = Path(__file__).resolve().parents[1]
MODEL_PATH = BACKEND_DIR / "app" / "models" / "view_classifier.pt"
STATIC_DIR = Path(__file__).resolve().parent / "classify_static"

app = FastAPI()

_checkpoint = torch.load(MODEL_PATH, map_location="cpu")
_classes = _checkpoint["classes"]
_image_size = _checkpoint["image_size"]
_transform = transforms.Compose([
    transforms.Resize(256),
    transforms.CenterCrop(_image_size),
    transforms.ToTensor(),
    transforms.Normalize(_checkpoint["normalize_mean"], _checkpoint["normalize_std"]),
])


def _build_model(num_classes: int) -> nn.Module:
    model = models.mobilenet_v2(weights=None)
    in_features = model.classifier[-1].in_features
    model.classifier[-1] = nn.Linear(in_features, num_classes)
    return model


_model = _build_model(len(_classes))
_model.load_state_dict(_checkpoint["state_dict"])
_model.eval()


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/predict")
async def predict(file: UploadFile = File(...)):
    raw = await file.read()
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    tensor = _transform(image).unsqueeze(0)

    with torch.no_grad():
        logits = _model(tensor)
        probs = torch.softmax(logits, dim=1)[0]

    ranked = sorted(
        ({"label": label, "probability": float(prob)} for label, prob in zip(_classes, probs)),
        key=lambda item: item["probability"],
        reverse=True,
    )
    return {
        "predicted_label": ranked[0]["label"],
        "confidence": ranked[0]["probability"],
        "probabilities": ranked,
    }
